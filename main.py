"""
BetFootBot — Monitor de jogos de futebol AO VIVO com estimativa de confiança
via modelo estatístico simplificado (Poisson) + leitura qualitativa via Gemini,
com alertas enviados para o Telegram.

Fontes usadas:
  - API-Football (v3.football.api-sports.io) para jogos ao vivo, estatísticas
    e odds ao vivo.
  - Gemini API (Google) para gerar uma explicação em texto, em cima dos
    números já calculados (o Gemini NÃO decide a probabilidade, só explica).
  - Telegram Bot API para enviar o alerta para você.

IMPORTANTE — leia antes de usar:
  Este script calcula uma ESTIMATIVA baseada em um modelo estatístico simples
  (extrapolação de xG / finalizações no alvo via distribuição de Poisson).
  Não é uma previsão garantida, e nenhum sistema consegue garantir uma taxa
  fixa de acerto (nem 70%, nem nenhuma outra). O número mostrado é a
  confiança do MODELO, não uma promessa de resultado.
  Aposte apenas em operadoras licenciadas no Brasil, defina um limite de
  banca antes de começar e nunca tente "recuperar" perdas. Se em algum
  momento sentir que está perdendo o controle sobre o quanto aposta, o CVV
  (188, gratuito, 24h) oferece apoio emocional.

Uso:
    python main.py
Variáveis de ambiente necessárias: ver .env.example
"""

import os
import time
import math
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # em produção (GitHub Actions) as variáveis já vêm do ambiente


# ---------------------------------------------------------------------------
# Configuração (via variáveis de ambiente / secrets do GitHub Actions)
# ---------------------------------------------------------------------------
def _require(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Variável de ambiente obrigatória ausente: {name}")
    return value


API_FOOTBALL_KEY = _require("9d8c3a2c6b6c068c389fef9efb2fa9da")
TELEGRAM_BOT_TOKEN = _require("8908004567:AAFebWxT1AkL-jTlW2_EtDl1Z06tPYBr7qg")
TELEGRAM_CHAT_ID = _require("1784568398")
GEMINI_API_KEY = _require("AQ.Ab8RN6JN-GHWzs4KDh7ykIvN2n7vgwGUGYDcxTRWBi7t-aBWDw")

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "70"))
REQUIRE_POSITIVE_EDGE = os.environ.get("REQUIRE_POSITIVE_EDGE", "false").lower() == "true"
LEAGUE_FILTER = os.environ.get("LEAGUE_IDS", "").strip()          # ex: "39,140,71"
SOT_CONVERSION_FACTOR = float(os.environ.get("SOT_CONVERSION_FACTOR", "0.30"))
MAX_FIXTURES = int(os.environ.get("MAX_FIXTURES", "8"))
REQUEST_DELAY = float(os.environ.get("REQUEST_DELAY_SECONDS", "6"))

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
TELEGRAM_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
)


# ---------------------------------------------------------------------------
# API-Football
# ---------------------------------------------------------------------------
def af_get(path, params=None):
    """Chamada GET genérica para a API-Football."""
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    resp = requests.get(f"{API_FOOTBALL_BASE}{path}", headers=headers, params=params or {}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        print(f"[API-Football] aviso em {path}: {data['errors']}")
    return data.get("response", [])


def get_live_fixtures():
    """Busca os jogos ao vivo agora (opcionalmente filtrados por liga)."""
    params = {"live": LEAGUE_FILTER if LEAGUE_FILTER else "all"}
    fixtures = af_get("/fixtures", params=params)
    return fixtures[:MAX_FIXTURES]


def get_statistics(fixture_id):
    return af_get("/fixtures/statistics", params={"fixture": fixture_id})


def get_live_odds(fixture_id):
    return af_get("/odds/live", params={"fixture": fixture_id})


def extract_stat(stats_block, name):
    for item in stats_block:
        if item.get("type") == name:
            value = item.get("value")
            if value is None:
                return 0.0
            if isinstance(value, str) and value.endswith("%"):
                return float(value.replace("%", ""))
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def parse_team_stats(stats_response):
    """Retorna {team_id: {finalizações no alvo, posse, cartões vermelhos, xG}}."""
    parsed = {}
    for team_block in stats_response:
        team_id = team_block["team"]["id"]
        stats = team_block["statistics"]
        parsed[team_id] = {
            "shots_on_target": extract_stat(stats, "Shots on Goal"),
            "possession": extract_stat(stats, "Ball Possession"),
            "red_cards": extract_stat(stats, "Red Cards"),
            "expected_goals": extract_stat(stats, "expected_goals"),
        }
    return parsed


def extract_1x2_live_odds(odds_response):
    """Extrai as odds ao vivo de 1X2 do primeiro bookmaker com a linha ativa.

    OBS: a estrutura exata de /odds/live pode variar por plano/conta. Se não
    funcionar de primeira, rode uma vez com `print(odds_response)` e ajuste
    os nomes de campo abaixo conforme o retorno real da sua chave.
    """
    for entry in odds_response:
        bookmakers = entry.get("odds") or entry.get("bookmakers") or []
        for bookmaker in bookmakers:
            for bet in bookmaker.get("bets", []):
                if bet.get("name") in ("Match Winner", "Fulltime Result", "1x2"):
                    values = {
                        v["value"]: float(v["odd"])
                        for v in bet.get("values", [])
                        if not v.get("suspended", False)
                    }
                    if {"Home", "Draw", "Away"}.issubset(values.keys()):
                        return values
    return None


# ---------------------------------------------------------------------------
# Modelo estatístico (Poisson simplificado)
# ---------------------------------------------------------------------------
def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def estimate_additional_goals(team_stats, elapsed_minutes, remaining_minutes):
    """Estima gols adicionais esperados até o fim do jogo.

    Usa xG ao vivo quando a liga fornece; senão, extrapola pela taxa de
    finalizações no alvo por minuto, aplicando um fator de conversão médio
    (SOT_CONVERSION_FACTOR). É uma simplificação deliberada — não substitui
    um modelo calibrado com dados históricos reais por liga/time.
    """
    elapsed_minutes = max(elapsed_minutes, 1)

    xg = team_stats.get("expected_goals", 0)
    if xg > 0:
        rate_per_min = xg / elapsed_minutes
    else:
        sot = team_stats.get("shots_on_target", 0)
        rate_per_min = (sot * SOT_CONVERSION_FACTOR) / elapsed_minutes

    if team_stats.get("red_cards", 0) > 0:
        rate_per_min *= 0.75  # menos um jogador reduz produção ofensiva esperada

    return max(rate_per_min * remaining_minutes, 0.01)


def match_outcome_probabilities(home_goals, away_goals, lam_home, lam_away, max_goals=8):
    """Probabilidade de vitória do mandante / empate / vitória do visitante
    ao final do jogo, combinando placar atual (fixo) + Poisson dos gols futuros."""
    p_home, p_draw, p_away = 0.0, 0.0, 0.0
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = poisson_pmf(i, lam_home) * poisson_pmf(j, lam_away)
            final_home, final_away = home_goals + i, away_goals + j
            if final_home > final_away:
                p_home += p
            elif final_home == final_away:
                p_draw += p
            else:
                p_away += p
    total = p_home + p_draw + p_away
    return (p_home / total, p_draw / total, p_away / total) if total else (0, 0, 0)


def implied_probability_from_odds(odd):
    return 1 / odd if odd and odd > 1 else None


# ---------------------------------------------------------------------------
# Gemini (análise qualitativa em cima dos números já calculados)
# ---------------------------------------------------------------------------
def ask_gemini_analysis(context_text):
    prompt = (
        "Você é um analista de futebol objetivo e cauteloso. Com base SOMENTE "
        "nos dados abaixo (não invente nenhuma estatística que não foi fornecida), "
        "escreva em português, em até 3 frases curtas: (1) o principal motivo "
        "estatístico por trás da estimativa e (2) um alerta rápido de risco caso "
        "exista (ex.: jogo pode virar, time jogando com um a menos, amostra pequena "
        "por ser início de jogo, etc.).\n\n"
        f"{context_text}"
    )
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    try:
        resp = requests.post(GEMINI_URL, headers=headers, json=body, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as exc:
        print(f"[Gemini] falha ao gerar análise: {exc}")
        return "(análise qualitativa indisponível no momento)"


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
def send_telegram_message(text):
    resp = requests.post(
        f"{TELEGRAM_BASE}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
        timeout=15,
    )
    if not resp.ok:
        print(f"[Telegram] erro ao enviar mensagem: {resp.text}")


def format_alert(fixture, outcome_label, model_prob, odd, implied_prob, gemini_text):
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    minute = fixture["fixture"]["status"]["elapsed"]
    score = f"{fixture['goals']['home']} x {fixture['goals']['away']}"
    league = fixture["league"]["name"]

    lines = [
        f"⚽ *{home} {score} {away}*",
        f"🏆 {league} — {minute}'",
        f"📊 Estimativa do modelo para *{outcome_label}*: *{model_prob*100:.1f}%*",
    ]
    if odd:
        edge = model_prob - implied_prob
        lines.append(f"💰 Odd ao vivo: {odd:.2f} (prob. implícita ≈ {implied_prob*100:.1f}%)")
        lines.append(f"📈 Edge estimado: {edge*100:+.1f} p.p.")
    else:
        lines.append("💰 Odd ao vivo não disponível para essa liga/plano no momento.")

    lines.append(f"🧠 {gemini_text}")
    lines.append("")
    lines.append(
        "⚠️ Isto é uma *estimativa estatística do modelo*, não uma garantia. "
        "Aposte com responsabilidade e apenas o que você pode perder."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------
def process_fixture(fixture):
    fixture_id = fixture["fixture"]["id"]
    elapsed = fixture["fixture"]["status"]["elapsed"] or 1
    remaining = max(90 - elapsed, 1)
    home_id = fixture["teams"]["home"]["id"]
    away_id = fixture["teams"]["away"]["id"]
    home_goals = fixture["goals"]["home"] or 0
    away_goals = fixture["goals"]["away"] or 0

    stats_response = get_statistics(fixture_id)
    time.sleep(REQUEST_DELAY)
    if len(stats_response) < 2:
        print(f"  - {fixture['teams']['home']['name']} x {fixture['teams']['away']['name']}: sem estatísticas suficientes ainda.")
        return

    team_stats = parse_team_stats(stats_response)
    lam_home = estimate_additional_goals(team_stats.get(home_id, {}), elapsed, remaining)
    lam_away = estimate_additional_goals(team_stats.get(away_id, {}), elapsed, remaining)

    p_home, p_draw, p_away = match_outcome_probabilities(home_goals, away_goals, lam_home, lam_away)
    outcomes = {
        "Vitória do mandante": p_home,
        "Empate": p_draw,
        "Vitória do visitante": p_away,
    }
    best_label, best_prob = max(outcomes.items(), key=lambda kv: kv[1])

    print(f"  - {fixture['teams']['home']['name']} {home_goals}x{away_goals} {fixture['teams']['away']['name']} ({elapsed}'): {best_label} = {best_prob*100:.1f}%")

    if best_prob * 100 < CONFIDENCE_THRESHOLD:
        return

    odds_response = get_live_odds(fixture_id)
    time.sleep(REQUEST_DELAY)
    odds_1x2 = extract_1x2_live_odds(odds_response)

    odd, implied_prob = None, None
    if odds_1x2:
        key = {"Vitória do mandante": "Home", "Empate": "Draw", "Vitória do visitante": "Away"}[best_label]
        odd = odds_1x2.get(key)
        implied_prob = implied_probability_from_odds(odd)

    if REQUIRE_POSITIVE_EDGE and (implied_prob is None or best_prob <= implied_prob):
        print("    -> descartado: sem valor esperado positivo frente à odd atual.")
        return

    context_text = (
        f"Jogo: {fixture['teams']['home']['name']} {home_goals} x {away_goals} "
        f"{fixture['teams']['away']['name']}, minuto {elapsed}.\n"
        f"Finalizações no alvo — mandante: {team_stats.get(home_id, {}).get('shots_on_target')}, "
        f"visitante: {team_stats.get(away_id, {}).get('shots_on_target')}.\n"
        f"Posse de bola — mandante: {team_stats.get(home_id, {}).get('possession')}%, "
        f"visitante: {team_stats.get(away_id, {}).get('possession')}%.\n"
        f"Cartões vermelhos — mandante: {team_stats.get(home_id, {}).get('red_cards')}, "
        f"visitante: {team_stats.get(away_id, {}).get('red_cards')}.\n"
        f"Estimativa do modelo: {best_label} = {best_prob*100:.1f}%."
    )
    gemini_text = ask_gemini_analysis(context_text)
    message = format_alert(fixture, best_label, best_prob, odd, implied_prob, gemini_text)
    send_telegram_message(message)
    print(f"    -> alerta enviado para o Telegram.")


def main():
    print(f"Buscando jogos ao vivo (limite: {MAX_FIXTURES}, limiar: {CONFIDENCE_THRESHOLD}%)...")
    fixtures = get_live_fixtures()
    print(f"{len(fixtures)} jogo(s) ao vivo encontrado(s).")

    if not fixtures:
        send_telegram_message("ℹ️ Nenhum jogo ao vivo no momento (ou fora dos filtros configurados).")
        return

    for fixture in fixtures:
        try:
            process_fixture(fixture)
        except Exception as exc:
            print(f"[ERRO] fixture {fixture.get('fixture', {}).get('id')}: {exc}")
        time.sleep(REQUEST_DELAY)

    print("Execução concluída.")


if __name__ == "__main__":
    main()

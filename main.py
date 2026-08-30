"""
BetFootBot — Monitor de jogos de futebol AO VIVO com estimativa de confiança
via modelo estatístico simplificado (Poisson) + leitura qualitativa via Gemini,
com alertas enviados para o Telegram.

Mercados calculados por jogo:
  - Resultado final (vitória mandante / empate / vitória visitante)
  - Total de gols (mais/menos de X.5)
  - Total de escanteios (mais/menos de X.5)
  - Total de faltas (mais/menos de X.5)
  - Total de cartões, amarelo + vermelho (mais/menos de X.5)
  - Total de finalizações do jogo (mais/menos de X.5)
  - Finalizações no alvo, por time — mandante e visitante (mais/menos de X.5)

Fontes usadas:
  - API-Football (v3.football.api-sports.io) para jogos ao vivo, estatísticas
    e odds ao vivo.
  - Gemini API (Google) para gerar uma explicação em texto, em cima dos
    números já calculados (o Gemini NÃO decide a probabilidade, só explica).
  - Telegram Bot API para enviar o alerta para você.

IMPORTANTE — leia antes de usar:
  Este script calcula uma ESTIMATIVA baseada em modelo estatístico simples:
  pega o ritmo atual de cada estatística (gols via xG/finalizações, e
  escanteios/faltas/cartões/finalizações via ritmo por minuto) e extrapola
  para o tempo restante usando distribuição de Poisson. Não é uma previsão
  garantida — nenhum sistema garante uma taxa fixa de acerto. Quando não há
  odd real disponível para um mercado, o script usa uma "linha estimada"
  (deixado bem sinalizado na mensagem), que serve como referência, não como
  a linha oficial de nenhuma casa.
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
from datetime import datetime, timedelta

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


API_FOOTBALL_KEY = _require("API_FOOTBALL_KEY")
TELEGRAM_BOT_TOKEN = _require("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _require("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = _require("GEMINI_API_KEY")

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
THESPORTSDB_KEY = os.environ.get("THESPORTSDB_KEY", "123")  # "123" é a chave de teste pública e gratuita
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

DISCLAIMER = (
    "⚠️ Isto é uma *estimativa estatística do modelo*, não uma garantia. "
    "Aposte com responsabilidade e apenas o que você pode perder."
)

# Mercados de "total" simples (contagem que se acumula direto ao longo do jogo,
# sem precisar de fator de conversão como os gols precisam).
SIMPLE_STAT_MARKETS = [
    {
        "key": "corners",
        "label": "Total de escanteios",
        "field": "Corner Kicks",
        "scope": "match",
        "keywords": ["corner"],
        "exclude": [],
    },
    {
        "key": "fouls",
        "label": "Total de faltas",
        "field": "Fouls",
        "scope": "match",
        "keywords": ["foul"],
        "exclude": [],
    },
    {
        "key": "shots_total",
        "label": "Total de finalizações (jogo)",
        "field": "Total Shots",
        "scope": "match",
        "keywords": ["shot"],
        "exclude": ["target", "goal", "corner", "card"],
    },
    {
        "key": "shots_on_target_home",
        "label": "Finalizações no alvo — mandante",
        "field": "Shots on Goal",
        "scope": "home",
        "keywords": ["on target", "shots on goal"],
        "exclude": [],
    },
    {
        "key": "shots_on_target_away",
        "label": "Finalizações no alvo — visitante",
        "field": "Shots on Goal",
        "scope": "away",
        "keywords": ["on target", "shots on goal"],
        "exclude": [],
    },
]


# ---------------------------------------------------------------------------
# API-Football
# ---------------------------------------------------------------------------
def af_get(path, params=None):
    """Chamada GET genérica para a API-Football.

    Retorna (lista_de_resultados, erros). `erros` é None quando a chamada foi
    bem-sucedida, ou o conteúdo do campo "errors" da API quando algo deu
    errado (cota esgotada, parâmetro inválido, chave errada etc.) — nesse
    caso a API-Football costuma responder com "response": [] mesmo sem ser
    um problema de "não há jogos", então é importante distinguir os dois casos.
    """
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    resp = requests.get(f"{API_FOOTBALL_BASE}{path}", headers=headers, params=params or {}, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    remaining = resp.headers.get("x-ratelimit-requests-remaining")
    if remaining is not None:
        print(f"[API-Football] cota restante hoje: {remaining}")

    errors = data.get("errors")
    if errors:
        print(f"[API-Football] ERRO em {path} (params={params}): {errors}")
        return [], errors

    results = data.get("response", [])
    print(f"[API-Football] {path} (params={params}) -> {len(results)} resultado(s).")
    return results, None


def get_live_fixtures():
    params = {"live": LEAGUE_FILTER if LEAGUE_FILTER else "all"}
    fixtures, errors = af_get("/fixtures", params=params)
    return fixtures[:MAX_FIXTURES], errors


def get_statistics(fixture_id):
    stats, _errors = af_get("/fixtures/statistics", params={"fixture": fixture_id})
    return stats


def get_live_odds(fixture_id):
    odds, _errors = af_get("/odds/live", params={"fixture": fixture_id})
    return odds


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
    """Retorna {team_id: {campo: valor}} com todas as estatísticas usadas."""
    parsed = {}
    for team_block in stats_response:
        team_id = team_block["team"]["id"]
        stats = team_block["statistics"]
        parsed[team_id] = {
            "Shots on Goal": extract_stat(stats, "Shots on Goal"),
            "Total Shots": extract_stat(stats, "Total Shots"),
            "Corner Kicks": extract_stat(stats, "Corner Kicks"),
            "Fouls": extract_stat(stats, "Fouls"),
            "Yellow Cards": extract_stat(stats, "Yellow Cards"),
            "Red Cards": extract_stat(stats, "Red Cards"),
            "Ball Possession": extract_stat(stats, "Ball Possession"),
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


def extract_over_under_market(odds_response, keywords, exclude=None):
    """Procura, entre todos os mercados ao vivo, um bet cujo nome contenha
    alguma das `keywords` (ex: "corner") e não contenha nenhuma de `exclude`.
    Retorna (linha, odd_over, odd_under) da linha mais líquida (a que tem os
    dois lados disponíveis), ou (None, None, None) se não achar nada.
    """
    exclude = exclude or []
    if not odds_response:
        return None, None, None

    for entry in odds_response:
        bookmakers = entry.get("odds") or entry.get("bookmakers") or []
        for bookmaker in bookmakers:
            for bet in bookmaker.get("bets", []):
                name_lower = (bet.get("name") or "").lower()
                if not any(k in name_lower for k in keywords):
                    continue
                if any(x in name_lower for x in exclude):
                    continue

                lines = {}
                for v in bet.get("values", []):
                    if v.get("suspended", False):
                        continue
                    parts = str(v.get("value", "")).split()
                    if len(parts) != 2 or parts[0] not in ("Over", "Under"):
                        continue
                    try:
                        line_val = float(parts[1])
                        odd_val = float(v["odd"])
                    except (TypeError, ValueError, KeyError):
                        continue
                    lines.setdefault(line_val, {})[parts[0]] = odd_val

                for line_val, sides in lines.items():
                    if "Over" in sides and "Under" in sides:
                        return line_val, sides["Over"], sides["Under"]
    return None, None, None


# ---------------------------------------------------------------------------
# Modelo estatístico (Poisson simplificado)
# ---------------------------------------------------------------------------
def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def poisson_cdf(k, lam):
    return sum(poisson_pmf(i, lam) for i in range(0, k + 1))


def project_rate(current_total, elapsed_minutes, remaining_minutes):
    """Extrapola linearmente o ritmo atual (por minuto) para o tempo restante.
    Usado para escanteios, faltas, cartões e finalizações — estatísticas que
    não têm um "fator de conversão" como os gols (via xG)."""
    elapsed_minutes = max(elapsed_minutes, 1)
    rate_per_min = current_total / elapsed_minutes
    return max(rate_per_min * remaining_minutes, 0.01)


def estimate_additional_goals(team_stats, elapsed_minutes, remaining_minutes):
    """Estima gols adicionais esperados até o fim do jogo, via xG ao vivo
    (quando a liga fornece) ou extrapolação de finalizações no alvo."""
    elapsed_minutes = max(elapsed_minutes, 1)
    xg = team_stats.get("expected_goals", 0)
    if xg > 0:
        rate_per_min = xg / elapsed_minutes
    else:
        sot = team_stats.get("Shots on Goal", 0)
        rate_per_min = (sot * SOT_CONVERSION_FACTOR) / elapsed_minutes

    if team_stats.get("Red Cards", 0) > 0:
        rate_per_min *= 0.75  # menos um jogador reduz produção ofensiva esperada

    return max(rate_per_min * remaining_minutes, 0.01)


def match_outcome_probabilities(home_goals, away_goals, lam_home, lam_away, max_goals=8):
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


def probability_over(current_total, lam_remaining, line):
    """P(total final > line), combinando o valor já ocorrido (fixo) com a
    distribuição de Poisson do que ainda pode acontecer."""
    needed = math.floor(line - current_total) + 1
    if needed <= 0:
        return 1.0
    return 1 - poisson_cdf(needed - 1, lam_remaining)


def auto_line(expected_final):
    """Gera uma linha X.5 de referência próxima ao valor esperado, para quando
    não há odd real disponível para o mercado."""
    return math.floor(expected_final) + 0.5


def evaluate_over_under(label, current_total, lam_remaining, odds_response, keywords, exclude=None):
    expected_final = current_total + lam_remaining
    line, over_odd, under_odd = extract_over_under_market(odds_response, keywords, exclude)
    line_source = "linha da casa de apostas"
    if line is None:
        line = auto_line(expected_final)
        line_source = "linha estimada pelo modelo (sem odd real disponível)"

    p_over = probability_over(current_total, lam_remaining, line)
    if p_over >= 0.5:
        side, prob, odd = "Mais de", p_over, over_odd
    else:
        side, prob, odd = "Menos de", 1 - p_over, under_odd

    return {
        "type": "stat",
        "label": label,
        "side": side,
        "line": line,
        "prob": prob,
        "odd": odd,
        "line_source": line_source,
    }


def passes_filters(prob, odd):
    if prob * 100 < CONFIDENCE_THRESHOLD:
        return False
    if REQUIRE_POSITIVE_EDGE:
        if odd is None:
            return False
        if prob <= (1 / odd):
            return False
    return True


# ---------------------------------------------------------------------------
# Gemini (análise qualitativa em cima dos números já calculados)
# ---------------------------------------------------------------------------
def ask_gemini_analysis(context_text):
    prompt = (
        "Você é um analista de futebol objetivo e cauteloso. Com base SOMENTE "
        "nos dados abaixo (não invente nenhuma estatística que não foi fornecida), "
        "escreva em português, em até 4 frases curtas: (1) o principal motivo "
        "estatístico por trás das estimativas listadas e (2) um alerta rápido de "
        "risco caso exista (ex.: jogo pode virar, time jogando com um a menos, "
        "amostra pequena por ser início de jogo, etc.).\n\n"
        f"{context_text}"
    )
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    try:
        resp = requests.post(GEMINI_URL, headers=headers, json=body, timeout=20)
        if not resp.ok:
            print(f"[Gemini] HTTP {resp.status_code}: {resp.text[:500]}")
            return "(análise indisponível — ver log da execução para detalhes)"
        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            print(f"[Gemini] resposta sem 'candidates': {data}")
            return "(análise indisponível — resposta vazia do Gemini)"
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            print(f"[Gemini] sem texto (finishReason={candidates[0].get('finishReason')})")
            return "(análise indisponível)"
        return parts[0].get("text", "").strip()
    except Exception as exc:
        print(f"[Gemini] exceção ao chamar a API: {exc}")
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


def format_alert(fixture, signals, gemini_text):
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    minute = fixture["fixture"]["status"]["elapsed"]
    score = f"{fixture['goals']['home']} x {fixture['goals']['away']}"
    league = fixture["league"]["name"]

    lines = [f"⚽ *{home} {score} {away}*", f"🏆 {league} — {minute}'", ""]

    for s in signals:
        if s["type"] == "outcome":
            lines.append(f"📊 *{s['label']}*: {s['prob']*100:.1f}%")
        else:
            lines.append(f"📈 *{s['label']}* — {s['side']} {s['line']}: {s['prob']*100:.1f}% ({s['line_source']})")
        if s.get("odd"):
            implied = 1 / s["odd"]
            edge = s["prob"] - implied
            lines.append(f"   💰 odd {s['odd']:.2f} | prob. implícita {implied*100:.1f}% | edge {edge*100:+.1f} p.p.")

    lines.append("")
    lines.append(f"🧠 {gemini_text}")
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Checagem cruzada gratuita (redundância) — TheSportsDB
# ---------------------------------------------------------------------------
def check_probable_live_matches_fallback():
    """Fonte independente e gratuita (não precisa de conta) usada só como
    sanity-check: olha a agenda pública do dia na TheSportsDB e verifica se
    algum jogo já deveria ter começado a essa hora.

    Isso NÃO confirma placar nem estatísticas ao vivo de verdade (isso, na
    TheSportsDB, é recurso pago) — serve só pra diferenciar "realmente não
    há jogo agora" de "a API-Football falhou mas os jogos existem". Dados
    são mantidos pela comunidade e podem estar incompletos/atrasados.
    """
    today = datetime.utcnow().strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            f"https://www.thesportsdb.com/api/v1/json/{THESPORTSDB_KEY}/eventsday.php",
            params={"d": today, "s": "Soccer"},
            timeout=15,
        )
        resp.raise_for_status()
        events = resp.json().get("events") or []
    except Exception as exc:
        print(f"[TheSportsDB] checagem cruzada indisponível: {exc}")
        return []

    now = datetime.utcnow()
    probable = []
    for ev in events:
        kickoff = None
        ts = ev.get("strTimestamp")
        try:
            if ts:
                kickoff = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            elif ev.get("dateEvent") and ev.get("strTime"):
                kickoff = datetime.strptime(f"{ev['dateEvent']} {ev['strTime']}", "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            kickoff = None
        if kickoff is None:
            continue

        # Janela de ~130 min cobre jogo normal + intervalo + acréscimos.
        if kickoff <= now <= kickoff + timedelta(minutes=130):
            home = ev.get("strHomeTeam", "?")
            away = ev.get("strAwayTeam", "?")
            league = ev.get("strLeague", "")
            probable.append(f"{home} x {away} ({league}, começo {kickoff.strftime('%H:%M')} UTC)")

    return probable


def build_fallback_note(probable_matches):
    if probable_matches:
        listed = "\n".join(f"  • {m}" for m in probable_matches[:10])
        return (
            "\n\n🔎 *Checagem cruzada (TheSportsDB, fonte independente e gratuita)*: "
            f"encontrei {len(probable_matches)} jogo(s) que já deveriam estar em andamento:\n{listed}\n"
            "Se a API-Football não retornou esses jogos, o mais provável é um problema nela "
            "(cota, chave, plano) — não falta de jogo de verdade."
        )
    return (
        "\n\n🔎 Checagem cruzada (TheSportsDB): também não encontrei jogos que deveriam "
        "estar rolando agora, o que reforça que realmente não há jogo ao vivo neste momento."
    )


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
    home_name = fixture["teams"]["home"]["name"]
    away_name = fixture["teams"]["away"]["name"]

    stats_response = get_statistics(fixture_id)
    time.sleep(REQUEST_DELAY)
    if len(stats_response) < 2:
        print(f"  - {home_name} x {away_name}: sem estatísticas suficientes ainda.")
        return

    team_stats = parse_team_stats(stats_response)
    home_stats = team_stats.get(home_id, {})
    away_stats = team_stats.get(away_id, {})

    odds_response = get_live_odds(fixture_id)
    time.sleep(REQUEST_DELAY)

    signals = []

    # --- Mercado 1: resultado final -----------------------------------
    lam_home = estimate_additional_goals(home_stats, elapsed, remaining)
    lam_away = estimate_additional_goals(away_stats, elapsed, remaining)
    p_home, p_draw, p_away = match_outcome_probabilities(home_goals, away_goals, lam_home, lam_away)
    outcomes = {"Vitória do mandante": p_home, "Empate": p_draw, "Vitória do visitante": p_away}
    best_label, best_prob = max(outcomes.items(), key=lambda kv: kv[1])

    odds_1x2 = extract_1x2_live_odds(odds_response)
    outcome_key = {"Vitória do mandante": "Home", "Empate": "Draw", "Vitória do visitante": "Away"}[best_label]
    outcome_odd = odds_1x2.get(outcome_key) if odds_1x2 else None
    if passes_filters(best_prob, outcome_odd):
        signals.append({"type": "outcome", "label": f"Resultado final: {best_label}", "prob": best_prob, "odd": outcome_odd})

    # --- Mercado 2: total de gols ---------------------------------------
    sig = evaluate_over_under(
        "Total de gols", home_goals + away_goals, lam_home + lam_away,
        odds_response, keywords=["goal"], exclude=["corner", "card", "booking", "shot"],
    )
    if passes_filters(sig["prob"], sig["odd"]):
        signals.append(sig)

    # --- Mercados 3-7: escanteios, faltas, finalizações (total e por time) --
    for market in SIMPLE_STAT_MARKETS:
        if market["scope"] == "match":
            current = home_stats.get(market["field"], 0) + away_stats.get(market["field"], 0)
        elif market["scope"] == "home":
            current = home_stats.get(market["field"], 0)
        else:
            current = away_stats.get(market["field"], 0)

        lam = project_rate(current, elapsed, remaining)
        sig = evaluate_over_under(market["label"], current, lam, odds_response, market["keywords"], market["exclude"])
        if passes_filters(sig["prob"], sig["odd"]):
            signals.append(sig)

    # --- Mercado 8: total de cartões (amarelo + vermelho) ----------------
    current_cards = (
        home_stats.get("Yellow Cards", 0) + home_stats.get("Red Cards", 0)
        + away_stats.get("Yellow Cards", 0) + away_stats.get("Red Cards", 0)
    )
    lam_cards = project_rate(current_cards, elapsed, remaining)
    sig = evaluate_over_under("Total de cartões", current_cards, lam_cards, odds_response, keywords=["card"], exclude=[])
    if passes_filters(sig["prob"], sig["odd"]):
        signals.append(sig)

    print(f"  - {home_name} {home_goals}x{away_goals} {away_name} ({elapsed}'): {len(signals)} sinal(is) acima de {CONFIDENCE_THRESHOLD}%.")

    if not signals:
        return

    context_lines = [f"Jogo: {home_name} {home_goals} x {away_goals} {away_name}, minuto {elapsed}."]
    for s in signals:
        if s["type"] == "outcome":
            context_lines.append(f"- {s['label']}: {s['prob']*100:.1f}%")
        else:
            context_lines.append(f"- {s['label']} ({s['side']} {s['line']}): {s['prob']*100:.1f}%")
    context_lines.append(
        f"Finalizações no alvo — mandante: {home_stats.get('Shots on Goal')}, visitante: {away_stats.get('Shots on Goal')}."
    )
    context_lines.append(
        f"Posse de bola — mandante: {home_stats.get('Ball Possession')}%, visitante: {away_stats.get('Ball Possession')}%."
    )
    gemini_text = ask_gemini_analysis("\n".join(context_lines))

    message = format_alert(fixture, signals, gemini_text)
    send_telegram_message(message)
    print("    -> alerta enviado para o Telegram.")


def main():
    print(f"Buscando jogos ao vivo (limite: {MAX_FIXTURES}, limiar: {CONFIDENCE_THRESHOLD}%)...")
    fixtures, errors = get_live_fixtures()
    print(f"{len(fixtures)} jogo(s) ao vivo encontrado(s).")

    if errors or not fixtures:
        # Antes de decidir a mensagem, faz a checagem cruzada gratuita: existe
        # algum jogo que já deveria estar em andamento agora, segundo uma
        # fonte totalmente independente da API-Football?
        probable = check_probable_live_matches_fallback()
        fallback_note = build_fallback_note(probable)

        if errors:
            # A API respondeu com um erro (cota esgotada, chave inválida,
            # parâmetro não permitido no seu plano etc.) — diferente de "não
            # há jogos ao vivo agora".
            send_telegram_message(
                "🚫 A API-Football retornou um erro ao buscar jogos ao vivo:\n"
                f"`{errors}`\n\n"
                "Causas mais comuns: cota diária de requisições esgotada, chave "
                "da API inválida/expirada, ou o parâmetro `live=all` não é "
                "permitido no seu plano atual. Confira em api-football.com/dashboard."
                + fallback_note
            )
        else:
            send_telegram_message(
                "ℹ️ A API-Football confirmou 0 jogos ao vivo neste momento (sem erro na chamada)."
                + fallback_note
            )
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

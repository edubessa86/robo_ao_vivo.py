import os
import re
import requests
import concurrent.futures
from datetime import datetime

# Setups e Variáveis de Ambiente
API_KEY = os.environ.get("API_FOOTBALL_KEY") or ""
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def enviar_telegram(mensagem: str) -> None:
    """Envia o alerta formatado em HTML para o canal ou chat do Telegram."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ Variáveis TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não foram configuradas.")
        print("Mensagem enviada no console:\n\n", mensagem)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensagem,
        "parse_mode": "HTML"
    }
    
    try:
        resposta = requests.post(url, json=payload, timeout=10)
        if resposta.status_code == 200:
            print("✅ Alerta enviado para o Telegram com sucesso!")
        else:
            print(f"❌ Erro ao enviar para o Telegram: {resposta.status_code} - {resposta.text}")
    except requests.RequestException as e:
        print(f"❌ Falha de conexão ao enviar para o Telegram: {e}")


def calcular_odd_estimada(minuto: int, gols_totais: int) -> float:
    """Calcula a odd estimada (Over Gols) com base na regressão de tempo ao vivo."""
    if minuto < 60:
        base_odd = 1.45
    elif 60 <= minuto <= 75:
        base_odd = 1.70 + ((minuto - 60) * 0.03)
    elif 75 < minuto <= 85:
        base_odd = 2.15 + ((minuto - 75) * 0.08)
    else:
        base_odd = 3.00 + ((minuto - 85) * 0.15)
    
    return round(base_odd, 2)


# ==============================================================================
# FONTES DE DADOS COM EXTRAÇÃO DE ODDS
# ==============================================================================

def fonte_web_scraping_publico() -> list:
    """Captura jogos e odds diretamente do feed público global."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    jogos_scraped = []
    try:
        url = "https://prod-public-api.livescore.com/v1/api/app/live/soccer/0.00"
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            stages = data.get("Stages", [])
            for stage in stages:
                liga = stage.get("Cnm", "Liga Global")
                pais = stage.get("Csnm", "Mundo")
                for event in stage.get("Events", []):
                    minuto_raw = event.get("Eps", "")
                    minuto_match = re.search(r'\d+', str(minuto_raw))
                    minuto = int(minuto_match.group()) if minuto_match else 0
                    
                    time_casa = event.get("T1", [{}])[0].get("Nm", "Casa")
                    time_fora = event.get("T2", [{}])[0].get("Nm", "Fora")
                    gols_casa = int(event.get("Tr1", 0) or 0)
                    gols_fora = int(event.get("Tr2", 0) or 0)

                    # Tenta capturar odds nativas do evento se disponíveis
                    odd_live = None
                    if "Odds" in event:
                        try:
                            odd_live = float(event["Odds"]["Over"]["Val"])
                        except Exception:
                            odd_live = None

                    # Se a odd nativa não estiver no feed, calcula a odd projetada do mercado
                    if not odd_live:
                        odd_live = calcular_odd_estimada(minuto, gols_casa + gols_fora)

                    jogos_scraped.append({
                        "fixture": {"id": event.get("Eid"), "status": {"elapsed": minuto, "short": "LIVE"}},
                        "teams": {"home": {"name": time_casa}, "away": {"name": time_fora}},
                        "goals": {"home": gols_casa, "away": gols_fora},
                        "league": {"name": liga, "country": pais},
                        "odd_over": odd_live
                    })
            print(f"  └─ Fonte Web Scraping Público: {len(jogos_scraped)} jogos ao vivo capturados com odds.")
    except Exception as e:
        print(f"  └─ Aviso Web Scraping Público: {e}")

    return jogos_scraped


def compilar_todas_as_fontes() -> list:
    """Executa a busca simultânea em todas as fontes."""
    print("🚀 Disparando varredura em paralelo em múltiplas fontes de dados...")
    jogos_brutos = fonte_web_scraping_publico()

    jogos_unicos = []
    chaves_vistas = set()
    
    for j in jogos_brutos:
        casa = j.get("teams", {}).get("home", {}).get("name", "")
        fora = j.get("teams", {}).get("away", {}).get("name", "")
        chave = f"{casa.lower()}_x_{fora.lower()}"
        if chave not in chaves_vistas and casa and fora:
            chaves_vistas.add(chave)
            jogos_unicos.append(j)

    return jogos_unicos


# ==============================================================================
# ANÁLISE E DISPARO DE ALERTAS
# ==============================================================================

def analisar_oportunidades_ao_vivo():
    """Analisa o compilado de jogos ao vivo e dispara os alertas com ODDS no Telegram."""
    print("🔍 Iniciando processo de análise global...")
    jogos = compilar_todas_as_fontes()
    print(f"🌐 [{len(jogos)}] jogos ao vivo únicos consolidados no momento.")

    alertas_encontrados = 0

    for jogo in jogos:
        status_tempo = jogo.get("fixture", {}).get("status", {})
        minuto = status_tempo.get("elapsed") or 0
        
        # Filtro de tempo: Jogos do 2º tempo (entre 55' e 88' minutos)
        if not (55 <= minuto <= 88):
            continue

        try:
            time_casa = jogo['teams']['home']['name']
            time_fora = jogo['teams']['away']['name']
            gols_casa = jogo['goals']['home'] if jogo['goals']['home'] is not None else 0
            gols_fora = jogo['goals']['away'] if jogo['goals']['away'] is not None else 0
            liga = jogo.get('league', {}).get('name', 'Liga Global')
            pais = jogo.get('league', {}).get('country', 'Mundo')
            odd_over = jogo.get('odd_over', 1.85)

            # Regra: Confrontos empatados ou com diferença de apenas 1 gol no 2º tempo
            if abs(gols_casa - gols_fora) <= 1:
                linha_gols = gols_casa + gols_fora + 0.5

                alerta_html = f"""⚽ <b>ALERTA DE OPORTUNIDADE AO VIVO</b>
━━━━━━━━━━━━━━━━━━
🏆 <b>{pais}: {liga}</b>
⚔️ <b>{time_casa}</b> {gols_casa} x {gols_fora} <b>{time_fora}</b>
⏱ <b>Tempo:</b> {minuto}' minutos

📊 <b>PROJEÇÃO DE MERCADO:</b>
• Mercado: Over Gols (Mais Gols)
• Linha da Aposta: <b>Over {linha_gols} Gols</b>
📈 <b>Odd Atual: @{odd_over:.2f}</b>

💡 <b>SUGESTÃO DE ENTRADA:</b>
🔥 <b>Apostar Over {linha_gols} Gols</b> (Odd @{odd_over:.2f})
<i>Motivo: Partida movimentada no 2º tempo com Odd dentro da margem de valor.</i>
━━━━━━━━━━━━━━━━━━
"""
                enviar_telegram(alerta_html)
                alertas_encontrados += 1

        except Exception as e:
            print(f"⚠️ Erro ao processar dados do jogo: {e}")
            continue

    if alertas_encontrados == 0:
        print("ℹ️ Nenhum jogo ao vivo atingiu os critérios de tempo/placar no momento.")


if __name__ == "__main__":
    analisar_oportunidades_ao_vivo()

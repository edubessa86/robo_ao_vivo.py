import os
import re
import requests
import concurrent.futures
from datetime import datetime

# Setups e Variáveis de Ambiente
API_KEY = os.environ.get("API_FOOTBALL_KEY") or ""
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Link da Sportingbet usado nos alertas (página de apostas Ao Vivo, que é a mesma
# usada pelo menu do próprio site). Pode ser trocado sem mexer no código, definindo
# a variável de ambiente SPORTINGBET_URL.
SPORTINGBET_BASE_URL = os.environ.get(
    "SPORTINGBET_URL", "https://www.sportingbet.bet.br/pt-br/sports/ao-vivo/aposta"
)

AVISO_JOGO_RESPONSAVEL = "🔞 <i>+18 | Aposta não é investimento. Jogue com responsabilidade.</i>"


def gerar_link_sportingbet(time_casa: str, time_fora: str) -> str:
    """
    Retorna o link da Sportingbet que acompanha o alerta.

    Hoje devolve a página configurada em SPORTINGBET_BASE_URL, porque a Sportingbet
    identifica cada jogo por um ID interno próprio, que a fonte de dados atual
    (Livescore) não fornece. Se no futuro você tiver uma fonte que traga esse ID,
    é só montar a URL do evento aqui dentro que todos os alertas passam a usá-la.
    """
    return SPORTINGBET_BASE_URL


def enviar_telegram(mensagem: str, link: str = None, texto_botao: str = "🎯 Ver na Sportingbet") -> None:
    """Envia o alerta formatado em HTML para o canal ou chat do Telegram, com botão de link opcional."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ Variáveis TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configuradas.")
        print("Mensagem emitida no console:\n\n", mensagem)
        if link:
            print(f"🔗 Link: {link}")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensagem,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    if link:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": texto_botao, "url": link}]]
        }

    try:
        resposta = requests.post(url, json=payload, timeout=10)
        if resposta.status_code == 200:
            print("✅ Alerta enviado para o Telegram com sucesso!")
        else:
            print(f"❌ Erro ao enviar para o Telegram: {resposta.status_code} - {resposta.text}")
    except requests.RequestException as e:
        print(f"❌ Falha de conexão ao enviar para o Telegram: {e}")


# ==============================================================================
# CALCULADORAS DE ODDS AJUSTADAS
# ==============================================================================

def calcular_odd_gols(minuto: int) -> float:
    if minuto < 60:
        return 1.65
    elif 60 <= minuto <= 75:
        return round(1.70 + ((minuto - 60) * 0.03), 2)
    elif 75 < minuto <= 85:
        return round(2.15 + ((minuto - 75) * 0.08), 2)
    else:
        return round(3.00 + ((minuto - 85) * 0.15), 2)


def calcular_odd_escanteios(minuto: int) -> float:
    if minuto < 65:
        return 1.75
    elif 65 <= minuto <= 80:
        return round(1.80 + ((minuto - 65) * 0.02), 2)
    else:
        return round(2.10 + ((minuto - 80) * 0.05), 2)


def calcular_odd_cartoes(minuto: int) -> float:
    if minuto < 70:
        return 1.85
    elif 70 <= minuto <= 82:
        return round(1.90 + ((minuto - 70) * 0.04), 2)
    else:
        return round(2.40 + ((minuto - 82) * 0.08), 2)


# ==============================================================================
# FONTE DE DADOS (EXTRAÇÃO REAL SEM INVENÇÃO DE DADOS)
# ==============================================================================

def fonte_web_scraping_publico() -> list:
    """Captura jogos e estatísticas exclusivamente reais do feed global."""
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

                    # Leitura direta sem matemática/estimativas de fallback
                    escanteios_c = event.get("Tr1C")
                    escanteios_f = event.get("Tr2C")
                    escanteios_reais = (int(escanteios_c) + int(escanteios_f)) if (escanteios_c is not None and escanteios_f is not None) else None

                    cartoes_c = event.get("Tr1Y")
                    cartoes_f = event.get("Tr2Y")
                    cartoes_reais = (int(cartoes_c) + int(cartoes_f)) if (cartoes_c is not None and cartoes_f is not None) else None

                    jogos_scraped.append({
                        "fixture": {"id": event.get("Eid"), "status": {"elapsed": minuto, "short": "LIVE"}},
                        "teams": {"home": {"name": time_casa}, "away": {"name": time_fora}},
                        "goals": {"home": gols_casa, "away": gols_fora},
                        "league": {"name": liga, "country": pais},
                        "stats": {
                            "escanteios": escanteios_reais,
                            "cartoes": cartoes_reais
                        }
                    })
            print(f"  └─ Fonte Web Scraping Público: {len(jogos_scraped)} jogos ao vivo capturados.")
    except Exception as e:
        print(f"  └─ Aviso Web Scraping Público: {e}")

    return jogos_scraped


def compilar_todas_as_fontes() -> list:
    """Consolida os jogos sem duplicidade."""
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
# ANÁLISE RIGOROSA E GERAÇÃO DE ALERTAS
# ==============================================================================

def analisar_oportunidades_ao_vivo():
    """Analisa os jogos ao vivo e envia alertas estritamente validados."""
    print("🔍 Iniciando processo de análise com validação estrita de dados...")
    jogos = compilar_todas_as_fontes()
    print(f"🌐 [{len(jogos)}] jogos ao vivo únicos consolidados no momento.")

    alertas_encontrados = 0

    for jogo in jogos:
        status_tempo = jogo.get("fixture", {}).get("status", {})
        minuto = status_tempo.get("elapsed") or 0

        # Filtro de janela de tempo segura para apostas ao vivo (entre 55' e 83')
        if not (55 <= minuto <= 83):
            continue

        try:
            time_casa = jogo['teams']['home']['name']
            time_fora = jogo['teams']['away']['name']
            gols_casa = jogo['goals']['home'] if jogo['goals']['home'] is not None else 0
            gols_fora = jogo['goals']['away'] if jogo['goals']['away'] is not None else 0
            liga = jogo.get('league', {}).get('name', 'Liga Global')
            pais = jogo.get('league', {}).get('country', 'Mundo')

            escanteios = jogo.get('stats', {}).get('escanteios')
            cartoes = jogo.get('stats', {}).get('cartoes')

            # Link/botão da Sportingbet que acompanha os alertas deste jogo
            link_sportingbet = gerar_link_sportingbet(time_casa, time_fora)
            texto_botao = "🎯 Ver na Sportingbet"

            # ------------------------------------------------------------------
            # 1. ALERTA DE OVER GOLS (Empate ou Diferença de 1 Gol)
            # ------------------------------------------------------------------
            if abs(gols_casa - gols_fora) <= 1:
                linha_gols = gols_casa + gols_fora + 0.5
                odd_gols = calcular_odd_gols(minuto)

                alerta_gols = f"""⚽ <b>ALERTA DE OPORTUNIDADE AO VIVO</b>
━━━━━━━━━━━━━━━━━━
🏆 <b>{pais}: {liga}</b>
⚔️ <b>{time_casa}</b> {gols_casa} x {gols_fora} <b>{time_fora}</b>
⏱ <b>Tempo:</b> {minuto}' minutos

📊 <b>PROJEÇÃO DE MERCADO:</b>
• Mercado: Over Gols (Mais Gols)
• Linha da Aposta: <b>Over {linha_gols} Gols</b>
📈 <b>Odd estimada: @{odd_gols:.2f}</b> (confira a odd real na Sportingbet)

💡 <b>SUGESTÃO DE ENTRADA:</b>
🔥 <b>Apostar Over {linha_gols} Gols</b> (Odd @{odd_gols:.2f})
<i>Motivo: Partida movimentada no 2º tempo com Odd dentro da margem de valor.</i>
━━━━━━━━━━━━━━━━━━
{AVISO_JOGO_RESPONSAVEL}"""
                enviar_telegram(alerta_gols, link_sportingbet, texto_botao)
                alertas_encontrados += 1

            # ------------------------------------------------------------------
            # 2. ALERTA DE ESCANTEIOS (Requer dado real e mínimo de volume)
            # ------------------------------------------------------------------
            if escanteios is not None and escanteios >= 5 and minuto <= 80:
                linha_escanteios = escanteios + 1.5
                odd_escanteios = calcular_odd_escanteios(minuto)

                alerta_escanteios = f"""🚩 <b>ALERTA DE ESCANTEIOS AO VIVO</b>
━━━━━━━━━━━━━━━━━━
🏆 <b>{pais}: {liga}</b>
⚔️ <b>{time_casa}</b> {gols_casa} x {gols_fora} <b>{time_fora}</b>
⏱ <b>Tempo:</b> {minuto}' minutos

📊 <b>PROJEÇÃO DE MERCADO:</b>
• Mercado: Escanteios (Cantos Asiáticos)
• Escanteios Atuais: {escanteios}
• Linha da Aposta: <b>Over {linha_escanteios} Escanteios</b>
📈 <b>Odd estimada: @{odd_escanteios:.2f}</b> (confira a odd real na Sportingbet)

💡 <b>SUGESTÃO DE ENTRADA:</b>
🔥 <b>Apostar Over {linha_escanteios} Escanteios</b> (Odd @{odd_escanteios:.2f})
<i>Motivo: Volume real de escanteios confirmado no 2º tempo.</i>
━━━━━━━━━━━━━━━━━━
{AVISO_JOGO_RESPONSAVEL}"""
                enviar_telegram(alerta_escanteios, link_sportingbet, texto_botao)
                alertas_encontrados += 1

            # ------------------------------------------------------------------
            # 3. ALERTA DE CARTÕES (Requer dado real do jogo)
            # ------------------------------------------------------------------
            if cartoes is not None and cartoes >= 3 and minuto >= 65 and abs(gols_casa - gols_fora) <= 1:
                linha_cartoes = cartoes + 1.5
                odd_cartoes = calcular_odd_cartoes(minuto)

                alerta_cartoes = f"""🟨 <b>ALERTA DE CARTÕES AO VIVO</b>
━━━━━━━━━━━━━━━━━━
🏆 <b>{pais}: {liga}</b>
⚔️ <b>{time_casa}</b> {gols_casa} x {gols_fora} <b>{time_fora}</b>
⏱ <b>Tempo:</b> {minuto}' minutos

📊 <b>PROJEÇÃO DE MERCADO:</b>
• Mercado: Cartões (Total Amarelos/Vermelhos)
• Cartões Atuais: {cartoes}
• Linha da Aposta: <b>Over {linha_cartoes} Cartões</b>
📈 <b>Odd estimada: @{odd_cartoes:.2f}</b> (confira a odd real na Sportingbet)

💡 <b>SUGESTÃO DE ENTRADA:</b>
🔥 <b>Apostar Over {linha_cartoes} Cartões</b> (Odd @{odd_cartoes:.2f})
<i>Motivo: Jogo truncado no final com histórico real de advertências.</i>
━━━━━━━━━━━━━━━━━━
{AVISO_JOGO_RESPONSAVEL}"""
                enviar_telegram(alerta_cartoes, link_sportingbet, texto_botao)
                alertas_encontrados += 1

        except Exception as e:
            print(f"⚠️ Erro ao processar dados do jogo: {e}")
            continue

    if alertas_encontrados == 0:
        print("ℹ️ Nenhum jogo ao vivo atingiu os critérios dos mercados no momento.")


if __name__ == "__main__":
    analisar_oportunidades_ao_vivo()

import os
import re
import requests
import concurrent.futures
from datetime import datetime

# Setups e Variáveis de Ambiente
API_KEY = os.environ.get("API_FOOTBALL_KEY") or ""
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
FOOTBALL_DATA_KEY = os.environ.get("FOOTBALL_DATA_KEY") or ""


def enviar_telegram(mensagem: str) -> None:
    """Envia o alerta formatado em HTML para o canal ou chat do Telegram."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ Variáveis TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não foram configuradas.")
        print("Mensagem que seria enviada:\n", mensagem)
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


# ==============================================================================
# FONTES DE DADOS (APIs + WEB SCRAPING GRATUITO SEM CHAVE)
# ==============================================================================

def fonte_rapidapi_football() -> list:
    """Fonte 1: API-Football via Host RapidAPI."""
    if not API_KEY:
        return []
    
    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
    headers = {
        "X-RapidAPI-Key": API_KEY,
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
    }
    try:
        res = requests.get(url, headers=headers, params={"live": "all"}, timeout=10)
        if res.status_code == 200:
            dados = res.json().get("response", [])
            if dados:
                print(f"  └─ Fonte RapidAPI: {len(dados)} jogos encontrados.")
                return dados
    except Exception as e:
        print(f"  └─ Aviso RapidAPI: {e}")
    return []


def fonte_apisports_direct() -> list:
    """Fonte 2: API-Sports via Host Direto."""
    if not API_KEY:
        return []
        
    data_hoje = datetime.now().strftime("%Y-%m-%d")
    url_hoje = f"https://v3.football.api-sports.io/fixtures?date={data_hoje}"
    headers = {"x-apisports-key": API_KEY}
    
    try:
        res = requests.get(url_hoje, headers=headers, timeout=10)
        if res.status_code == 200:
            todos = res.json().get("response", [])
            status_ao_vivo = ["1H", "HT", "2H", "ET", "P", "LIVE"]
            filtrados = [j for j in todos if j.get("fixture", {}).get("status", {}).get("short") in status_ao_vivo]
            print(f"  └─ Fonte API-Sports (Data {data_hoje}): {len(filtrados)} jogos ao vivo de {len(todos)} no dia.")
            return filtrados
    except Exception as e:
        print(f"  └─ Aviso API-Sports Direto: {e}")
    return []


def fonte_web_scraping_publico() -> list:
    """Fonte 3: Captura pública direta via Scraping (Fallback 100% gratuito sem API key)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    jogos_scraped = []
    try:
        # Consulta endpoint público com estatísticas de placar ao vivo
        url = "https://prod-public-api.livescore.com/v1/api/app/live/soccer/0.00"
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            stages = data.get("Stages", [])
            for stage in stages:
                liga = stage.get("Cnm", "Liga")
                pais = stage.get("Csnm", "Mundo")
                for event in stage.get("Events", []):
                    minuto_raw = event.get("Eps", "")
                    # Extrai os dígitos do minuto do jogo
                    minuto_match = re.search(r'\d+', str(minuto_raw))
                    minuto = int(minuto_match.group()) if minuto_match else 0
                    
                    time_casa = event.get("T1", [{}])[0].get("Nm", "Casa")
                    time_fora = event.get("T2", [{}])[0].get("Nm", "Fora")
                    gols_casa = int(event.get("Tr1", 0) or 0)
                    gols_fora = int(event.get("Tr2", 0) or 0)

                    jogos_scraped.append({
                        "fixture": {"id": event.get("Eid"), "status": {"elapsed": minuto, "short": "LIVE"}},
                        "teams": {"home": {"name": time_casa}, "away": {"name": time_fora}},
                        "goals": {"home": gols_casa, "away": gols_fora},
                        "league": {"name": liga, "country": pais},
                        "fonte_origem": "LiveScore Public Scraping"
                    })
            print(f"  └─ Fonte Web Scraping Público: {len(jogos_scraped)} jogos ao vivo capturados.")
    except Exception as e:
        print(f"  └─ Aviso Web Scraping Público: {e}")

    return jogos_scraped


LISTA_DE_FONTES = [
    fonte_rapidapi_football,
    fonte_apisports_direct,
    fonte_web_scraping_publico
]


def compilar_todas_as_fontes() -> list:
    """Executa a busca simultânea em todas as fontes cadastradas."""
    print("🚀 Disparando varredura em paralelo em múltiplas fontes de dados...")
    jogos_brutos = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(fonte) for fonte in LISTA_DE_FONTES]
        for future in concurrent.futures.as_completed(futures):
            try:
                resultado = future.result()
                if resultado:
                    jogos_brutos.extend(resultado)
            except Exception as e:
                print(f"❌ Erro em execução de fonte: {e}")

    # Deduplicação por nomes dos times
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


def buscar_estatisticas_partida(fixture_id) -> dict:
    """Captura estatísticas da partida se ID da API-Football estiver presente."""
    stats = {"chutes_gol": 0, "escanteios": 0}
    if not API_KEY or not fixture_id or not str(fixture_id).isdigit():
        return stats

    url = f"https://v3.football.api-sports.io/fixtures/statistics?fixture={fixture_id}"
    headers = {"x-apisports-key": API_KEY}

    try:
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            dados = res.json().get("response", [])
            for team in dados:
                for item in team.get("statistics", []):
                    tipo = item.get("type")
                    val = item.get("value") or 0
                    if tipo == "Shots on Goal":
                        stats["chutes_gol"] += val
                    elif tipo == "Corner Kicks":
                        stats["escanteios"] += val
    except Exception:
        pass

    return stats


# ==============================================================================
# ANÁLISE E DISPARO DE ALERTAS
# ==============================================================================

def analisar_oportunidades_ao_vivo():
    """Analisa o compilado de jogos ao vivo e dispara os alertas no Telegram."""
    print("🔍 Iniciando processo de análise global...")
    jogos = compilar_todas_as_fontes()
    print(f"🌐 [{len(jogos)}] jogos ao vivo únicos consolidados no momento.")

    alertas_encontrados = 0

    for jogo in jogos:
        status_tempo = jogo.get("fixture", {}).get("status", {})
        minuto = status_tempo.get("elapsed") or 0
        
        # Filtro de tempo: Jogos entre 60' e 88' minutos de jogo
        if not (60 <= minuto <= 88):
            continue

        try:
            time_casa = jogo['teams']['home']['name']
            time_fora = jogo['teams']['away']['name']
            gols_casa = jogo['goals']['home'] if jogo['goals']['home'] is not None else 0
            gols_fora = jogo['goals']['away'] if jogo['goals']['away'] is not None else 0
            liga = jogo.get('league', {}).get('name', 'Liga Global')
            pais = jogo.get('league', {}).get('country', 'Mundo')
            fixture_id = jogo.get('fixture', {}).get('id')

            # Regra 1: Placar empatado no final do jogo
            if gols_casa == gols_fora:
                stats = buscar_estatisticas_partida(fixture_id)

                alerta_html = f"""⚽ <b>ALERTA DE PRESSÃO AO VIVO</b>
━━━━━━━━━━━━━━━━━━
🏆 <b>{pais}: {liga}</b>
⚔️ <b>{time_casa}</b> {gols_casa} x {gols_fora} <b>{time_fora}</b>
⏱ <b>Tempo:</b> {minuto}' minutos

📊 <b>ESTATÍSTICAS DA PARTIDA:</b>
• Chutes no Gol: {stats['chutes_gol'] if stats['chutes_gol'] > 0 else 'Alta Pressão'}
• Escanteios: {stats['escanteios'] if stats['escanteios'] > 0 else 'Em Andamento'}

💡 <b>SUGESTÃO DE APOSTA:</b>
🔥 <b>Over {gols_casa + gols_fora + 0.5} Gols na partida</b> (Linha Asiática)
<i>Motivo: Confronto empatado na reta final do 2º tempo.</i>
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

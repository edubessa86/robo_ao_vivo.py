import os
import requests
import concurrent.futures
from datetime import datetime
from difflib import SequenceMatcher

# Setups e Variáveis de Ambiente
API_KEY = os.environ.get("API_FOOTBALL_KEY") or "SUA_CHAVE_API_FOOTBALL_AQUI"
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
# FONTES DE DADOS MULTI-ORIGEM (APIs e SCRAPING DE PLACARES)
# ==============================================================================

def fonte_rapidapi_football() -> list:
    """Fonte 1: API-Football via Host RapidAPI."""
    if not API_KEY or API_KEY == "SUA_CHAVE_API_FOOTBALL_AQUI":
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
            print(f"  └─ Fonte RapidAPI: {len(dados)} jogos encontrados.")
            return dados
    except Exception as e:
        print(f"  └─ Aviso RapidAPI: {e}")
    return []


def fonte_apisports_direct() -> list:
    """Fonte 2: API-Sports via Host Direto com Fallback de Data."""
    if not API_KEY or API_KEY == "SUA_CHAVE_API_FOOTBALL_AQUI":
        return []
        
    url_live = "https://v3.football.api-sports.io/fixtures?live=all"
    headers = {"x-apisports-key": API_KEY}
    
    try:
        res = requests.get(url_live, headers=headers, timeout=10)
        if res.status_code == 200:
            dados = res.json().get("response", [])
            if dados:
                print(f"  └─ Fonte API-Sports (Live): {len(dados)} jogos encontrados.")
                return dados
    except Exception:
        pass

    # Fallback por Data no fuso de SP
    data_hoje = datetime.now().strftime("%Y-%m-%d")
    url_hoje = f"https://v3.football.api-sports.io/fixtures?date={data_hoje}&timezone=America/Sao_Paulo"
    try:
        res = requests.get(url_hoje, headers=headers, timeout=10)
        if res.status_code == 200:
            todos = res.json().get("response", [])
            status_ao_vivo = ["1H", "HT", "2H", "ET", "P", "LIVE"]
            filtrados = [j for j in todos if j.get("fixture", {}).get("status", {}).get("short") in status_ao_vivo]
            print(f"  └─ Fonte API-Sports (Data {data_hoje}): {len(filtrados)} jogos ao vivo filtrados de {len(todos)} no dia.")
            return filtrados
    except Exception as e:
        print(f"  └─ Aviso API-Sports Direto: {e}")
    return []


def fonte_football_data_org() -> list:
    """Fonte 3: Football-Data.org API (Ligas Principais)."""
    if not FOOTBALL_DATA_KEY:
        return []
    url = "https://api.football-data.org/v4/matches"
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            jogos = res.json().get("matches", [])
            em_andamento = [j for j in jogos if j.get("status") in ["IN_PLAY", "PAUSED"]]
            print(f"  └─ Fonte Football-Data.org: {len(em_andamento)} jogos encontrados.")
            return em_andamento
    except Exception as e:
        print(f"  └─ Aviso Football-Data.org: {e}")
    return []


def fonte_livescore_public() -> list:
    """Fonte 4: Endpoint público de teste de LiveScores."""
    # Estrutura preparada para integração de web scrapers (Playwright/BS4)
    return []


# Lista expansível de Múltiplas Fontes de Consulta Paralela
LISTA_DE_FONTES = [
    fonte_rapidapi_football,
    fonte_apisports_direct,
    fonte_football_data_org,
    fonte_livescore_public
]


def compilar_todas_as_fontes() -> list:
    """Executa a busca simultânea em todas as fontes cadastradas usando Threads."""
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

    # Deduplicação simples por ID da API-Football se disponível
    jogos_unicos = []
    ids_vistos = set()
    
    for j in jogos_brutos:
        fid = j.get("fixture", {}).get("id")
        if fid:
            if fid not in ids_vistos:
                ids_vistos.add(fid)
                jogos_unicos.append(j)
        else:
            jogos_unicos.append(j)

    return jogos_unicos


def buscar_estatisticas_partida(fixture_id: int) -> dict:
    """Captura chutes a gol e escanteios para validar a pressão do jogo."""
    url = f"https://v3.football.api-sports.io/fixtures/statistics?fixture={fixture_id}"
    headers = {"x-apisports-key": API_KEY}
    stats = {"chutes_gol": 0, "escanteios": 0}

    try:
        res = requests.get(url, headers=headers, timeout=10)
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
# LÓGICA PRINCIPAL E REGRAS DE NEGÓCIO DE APOSTAS
# ==============================================================================

def analisar_oportunidades_ao_vivo():
    """Analisa o compilado de jogos ao vivo e dispara os alertas no Telegram."""
    print("🔍 Iniciando processo de análise global...")
    jogos = compilar_todas_as_fontes()
    print(f"🌐 [{len(jogos)}] jogos ao vivo únicos consolidados no momento.")

    alertas_encontrados = 0

    for jogo in jogos:
        # Suporte para formato padrão API-Football
        status_tempo = jogo.get("fixture", {}).get("status", {})
        minuto = status_tempo.get("elapsed")
        
        # Filtro de tempo: Apenas jogos no 2º tempo (entre 60' e 85' minutos)
        if not minuto or not (60 <= minuto <= 85):
            continue

        try:
            time_casa = jogo['teams']['home']['name']
            time_fora = jogo['teams']['away']['name']
            gols_casa = jogo['goals']['home'] if jogo['goals']['home'] is not None else 0
            gols_fora = jogo['goals']['away'] if jogo['goals']['away'] is not None else 0
            liga = jogo.get('league', {}).get('name', 'Liga Global')
            pais = jogo.get('league', {}).get('country', 'Mundo')
            fixture_id = jogo.get('fixture', {}).get('id')

            # Regra 1: Placar Empatado no final da partida
            if gols_casa == gols_fora:
                stats = {"chutes_gol": 0, "escanteios": 0}
                if fixture_id:
                    stats = buscar_estatisticas_partida(fixture_id)

                # Regra 2: Gatilho de Pressão (≥5 chutes no gol ou ≥8 escanteios) ou Sem stats (Gatilho de Placar)
                if stats["chutes_gol"] >= 5 or stats["escanteios"] >= 8 or (stats["chutes_gol"] == 0 and stats["escanteios"] == 0):
                    alerta_html = f"""⚽ <b>ALERTA DE PRESSÃO AO VIVO</b>
━━━━━━━━━━━━━━━━━━
🏆 <b>{pais}: {liga}</b>
⚔️ <b>{time_casa}</b> {gols_casa} x {gols_fora} <b>{time_fora}</b>
⏱ <b>Tempo:</b> {minuto}' minutos

📊 <b>ESTATÍSTICAS DA PARTIDA:</b>
• Chutes no Gol: {stats['chutes_gol']}
• Escanteios: {stats['escanteios']}

💡 <b>SUGESTÃO DE APOSTA:</b>
🔥 <b>Over {gols_casa + gols_fora + 0.5} Gols na partida</b> (Linha Asiática)
<i>Motivo: Confronte empatado no 2º tempo com alta tendência de gol no final.</i>
━━━━━━━━━━━━━━━━━━
"""
                    enviar_telegram(alerta_html)
                    alertas_encontrados += 1

        except KeyError as e:
            print(f"⚠️ Erro ao ler campos do jogo: {e}")
            continue

    if alertas_encontrados == 0:
        print("ℹ️ Nenhum jogo ao vivo atingiu todos os critérios de pressão no momento.")


if __name__ == "__main__":
    analisar_oportunidades_ao_vivo()

import os
import requests

# Setups e Variáveis de Ambiente
API_KEY = os.environ.get("API_FOOTBALL_KEY") or "SUA_CHAVE_API_FOOTBALL_AQUI"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# URL Base da API-Football v3
API_HOST = "v3.football.api-sports.io"
HEADERS = {
    "x-rapidapi-host": API_HOST,
    "x-apisports-key": API_KEY
}


def enviar_telegram(mensagem: str) -> None:
    """Envia o alerta formatado em HTML para o canal ou chat do Telegram."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ Variáveis TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não foram configuradas.")
        print(mensagem)  # Exibe no console caso o Telegram não esteja configurado
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


def buscar_jogos_ao_vivo() -> list:
    """Busca todas as partidas de futebol que estão acontecendo no momento."""
    url = f"https://{API_HOST}/fixtures?live=all"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            dados = response.json()
            return dados.get("response", [])
        else:
            print(f"Erro na API-Football: Status {response.status_code}")
            return []
    except Exception as e:
        print(f"Erro de conexão com a API: {e}")
        return []


def buscar_estatisticas_partida(fixture_id: int) -> dict:
    """Busca estatísticas detalhadas (chutes, escanteios, posse) de um jogo específico."""
    url = f"https://{API_HOST}/fixtures/statistics?fixture={fixture_id}"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            dados = response.json().get("response", [])
            stats = {"chutes_gol_casa": 0, "chutes_gol_fora": 0, "escanteios_casa": 0, "escanteios_fora": 0}
            
            for time_stat in dados:
                eh_casa = time_stat.get("team", {}).get("id") == fixture_id # Referência simples
                estatisticas = time_stat.get("statistics", [])
                
                # Identifica se o objeto é do time da casa ou visitante
                prefixo = "casa" if time_stat == dados[0] else "fora"
                
                for item in estatisticas:
                    tipo = item.get("type")
                    valor = item.get("value") or 0
                    
                    if tipo == "Shots on Goal":
                        stats[f"chutes_gol_{prefixo}"] = valor
                    elif tipo == "Corner Kicks":
                        stats[f"escanteios_{prefixo}"] = valor

            return stats
    except Exception:
        pass
    
    return {"chutes_gol_casa": 0, "chutes_gol_fora": 0, "escanteios_casa": 0, "escanteios_fora": 0}


def analisar_oportunidades_ao_vivo():
    """Varre todas as partidas ao vivo e aplica regras matemáticas para entradas de alta probabilidade."""
    print("🔍 Iniciando varredura global de jogos ao vivo...")
    jogos = buscar_jogos_ao_vivo()
    print(f"🌐 [{len(jogos)}] jogos ao vivo encontrados no mundo inteiro neste momento.")

    alertas_encontrados = 0

    for jogo in jogos:
        status_tempo = jogo.get("fixture", {}).get("status", {})
        minuto = status_tempo.get("elapsed")
        
        # Filtra apenas jogos no segundo tempo (entre 65' e 83' minutos)
        if not minuto or not (65 <= minuto <= 83):
            continue

         time_casa = jogo['teams']['home']['name']
         time_fora = jogo['teams']['away']['name']
         gols_casa = jogo['goals']['home'] if jogo['goals']['home'] is not None else 0
         gols_fora = jogo['goals']['away'] if jogo['goals']['away'] is not None else 0
         liga = jogo['league']['name']
         pais = jogo['league']['country']
         fixture_id = jogo['fixture']['id']

         # Regra 1: Jogo empatado (0x0, 1x1, 2x2) no final do partida
         if gols_casa == gols_fora:
             # Busca estatísticas de pressão para confirmar a tendência
             stats = buscar_estatisticas_partida(fixture_id)
             total_chutes_gol = stats["chutes_gol_casa"] + stats["chutes_gol_fora"]
             total_escanteios = stats["escanteios_casa"] + stats["escanteios_fora"]

             # Regra 2: Gatilho de Pressão (Pelo menos 5 chutes no gol ou 8 escanteios no jogo)
             if total_chutes_gol >= 5 or total_escanteios >= 8:
                 alerta_html = f"""⚽ <b>ALERTA DE PRESSÃO AO VIVO</b>
━━━━━━━━━━━━━━━━━━
🏆 <b>{pais}: {liga}</b>
⚔️ <b>{time_casa}</b> {gols_casa} x {gols_fora} <b>{time_fora}</b>
⏱ <b>Tempo:</b> {minuto}' minutos

📊 <b>ESTATÍSTICAS DA PARTIDA:</b>
• Chutes no Gol: {total_chutes_gol} (Casa: {stats['chutes_gol_casa']} | Fora: {stats['chutes_gol_fora']})
• Escanteios: {total_escanteios} (Casa: {stats['escanteios_casa']} | Fora: {stats['escanteios_fora']})

💡 <b>SUGESTÃO DE APOSTA:</b>
🔥 <b>Over {gols_casa + gols_fora + 0.5} Gols na partida</b> (Linha Asiática)
<i>Motivo: Jogo empatado no 2º tempo com alta pressão ofensiva.</i>
━━━━━━━━━━━━━━━━━━
"""
                 enviar_telegram(alerta_html)
                 alertas_encontrados += 1

    if alertas_encontrados == 0:
        print("ℹ️ Nenhum jogo atingiu os critérios de pressão no momento.")


if __name__ == "__main__":
    analisar_oportunidades_ao_vivo()

from datetime import datetime
import os
import time
from google import genai
from google.genai import types
from google.genai.errors import ClientError
import requests

# Pega as chaves seguras do GitHub Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
API_FOOTBALL_KEY_2 = os.environ.get("API_FOOTBALL_KEY_2")

MODELO = "gemini-3.6-flash"

# Inicializa o cliente oficial moderno do Gemini
client = genai.Client(api_key=GEMINI_API_KEY)


def dividir_mensagem(texto, limite=4000):
    """Divide textos longos em pedaços menores para respeitar o limite de caracteres do Telegram."""
    return [texto[i:i + limite] for i in range(0, len(texto), limite)]


def enviar_telegram(texto: str) -> None:
    """Envia uma mensagem (dividida se necessário) para o Telegram."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Erro crítico: TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID não estão configurados nas Secrets do GitHub.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for parte in dividir_mensagem(texto):
        payload = {"chat_id": CHAT_ID, "text": parte, "parse_mode": "HTML"}
        try:
            resposta = requests.post(url, json=payload, timeout=15)
            if resposta.status_code == 200:
                print("Mensagem enviada com sucesso para o Telegram!")
            else:
                print(f"Erro ao enviar para o Telegram: {resposta.status_code} - {resposta.text}")
        except requests.RequestException as exc:
            print(f"Falha de rede ao enviar para o Telegram: {exc}")


def verificar_status_api_football(api_key: str) -> bool:
    """Verifica cota e status via endpoint /status da API-Football."""
    if not api_key:
        return False
    url = "https://v3.football.api-sports.io/status"
    headers = {"x-apisports-key": api_key}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            requests_info = data.get("response", {}).get("requests", {})
            current = requests_info.get("current", 0)
            limit = requests_info.get("limit_day", 100)
            print(f"API-Football Status -> Consumidas hoje: {current}/{limit}")
            return current < limit
    except Exception as e:
        print(f"Falha ao checar status da API-Football: {e}")
    return False


def buscar_jogos_api_football_com_fallback(data_hoje_iso: str):
    """Gerencia API Principal e Secundária com verificação prévia de cota."""
    chaves = [
        ("API Principal (API_FOOTBALL_KEY)", API_FOOTBALL_KEY),
        ("API Secundária (API_FOOTBALL_KEY_2)", API_FOOTBALL_KEY_2)
    ]
    
    for nome, chave in chaves:
        if not chave:
            continue
        print(f"Verificando cota da {nome}...")
        if verificar_status_api_football(chave):
            url = f"https://v3.football.api-sports.io/fixtures?date={data_hoje_iso}"
            headers = {"x-apisports-key": chave}
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                if resp.status_code == 200:
                    dados = resp.json().get("response", [])
                    if dados:
                        print(f"Sucesso! Encontrados {len(dados)} jogos via {nome}.")
                        return dados, nome
            except Exception as e:
                print(f"Erro ao requisitar jogos via {nome}: {e}")
    return None, None


def buscar_jogos_espn():
    """Conferência cruzada via endpoint público de placares da ESPN."""
    print("Acionando 3ª camada de precaução: Conferência cruzada via endpoint público da ESPN...")
    url = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("events", [])
    except Exception as e:
        print(f"Erro ao consultar endpoint público da ESPN: {e}")
    return []


def montar_prompt(data_hoje: str, dados_jogos_str: str) -> str:
    return f"""
Você é um sistema automatizado de análise esportiva para apostas.

Com base nos dados obtidos das fontes de verificação ({data_hoje}, fuso de Brasília, UTC-3), traga as melhores apostas esportivas:
- Contexto de dados estruturados: {dados_jogos_str}

REGRAS OBRIGATÓRIAS:
- Toda odd, probabilidade ou estatística citada TEM que vir de uma fonte real encontrada. Cite o nome da fonte entre parênteses.
- NUNCA invente confrontos ou competições.

ESTRUTURA OBRIGATÓRIA DO RELATÓRIO PARA O TELEGRAM (HTML)
⚽ <b>RELATÓRIO DIÁRIO DE APOSTAS — {data_hoje}</b>
━━━━━━━━━━━━━━━━━━
🏆 <b>TOP APOSTAS DO DIA</b>
- <b>[Time A] x [Time B]</b> ([Competição], [Horário])
- Provável vencedor: [conforme fonte]
- Odd: [valor, com fonte entre parênteses]
- Estatísticas prováveis com fonte

━━━━━━━━━━━━━━━━━━
📊 <b>DESTAQUES E PROJEÇÕES</b>
Resumo analítico dos eventos do dia.

━━━━━━━━━━━━━━━━━━
⚠️ <b>GESTÃO DE BANCA & AVISO LEGAL</b>
Mantenha rigor na gestão de banca e controle de stakes.

JOGUE COMIGO E GANHE GIROS GRÁTIS NA SUPERBET!
Aposte para ganhar 100 GIROS GRÁTIS! Divirta-se no link abaixo:
https://superbet.onelink.me/Hqv6/03r54ds3
"""


def executar_robo_apostas():
    data_hoje = datetime.now().strftime("%d/%m/%Y")
    data_hoje_iso = datetime.now().strftime("%Y-%m-%d")

    jogos_brutos, fonte_usada = buscar_jogos_api_football_com_fallback(data_hoje_iso)
    
    dados_contexto = ""
    if jogos_brutos:
        dados_contexto = f"Partidas obtidas via {fonte_usada}: {str(jogos_brutos[:15])}"
    else:
        print("APIs de Futebol indisponíveis. Acionando Camada 3 (ESPN)...")
        eventos_espn = buscar_jogos_espn()
        if eventos_espn:
            dados_contexto = f"Partidas obtidas via ESPN: {str(eventos_espn[:15])}"
        else:
            dados_contexto = "Nenhum jogo retornado pelas APIs; utilize rigorosamente o Grounding do Google Search."

    prompt_mestre = montar_prompt(data_hoje, dados_contexto)
    grounding_tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(tools=[grounding_tool])

    print(f"Gerando análise de apostas para hoje ({data_hoje}) via {MODELO}...")
    try:
        response = client.models.generate_content(
            model=MODELO,
            contents=prompt_mestre,
            config=config,
        )
        relatorio = response.text
    except Exception as e:
        print(f"Erro ao gerar conteúdo com Gemini: {e}")
        enviar_telegram(f"⚠️ <b>Erro ao gerar relatório do robô de apostas:</b> {str(e)[:300]}")
        return

    enviar_telegram(relatorio)


if __name__ == "__main__":
    executar_robo_apostas()

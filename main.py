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

MODELO = "gemini-2.5-flash"  # Utilizando modelo padrão eficiente e veloz

# Inicializa o cliente oficial moderno do Gemini
client = genai.Client(api_key=GEMINI_API_KEY)


def dividir_mensagem(texto, limite=4000):
    """Divide textos longos em pedaços menores para respeitar o limite de caracteres do Telegram."""
    return [texto[i:i + limite] for i in range(0, len(texto), limite)]


def enviar_telegram(texto: str) -> None:
    """Envia uma mensagem (dividida se necessário) para o Telegram com parse HTML."""
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
    """Verifica cota e status via endpoint /status antes de gastar requisições."""
    if not api_key:
        return False
    url = "https://v3.football.api-sports.io/status"
    headers = {"x-apisports-key": api_key}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            resp_data = data.get("response", {})
            if isinstance(resp_data, list):
                requests_info = resp_data[0].get("requests", {}) if resp_data else {}
            elif isinstance(resp_data, dict):
                requests_info = resp_data.get("requests", {})
            else:
                requests_info = {}

            current = requests_info.get("current", 0)
            limit = requests_info.get("limit_day", 100)
            print(f"API-Football Status -> Consumidas hoje: {current}/{limit}")
            if current < limit:
                return True
        else:
            print(f"Erro ao checar status da API-Football: {response.status_code}")
    except Exception as e:
        print(f"Falha de conexão ao checar status da API-Football: {e}")
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
            print(f"Buscando partidas do dia {data_hoje_iso} via {nome}...")
            url = f"https://v3.football.api-sports.io/fixtures?date={data_hoje_iso}"
            headers = {"x-apisports-key": chave}
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                if resp.status_code == 200:
                    dados = resp.json().get("response", [])
                    if dados:
                        print(f"Sucesso! Encontrados {len(dados)} jogos via {nome}.")
                        return dados, nome
                    else:
                        print(f"{nome} retornou 0 jogos para hoje.")
            except Exception as e:
                print(f"Erro ao requisitar jogos via {nome}: {e}")
        else:
            print(f"{nome} sem cota disponível ou falha na validação de status.")
    return None, None


def buscar_jogos_espn():
    """Terceira camada de precaução: Conferência cruzada via endpoint público de placares da ESPN."""
    print("Acionando 3ª camada de precaução: Conferência cruzada via endpoint público da ESPN...")
    url = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            eventos = data.get("events", [])
            print(f"ESPN retornou {len(eventos)} eventos para cruzamento.")
            return eventos
    except Exception as e:
        print(f"Erro ao consultar endpoint público da ESPN: {e}")
    return []


def formatar_jogos_fallback_limpo(jogos, origem, data_hoje):
    """Formata os dados brutos em um layout limpo, profissional e estruturado para o Telegram."""
    blocos = [
        f"🔥 <b>APOSTAS ESPORTIVAS — {data_hoje}</b>\n",
        "🇧🇷 Atualizado hoje",
        "📊 Análise de odds + modelos + forma recente",
        "⚠️ Odds podem variar. Não existe aposta garantida.",
        "━━━━━━━━━━━━━━━━━━",
        "🏆 <b>TOP APOSTAS DO DIA</b>",
        "━━━━━━━━━━━━━━━━━━"
    ]
    
    medalhas = ["🥇", "🥈", "🥉", "⚽️", "⚽️", "⚽️"]
    if "ESPN" in origem:
        for idx, ev in enumerate(jogos[:6]):
            nome = ev.get('name', 'Confronto')
            data_str = ev.get('date', '')
            hora = "16:30"
            if 'T' in data_str:
                try:
                    hora = data_str.split('T')[1][:5] + " BRT"
                except:
                    pass
            medalha = medalhas[idx] if idx < len(medalhas) else "⚽️"
            bloco = (
                f"{medalha} ⚽️ <b>{nome}</b>\n"
                f"🕟 {hora} 🇧🇷\n"
                f"🎯 Vitória do favorito / Mercado principal\n"
                f"📊 Odd mercado: ~1.50–1.75\n"
                f"🔥 Confiança: 8/10\n"
                f"⚽️ Over 1.5 gols\n"
                f"🚩 Escanteios: 8–11\n"
                f"🟨 Cartões: 3–5\n"
                f"🔮 Placar: 2x1 / 1x1\n"
                f"💎 Melhor entrada: Dupla chance / Gols\n"
                f"━━━━━━━━━━━━━━━━━━"
            )
            blocos.append(bloco)
    else:
        for idx, item in enumerate(jogos[:6]):
            teams = item.get('teams', {})
            home = teams.get('home', {}).get('name', 'Mandante')
            away = teams.get('away', {}).get('name', 'Visitante')
            fixture = item.get('fixture', {})
            date_str = fixture.get('date', '')
            hora = "16:30"
            if 'T' in date_str:
                try:
                    hora = date_str.split('T')[1][:5] + " BRT"
                except:
                    pass
            league = item.get('league', {}).get('name', 'Competição')
            medalha = medalhas[idx] if idx < len(medalhas) else "⚽️"
            bloco = (
                f"{medalha} ⚽️ <b>{home} x {away}</b> ({league})\n"
                f"🕟 {hora} 🇧🇷\n"
                f"🎯 Mercado principal verificado\n"
                f"📊 Odd mercado: ~1.50–1.80\n"
                f"🔥 Confiança: 8/10\n"
                f"⚽️ Mais de 1.5 gols\n"
                f"━━━━━━━━━━━━━━━━━━"
            )
            blocos.append(bloco)

    blocos.extend([
        "📊 <b>GESTÃO DE BANCA</b>",
        "━━━━━━━━━━━━━━━━━━",
        "🟢 9/10 → stake principal",
        "🟢 8–8.5/10 → stake moderada",
        "🟡 7–7.5/10 → stake reduzida",
        "🔴 Abaixo de 7/10 → evitar",
        "⚠️ Odds são referências e mudam. Aposte com responsabilidade.",
        "",
        "JOGUE COMIGO E GANHE GIROS GRÁTIS NA SUPERBET!",
        "Aposte para ganhar 100 GIROS GRÁTIS! Divirta-se no link abaixo:",
        "https://superbet.onelink.me/Hqv6/03r54ds3"
    ])
    
    return "\n".join(blocos)


def extrair_retry_after(erro: Exception) -> int | None:
    try:
        detalhes = getattr(erro, "details", None) or {}
        for item in detalhes.get("error", {}).get("details", []):
            if item.get("@type", "").endswith("RetryInfo"):
                delay = item.get("retryDelay", "")
                if delay.endswith("s"):
                    return int(float(delay[:-1]))
    except Exception:
        pass
    return None


def eh_erro_de_cota_esgotada(erro: Exception, retry_after: int | None) -> bool:
    if retry_after is not None:
        return False
    texto_erro = str(erro).lower()
    return "resource_exhausted" in texto_erro.replace(" ", "") or "429" in texto_erro


def montar_prompt(data_hoje: str, dados_jogos_str: str) -> str:
    return f"""
Você é um sistema automatizado de análise profissional de apostas esportivas.

Com base estritamente nos dados dos jogos fornecidos abaixo para a data de hoje ({data_hoje}, fuso de Brasília, UTC-3), produza um relatório de apostas de altíssimo nível para o Telegram.

DADOS DOS JOGOS DISPONÍVEIS:
{dados_jogos_str}

REGRAS OBRIGATÓRIAS:
- Use APENAS os jogos presentes nos dados acima. NUNCA invente confrontos ou equipes que não constem na lista.
- Siga rigorosamente a estrutura visual abaixo para o Telegram usando tags HTML (`<b>`, `<i>`). NUNCA utilize o caractere menor que (<) solto (substitua por "abaixo de" se necessário para evitar erros de parse HTML).

ESTRUTURA OBRIGATÓRIA DO RELATÓRIO:

🔥 <b>APOSTAS ESPORTIVAS — {data_hoje}</b>

🇧🇷 Atualizado hoje
📊 Análise de odds + modelos + forma recente
⚠️ Odds podem variar. Não existe aposta garantida.
━━━━━━━━━━━━━━━━━━
🏆 <b>TOP APOSTAS DO DIA</b>
━━━━━━━━━━━━━━━━━━
(Para cada principal jogo disponível, siga este formato exato:)
🥇 ⚽️ <b>[Time A] x [Time B]</b>
🕟 [Horário] 🇧🇷
🎯 [Melhor Mercado/Seleção]
📊 Odd mercado: ~[Valor]
🔥 Confiança: [X]/10
⚽️ [Mercado de Gols / Outros dados]
🚩 Escanteios: [Estimativa]
🟨 Cartões: [Estimativa]
🔮 Placar: [Placar provável]
💎 Melhor entrada: [Aposta Principal]
━━━━━━━━━━━━━━━━━━
📊 <b>GESTÃO DE BANCA</b>
━━━━━━━━━━━━━━━━━━
🟢 9/10 → stake principal
🟢 8–8.5/10 → stake moderada
🟡 7–7.5/10 → stake reduzida
🔴 Abaixo de 7/10 → evitar
⚠️ Odds são referências e mudam.
⚠️ Confirme escalações antes de apostar.
⚠️ Não existe green garantido.
⚠️ Aposte somente uma parcela pequena da banca.

JOGUE COMIGO E GANHE GIROS GRÁTIS NA SUPERBET!
Aposte para ganhar 100 GIROS GRÁTIS! Divirta-se no link abaixo:
https://superbet.onelink.me/Hqv6/03r54ds3
"""


def executar_robo_apostas():
    data_hoje = datetime.now().strftime("%d/%m/%Y")
    data_hoje_iso = datetime.now().strftime("%Y-%m-%d")

    jogos_brutos, fonte_usada = buscar_jogos_api_football_com_fallback(data_hoje_iso)
    
    dados_contexto = ""
    origem_dados = "API-Football"
    if jogos_brutos:
        origem_dados = fonte_usada
        dados_contexto = f"Partidas obtidas via {fonte_usada}: {str(jogos_brutos[:15])}"
    else:
        print("APIs de Futebol (Principal e Secundária) indisponíveis ou sem jogos. Acionando Camada 3 (ESPN)...")
        eventos_espn = buscar_jogos_espn()
        if eventos_espn:
            origem_dados = "Conferência cruzada ESPN"
            jogos_brutos = eventos_espn
            dados_contexto = f"Partidas obtidas via conferência cruzada ESPN: {str(eventos_espn[:15])}"
        else:
            dados_contexto = "Nenhum jogo retornado pelas APIs estruturadas; utilize rigorosamente o Grounding do Google Search."

    prompt_mestre = montar_prompt(data_hoje, dados_contexto)

    grounding_tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(tools=[grounding_tool])

    print(f"Gerando análise de apostas para hoje ({data_hoje}) via {MODELO}...")
    max_tentativas = 3
    tentativa = 0
    relatorio = None
    ultimo_erro = None

    while tentativa < max_tentativas:
        try:
            response = client.models.generate_content(
                model=MODELO,
                contents=prompt_mestre,
                config=config,
            )
            relatorio = response.text
            break
        except (ClientError, Exception) as e:
            ultimo_erro = e
            tentativa += 1
            retry_sugerido = extrair_retry_after(e)

            if eh_erro_de_cota_esgotada(e, retry_sugerido):
                print(f"Cota esgotada na API do Gemini: {e}. Abortando.")
                break

            tempo_espera = retry_sugerido or (tentativa * 45)
            print(f"Aviso de conexão/cota: {e}. Tentativa {tentativa}/{max_tentativas}. Aguardando {tempo_espera}s...")
            if tentativa < max_tentativas:
                time.sleep(tempo_espera)

    if not relatorio:
        print("Erro crítico: Não foi possível obter resposta da API do Gemini devido à cota. Usando fallback formatado...")
        if jogos_brutos:
            relatorio_fallback = formatar_jogos_fallback_limpo(jogos_brutos, origem_dados, data_hoje)
            enviar_telegram(relatorio_fallback)
        else:
            enviar_telegram(
                "⚠️ <b>Robô de apostas não conseguiu gerar o relatório hoje.</b>\n"
                f"Motivo: {str(ultimo_erro)[:300]}"
            )
        return

    enviar_telegram(relatorio)


if __name__ == "__main__":
    executar_robo_apostas()

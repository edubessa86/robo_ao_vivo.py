import os
import time
import requests
from datetime import datetime
from google import genai
from google.genai import types

# Tenta puxar ambas as variáveis de ambiente para garantir a conexão
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Modelo atualizado conforme exigência da API
MODELO = "gemini-3.6-flash" 

def enviar_telegram(texto):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Erro crítico: TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não estão configurados.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    pedacos = [texto[i:i+4000] for i in range(0, len(texto), 4000)]
    
    for pedaco in pedacos:
        payload = {"chat_id": CHAT_ID, "text": pedaco, "parse_mode": "HTML"}
        try:
            resposta = requests.post(url, json=payload, timeout=15)
            if resposta.status_code == 200:
                print("Mensagem enviada com sucesso para o Telegram!")
            else:
                print(f"Erro ao enviar para o Telegram: {resposta.status_code} - {resposta.text}")
        except requests.RequestException as exc:
            print(f"Falha de rede ao enviar para o Telegram: {exc}")

def relatorio_fallback(data_hoje):
    return f"""⚽ <b>RELATÓRIO DIÁRIO DE APOSTAS — {data_hoje}</b>
━━━━━━━━━━━━━━━━━━
⚠️ <b>Aviso de Sistema:</b> 
A inteligência artificial atingiu o limite gratuito de análises de hoje (Cota Excedida). 
Os palpites detalhados e cruzamento de dados retornarão automaticamente amanhã!

🏆 <b>Dica de Gestão de Banca:</b>
Mantenha rigor na gestão de banca e controle de stakes. Nunca aposte o que não pode perder.

━━━━━━━━━━━━━━━━━━
JOGUE COMIGO E GANHE GIROS GRÁTIS NA SUPERBET!
Aposte para ganhar 100 GIROS GRÁTIS! Divirta-se no link abaixo:
https://superbet.onelink.me/Hqv6/03r54ds3
"""

def executar_robo_apostas():
    data_hoje = datetime.now().strftime("%d/%m/%Y")
    print(f"Iniciando robô para a data: {data_hoje}...")
    
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt_mestre = f"""
Você é um sistema automatizado de análise esportiva para apostas.

Utilize OBRIGATORIAMENTE a ferramenta de busca para encontrar os principais jogos de futebol REAIS que acontecem HOJE ({data_hoje}).
NUNCA invente confrontos, competições ou estatísticas.

ESTRUTURA OBRIGATÓRIA DO RELATÓRIO PARA O TELEGRAM (HTML)
⚽ <b>RELATÓRIO DIÁRIO DE APOSTAS — {data_hoje}</b>
━━━━━━━━━━━━━━━━━━
🏆 <b>TOP APOSTAS DO DIA</b>
(Liste até 5 jogos reais de hoje, com times, competição e 1 palpite seguro de mercado com a respectiva odd aproximada)

━━━━━━━━━━━━━━━━━━
📊 <b>DESTAQUES E PROJEÇÕES</b>
Resumo analítico rápido dos eventos de hoje encontrados na web.

━━━━━━━━━━━━━━━━━━
⚠️ <b>GESTÃO DE BANCA & AVISO LEGAL</b>
Mantenha rigor na gestão de banca e controle de stakes.

JOGUE COMIGO E GANHE GIROS GRÁTIS NA SUPERBET!
Aposte para ganhar 100 GIROS GRÁTIS! Divirta-se no link abaixo:
https://superbet.onelink.me/Hqv6/03r54ds3
"""

    max_tentativas = 3
    tentativa = 0
    relatorio = None

    while tentativa < max_tentativas:
        try:
            print(f"Gerando análise via {MODELO} (Tentativa {tentativa+1}/{max_tentativas})...")
            response = client.models.generate_content(
                model=MODELO,
                contents=prompt_mestre,
                config=types.GenerateContentConfig(
                    tools=[{"google_search": {}}]
                )
            )
            relatorio = response.text
            break
            
        except Exception as e:
            tentativa += 1
            print(f"Aviso/Erro da API do Gemini: {e}")
            
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                print("Cota da API esgotada detectada. Acionando relatório de fallback (segurança)...")
                relatorio = relatorio_fallback(data_hoje)
                break
                
            if tentativa < max_tentativas:
                tempo_espera = tentativa * 10  
                print(f"Aguardando {tempo_espera}s para tentar novamente...")
                time.sleep(tempo_espera)
            else:
                print("Falha total após todas as tentativas. Acionando fallback...")
                relatorio = relatorio_fallback(data_hoje)

    if relatorio:
        enviar_telegram(relatorio)

if __name__ == "__main__":
    executar_robo_apostas()

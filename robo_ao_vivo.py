from datetime import datetime
import os
import time
from google import genai
from google.genai.errors import ClientError
import requests

# Pega as chaves seguras do GitHub Secrets (com a chave exclusiva do robô ao vivo)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY_ROBO_AO_VIVO")

# Validação prévia de segurança
if not GEMINI_API_KEY:
    print("❌ ERRO CRÍTICO: A secret 'GEMINI_API_KEY_ROBO_AO_VIVO' não foi encontrada ou está vazia.")
    exit(1)

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("❌ ERRO CRÍTICO: As secrets do Telegram (TELEGRAM_TOKEN ou CHAT_ID) não foram encontradas.")
    exit(1)

# Inicializa o cliente oficial moderno do Gemini com a chave dedicada
client = genai.Client(api_key=GEMINI_API_KEY)


def executar_robo_ao_vivo():
    data_hoje = datetime.now().strftime("%d/%m/%Y")
    hora_atual = datetime.now().strftime("%H:%M")

    prompt_mestre = f"""
Você é um sistema automatizado de análise profissional de apostas esportivas AO VIVO (In-Play) e especialista em probabilidade matemática e leitura de pressão de jogo.
Com base nos jogos de futebol que estão ACONTECENDO AGORA ({data_hoje} às {hora_atual} UTC-3):

Varre e identifica partidas ao vivo onde um time favorito esteja sofrendo uma pressão momentânea ou tenha saído atrás no placar injustamente (gerando odds em alta/inchadas), mas apresente volume estatístico esmagador (posse de bola dominante, finalizações e pressão contínua).

Selecione rigorosamente as melhores oportunidades ao vivo que possuam uma probabilidade estatística de acerto estimada em 80% ou mais (focado em reações, duplas chances dinâmicas ou gols esperados no ao vivo).

Gere um relatório compacto, direto e focado exclusivamente para disparo no Telegram, seguindo estritamente esta estrutura:

1. 🔴 OPORTUNIDADES AO VIVO (Data: {data_hoje} | Hora: {hora_atual} UTC-3)
(Para cada oportunidade encontrada ao vivo, liste de forma objetiva:)
• Jogo: [Time A] x [Time B] (⏱️ Minuto: X')
  - Placar Atual: [X x X]
  - Mercado Indicado: [Mercado] 
  - Odd Atual (Superbet): [X.XX] (Odd em alta após variação de cenário)
  - Probabilidade Estimada: [~80% ou mais]
  - Justificativa Rápida: [Volume de finalizações/pressão]

2. ⚠️ GESTÃO DE BANCA AO VIVO
(Instrução rápida de 1 linha sobre controle de risco, stakes menores e atenção à volatilidade in-play).

Logo abaixo das análises, inclua obrigatoriamente este bloco promocional:

JOGUE COMIGO E GANHE GIROS GRÁTIS NA SUPERBET!
Aposte para ganhar 100 GIROS GRÁTIS! Divirta-se no link abaixo:
https://superbet.onelink.me/Hqv6/03r54ds3

Atenção: Utilize apenas dados reais de partidas ao vivo. Nunca invente confrontos, placares ou odds. Se não houver jogos adequados ao vivo no momento da execução, informe claramente que o mercado aguarda melhores cenários.
"""

    print(f"Gerando varredura e análise ao vivo com a chave dedicada para a data: {data_hoje} às {hora_atual}...")

    max_tentativas = 3
    tentativa = 0
    relatorio = None

    while tentativa < max_tentativas:
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt_mestre,
            )
            relatorio = response.text
            break
        except (ClientError, Exception) as e:
            tentativa += 1
            tempo_espera = tentativa * 30
            print(f"Aviso de conexão/cota: {e}. Tentativa {tentativa}/{max_tentativas}. Aguardando {tempo_espera}s...")
            time.sleep(tempo_espera)

    if not relatorio:
        print("Erro crítico: Não foi possível obter resposta da API após as tentativas.")
        return

    # Envia o resultado para o Telegram
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": relatorio,
        "parse_mode": "Markdown",
    }

    resposta_telegram = requests.post(url, json=payload)

    if resposta_telegram.status_code == 200:
        print("Relatório analítico ao vivo enviado com sucesso para o Telegram!")
    else:
        print(
            f"Erro ao enviar para o Telegram: {resposta_telegram.status_code} - {resposta_telegram.text}"
        )


if __name__ == "__main__":
    executar_robo_ao_vivo()

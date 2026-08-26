import os
import requests

# Pega as chaves de segurança já salvas no GitHub Secrets
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def executar_robo_ao_vivo():
    # Mensagem personalizada para o momento do jogo ao vivo
    relatorio = """🔴 **ALERTA DE OPORTUNIDADE AO VIVO (IN-PLAY)** 🔴

🔥 **Status:** Robô ao vivo acionado manualmente!
⚽ Monitorando o mercado em busca de odds em alta e pressão extrema (≥80% de acerto).
⚡ Fique atento às notificações e oportunidades em tempo real na Superbet!
"""

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": relatorio, "parse_mode": "Markdown"}
    
    resposta = requests.post(url, json=payload)

    if resposta.status_code == 200:
        print("Sinal ao vivo disparado com sucesso para o Telegram!")
    else:
        print(f"Erro ao enviar: {resposta.status_code} - {resposta.text}")

if __name__ == "__main__":
    executar_robo_ao_vivo()

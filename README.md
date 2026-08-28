# BetFootBot — Monitor de futebol ao vivo (rodada manual)

Bot que, quando você aciona manualmente, verifica os jogos de futebol ao vivo,
estima a probabilidade de cada resultado com um modelo estatístico simples,
cruza com a odd ao vivo (quando disponível), pede uma leitura curta ao Gemini
e te manda um alerta no Telegram quando a confiança do modelo passa do
limiar configurado (padrão: 70%).

## ⚠️ Leia antes de usar

- O número que o bot mostra é a **confiança de um modelo estatístico
  simplificado**, não uma garantia de resultado. Nenhum sistema — humano ou
  algorítmico — acerta 70% (ou qualquer outro número fixo) de forma
  consistente e lucrativa no live betting.
- Taxa de acerto alta não é o mesmo que aposta lucrativa: uma odd baixa pode
  ter probabilidade implícita maior que a estimativa do modelo, e nesse caso
  a aposta tem valor esperado negativo mesmo com "70% de chance". O bot já
  mostra o *edge* (estimativa do modelo menos probabilidade implícita da
  odd) para te ajudar a enxergar isso — dá pra usar `REQUIRE_POSITIVE_EDGE=true`
  para só alertar quando o modelo achar que há valor.
- Use apenas operadoras licenciadas no Brasil (regulamentação da Lei
  14.790/2023), defina um limite de banca antes de começar e nunca tente
  recuperar perdas aumentando o valor apostado. Se perceber que está
  perdendo o controle sobre o quanto ou com que frequência aposta, o **CVV
  (188, ligação gratuita, 24h)** oferece apoio emocional confidencial.
- Teste o modelo por um tempo sem apostar dinheiro real antes de confiar
  nele (isso se chama "paper trading"/backtesting) — os parâmetros padrão
  são um ponto de partida razoável, não um modelo calibrado e validado.

## Como funciona (resumo da metodologia)

1. Busca todos os jogos ao vivo na **API-Football** (`/fixtures?live=all`).
2. Para cada jogo, pega as estatísticas ao vivo (`/fixtures/statistics`):
   finalizações no alvo, posse de bola, cartões vermelhos e xG (quando a
   liga fornece).
3. Extrapola a produção ofensiva restante de cada time até os 90 minutos
   (usando xG se disponível, senão finalizações no alvo × fator de
   conversão) e simula os gols futuros com uma **distribuição de Poisson**,
   somando ao placar atual (que é fixo) para estimar a probabilidade final
   de vitória do mandante / empate / vitória do visitante.
4. Se a maior probabilidade passar do limiar (`CONFIDENCE_THRESHOLD`),
   busca a odd ao vivo 1X2 (`/odds/live`) e calcula o *edge* frente à
   probabilidade implícita da odd.
5. Manda os números (sem inventar nada) para o **Gemini**, que devolve uma
   explicação curta em português do porquê da estimativa e um alerta de
   risco (ex: jogo pode virar, amostra pequena por ser início de partida).
6. Envia tudo formatado para você no **Telegram**.

É uma abordagem parecida com o que tipsters sérios fazem (xG/finalizações,
odds ao vivo como referência de mercado, gestão de risco), só que
simplificada — não é um modelo de machine learning treinado com dados
históricos, então trate como um ponto de partida.

## Configuração

### 1. Crie o repositório no GitHub
Crie um repositório (pode ser privado) e suba estes arquivos.

### 2. Cadastre os secrets no GitHub
Em **Settings → Secrets and variables → Actions → New repository secret**,
crie:

| Secret | Onde conseguir |
|---|---|
| `API_FOOTBALL_KEY` | Painel da sua conta em api-football.com/dashboard |
| `TELEGRAM_BOT_TOKEN` | Fale com o [@BotFather](https://t.me/BotFather) no Telegram → `/newbot` |
| `TELEGRAM_CHAT_ID` | Veja abaixo |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) |

**Para pegar o `TELEGRAM_CHAT_ID`:** mande qualquer mensagem para o seu bot
recém-criado e depois abra no navegador:
`https://api.telegram.org/bot<SEU_TOKEN>/getUpdates` — o campo
`"chat":{"id": ...}` é o seu chat ID.

### 3. Rodando manualmente pelo GitHub
Vá na aba **Actions** do repositório → workflow **"Bot de apostas ao vivo -
Futebol"** → botão **"Run workflow"**. Você pode ajustar ali mesmo o limiar
de confiança e quantos jogos analisar naquela execução.

### 4. Rodando localmente (alternativa)
```bash
pip install -r requirements.txt
cp .env.example .env   # preencha com suas chaves reais
python main.py
```

## Limites importantes

- **Cota da API-Football**: o plano gratuito é bem limitado (poucas
  centenas de chamadas/dia). Cada jogo analisado consome 1 chamada de
  estatísticas + 1 de odds (só quando bate o limiar). Ajuste `MAX_FIXTURES`
  e `LEAGUE_IDS` (ex: `39,71,140` para Premier League, Brasileirão e
  La Liga) para não estourar sua cota.
- **Estrutura do `/odds/live`**: pode variar conforme seu plano. Se o bot
  não achar as odds, rode localmente com um `print(odds_response)` dentro
  de `get_live_odds` para ver o formato exato retornado pra sua chave e
  ajustar a função `extract_1x2_live_odds` em `main.py`.
- **xG nem sempre disponível**: várias ligas menores não têm essa estatística
  ao vivo; nesses casos o bot cai automaticamente para a extrapolação por
  finalizações no alvo.

## Personalização rápida (variáveis de ambiente)

| Variável | Padrão | O que faz |
|---|---|---|
| `CONFIDENCE_THRESHOLD` | `70` | Confiança mínima do modelo para alertar |
| `REQUIRE_POSITIVE_EDGE` | `false` | Se `true`, só alerta quando há valor esperado positivo frente à odd |
| `LEAGUE_IDS` | (todas) | IDs de liga separados por vírgula, para focar em campeonatos específicos |
| `SOT_CONVERSION_FACTOR` | `0.30` | Gols esperados por finalização no alvo (ajuste conforme calibração própria) |
| `MAX_FIXTURES` | `8` | Máximo de jogos analisados por execução (cuidado com a cota da API) |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Modelo do Gemini usado para a explicação |

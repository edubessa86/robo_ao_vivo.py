import os
import textwrap

BASE = "/workspaces/robo_ao_vivo.py"

PARSER = '''import re
from dataclasses import dataclass


@dataclass
class Aposta:
    esporte: str
    liga: str
    mandante: str
    placar_mand: int
    placar_vis: int
    visitante: str
    minuto: int
    mercado: str
    linha: str
    odd: float
    descricao: str
    stake: float = 0.0
    raw: str = ""
    market_id: str = ""
    market_type: str = ""
    selection_id: str = ""
    event_id: str = ""
    running: bool = False
    running_id: str = ""

    def chave(self) -> str:
        return f"{self.mandante}|{self.visitante}|{self.linha}|{self.minuto}"


def _odd(s: str) -> float:
    return float(s.strip().replace(",", "."))


def _limpar(t: str) -> str:
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\\*\\*([^*]+)\\*\\*", r"\\1", t)
    t = re.sub(r"\\*([^*]+)\\*", r"\\1", t)
    t = re.sub(r"_([^_]+)_", r"\\1", t)
    return t


def parse_alerta(text: str):
    raw = text.strip()
    t = _limpar(raw)

    m = re.search("\\U0001F3C6\\\\s*(.+?)\\\\s*\\\\n", t)
    liga = m.group(1).strip() if m else "Desconhecida"

    m = re.search("\\u2694\\\\ufe0f?\\\\s*(.+?)\\\\s+(\\\\d+)\\\\s*x\\\\s*(\\\\d+)\\\\s+(.+?)\\\\s*\\\\n", t)
    if m:
        mandante = m.group(1).strip()
        placar_mand = int(m.group(2))
        placar_vis = int(m.group(3))
        visitante = m.group(4).strip()
    else:
        mandante, placar_mand, placar_vis, visitante = "", 0, 0, ""

    m = re.search("\\u23F1\\\\s*Tempo:\\\\s*(\\\\d+)", t)
    minuto = int(m.group(1)) if m else 0

    m = re.search("\\u2022\\\\s*Mercado:\\\\s*([^\\\\n]+)", t)
    mercado = m.group(1).strip() if m else "Desconhecida"

    m = re.search("\\u2022\\\\s*Linha da Aposta:\\\\s*(.+?)\\\\s*$", t, re.M)
    linha = m.group(1).strip() if m else "Desconhecida"

    m = re.search("@([\\\\d.,]+)", t)
    odd = _odd(m.group(1)) if m else 0.0

    desc = f"{mandante} {placar_mand}x{placar_vis} {visitante} - {linha} @ {odd}"

    return Aposta(
        esporte="Futebol",
        liga=liga,
        mandante=mandante,
        placar_mand=placar_mand,
        placar_vis=placar_vis,
        visitante=visitante,
        minuto=minuto,
        mercado=mercado,
        linha=linha,
        odd=odd,
        descricao=desc,
        raw=raw,
    )
'''

CONFIG = '''import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _f(name: str, default: str) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _b(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on", "sim"}


@dataclass
class Config:
    sportsbook_url: str = os.environ.get("SPORTSBOOK_URL", "https://www.bingoemcasa17.com/pt-BR/sportsbook")
    api_base_url: str = os.environ.get("API_BASE_URL", "")
    cpf: str = os.environ.get("BET_CPF", "")
    senha: str = os.environ.get("BET_SENHA", "")
    stake: float = _f("BET_STAKE", "10")
    odd_min: float = _f("BET_ODD_MIN", "1.50")
    odd_tolerance: float = _f("BET_ODD_TOLERANCE", "0.10")
    headless: bool = _b("BET_HEADLESS", "true")
    timeout_ms: int = int(os.environ.get("BET_TIMEOUT_MS", "30000"))
    log_file: str = os.environ.get("BET_LOG_FILE", "logs/apostas.jsonl")
    state_file: str = os.environ.get("BET_STATE_FILE", "logs/estado.json")
    dedupe_window_s: int = int(os.environ.get("BET_DEDUPE_WINDOW_S", "600"))
    executor_enabled: bool = _b("BET_EXECUTOR_ENABLED", "false")
    telegram_token: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.environ.get("TELEGRAM_CHAT_ID", "")
'''

FILTERS = '''import json
import os
import time
from dataclasses import dataclass, field

from bets.parser import Aposta


@dataclass
class State:
    vistos: dict = field(default_factory=dict)
    morto: bool = False

    def load(self, path: str) -> None:
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.vistos = data.get("vistos", {})
            self.morto = bool(data.get("morto", False))
        except Exception:
            pass

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"vistos": self.vistos, "morto": self.morto}, f, ensure_ascii=False)


@dataclass
class Filtros:
    stake: float = 10.0
    odd_min: float = 1.50
    odd_tolerance: float = 0.10
    dedupe_window_s: int = 600

    def pode_executar(self, a: Aposta, state: State) -> "tuple[bool, str]":
        if state.morto:
            return False, "kill switch ativo"
        if a.odd < self.odd_min:
            return False, f"odd {a.odd} abaixo do minimo {self.odd_min}"
        chave = a.chave()
        agora = time.time()
        ult = state.vistos.get(chave)
        if ult and (agora - float(ult)) < self.dedupe_window_s:
            return False, "duplicado (ja processado)"
        state.vistos[chave] = agora
        for k in [k for k, v in state.vistos.items() if agora - float(v) > self.dedupe_window_s * 3]:
            state.vistos.pop(k, None)
        return True, "ok"


class ExecutorLog:
    def __init__(self, path: str):
        self.path = path

    def registrar(self, **kw) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        kw.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(kw, ensure_ascii=False) + "\\n")
'''

TESTS = '''from bets.parser import parse_alerta

MSG_HTML = """\\u26BD <b>ALERTA DE OPORTUNIDADE AO VIVO</b>
\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501
\\U0001F3C6 <b>Iran: Iran</b>
\\u2694\\ufe0f <b>Havadar SC</b> 0 x 0 <b>Mes Kerman</b>
\\u23F1 <b>Tempo:</b> 57' minutos
\\U0001F4CA <b>PROJECAO DE MERCADO:</b>
\\u2022 Mercado: Over Gols (Mais Gols)
\\u2022 Linha da Aposta: <b>Over 0.5 Gols</b>
\\U0001F4C8 <b>Odd estimada: @1.65</b>
\\U0001F4A1 <b>SUGESTAO DE ENTRADA:</b>
\\U0001F525 <b>Apostar Over 0.5 Gols</b> (Odd @1.65)"""

MSG_MD = """\\u26BD **ALERTA DE OPORTUNIDADE AO VIVO**
\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501
\\U0001F3C6 **Iran: Iran**
\\u2694\\ufe0f **Havadar SC** 0 x 0 **Mes Kerman**
\\u23F1 **Tempo:** 57' minutos
\\U0001F4CA **PROJECAO DE MERCADO:**
\\u2022 Mercado: Over Gols (Mais Gols)
\\u2022 Linha da Aposta: **Over 0.5 Gols**
\\U0001F4C8 **Odd estimada: @1.65**
\\U0001F4A1 **SUGESTAO DE ENTRADA:**
\\U0001F525 **Apostar Over 0.5 Gols** (Odd @1.65)"""


def test_parse_html():
    a = parse_alerta(MSG_HTML)
    assert a is not None, "parser retornou None"
    assert a.mandante == "Havadar SC", f"mandante={a.mandante!r}"
    assert a.visitante == "Mes Kerman", f"visitante={a.visitante!r}"
    assert a.placar_mand == 0
    assert a.placar_vis == 0
    assert a.minuto == 57, f"minuto={a.minuto!r}"
    assert a.linha == "Over 0.5 Gols", f"linha={a.linha!r}"
    assert a.odd == 1.65, f"odd={a.odd!r}"
    assert a.liga == "Iran: Iran", f"liga={a.liga!r}"


def test_parse_markdown():
    a = parse_alerta(MSG_MD)
    assert a is not None, "parser retornou None"
    assert a.odd == 1.65, f"odd={a.odd!r}"
    assert a.minuto == 57, f"minuto={a.minuto!r}"
    assert a.mandante == "Havadar SC", f"mandante={a.mandante!r}"
    assert a.visitante == "Mes Kerman", f"visitante={a.visitante!r}"


def test_parse_odd_com_virgula():
    t = MSG_HTML.replace("@1.65", "@1,65")
    a = parse_alerta(t)
    assert a.odd == 1.65, f"odd={a.odd!r}"


def test_parse_texto_sem_operacao():
    a = parse_alerta("mensagem qualquer")
    assert a is None or a.mandante == ""
'''

FILES = {
    "bets/parser.py": PARSER,
    "bets/config.py": CONFIG,
    "bets/filters.py": FILTERS,
    "tests/test_parser.py": TESTS,
}

for rel, content in FILES.items():
    path = os.path.join(BASE, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK", rel)

print("--- verificacao ---")
import ast
for rel in FILES:
    p = os.path.join(BASE, rel)
    try:
        ast.parse(open(p, encoding="utf-8").read())
        print("SYNTAX OK", rel)
    except SyntaxError as e:
        print("SYNTAX ERROR", rel, e)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEND — assistente de IA para terminal (estilo Claude Code / Gemini CLI).

Conecta automaticamente ao LM Studio (http://127.0.0.1:1234) ou a qualquer
servidor compatível com a API da OpenAI.

Modos:
  - chat   : conversa normal, sem ferramentas
  - coding : pode ler/escrever arquivos, listar diretórios e executar comandos
  - plan   : produz apenas um plano, sem executar ferramentas

Pensamento (thinking) ligado/desligado via --thinking / --no-thinking
(requer um modelo com suporte a raciocínio no LM Studio).

Uso:
  send                     modo interativo
  send "pergunta"          resposta única
  send --code --plan       etc.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import readline  # noqa: F401 — histórico de input no Linux/macOS
except ImportError:  # pragma: no cover
    readline = None

try:  # Windows: console em UTF-8
    if os.name == "nt":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

VERSION = "1.0.0"
DEFAULT_BASE_URL = "http://127.0.0.1:1234"
DEFAULT_UPDATE_URL = (
    "https://github.com/contasuportedis-png/SEND/releases/latest/download/send.py"
)
RAW_FALLBACK_URL = (
    "https://raw.githubusercontent.com/contasuportedis-png/SEND/"
    "arena/01a0252e-send/send.py"
)

SEND_HOME = Path(os.environ.get("SEND_HOME", str(Path.home() / ".send")))
CONFIG_PATH = SEND_HOME / "config.json"
HISTORY_PATH = SEND_HOME / "history.jsonl"
INPUT_HISTORY = SEND_HOME / "input_history"

MAX_TOOL_ROUNDS = 12
RUN_TIMEOUT = 120
TOOL_OUTPUT_LIMIT = 4000
MAX_READ_BYTES = 256 * 1024

# ---------------------------------------------------------------------------
# Cores de terminal
# ---------------------------------------------------------------------------

class C:
    def __init__(self, enabled):
        self.enabled = enabled

    def _w(self, code, s):
        return f"\033[{code}m{s}\033[0m" if self.enabled else str(s)

    def bold(self, s):    return self._w("1", s)
    def dim(self, s):     return self._w("2", s)
    def red(self, s):     return self._w("31", s)
    def green(self, s):   return self._w("32", s)
    def yellow(self, s):  return self._w("33", s)
    def cyan(self, s):    return self._w("36", s)
    def magenta(self, s): return self._w("35", s)


def make_colors():
    if os.environ.get("NO_COLOR"):
        return C(False)
    if not sys.stdout.isatty():
        return C(False)
    if os.name == "nt":
        try:
            os.system("")  # ativa sequências VT no Windows 10+
        except Exception:
            return C(False)
    return C(True)


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "base_url": DEFAULT_BASE_URL,
    "api_key": "",
    "model": None,                 # None = detecta o primeiro modelo do LM Studio
    "mode": "coding",              # chat | coding | plan
    "thinking": False,
    "reasoning_effort": "medium",  # low | medium | high
    "show_reasoning": True,
    "auto_confirm": False,         # -y
    "temperature": 0.7,
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.update({k: v for k, v in data.items() if k in cfg})
    except Exception:
        pass
    if os.environ.get("SEND_BASE_URL"):
        cfg["base_url"] = os.environ["SEND_BASE_URL"].rstrip("/")
    if os.environ.get("SEND_MODEL"):
        cfg["model"] = os.environ["SEND_MODEL"]
    if os.environ.get("SEND_API_KEY"):
        cfg["api_key"] = os.environ["SEND_API_KEY"]
    return cfg


def save_config(cfg):
    try:
        SEND_HOME.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        print(f"⚠ não foi possível salvar a configuração: {e}")


# ---------------------------------------------------------------------------
# HTTP + streaming (API compatível com OpenAI / LM Studio)
# ---------------------------------------------------------------------------

def _request(url, payload=None, api_key="", method="POST", timeout=30):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    return urllib.request.urlopen(req, timeout=timeout)


def http_json(url, payload=None, api_key="", method="GET", timeout=15):
    with _request(url, payload, api_key, method, timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def stream_sse(url, payload, api_key=""):
    """Gera as linhas `data:` de uma resposta SSE (streaming)."""
    resp = _request(url, payload, api_key, timeout=60)
    buf = b""
    for raw in resp:
        buf += raw
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.decode("utf-8", errors="replace").strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                yield line[5:].strip()


def list_models(base_url, api_key=""):
    data = http_json(base_url + "/v1/models", api_key=api_key, method="GET")
    out = []
    for m in data.get("data", []):
        mid = m.get("id") or m.get("name") or ""
        if mid:
            out.append(mid)
    return out


def resolve_model(cfg, c):
    """Retorna o id do modelo: o configurado ou o primeiro do LM Studio."""
    if cfg.get("model"):
        return cfg["model"]
    try:
        models = list_models(cfg["base_url"], cfg["api_key"])
    except urllib.error.URLError as e:
        raise ConnectionError(
            f"Não consegui conectar ao LM Studio em {cfg['base_url']} ({e.reason}).\n"
            "  ➜ Abra o LM Studio, carregue um modelo e clique em "
            "'Developer' → 'Start Server' (porta 1234)."
        )
    except Exception as e:
        raise ConnectionError(f"Erro ao consultar o LM Studio em {cfg['base_url']}: {e}")
    if not models:
        raise ConnectionError(
            "O LM Studio respondeu, mas nenhum modelo está carregado.\n"
            "  ➜ Carregue um modelo no LM Studio e tente de novo."
        )
    return models[0]


# ---------------------------------------------------------------------------
# Prompts de sistema
# ---------------------------------------------------------------------------

BASE_SYSTEM = (
    "Você é o SEND, um assistente de IA que roda em um terminal, no estilo de "
    "Claude Code. Responda de forma clara e direta em português do Brasil, "
    "salvo se o usuário pedir outro idioma. Ao ajudar com código, mostre os "
    "trechos relevantes e explique brevemente o que fez."
)

CODING_SYSTEM = (
    " Você está em MODO CODING: pode usar as ferramentas disponíveis para ler "
    "arquivos, escrever arquivos, listar diretórios e executar comandos quando "
    "necessário. Prefira usar as ferramentas em vez de pedir para o usuário "
    "fazer. Nunca invente o conteúdo de arquivos que você não leu."
)

PLAN_SYSTEM = (
    " Você está em MODO PLANO: NÃO execute ferramentas, não edite arquivos e "
    "não rode comandos. Produza apenas um plano claro, passo a passo, com "
    "objetivo, arquivos afetados e ordem de execução. No final, pergunte se o "
    "usuário quer que você execute o plano."
)


def system_prompt(cfg, extra=""):
    parts = [BASE_SYSTEM]
    if cfg["mode"] == "coding":
        parts.append(CODING_SYSTEM)
    elif cfg["mode"] == "plan":
        parts.append(PLAN_SYSTEM)
    if extra:
        parts.append(" Instrução adicional do usuário: " + extra)
    return "".join(parts)


# ---------------------------------------------------------------------------
# Ferramentas (modo coding)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Lê o conteúdo de um arquivo de texto do projeto. "
                           "Retorna o conteúdo ou uma mensagem de erro.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Caminho do arquivo (relativo ao "
                                       "diretório atual ou absoluto).",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Cria ou sobrescreve um arquivo com o conteúdo "
                           "informado. Cria as pastas intermediárias se "
                           "necessário.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Caminho do arquivo (relativo ou absoluto).",
                    },
                    "content": {
                        "type": "string",
                        "description": "Conteúdo completo do arquivo.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "Lista arquivos e pastas de um diretório.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Diretório a listar (padrão: diretório atual).",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Executa um comando no shell do usuário e retorna a "
                           "saída. Use para testar, compilar ou rodar código.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Comando a executar.",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Tempo máximo em segundos (padrão 120).",
                    },
                },
                "required": ["command"],
            },
        },
    },
]


def ask_yes_no(c, question, default=False):
    if not sys.stdin.isatty():
        return default
    try:
        r = input(f"{c.bold(question)} (s/N) ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not r:
        return default
    return r in ("s", "sim", "y", "yes")


def tool_read(args, c):
    p = Path(args.get("path", "")).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    p = p.resolve()
    if not p.exists():
        return f"Erro: arquivo não encontrado: {p}"
    if p.is_dir():
        return f"Erro: '{p}' é um diretório. Use a ferramenta list_files."
    data = p.read_bytes()
    if len(data) > MAX_READ_BYTES:
        return f"Arquivo muito grande ({len(data)} bytes). Leia apenas uma parte."
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return f"(Arquivo binário com {len(data)} bytes — conteúdo não exibido)"


def tool_write(args, c):
    p = Path(args.get("path", "")).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    p = p.resolve()
    content = args.get("content", "")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Arquivo escrito: {p} ({len(content.encode('utf-8'))} bytes)"


def tool_list(args, c):
    p = Path(args.get("path", ".")).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    p = p.resolve()
    if not p.exists():
        return f"Erro: diretório não encontrado: {p}"
    if not p.is_dir():
        return f"Erro: '{p}' não é um diretório."
    try:
        entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except PermissionError:
        return f"Erro: sem permissão para listar {p}"
    lines = []
    for e in entries[:300]:
        suffix = "/" if e.is_dir() else ""
        lines.append(e.name + suffix)
    if len(entries) > 300:
        lines.append(f"... (+{len(entries) - 300} itens)")
    return "\n".join(lines) if lines else "(diretório vazio)"


def tool_run(args, c):
    cmd = args.get("command", "")
    try:
        timeout = int(args.get("timeout") or RUN_TIMEOUT)
    except (TypeError, ValueError):
        timeout = RUN_TIMEOUT
    timeout = max(1, min(timeout, RUN_TIMEOUT))
    print(c.dim(f"    $ {cmd}"))
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=str(Path.cwd()),
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"Comando excedeu {timeout}s e foi cancelado."
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if len(out) > TOOL_OUTPUT_LIMIT:
        out = out[:TOOL_OUTPUT_LIMIT] + f"\n… (saída truncada, {len(out)} bytes no total)"
    tail = f"código de saída: {proc.returncode}"
    return f"{tail}\n{out}" if out else f"{tail} (sem saída)"


def execute_tool(name, args, c, auto_confirm):
    try:
        if name == "read_file":
            return tool_read(args, c)
        if name == "write_file":
            if not auto_confirm:
                if not ask_yes_no(c, f"Escrever arquivo '{args.get('path', '?')}'?"):
                    return None
            return tool_write(args, c)
        if name == "list_files":
            return tool_list(args, c)
        if name == "run_command":
            if not auto_confirm:
                preview = args.get("command", "")[:80]
                if not ask_yes_no(c, f"Executar comando: {preview}…"):
                    return None
            return tool_run(args, c)
        return f"Ferramenta desconhecida: {name}"
    except Exception as e:
        return f"Erro ao executar {name}: {e}"


def compact_args(args):
    s = json.dumps(args, ensure_ascii=False)
    return s if len(s) <= 100 else s[:97] + "..."


# ---------------------------------------------------------------------------
# Sessão e chamada ao modelo
# ---------------------------------------------------------------------------

class Session:
    def __init__(self, cfg, c):
        self.cfg = cfg
        self.c = c
        self.messages = []
        self.model_id = None


def call_model(sess, tools_enabled, c, cfg):
    """Chama a API com streaming. Retorna (conteúdo, lista de tool_calls)."""
    if sess.model_id is None:
        sess.model_id = resolve_model(cfg, c)
    messages = [{"role": "system", "content": system_prompt(cfg)}] + sess.messages
    payload = {
        "model": sess.model_id,
        "messages": messages,
        "stream": True,
        "temperature": cfg["temperature"],
    }
    if tools_enabled:
        payload["tools"] = TOOLS
        payload["tool_choice"] = "auto"
    if cfg["thinking"]:
        payload["reasoning_effort"] = cfg["reasoning_effort"]

    try:
        stream = stream_sse(cfg["base_url"] + "/v1/chat/completions", payload, cfg["api_key"])
        return _consume_stream(stream, c, cfg)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if cfg["thinking"] and e.code in (400, 422) and any(
            w in body.lower() for w in ("reasoning", "thinking")
        ):
            print(c.yellow(
                "⚠ Este modelo não suporta 'reasoning_effort'. "
                "Desligando o pensamento para esta sessão."
            ))
            cfg["thinking"] = False
            payload.pop("reasoning_effort", None)
            stream = stream_sse(cfg["base_url"] + "/v1/chat/completions",
                                payload, cfg["api_key"])
            return _consume_stream(stream, c, cfg)
        raise


def _consume_stream(stream, c, cfg):
    """Lê um stream SSE e devolve (conteúdo, tool_calls) já formatados."""
    content_parts = []
    reasoning_parts = []
    tool_calls = {}
    order = []
    try:
        for raw in stream:
            if raw == "[DONE]":
                break
            try:
                evt = json.loads(raw)
            except Exception:
                continue
            for ch in evt.get("choices", []):
                delta = ch.get("delta", {}) or {}
                if delta.get("content"):
                    piece = delta["content"]
                    content_parts.append(piece)
                    sys.stdout.write(piece)
                    sys.stdout.flush()
                if delta.get("reasoning_content") and cfg["show_reasoning"] and c.enabled:
                    piece = delta["reasoning_content"]
                    reasoning_parts.append(piece)
                    sys.stdout.write(c.dim(piece))
                    sys.stdout.flush()
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    if idx not in tool_calls:
                        tool_calls[idx] = {
                            "id": tc.get("id") or "",
                            "function": {"name": "", "arguments": ""},
                        }
                        order.append(idx)
                    if tc.get("id"):
                        tool_calls[idx]["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        tool_calls[idx]["function"]["name"] += fn["name"]
                    if fn.get("arguments"):
                        tool_calls[idx]["function"]["arguments"] += fn["arguments"]
    except KeyboardInterrupt:
        print()
        return "".join(content_parts), []

    if content_parts:
        sys.stdout.write("\n")
        sys.stdout.flush()
    return "".join(content_parts), [tool_calls[i] for i in order]


def run_agent(sess, tools_enabled, c, auto_confirm):
    """Laço de conversa com ferramentas. Retorna a resposta final."""
    cfg = sess.cfg
    content = ""
    for _ in range(MAX_TOOL_ROUNDS):
        content, calls = call_model(sess, tools_enabled, c, cfg)
        if not calls:
            if content:
                sess.messages.append({"role": "assistant", "content": content})
            else:
                sess.messages.append({"role": "assistant", "content": ""})
            return content
        asst = {
            "role": "assistant",
            "content": content or None,
            "tool_calls": [],
        }
        for i, tc in enumerate(calls):
            asst["tool_calls"].append(
                {
                    "id": tc["id"] or f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                }
            )
        sess.messages.append(asst)
        for tc in calls:
            name = tc["function"]["name"]
            raw = tc["function"]["arguments"]
            try:
                args = json.loads(raw) if raw else {}
                if not isinstance(args, dict):
                    args = {"_raw": raw}
            except Exception:
                args = {"_raw": raw}
            print(c.yellow(f"  🔧 {name} {compact_args(args)}"))
            result = execute_tool(name, args, c, auto_confirm)
            if result is None:
                result = (
                    "O usuário recusou executar esta ferramenta. "
                    "Explique e prossiga sem executá-la."
                )
            sess.messages.append(
                {"role": "tool", "tool_call_id": tc["id"] or f"call_{len(sess.messages)}",
                 "content": result}
            )
    print(c.yellow("⚠ Limite de iterações de ferramentas atingido. Encerrando."))
    return content


def ask_model(sess, tools_enabled, c, auto_confirm):
    """Chama o modelo; se o modelo não suportar ferramentas, cai para chat."""
    try:
        return run_agent(sess, tools_enabled, c, auto_confirm)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if tools_enabled and e.code in (400, 422) and "tool" in body.lower():
            print(c.yellow(
                "⚠ Este modelo não suporta ferramentas. Continuando em modo chat."
            ))
            return run_agent(sess, False, c, auto_confirm)
        raise


# ---------------------------------------------------------------------------
# Histórico / sessões salvas
# ---------------------------------------------------------------------------

def save_history(messages):
    try:
        SEND_HOME.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            for m in messages:
                f.write(
                    json.dumps(
                        {"ts": time.time(), "role": m.get("role"),
                         "content": m.get("content", "")},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    except Exception:
        pass


def save_session(sess, name=None):
    SEND_HOME.mkdir(parents=True, exist_ok=True)
    d = SEND_HOME / "sessions"
    d.mkdir(exist_ok=True)
    if not name:
        name = time.strftime("sessao-%Y%m%d-%H%M%S.json")
    p = Path(name)
    if not p.is_absolute():
        p = d / name
    if p.suffix != ".json":
        p = Path(str(p) + ".json")
    p.write_text(json.dumps(sess.messages, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Conversa salva em {p}")


def load_session(sess, name):
    p = Path(name).expanduser()
    if not p.is_absolute():
        p = SEND_HOME / "sessions" / name
    if not p.exists() and p.suffix != ".json":
        p = Path(str(p) + ".json")
    if not p.exists():
        print(f"✗ Arquivo não encontrado: {p}")
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list) and all("role" in m for m in data):
            sess.messages = data
            print(f"✅ Conversa carregada de {p} ({len(data)} mensagens)")
            return True
        print("✗ O arquivo não parece ser uma conversa do SEND.")
    except Exception as e:
        print(f"✗ Erro ao carregar: {e}")
    return False


# ---------------------------------------------------------------------------
# Modo interativo (REPL)
# ---------------------------------------------------------------------------

HELP_TEXT = """\
Comandos do SEND:
  /help               mostra esta ajuda
  /exit, /quit        sai do SEND
  /clear              limpa a conversa atual
  /model [nome]       mostra ou troca o modelo (ex.: /model qwen2.5-coder-7b)
  /models             lista os modelos carregados no LM Studio
  /code               modo coding: ferramentas de arquivo e comandos
  /chat               modo chat: só conversa, sem ferramentas
  /plan               modo plano: só planeja, não executa nada
  /thinking [on|off]  liga/desliga o pensamento do modelo
  /tools [on|off]     liga/desliga as ferramentas manualmente
  /status             mostra o estado da sessão
  /save [arquivo]     salva a conversa em ~/.send/sessions/
  /load arquivo       carrega uma conversa salva
  /update             atualiza o SEND para a versão mais recente
  /doctor             diagnostica a instalação e a conexão com o LM Studio

Dicas:
  • use \\ no fim da linha para continuar em outra linha
  • Ctrl+C interrompe a resposta; Ctrl+C de novo sai
"""


def handle_command(sess, line, c, tools_enabled):
    """Processa um comando iniciado com '/'. Retorna (sair?, tools_enabled)."""
    cfg = sess.cfg
    cmd = line.split()[0].lower()
    rest = line[len(cmd):].strip()

    if cmd in ("/exit", "/quit"):
        print("Até logo! 👋")
        return True, tools_enabled
    if cmd == "/help":
        print(HELP_TEXT)
        return False, tools_enabled
    if cmd == "/clear":
        sess.messages = []
        print("🧹 Conversa limpa.")
        return False, tools_enabled
    if cmd == "/model":
        if not rest:
            print(f"Modelo atual: {sess.model_id or cfg['model'] or 'auto'}")
        else:
            name = rest
            try:
                available = list_models(cfg["base_url"], cfg["api_key"])
                if available and name not in available:
                    print(c.yellow(
                        f"⚠ '{name}' não está carregado no LM Studio. "
                        f"Disponíveis: {', '.join(available)}"
                    ))
            except Exception:
                pass
            cfg["model"] = name
            sess.model_id = name
            save_config(cfg)
            print(f"✅ Modelo definido: {name}")
        return False, tools_enabled
    if cmd == "/models":
        try:
            models = list_models(cfg["base_url"], cfg["api_key"])
            if not models:
                print(c.yellow("⚠ Nenhum modelo carregado no LM Studio."))
            else:
                print(f"Modelos em {cfg['base_url']}:")
                for m in models:
                    mark = " ← atual" if m == (sess.model_id or cfg["model"]) else ""
                    print(f"  • {m}{mark}")
        except Exception as e:
            print(c.red(f"✗ {e}"))
        return False, tools_enabled
    if cmd == "/code":
        cfg["mode"] = "coding"
        save_config(cfg)
        print("🛠 Modo coding ativado (ferramentas disponíveis).")
        return False, True
    if cmd == "/chat":
        cfg["mode"] = "chat"
        save_config(cfg)
        print("💬 Modo chat ativado (sem ferramentas).")
        return False, False
    if cmd == "/plan":
        cfg["mode"] = "plan"
        save_config(cfg)
        print("📋 Modo plano ativado (só planeja, não executa).")
        return False, False
    if cmd == "/thinking":
        if rest in ("on", "off"):
            cfg["thinking"] = rest == "on"
            save_config(cfg)
            print(f"🧠 Pensamento: {'ligado' if cfg['thinking'] else 'desligado'}")
        else:
            print(f"🧠 Pensamento: {'ligado' if cfg['thinking'] else 'desligado'} "
                  f"(use /thinking on ou /thinking off)")
        return False, tools_enabled
    if cmd == "/tools":
        if rest in ("on", "off"):
            on = rest == "on"
            if on and cfg["mode"] == "plan":
                print(c.yellow("⚠ O modo plano não usa ferramentas. Use /code."))
                return False, tools_enabled
            print(f"🔧 Ferramentas: {'ligadas' if on else 'desligadas'}")
            return False, on
        print(f"🔧 Ferramentas: {'ligadas' if tools_enabled else 'desligadas'}")
        return False, tools_enabled
    if cmd == "/status":
        print(f"  Servidor : {cfg['base_url']}")
        print(f"  Modelo   : {sess.model_id or cfg['model'] or 'auto'}")
        print(f"  Modo     : {cfg['mode']}")
        print(f"  Ferramentas: {'sim' if tools_enabled else 'não'}")
        print(f"  Pensamento : {'sim' if cfg['thinking'] else 'não'}")
        print(f"  Config   : {CONFIG_PATH}")
        return False, tools_enabled
    if cmd == "/save":
        save_session(sess, rest or None)
        return False, tools_enabled
    if cmd == "/load":
        if rest:
            load_session(sess, rest)
        else:
            print("Uso: /load <arquivo>")
        return False, tools_enabled
    if cmd == "/update":
        self_update(c)
        return False, tools_enabled
    if cmd == "/doctor":
        doctor(cfg, c)
        return False, tools_enabled
    print(c.yellow(f"Comando desconhecido: {cmd} (use /help)"))
    return False, tools_enabled


def read_input(prompt, c):
    try:
        line = input(prompt)
    except EOFError:
        return None
    while line.rstrip().endswith("\\"):
        line = line.rstrip()[:-1]
        try:
            more = input(c.dim("  ... "))
        except EOFError:
            break
        line += "\n" + more
    return line


def make_prompt(c, sess):
    badge = sess.model_id or "?"
    mode = sess.cfg["mode"].upper()
    think = " 🧠" if sess.cfg["thinking"] else ""
    return f"{c.cyan('send')}{c.dim(f'({badge}·{mode})')}{think} {c.bold('❯')} "


def repl(sess, c, tools_enabled):
    cfg = sess.cfg
    print()
    print(c.bold(c.cyan(f" ⚡ SEND v{VERSION}")) + " — assistente de IA no terminal (LM Studio)")
    print(c.dim("   Digite /help para os comandos • Ctrl+C para sair"))
    print()

    if readline:
        try:
            readline.read_history_file(str(INPUT_HISTORY))
        except Exception:
            pass

    while True:
        try:
            line = read_input(make_prompt(c, sess), c)
        except KeyboardInterrupt:
            print()
            break
        if line is None:
            print()
            break
        line = line.strip()
        if not line:
            continue
        if line.startswith("/"):
            do_exit, tools_enabled = handle_command(sess, line, c, tools_enabled)
            if do_exit:
                break
            continue

        sess.messages.append({"role": "user", "content": line})
        save_history([{"role": "user", "content": line}])
        try:
            ask_model(sess, tools_enabled and cfg["mode"] != "plan", c, cfg["auto_confirm"])
        except urllib.error.URLError as e:
            print(c.red(f"✗ Não consegui conectar ao servidor ({cfg['base_url']})."))
            print(c.yellow("  LM Studio está rodando? Use 'send --doctor' para diagnosticar."))
        except urllib.error.HTTPError as e:
            print(c.red(f"✗ Erro HTTP {e.code} do servidor:"))
            print(c.red(e.read().decode("utf-8", "replace")[:500]))
        except ConnectionError as e:
            print(c.red(f"✗ {e}"))
        except KeyboardInterrupt:
            print()
        except Exception as e:
            print(c.red(f"✗ Erro: {e}"))
        if sess.messages and sess.messages[-1]["role"] == "assistant":
            save_history([sess.messages[-1]])

    if readline:
        try:
            readline.write_history_file(str(INPUT_HISTORY))
        except Exception:
            pass
    return 0


# ---------------------------------------------------------------------------
# Execução única, diagnóstico, atualização
# ---------------------------------------------------------------------------

def one_shot(sess, prompt, c, tools_enabled, auto_confirm):
    prompt = prompt.strip()
    if not prompt:
        print(c.yellow('Nenhum prompt. Use: send "sua pergunta" — ou rode só "send" '
                       "para o modo interativo."))
        return 1
    sess.messages.append({"role": "user", "content": prompt})
    save_history([{"role": "user", "content": prompt}])
    try:
        ask_model(sess, tools_enabled and sess.cfg["mode"] != "plan", c, auto_confirm)
    except urllib.error.URLError as e:
        print(c.red(f"✗ Não consegui conectar ao servidor ({sess.cfg['base_url']})."))
        print(c.yellow("  LM Studio está rodando? Use 'send --doctor' para diagnosticar."))
        return 2
    except urllib.error.HTTPError as e:
        print(c.red(f"✗ Erro HTTP {e.code} do servidor:"))
        print(c.red(e.read().decode("utf-8", "replace")[:500]))
        return 1
    except ConnectionError as e:
        print(c.red(f"✗ {e}"))
        return 2
    except Exception as e:
        print(c.red(f"✗ Erro: {e}"))
        return 1
    if sess.messages and sess.messages[-1]["role"] == "assistant":
        save_history([sess.messages[-1]])
    return 0


def doctor(cfg, c):
    print(c.bold("SEND — diagnóstico"))
    print(f"  Versão   : {VERSION}")
    print(f"  Python   : {sys.version.split()[0]} ({sys.platform})")
    print(f"  Config   : {CONFIG_PATH} {'(existe)' if CONFIG_PATH.exists() else '(não criada ainda)'}")
    print(f"  Servidor : {cfg['base_url']}")
    print(f"  Modelo   : {cfg['model'] or 'auto (primeiro disponível)'}")
    print(f"  Modo     : {cfg['mode']} | Pensamento: {'ligado' if cfg['thinking'] else 'desligado'}")
    print()
    print(c.bold("Testando conexão com o LM Studio…"))
    t0 = time.time()
    try:
        models = list_models(cfg["base_url"], cfg["api_key"])
        dt = (time.time() - t0) * 1000
        print(c.green(f"  ✅ Conexão OK em {dt:.0f} ms"))
        if models:
            print(f"  Modelos disponíveis ({len(models)}):")
            for m in models:
                print(f"    • {m}")
            return 0
        print(c.yellow("  ⚠ Servidor respondeu, mas nenhum modelo está carregado."))
        print(c.yellow("     Carregue um modelo no LM Studio e tente de novo."))
        return 1
    except urllib.error.URLError as e:
        print(c.red(f"  ✗ Não foi possível conectar em {cfg['base_url']} ({e.reason})"))
        print(c.yellow("  Como resolver:"))
        print(c.yellow("    1. Abra o LM Studio e carregue um modelo (ex.: Qwen2.5 Coder 7B)"))
        print(c.yellow("    2. Clique na aba 'Developer' (Servidor Local) → 'Start Server'"))
        print(c.yellow("    3. Confirme que a porta é 1234"))
        print(c.yellow("    4. Rode 'send --doctor' novamente"))
        return 1
    except Exception as e:
        print(c.red(f"  ✗ Erro: {e}"))
        return 1


def self_update(c, url=None):
    target = Path(os.path.realpath(__file__)).resolve()
    if not os.access(target.parent, os.W_OK):
        alt = Path.home() / ".local" / "bin" / "send"
        if not alt.exists():
            print(c.yellow(f"⚠ Sem permissão de escrita em {target}."))
            print(c.yellow(f"  Instalando a nova versão em {alt} …"))
        target = alt
    url = url or os.environ.get("SEND_UPDATE_URL") or DEFAULT_UPDATE_URL
    print(f"⬇ Baixando {url} …")
    tmp = target.with_suffix(".py.tmp")
    try:
        urllib.request.urlretrieve(url, tmp)
    except Exception as e:
        # Fallback: baixa direto do repositório (útil antes do 1º release)
        if url != RAW_FALLBACK_URL:
            print(c.yellow(f"  ⚠ {e}"))
            print(f"⬇ Tentando o repositório: {RAW_FALLBACK_URL} …")
            try:
                urllib.request.urlretrieve(RAW_FALLBACK_URL, tmp)
            except Exception as e2:
                print(c.red(f"✗ Falha no download: {e2}"))
                return 1
        else:
            print(c.red(f"✗ Falha no download: {e}"))
            return 1
    try:
        head = tmp.read_text(encoding="utf-8", errors="replace")[:200]
        if "SEND" not in head and "#!/usr/bin/env python3" not in head:
            raise ValueError("o arquivo baixado não parece ser o SEND")
        os.replace(tmp, target)
        os.chmod(target, 0o755)
        print(c.green(f"✅ SEND atualizado: {target}"))
        return 0
    except Exception as e:
        tmp.unlink(missing_ok=True)
        print(c.red(f"✗ Falha na atualização: {e}"))
        return 1


INSTALL_HINT = """\
Para instalar o SEND em outra máquina:

  Linux / macOS (Pop!_OS, Ubuntu, etc.):
    curl -fsSL https://github.com/contasuportedis-png/SEND/releases/latest/download/install.sh | bash

  Windows (PowerShell):
    irm https://github.com/contasuportedis-png/SEND/releases/latest/download/install.ps1 | iex

Depois: abra o LM Studio, carregue um modelo, inicie o servidor (porta 1234)
e rode:  send --doctor
"""


# ---------------------------------------------------------------------------
# Linha de comando
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        prog="send",
        description="SEND — assistente de IA no terminal (estilo Claude Code), "
                    "conectado ao LM Studio (http://127.0.0.1:1234).",
        epilog="Exemplos:\n"
               "  send                          modo interativo\n"
               "  send \"explique este código\"   resposta única\n"
               "  send --code \"crie um app\"     modo coding\n"
               "  send --plan \"refatore x\"      modo plano\n"
               "  send --thinking \"pergunta\"    com raciocínio (se o modelo suportar)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("prompt", nargs="*", help="prompt para execução única "
                    "(se omitido, abre o modo interativo)")
    ap.add_argument("-m", "--model", help="ID do modelo (padrão: primeiro "
                    "modelo carregado no LM Studio)")
    ap.add_argument("-u", "--base-url", default=None,
                    help=f"URL do servidor (padrão: {DEFAULT_BASE_URL})")
    ap.add_argument("-c", "--code", action="store_true",
                    help="modo coding: pode ler/escrever arquivos e executar comandos")
    ap.add_argument("-p", "--plan", action="store_true",
                    help="modo plano: só planeja, não executa nada")
    ap.add_argument("--chat", action="store_true",
                    help="modo chat: sem ferramentas")
    ap.add_argument("--thinking", action="store_true",
                    help="liga o modo pensamento (se o modelo suportar)")
    ap.add_argument("--no-thinking", action="store_true",
                    help="desliga o modo pensamento")
    ap.add_argument("--reasoning-effort", choices=["low", "medium", "high"],
                    help="esforço de raciocínio quando o pensamento está ligado "
                         "(padrão: medium)")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="confirma automaticamente as ferramentas (sem perguntar)")
    ap.add_argument("--no-tools", action="store_true",
                    help="desativa as ferramentas nesta sessão")
    ap.add_argument("--temperature", type=float,
                    help="temperatura do modelo (padrão: 0.7)")
    ap.add_argument("--models", action="store_true",
                    help="lista os modelos disponíveis no LM Studio e sai")
    ap.add_argument("--doctor", action="store_true",
                    help="diagnostica a instalação e a conexão com o LM Studio")
    ap.add_argument("--update", action="store_true",
                    help="atualiza o SEND para a versão mais recente")
    ap.add_argument("--install", action="store_true",
                    help="mostra o comando de instalação para outras máquinas")
    ap.add_argument("--system-text", default=None,
                    help="instrução de sistema adicional")
    ap.add_argument("-v", "--version", action="store_true", help="mostra a versão")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    c = make_colors()

    if args.version:
        print(f"SEND {VERSION}")
        return 0
    if args.install:
        print(INSTALL_HINT)
        return 0
    if args.update:
        return self_update(c)

    cfg = load_config()
    if args.base_url:
        cfg["base_url"] = args.base_url.rstrip("/")
    if args.model:
        cfg["model"] = args.model
    if args.thinking:
        cfg["thinking"] = True
    if args.no_thinking:
        cfg["thinking"] = False
    if args.reasoning_effort:
        cfg["reasoning_effort"] = args.reasoning_effort
    if args.temperature is not None:
        cfg["temperature"] = args.temperature
    if args.yes:
        cfg["auto_confirm"] = True
    if args.code:
        cfg["mode"] = "coding"
    elif args.plan:
        cfg["mode"] = "plan"
    elif args.chat:
        cfg["mode"] = "chat"

    if args.models:
        try:
            models = list_models(cfg["base_url"], cfg["api_key"])
            if not models:
                print(c.yellow("⚠ Nenhum modelo carregado no LM Studio."))
                return 1
            print(f"Modelos disponíveis em {cfg['base_url']} ({len(models)}):")
            for m in models:
                mark = " ← atual" if m == cfg["model"] else ""
                print(f"  • {m}{mark}")
            return 0
        except urllib.error.URLError as e:
            print(c.red(f"✗ Não consegui conectar ao LM Studio em "
                        f"{cfg['base_url']} ({e.reason})."))
            print(c.yellow("  Rode 'send --doctor' para ver como resolver."))
            return 2
        except Exception as e:
            print(c.red(f"✗ Erro: {e}"))
            return 1

    if args.doctor:
        return doctor(cfg, c)

    sess = Session(cfg, c)
    try:
        sess.model_id = resolve_model(cfg, c)
    except ConnectionError as e:
        if args.prompt or not sys.stdin.isatty():
            print(c.red("✗ " + str(e)))
            return 2
        print(c.yellow("⚠ " + str(e)))

    tools_enabled = (cfg["mode"] == "coding") and not args.no_tools

    prompt = " ".join(args.prompt).strip()
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read()

    if prompt:
        return one_shot(sess, prompt, c, tools_enabled, cfg["auto_confirm"])

    return repl(sess, c, tools_enabled)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)

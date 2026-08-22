#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEND — assistente de IA para terminal (estilo Claude Code / Gemini CLI).

Conecta automaticamente ao LM Studio/Ollama ou a providers de nuvem e
servidores customizados compatíveis com a API da OpenAI.

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
import atexit
import difflib
import fnmatch
import getpass
import html.parser
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
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

VERSION = "1.11.0"
DEFAULT_BASE_URL = "http://127.0.0.1:1234"
OLLAMA_URL = "http://127.0.0.1:11434"

# Todos os serviços abaixo expõem uma API compatível com OpenAI. Isso mantém
# ferramentas e streaming iguais entre nuvem e modelos locais. As chaves podem
# vir do ambiente, evitando gravá-las no config.json.
PROVIDER_PRESETS = {
    "auto": {
        "name": "Automático (LM Studio → Ollama)",
        "base_url": DEFAULT_BASE_URL, "env_key": "", "local": True,
    },
    "lmstudio": {
        "name": "LM Studio (local)",
        "base_url": DEFAULT_BASE_URL, "env_key": "", "local": True,
    },
    "ollama": {
        "name": "Ollama (local)",
        "base_url": OLLAMA_URL, "env_key": "", "local": True,
    },
    "claude": {
        "name": "Claude (Anthropic)", "base_url": "https://api.anthropic.com",
        "env_key": "ANTHROPIC_API_KEY", "api_format": "anthropic",
    },
    "openai": {
        "name": "OpenAI", "base_url": "https://api.openai.com",
        "env_key": "OPENAI_API_KEY",
    },
    "nvidia": {
        "name": "NVIDIA NIM", "base_url": "https://integrate.api.nvidia.com",
        "env_key": "NVIDIA_API_KEY",
    },
    "gemini": {
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_prefix": "", "env_key": "GEMINI_API_KEY",
    },
    "mistral": {
        "name": "Mistral AI", "base_url": "https://api.mistral.ai",
        "env_key": "MISTRAL_API_KEY",
    },
    "groq": {
        "name": "Groq", "base_url": "https://api.groq.com/openai",
        "env_key": "GROQ_API_KEY",
    },
    "cohere": {
        "name": "Cohere", "base_url": "https://api.cohere.ai/compatibility",
        "env_key": "COHERE_API_KEY",
    },
    "together": {
        "name": "Together AI", "base_url": "https://api.together.xyz",
        "env_key": "TOGETHER_API_KEY",
    },
    "perplexity": {
        "name": "Perplexity", "base_url": "https://api.perplexity.ai",
        "api_prefix": "", "env_key": "PERPLEXITY_API_KEY",
    },
    "deepseek": {
        "name": "DeepSeek", "base_url": "https://api.deepseek.com",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "xai": {
        "name": "xAI (Grok)", "base_url": "https://api.x.ai",
        "env_key": "XAI_API_KEY",
    },
    "openrouter": {
        "name": "OpenRouter", "base_url": "https://openrouter.ai/api",
        "env_key": "OPENROUTER_API_KEY",
    },
    "azure": {
        "name": "Azure OpenAI", "base_url": "https://RESOURCE.openai.azure.com/openai",
        "env_key": "AZURE_OPENAI_API_KEY", "needs_endpoint": True,
        "endpoint_hint": "https://SEU-RECURSO.openai.azure.com/openai",
    },
    "bedrock": {
        "name": "AWS Bedrock", "base_url": "https://bedrock-mantle.us-east-1.api.aws",
        "env_key": "AWS_BEARER_TOKEN_BEDROCK", "needs_endpoint": True,
        "endpoint_hint": "https://bedrock-mantle.REGIAO.api.aws",
    },
    "huggingface": {
        "name": "Hugging Face Inference",
        "base_url": "https://router.huggingface.co",
        "env_key": "HF_TOKEN",
    },
}

DEFAULT_UPDATE_URL = (
    "https://github.com/contasuportedis-png/SEND/releases/latest/download/send.py"
)
RAW_FALLBACK_URL = (
    "https://github.com/contasuportedis-png/SEND/raw/"
    "main/send.py"
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
# Estética — banner, painéis, gradiente, spinner e markdown colorido
# ---------------------------------------------------------------------------

import threading


def _rgb(r, g, b):
    return f"\033[38;2;{r};{g};{b}m"


def gradient(text, c, start=(45, 212, 255), end=(255, 90, 255)):
    """Texto com gradiente de cor (do ciano ao magenta)."""
    if not c.enabled or len(text) <= 1:
        return text
    n = len(text)
    out = []
    for i, ch in enumerate(text):
        t = i / max(1, n - 1)
        r = int(start[0] + (end[0] - start[0]) * t)
        g = int(start[1] + (end[1] - start[1]) * t)
        b = int(start[2] + (end[2] - start[2]) * t)
        out.append(_rgb(r, g, b) + ch)
    return "".join(out) + "\033[0m"


SEND_ART = [
    "███████╗███████╗███╗   ██╗██████╗ ",
    "██╔════╝██╔════╝████╗  ██║██╔══██╗",
    "███████╗█████╗  ██╔██╗ ██║██║  ██║",
    "╚════██║██╔══╝  ██║╚██╗██║██║  ██║",
    "███████║███████╗██║ ╚████║██████╔╝",
    "╚══════╝╚══════╝╚═╝  ╚═══╝╚═════╝ ",
]


def banner(c, model=None, mode=None):
    """Banner de boas-vindas com arte ASCII em gradiente."""
    if c.enabled:
        for i, line in enumerate(SEND_ART):
            t = i / max(1, len(SEND_ART) - 1)
            r = int(45 + (255 - 45) * t)
            g = int(212 + (90 - 212) * t)
            b = int(255 + (255 - 255) * t)
            print(_rgb(r, g, b) + line + "\033[0m")
    else:
        print(SEND_ART[0])
    info = f"v{VERSION}"
    if model:
        info += f"  ·  modelo: {model}"
    if mode:
        info += f"  ·  modo: {mode}"
    print(c.dim("  " + info))
    print(c.dim("  digite / para a paleta de comandos · /help · Ctrl+C para sair"))
    print()


def panel(title, body, c, color="cyan", width=66):
    """Painel com borda e título (ex.: ╭─ 📋 ETAPA 1/4 ───────╮)."""
    border = getattr(c, color)
    title_s = f" {title} "
    w = max(width, len(title) + 8)
    pad = w - len(title_s) - 2
    top = border("╭─") + c.bold(title_s) + border("─" * max(0, pad) + "╮")
    lines = str(body).split("\n")
    out = [top]
    for ln in lines:
        ln = ln[: w - 4]
        out.append(border("│ ") + ln + " " * max(0, w - 4 - len(ln)) + border(" │"))
    out.append(border("╰" + "─" * (w - 2) + "╯"))
    print("\n".join(out))


def hr(c, ch="─", n=56, color="dim"):
    """Linha divisória."""
    fn = getattr(c, color)
    print(fn(ch * n))


def small(title, body, c, color="cyan"):
    """Linha de status compacta:  ● título — texto"""
    border = getattr(c, color)
    print(border(" ● ") + c.bold(title) + c.dim(" — " + str(body)))


class Spinner:
    """Animação de carregamento (só em terminal interativo)."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, c, msg="processando…"):
        self.c = c
        self.msg = msg
        self._stop = False
        self._t = None

    def __enter__(self):
        if not self.c.enabled:
            return self
        sys.stdout.write(" ")
        sys.stdout.flush()
        self._stop = False

        def run():
            i = 0
            while not self._stop:
                f = self.FRAMES[i % len(self.FRAMES)]
                sys.stdout.write("\r" + self.c.cyan(f) + " " + self.msg)
                sys.stdout.flush()
                i += 1
                time.sleep(0.08)

        self._t = threading.Thread(target=run, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop = True
        if self._t:
            self._t.join(timeout=0.3)
        if self.c.enabled:
            sys.stdout.write("\r" + " " * (len(self.msg) + 4) + "\r")
            sys.stdout.flush()


def _inline_md(text, c):
    """Aplica cores a **negrito** e `código` em uma linha de texto."""
    text = re.sub(r"\*\*(.+?)\*\*", lambda m: c.bold(m.group(1)), text)
    text = re.sub(r"`([^`]+)`", lambda m: c.yellow(m.group(1)), text)
    text = re.sub(r"^#{1,6}\s*(.+)$", lambda m: c.bold(c.cyan(m.group(1))), text)
    return text


class MarkdownPrinter:
    """Imprime o streaming do modelo com cores: títulos, negrito, código,
    listas. Em terminal sem cor, escreve o texto puro."""

    def __init__(self, c, out=None):
        self.c = c
        self.out = out or sys.stdout
        self.line_buf = ""
        self.in_code = False

    def write(self, piece):
        self.line_buf += piece
        while "\n" in self.line_buf:
            line, self.line_buf = self.line_buf.split("\n", 1)
            self._emit(line)

    def finish(self):
        if self.line_buf:
            self._emit(self.line_buf)
        if not self.line_buf.endswith("\n"):
            self.out.write("\n")

    def _emit(self, line):
        if not self.c.enabled:
            self.out.write(line + "\n")
            return
        stripped = line.strip()
        if stripped.startswith("```"):
            if self.in_code:
                self.in_code = False
                self.out.write(self.c.dim("└" + "─" * 42) + "\n")
            else:
                lang = re.match(r"```([\w+\-]*)", stripped)
                lang = (lang.group(1) if lang and lang.group(1) else "código")
                self.out.write(self.c.dim(f"┌─ {lang} " + "─" * max(2, 38 - len(lang))) + "\n")
                self.in_code = True
            return
        if self.in_code:
            self.out.write(self.c.green(line) + "\n")
            return
        if line.startswith("#"):
            self.out.write(self.c.bold(self.c.cyan(line)) + "\n")
            return
        if stripped.startswith(("- ", "* ", "+ ", "• ")):
            self.out.write(self.c.cyan("  • ") + _inline_md(line[2:], self.c) + "\n")
            return
        if re.match(r"^\s*\d+[\.\)]", line):
            num = re.match(r"^\s*\d+", line).group(0)
            rest = re.sub(r"^\s*\d+[\.\)]\s*", " ", line, count=1)
            self.out.write(self.c.magenta("  " + num + ".") +
                           _inline_md(rest, self.c) + "\n")
            return
        self.out.write(_inline_md(line, self.c) + "\n")


TOOL_ICONS = {
    "read_file": "📄", "write_file": "📝", "edit_file": "✏️ ", "list_files": "📂",
    "find_files": "🔍", "run_command": "💻", "web_search": "🌐", "fetch_url": "🌐",
    "system_info": "🖥️", "open_file": "📂", "open_url": "🔗",
    "git_status": "🌿", "git_log": "🌿", "git_diff": "🌿", "git_commit": "🌿",
    "list_processes": "⚙️", "kill_process": "🛑", "read_memory": "🧠",
    "remember": "🧠", "create_skill": "⭐",
}


def tool_icon(name):
    if name.startswith("skill_"):
        return "⭐"
    return TOOL_ICONS.get(name, "🔧")


def nice_error(c, title, msg):
    """Erro em painel vermelho."""
    panel("✗ " + title, msg, c, color="red", width=66)


def _wait_key(timeout=4.0):
    """Aguarda uma tecla (sem precisar de Enter). Retorna '' no timeout."""
    import select
    import termios
    import tty
    if not sys.stdin.isatty() or os.name == "nt":
        return ""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        if r:
            return sys.stdin.read(1)
        return ""
    except Exception:
        return ""
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            pass


def show_thinking_panel(sess, c, cfg):
    """Mostra o pensamento do modelo em modo minimizado/expansível.

    Depois da resposta, imprime uma linha discreta:
        🧠 Pensamento do modelo (12 linhas) — [Enter] expandir · [q] pular
    Enter/espaço/e expande o painel; q (ou 4s de espera) minimiza.
    Fora de terminal interativo, apenas informa o comando /pensamento.
    """
    text = (getattr(sess, "last_reasoning", "") or "").strip()
    if not text or not cfg.get("show_reasoning", True):
        return
    n = len([ln for ln in text.splitlines() if ln.strip()])
    if not sys.stdin.isatty():
        print(c.dim(f"🧠 Pensamento do modelo ({n} linhas) — "
                    "use /pensamento para expandir"))
        return
    sys.stdout.write(c.dim(f"🧠 Pensamento do modelo ({n} linhas) — "
                           "[Enter] expandir · [q] pular "))
    sys.stdout.flush()
    key = _wait_key(4.0)
    sys.stdout.write("\r" + " " * 70 + "\r")
    sys.stdout.flush()
    if key in ("\r", "\n", " ", "e", "E"):
        panel("🧠 PENSAMENTO DO MODELO", text, c, color="magenta", width=78)
    print()


# ---------------------------------------------------------------------------
# Código: detecção de blocos e auto-salvar no computador
# ---------------------------------------------------------------------------

CODE_LANG_FILES = {
    "python": "main.py", "py": "main.py", "python3": "main.py",
    "javascript": "script.js", "js": "script.js", "node": "script.js",
    "typescript": "script.ts", "ts": "script.ts",
    "bash": "script.sh", "sh": "script.sh", "shell": "script.sh",
    "zsh": "script.sh", "html": "index.html", "css": "style.css",
    "json": "dados.json", "yaml": "config.yaml", "yml": "config.yml",
    "toml": "config.toml", "ini": "config.ini", "sql": "consulta.sql",
    "java": "Main.java", "c": "main.c", "cpp": "main.cpp", "c++": "main.cpp",
    "c#": "Program.cs", "cs": "Program.cs", "go": "main.go",
    "rust": "main.rs", "ruby": "script.rb", "rb": "script.rb",
    "php": "script.php", "swift": "main.swift", "kotlin": "Main.kt",
    "r": "analise.R", "lua": "script.lua", "perl": "script.pl",
    "markdown": "notas.md", "md": "notas.md", "text": "notas.txt",
    "dockerfile": "Dockerfile", "docker": "Dockerfile",
    "makefile": "Makefile", "make": "Makefile", "": "codigo.txt",
}


def _unique_name(name, used):
    if name not in used:
        return name
    stem, dot, ext = name.rpartition(".")
    i = 2
    while f"{stem}_{i}{dot}{ext}" in used:
        i += 1
    return f"{stem}_{i}{dot}{ext}"


def suggest_filename(lang, meta, used):
    """Sugere um nome de arquivo para um bloco de código.

    Usa o nome citado na cerca do código (```python app.py), senão mapeia
    pela linguagem.
    """
    m = (meta or "").strip()
    if m and "." in m:
        cand = m.split()[0].strip("`\"'()[]")
        if re.match(r"^[\w.\-/]+$", cand):
            return _unique_name(Path(cand).name, used)
    name = CODE_LANG_FILES.get((lang or "").lower(), "codigo.txt")
    return _unique_name(name, used)


def parse_code_blocks(content):
    """Extrai blocos de código cercados por ``` de uma resposta."""
    blocks = []
    if not content:
        return blocks
    for m in re.finditer(r"```([\w+\-]*)[ \t]*([^\n]*)\n(.*?)```",
                         content, re.S):
        lang = m.group(1).strip()
        meta = m.group(2).strip()
        code = m.group(3).rstrip("\n")
        if code.strip():
            blocks.append({"lang": lang, "meta": meta, "code": code})
    return blocks


def offer_save_code(content, c, cfg, auto_confirm, dest_dir=None):
    """Salva blocos de código da resposta no computador.

    - com -y / auto_save_code: salva tudo sem perguntar
    - interativo: pergunta 'salvar como X? (s/N/caminho)'
    - sem terminal: não pergunta, não salva
    Retorna a lista de arquivos salvos.
    """
    blocks = parse_code_blocks(content)
    if not blocks:
        return []
    saved = []
    base = Path(dest_dir) if dest_dir else Path.cwd()
    used = []
    for b in blocks[:4]:
        fname = suggest_filename(b["lang"], b["meta"], used)
        used.append(fname)
        target = base / fname
        if auto_confirm or cfg.get("auto_save_code"):
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(b["code"], encoding="utf-8")
                saved.append(str(target))
                print(c.green(f"  💾 Código salvo: {target}"))
            except Exception as e:
                print(c.red(f"  ✗ Não foi possível salvar {target}: {e}"))
            continue
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            continue
        try:
            r = input(c.dim(f"💾 Bloco de código ({b['lang'] or 'texto'}) — "
                            f"salvar como '{fname}'? (s/N/caminho) ")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not r or r.lower() in ("n", "não", "nao", "no"):
            continue
        if r.lower() not in ("s", "sim", "y", "yes"):
            target = Path(r).expanduser()
            if not target.is_absolute():
                target = Path.cwd() / target
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(b["code"], encoding="utf-8")
            saved.append(str(target))
            print(c.green(f"  ✅ Código salvo: {target}"))
        except Exception as e:
            print(c.red(f"  ✗ Não foi possível salvar {target}: {e}"))
    return saved


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "base_url": DEFAULT_BASE_URL,
    "api_key": "",
    "model": None,                 # None = detecta o primeiro modelo disponível
    "provider": "auto",            # preset ou id de um provider customizado
    "providers": {},               # configurações/último modelo por provider
    "setup_complete": False,        # assistente de primeira inicialização concluído
    "mode": "coding",              # chat | coding | plan | workflow
    "thinking": False,
    "reasoning_effort": "medium",  # low | medium | high
    "show_reasoning": True,
    "auto_confirm": False,         # -y
    "temperature": 0.7,
    "skills": ["arquivos", "terminal", "internet", "pc",
               "git", "processos", "memoria", "subagentes"],
    "auto_backend": True,          # detecta LM Studio → Ollama automaticamente
    "project_context": True,       # injeta a árvore do projeto no contexto
    "auto_summarize": True,        # resume conversas longas automaticamente
    "compression_threshold_tokens": 20000,  # ~80k chars, grátis estimativa local (tokens≈chars/4)
    "compression_proactive_prune": True,   # poda tool results grandes sem chamar API
    "auto_save_code": False,       # True = salva blocos de código sem perguntar
    "mcp_enabled": True,           # conecta servidores MCP de ~/.send/mcp.json
    "hooks": True,                 # executa hooks de ~/.send/hooks.json
    "auto_mode": True,             # escolhe o modo sozinho (chat/coding/plan/workflow)
    "outmode": False,              # OUTMODE: age sem pedir autorização
    # Guardrails grátis (local, sem API paga) — inspirado no Hermes
    "guardrails_warnings": True,   # avisa quando detecta loop de ferramentas
    "guardrails_hard_stop": False, # True = interrompe loop em vez de só avisar
    # Memória limitada grátis (sem API) — evita injeção infinita no prompt
    "memory_char_limit": 2200,     # ~800 tokens, pruned automaticamente
    "memory_nudge_interval": 10,   # a cada 10 turnos lembra o modelo de salvar
}

# Backups automáticos antes de editar/escrever arquivos
BACKUP_DIR = SEND_HOME / "backups"
BACKUP_INDEX = BACKUP_DIR / "index.json"

# ---------------------------------------------------------------------------
# Skills — habilidades que o SEND pode usar
# ---------------------------------------------------------------------------

SKILLS = {
    "arquivos": "ler, escrever, editar, listar e procurar arquivos no PC",
    "terminal": "executar comandos no terminal",
    "internet": "pesquisar na web e ler o conteúdo de páginas",
    "pc": "abrir arquivos/links no sistema e ver informações do PC",
    "git": "operar repositórios git (status, diff, log, commit)",
    "processos": "listar e encerrar processos do sistema",
    "memoria": "aprender com o tempo: lembrar informações, ver a memória "
               "de longo prazo e criar novas skills para o futuro",
    "subagentes": "delegar tarefas a subagentes especializados (revisor, "
                  "pesquisador, analista…), criar novos subagentes e montar "
                  "equipes de 2+ IAs trabalhando juntas (team)",
}

SKILL_ORDER = ["arquivos", "terminal", "internet", "pc",
               "git", "processos", "memoria", "subagentes"]

# Memória de longo prazo (aprendizado) e skills personalizadas
MEMORY_PATH = SEND_HOME / "memoria.md"
SKILLS_DIR = SEND_HOME / "skills"
SUBAGENTS_DIR = SEND_HOME / "subagents"
MCP_CONFIG_PATH = SEND_HOME / "mcp.json"
HOOKS_PATH = SEND_HOME / "hooks.json"

USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 "
              "Firefox/126.0")

# Endpoint de busca (padrão: DuckDuckGo, sem chave de API).
# Pode ser trocado com a variável SEND_SEARCH_URL (útil para testes).
SEARCH_URL = os.environ.get(
    "SEND_SEARCH_URL", "https://html.duckduckgo.com/html/?q={q}"
)

# Pastas ignoradas ao procurar arquivos
IGNORED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    "target", ".next", ".cache", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".tox", ".nox", ".nuxt", ".output", ".parcel-cache", ".svelte-kit",
    ".turbo", ".vite", ".idea", ".vscode",
}

MEMORY_PROMPT_HINT = (
    " Você tem uma memória de longo prazo em ~/.send/memoria.md. Sempre que "
    "aprender algo útil (preferências do usuário, decisões do projeto, bugs "
    "corrigidos, comandos importantes), registre com a ferramenta 'remember'. "
    "Você pode criar novas skills para o futuro com a ferramenta 'create_skill' "
    "e novos subagentes especializados com a ferramenta 'create_subagent'."
)


def memory_summary(limit=1800):
    """Retorna um resumo da memória de longo prazo (ou '' se vazia)."""
    try:
        if not MEMORY_PATH.exists():
            return ""
        text = MEMORY_PATH.read_text(encoding="utf-8").strip()
        if not text:
            return ""
        if len(text) > limit:
            text = text[:limit].rsplit("\n", 1)[0] + "\n… (memória truncada)"
        return text
    except Exception:
        return ""


def remember_entry(content):
    """Grava uma entrada com data na memória de longo prazo (com limite grátis)."""
    try:
        SEND_HOME.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M")
        entry = f"\n## {ts}\n- {content.strip()}\n"
        with open(MEMORY_PATH, "a", encoding="utf-8") as f:
            f.write(entry)
        # Pruning grátis: se exceder limite, mantém 80% mais recente
        try:
            limit = 2200
            # lê limite do config se possível (usa DEFAULT_CONFIG como fallback)
            text = MEMORY_PATH.read_text(encoding="utf-8")
            if len(text) > limit:
                # mantém cabeçalho se houver e últimos 80%
                keep = int(limit * 0.8)
                pruned = text[-keep:]
                # tenta cortar em quebra de seção
                cut = pruned.find("\n## ")
                if cut > 0:
                    pruned = pruned[cut:]
                header = "# Memória SEND — aprendizado acumulado (podado automaticamente)\n"
                MEMORY_PATH.write_text(header + pruned, encoding="utf-8")
        except Exception:
            pass
        return True
    except Exception:
        return False

def _memory_nudge_needed(sess):
    """Grátis: a cada N turnos lembra o modelo de consolidar memória."""
    try:
        interval = sess.cfg.get("memory_nudge_interval", 10)
        if not interval or interval <= 0:
            return False
        # conta turnos de usuário
        user_turns = sum(1 for m in sess.messages if m.get("role") == "user")
        return user_turns > 0 and user_turns % interval == 0
    except Exception:
        return False


def load_custom_skills():
    """Lê as skills personalizadas criadas pelo modelo (~/.send/skills/*.md).

    Cada arquivo .md tem o formato:
        # Skill: <nome>
        Descrição: <frase curta sobre o que ela faz>
        ## Instruções
        <corpo com as instruções que o modelo deve seguir>
    """
    out = []
    try:
        if not SKILLS_DIR.exists():
            return out
        for f in sorted(SKILLS_DIR.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            name = f.stem.strip().lower()
            if not name:
                continue
            m = re.search(r"(?im)^\s*descri(?:ção|cao)\s*:\s*(.+)$", text)
            desc = m.group(1).strip() if m else "(sem descrição)"
            out.append({"name": name, "description": desc, "instructions": text})
    except Exception:
        pass
    return out


def custom_skill_tool(cs):
    """Converte uma skill personalizada em uma ferramenta para a API."""
    return {
        "type": "function",
        "function": {
            "name": "skill_" + cs["name"],
            "description": ("Skill personalizada '" + cs["name"] + "': "
                            + cs["description"] + " Siga as instruções da skill "
                            "para executar a tarefa."),
            "parameters": {
                "type": "object",
                "properties": {
                    "tarefa": {
                        "type": "string",
                        "description": "O que você quer que a skill execute.",
                    }
                },
                "required": ["tarefa"],
            },
        },
        "skill": cs["name"],
    }


def get_tools(cfg):
    """Ferramentas da API filtrando pelas skills ativas + skills criadas."""
    enabled = set(cfg.get("skills", []))
    tools = [t for t in TOOLS if t.get("skill") in enabled]
    for cs in load_custom_skills():
        if cs["name"] in enabled:
            tools.append(custom_skill_tool(cs))
    if cfg.get("mcp_enabled", True):
        tools.extend(mcp_tools())
    return tools


# ---------------------------------------------------------------------------
# MCP (Model Context Protocol) — ferramentas de servidores externos
# ---------------------------------------------------------------------------
# Configuração: ~/.send/mcp.json
#   {"servers": {"nome": {"command": "npx",
#                         "args": ["-y", "@modelcontextprotocol/server-..."],
#                         "env": {"CHAVE": "valor"}}}}
# Cada servidor MCP expõe ferramentas que viram mcp_<servidor>_<ferramenta>.

MCP_PROTOCOL_VERSION = "2025-03-26"
_MCP = {"started": False, "servers": {}}


def mcp_load_config():
    """Lê ~/.send/mcp.json e devolve {nome: {command, args, env}}."""
    try:
        if not MCP_CONFIG_PATH.exists():
            return {}
        data = json.loads(MCP_CONFIG_PATH.read_text(encoding="utf-8"))
        servers = data.get("servers") or {}
        out = {}
        for name, spec in servers.items():
            if isinstance(spec, dict) and spec.get("command"):
                out[name] = {
                    "command": str(spec["command"]),
                    "args": [str(a) for a in (spec.get("args") or [])],
                    "env": {str(k): str(v) for k, v in (spec.get("env") or {}).items()},
                }
        return out
    except Exception:
        return {}


def _mcp_reader(proc, srv):
    """Thread: lê stdout do processo MCP e enfileira as mensagens JSON-RPC."""
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            srv["queue"].put(msg)
    except Exception:
        pass


def _mcp_err_reader(proc, srv):
    """Thread: drena o stderr do processo (evita travar o pipe)."""
    try:
        data = proc.stderr.read(20000)
        srv["stderr"] = data
    except Exception:
        pass


def _mcp_send(name, msg):
    srv = _MCP["servers"].get(name)
    if not srv or not srv.get("proc"):
        return False
    try:
        with srv["wlock"]:
            srv["proc"].stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            srv["proc"].stdin.flush()
        return True
    except Exception:
        return False


def _mcp_wait(srv, msg_id, timeout):
    end = time.time() + timeout
    while time.time() < end:
        try:
            msg = srv["queue"].get(timeout=0.2)
        except Exception:
            continue
        if isinstance(msg, dict) and msg.get("id") == msg_id:
            return msg
        # notificações do servidor (ex.: logs) — ignora
    return None


def _mcp_call(name, method, params=None, timeout=10):
    srv = _MCP["servers"].get(name)
    if not srv or srv.get("error"):
        return {"error": (srv.get("error") if srv else
                          "servidor MCP não conectado")}
    with srv["wlock"]:
        msg_id = srv["next_id"]
        srv["next_id"] += 1
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    if not _mcp_send(name, msg):
        return {"error": "falha ao enviar mensagem ao servidor MCP"}
    resp = _mcp_wait(srv, msg_id, timeout)
    if resp is None:
        return {"error": f"timeout aguardando '{method}'"}
    if resp.get("error"):
        return {"error": json.dumps(resp["error"], ensure_ascii=False)[:300]}
    return {"result": resp.get("result")}


def _mcp_tool_name(server, tool):
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "_", f"{server}_{tool}").strip("_")
    return "mcp_" + clean


def mcp_connect(name, spec, c):
    """Conecta a um servidor MCP via stdio (JSON-RPC 2.0, linhas newline)."""
    srv = {"tools": [], "error": None, "next_id": 1, "stderr": ""}
    _MCP["servers"][name] = srv
    try:
        env = dict(os.environ)
        env.update(spec["env"])
        proc = subprocess.Popen(
            [spec["command"]] + spec["args"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", bufsize=1, env=env,
        )
        srv["proc"] = proc
        srv["queue"] = queue.Queue()
        srv["wlock"] = threading.Lock()
        threading.Thread(target=_mcp_reader, args=(proc, srv),
                         daemon=True).start()
        threading.Thread(target=_mcp_err_reader, args=(proc, srv),
                         daemon=True).start()
        resp = _mcp_call(name, "initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "send", "version": VERSION},
        }, timeout=10)
        if "error" in resp:
            raise RuntimeError("initialize: " + resp["error"])
        _mcp_send(name, {"jsonrpc": "2.0",
                         "method": "notifications/initialized"})
        resp = _mcp_call(name, "tools/list", timeout=10)
        if "error" in resp:
            raise RuntimeError("tools/list: " + resp["error"])
        for t in (resp.get("result") or {}).get("tools") or []:
            tname = str(t.get("name") or "")
            if not tname:
                continue
            schema = t.get("inputSchema") or {}
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}
            srv["tools"].append({
                "type": "function",
                "function": {
                    "name": _mcp_tool_name(name, tname),
                    "description": (f"MCP [{name}] {tname}: "
                                    + str(t.get("description")
                                          or "(sem descrição)")),
                    "parameters": schema,
                },
                "skill": "mcp",
                "mcp": {"server": name, "tool": tname},
            })
        if c.enabled:
            print(c.dim(f"  🔌 MCP '{name}': {len(srv['tools'])} ferramentas "
                        f"conectadas"))
    except Exception as e:
        srv["error"] = str(e)
        if srv.get("proc"):
            try:
                srv["proc"].terminate()
            except Exception:
                pass
            srv["proc"] = None
        if c.enabled:
            print(c.yellow(f"  ⚠ MCP '{name}': falhou ao conectar — {e}"))


def mcp_start_all(c):
    """Conecta a todos os servidores configurados em ~/.send/mcp.json."""
    _MCP["started"] = True
    for name, spec in mcp_load_config().items():
        mcp_connect(name, spec, c)


def mcp_disconnect(name):
    srv = _MCP["servers"].get(name)
    if srv and srv.get("proc"):
        try:
            srv["proc"].terminate()
        except Exception:
            pass
        srv["proc"] = None


def mcp_stop_all():
    """Encerra os processos MCP na saída do programa."""
    if not _MCP.get("started"):
        return
    for name in list(_MCP["servers"]):
        mcp_disconnect(name)


atexit.register(mcp_stop_all)


def mcp_tools():
    """Ferramentas expostas pelos servidores MCP conectados."""
    out = []
    for srv_name, srv in _MCP["servers"].items():
        if srv.get("error"):
            continue
        out.extend(srv.get("tools", []))
    return out


def mcp_summary(cfg):
    """Resumo de status MCP para /status."""
    if not cfg.get("mcp_enabled", True):
        return "desligado"
    if not _MCP.get("started") or not _MCP["servers"]:
        return "nenhum servidor"
    n_ok = sum(1 for s in _MCP["servers"].values() if not s.get("error"))
    n_err = sum(1 for s in _MCP["servers"].values() if s.get("error"))
    if n_err:
        return f"{n_ok} conectado(s) · {n_err} com erro"
    return f"{n_ok} conectado(s)"


def _mcp_text(result):
    out = []
    for part in result.get("content") or []:
        if isinstance(part, dict):
            if part.get("type") == "text":
                out.append(str(part.get("text", "")))
            elif part.get("text"):
                out.append(str(part["text"]))
    return "\n".join(out)


def tool_mcp_call(name, args, c, cfg=None):
    """Executa uma ferramenta de um servidor MCP (mcp_<servidor>_<ferramenta>)."""
    for srv_name, srv in _MCP["servers"].items():
        for t in srv.get("tools", []):
            if t["function"]["name"] == name:
                resp = _mcp_call(srv_name, "tools/call",
                                 {"name": t["mcp"]["tool"],
                                  "arguments": args or {}},
                                 timeout=120)
                if "error" in resp:
                    return f"Erro MCP: {resp['error']}"
                result = resp.get("result") or {}
                if result.get("isError"):
                    return "Erro MCP: " + (_mcp_text(result) or "falha")
                return _mcp_text(result) or "(sem saída)"
    return f"Ferramenta MCP não encontrada: {name}"


# ---------------------------------------------------------------------------
# Hooks — comandos do sistema disparados em eventos (opcional)
# ---------------------------------------------------------------------------
# Configuração: ~/.send/hooks.json
#   {"SessionStart": ["comando"], "PreToolUse": ["comando"],
#    "PostToolUse": ["comando"], "SessionEnd": ["comando"]}
# Variáveis de ambiente: SEND_EVENT, SEND_TOOL, SEND_ARGS, SEND_RESULT,
# SEND_PROMPT. Comandos rodam via shell com timeout de 15s.

def run_hooks(event, c, cfg=None, **env):
    """Executa os hooks do evento (no-op se não houver arquivo configurado)."""
    if cfg is not None and not cfg.get("hooks", True):
        return
    try:
        if not HOOKS_PATH.exists():
            return
        data = json.loads(HOOKS_PATH.read_text(encoding="utf-8"))
        cmds = data.get(event) or []
        if not isinstance(cmds, list):
            return
        full_env = dict(os.environ)
        full_env["SEND_EVENT"] = event
        for k, v in env.items():
            full_env["SEND_" + k.upper()] = v
        for cmd in cmds:
            if not isinstance(cmd, str) or not cmd.strip():
                continue
            try:
                r = subprocess.run(cmd, shell=True, timeout=15, env=full_env,
                                   capture_output=True, text=True)
                out = (r.stdout or "").strip()
                if out and c.enabled:
                    for line in out.splitlines()[:5]:
                        print(c.dim("    🪝 " + line))
            except subprocess.TimeoutExpired:
                if c.enabled:
                    print(c.yellow("    🪝 hook excedeu 15s (ignorado)"))
            except Exception as e:
                if c.enabled:
                    print(c.dim(f"    🪝 hook falhou: {e}"))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Subagentes — agentes especializados que recebem tarefas delegadas
# ---------------------------------------------------------------------------
# Cada subagente é um arquivo em ~/.send/subagents/<nome>.md:
#   # Subagente: <nome>
#   Descrição: <o que ele faz>
#   Ferramentas: read_file, list_files   (opcional; 'nenhuma' = sem tools;
#                                         'todas' = mesmas do agente principal)
#   ## Instruções
#   <papel e regras do subagente>
# O agente principal delega com a ferramenta 'delegate' (ou /subagentes).

# Ferramentas padrão (seguras) quando o subagente não lista as suas
SUBAGENT_DEFAULT_TOOLS = [
    "read_file", "list_files", "find_files",
    "web_search", "fetch_url", "read_memory", "system_info",
]

DEFAULT_SUBAGENTS = {
    "revisor": (
        "# Subagente: revisor\n"
        "Descrição: revisa código procurando bugs, falhas de segurança e "
        "melhorias, e devolve uma lista de problemas encontrados\n"
        "Ferramentas: read_file, list_files, find_files\n"
        "## Instruções\n"
        "Você é um revisor de código experiente. Leia os arquivos indicados, "
        "procure bugs, problemas de segurança, código morto e oportunidades "
        "de melhoria. Responda com uma lista numerada e objetiva: problema, "
        "arquivo/linha, correção sugerida. Não edite arquivos."
    ),
    "pesquisador": (
        "# Subagente: pesquisador\n"
        "Descrição: pesquisa na internet e reúne informações com fontes para "
        "responder perguntas técnicas\n"
        "Ferramentas: web_search, fetch_url\n"
        "## Instruções\n"
        "Você é um pesquisador. Use web_search e fetch_url para buscar "
        "informações atualizadas e confiáveis. Responda com um resumo "
        "organizado citando as fontes consultadas. Se uma busca falhar, "
        "tente outra consulta com termos diferentes."
    ),
    "analista": (
        "# Subagente: analista\n"
        "Descrição: analisa problemas complexos, separa em partes e propõe "
        "soluções antes de qualquer implementação\n"
        "Ferramentas: read_file, list_files, find_files\n"
        "## Instruções\n"
        "Você é um analista. Entenda o problema, divida-o em partes, liste "
        "as opções de solução com prós e contras e recomende uma. Não "
        "execute comandos nem edite arquivos."
    ),
}


def ensure_default_subagents():
    """Cria os subagentes de exemplo na primeira execução (não sobrescreve)."""
    try:
        SUBAGENTS_DIR.mkdir(parents=True, exist_ok=True)
        for name, text in DEFAULT_SUBAGENTS.items():
            f = SUBAGENTS_DIR / (name + ".md")
            if not f.exists():
                f.write_text(text, encoding="utf-8")
    except Exception:
        pass


def load_subagents():
    """Lê os subagentes de ~/.send/subagents/*.md."""
    out = []
    try:
        if not SUBAGENTS_DIR.exists():
            return out
        for f in sorted(SUBAGENTS_DIR.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            name = f.stem.strip().lower()
            if not name:
                continue
            m = re.search(r"(?im)^\s*descri(?:ção|cao)\s*:\s*(.+)$", text)
            desc = m.group(1).strip() if m else "(sem descrição)"
            mt = re.search(r"(?im)^\s*ferramentas?\s*:\s*(.+)$", text)
            tools = None
            if mt:
                raw = mt.group(1).strip().lower()
                if raw in ("nenhuma", "nenhum", "sem", "chat"):
                    tools = []
                else:
                    tools = [t.strip() for t in re.split(r"[,;]", raw)
                             if t.strip()]
            out.append({"name": name, "description": desc, "tools": tools,
                        "instructions": text})
    except Exception:
        pass
    return out


def subagent_system_prompt(cfg, sa):
    """Prompt de sistema de um subagente: papel + instruções + memória."""
    parts = [
        BASE_SYSTEM,
        " Você está atuando como um SUBAGENTE especializado chamado '"
        + sa["name"] + "': " + sa["description"] + ".",
        " Sua tarefa foi delegada pelo agente principal do SEND. "
        "Execute-a completamente e responda apenas com o resultado final, "
        "de forma objetiva.",
    ]
    mem = memory_summary()
    if mem:
        parts.append("\n\n## Memória de longo prazo\n" + mem)
    parts.append("\n\n## Instruções do subagente\n" + (sa["instructions"] or ""))
    return "".join(parts)


def tools_by_names(names):
    """Ferramentas (nativas + skills criadas + MCP) filtradas por nome."""
    allt = list(TOOLS)
    for cs in load_custom_skills():
        allt.append(custom_skill_tool(cs))
    allt.extend(mcp_tools())
    allowed = set(names)
    return [t for t in allt if t["function"]["name"] in allowed]


def run_subagent(name, tarefa, c, cfg=None):
    """Executa um subagente com sua própria conversa e ferramentas.

    Retorna o texto final do subagente (para virar resultado de ferramenta).
    """
    sa = next((s for s in load_subagents() if s["name"] == name), None)
    if not sa:
        return (f"Subagente '{name}' não existe. Use a ferramenta "
                f"'create_subagent' para criá-lo, ou /subagentes para listar.")
    sub_cfg = dict(cfg or DEFAULT_CONFIG)
    sub = Session(sub_cfg, c)
    sub.system_override = subagent_system_prompt(sub_cfg, sa)
    sub.messages = [{"role": "user", "content": "Tarefa: " + tarefa}]
    if sa["tools"] is None:
        sub.custom_tools = [t for t in TOOLS
                            if t["function"]["name"] in SUBAGENT_DEFAULT_TOOLS]
        tools_on = True
    elif not sa["tools"]:
        sub.custom_tools = []
        tools_on = False
    elif "todas" in sa["tools"] or "todos" in sa["tools"]:
        sub.custom_tools = None  # mesmas ferramentas ativas do agente principal
        tools_on = True
    else:
        sub.custom_tools = tools_by_names(sa["tools"])
        tools_on = True
    print(c.cyan("  🤖 subagente ") + c.bold(sa["name"]) + c.dim(" — "
          + sa["description"]))
    print(c.dim("  ─ tarefa: " + tarefa[:120] + ("…" if len(tarefa) > 120
                                                 else "")))
    try:
        content = ask_model(sub, tools_on, c, True)  # sem perguntar: delegado
    except Exception as e:
        content = f"Erro ao executar o subagente: {e}"
    return f"[subagente:{name}]\n{content or '(sem resposta)'}"


def tool_delegate(args, c, cfg=None):
    """Ferramenta 'delegate': envia uma tarefa para um subagente."""
    name = str(args.get("nome") or args.get("name") or "").strip().lower()
    tarefa = str(args.get("tarefa") or "").strip()
    if not name:
        return "Erro: informe 'nome' do subagente (ex.: revisor)."
    if not tarefa:
        return "Erro: informe 'tarefa' para o subagente."
    return run_subagent(name, tarefa, c, cfg)


def tool_create_subagent(args, c, cfg=None):
    """Ferramenta 'create_subagent': cria um subagente para o futuro."""
    nome = str(args.get("nome") or "").strip().lower()
    desc = str(args.get("descricao") or "").strip()
    instrucoes = str(args.get("instrucoes") or "").strip()
    ferramentas = str(args.get("ferramentas") or "").strip()
    if not nome:
        return "Erro: informe 'nome' do subagente."
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", nome):
        return ("Erro: nome inválido — use só letras minúsculas, números, "
                "'-' ou '_'.")
    if not instrucoes:
        return "Erro: informe 'instrucoes' (o papel do subagente)."
    try:
        SUBAGENTS_DIR.mkdir(parents=True, exist_ok=True)
        f = SUBAGENTS_DIR / (nome + ".md")
        lines = ["# Subagente: " + nome,
                 "Descrição: " + (desc or nome),
                 "Ferramentas: " + ferramentas,
                 "## Instruções", instrucoes]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return (f"✅ Subagente '{nome}' criado em {f}. "
                "Disponível imediatamente para delegação.")
    except Exception as e:
        return f"Erro ao criar subagente: {e}"


def _parse_team_agent(spec):
    """Parseia 'nome' ou 'nome@model' ou 'nome:provider/model' -> (nome, model_override, provider_override)."""
    spec = spec.strip()
    if not spec:
        return None, None, None
    # suporta 'nome@model' e 'nome:provider/model' (ex: revisor:openai/gpt-4o)
    model_override = None
    provider_override = None
    name = spec
    if "@" in spec:
        # formato nome@model
        parts = spec.split("@", 1)
        name = parts[0].strip().lower()
        model_override = parts[1].strip()
    elif ":" in spec and "/" in spec:
        # formato nome:provider/model  -> ex: revisor:openai/gpt-4o
        idx = spec.find(":")
        name = spec[:idx].strip().lower()
        rest = spec[idx+1:].strip()
        if "/" in rest:
            prov, mod = rest.split("/", 1)
            provider_override = prov.strip()
            model_override = mod.strip()
        else:
            model_override = rest
    else:
        name = spec.strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", name):
        return None, None, None
    return name, model_override, provider_override


def run_team(tarefa, agentes, estrategia, c, cfg=None):
    """Executa uma equipe de 2+ subagentes em paralelo (grátis, local) e sintetiza.

    Cada agente pode ser 'nome' ou 'nome@model' para usar modelo diferente.
    Estratégias:
      paralelo   -> todos rodam ao mesmo tempo com a mesma tarefa (papel diferente)
      debate     -> primeiro propõe, segundo critica, terceiro sintetiza
      sequencial -> cada um rodando após o anterior, vendo resultado anterior
    Retorna texto com síntese + detalhes por agente.
    """
    if not agentes or len(agentes) < 2:
        return "Erro: equipe precisa de pelo menos 2 agentes (ex.: ['revisor','pesquisador'])."
    if not tarefa or not tarefa.strip():
        return "Erro: informe 'tarefa' para a equipe."
    estrategia = (estrategia or "paralelo").strip().lower()
    if estrategia not in ("paralelo", "debate", "sequencial"):
        estrategia = "paralelo"

    # valida agentes
    parsed = []
    for spec in agentes:
        name, model_o, prov_o = _parse_team_agent(str(spec))
        if not name:
            return f"Erro: agente inválido '{spec}' (use nome em minúsculas, a-z0-9_-)."
        sa = next((s for s in load_subagents() if s["name"] == name), None)
        if not sa:
            return f"Erro: subagente '{name}' não existe. Liste com /subagentes ou crie com create_subagent."
        parsed.append((name, model_o, prov_o, sa))

    print(c.cyan(f"  👥 equipe {estrategia} ") + c.bold(f"{len(parsed)} IAs") + c.dim(f" — {', '.join(a[0] for a in parsed)}"))
    print(c.dim(f"  ─ tarefa: {tarefa[:120]}{'...' if len(tarefa) > 120 else ''}"))

    results = {}
    errors = {}

    def _run_one(name, model_o, prov_o, sa):
        try:
            sub_cfg = dict(cfg or DEFAULT_CONFIG)
            # modelo diferente por agente (grátis: mesmo servidor local, modelo diferente)
            if model_o:
                sub_cfg["model"] = model_o
            if prov_o:
                sub_cfg["provider"] = prov_o
            sub = Session(sub_cfg, c)
            sub.system_override = subagent_system_prompt(sub_cfg, sa)
            # estratégia muda o prompt da tarefa
            if estrategia == "debate":
                role_tarefa = f"[DEBATE - você é {name}] {tarefa}"
            elif estrategia == "sequencial":
                role_tarefa = f"[SEQUENCIAL - equipe {estrategia}] {tarefa}"
            else:
                role_tarefa = tarefa
            sub.messages = [{"role": "user", "content": "Tarefa da equipe: " + role_tarefa}]
            if sa["tools"] is None:
                sub.custom_tools = [t for t in TOOLS if t["function"]["name"] in SUBAGENT_DEFAULT_TOOLS]
                tools_on = True
            elif not sa["tools"]:
                sub.custom_tools = []
                tools_on = False
            elif "todas" in sa["tools"] or "todos" in sa["tools"]:
                sub.custom_tools = None
                tools_on = True
            else:
                sub.custom_tools = tools_by_names(sa["tools"])
                tools_on = True
            content = ask_model(sub, tools_on, c, True)
            results[name] = content or "(sem resposta)"
        except Exception as e:
            errors[name] = str(e)
            results[name] = f"Erro: {e}"

    if estrategia == "sequencial":
        # sequencial: um após o outro, cada um vê resultado anterior (grátis)
        prev_text = ""
        for name, model_o, prov_o, sa in parsed:
            tarefa_seq = tarefa + (f"\n\nResultado anterior da equipe:\n{prev_text[:2000]}" if prev_text else "")
            # redefine _run_one temporariamente para usar tarefa_seq
            def _run_seq(n=name, m=model_o, p=prov_o, s=sa, task=tarefa_seq):
                try:
                    sub_cfg = dict(cfg or DEFAULT_CONFIG)
                    if m:
                        sub_cfg["model"] = m
                    if p:
                        sub_cfg["provider"] = p
                    sub = Session(sub_cfg, c)
                    sub.system_override = subagent_system_prompt(sub_cfg, s)
                    sub.messages = [{"role": "user", "content": "Tarefa da equipe (sequencial): " + task}]
                    if s["tools"] is None:
                        sub.custom_tools = [t for t in TOOLS if t["function"]["name"] in SUBAGENT_DEFAULT_TOOLS]
                        tools_on = True
                    elif not s["tools"]:
                        sub.custom_tools = []
                        tools_on = False
                    elif "todas" in s["tools"] or "todos" in s["tools"]:
                        sub.custom_tools = None
                        tools_on = True
                    else:
                        sub.custom_tools = tools_by_names(s["tools"])
                        tools_on = True
                    content = ask_model(sub, tools_on, c, True)
                    results[n] = content or "(sem resposta)"
                except Exception as e:
                    errors[n] = str(e)
                    results[n] = f"Erro: {e}"
            _run_seq()
            prev_text = results.get(name, "")
    else:
        # paralelo e debate: todos em threads ao mesmo tempo
        threads = []
        for name, model_o, prov_o, sa in parsed:
            th = threading.Thread(target=_run_one, args=(name, model_o, prov_o, sa), daemon=True)
            th.start()
            threads.append(th)
        for th in threads:
            th.join(timeout=180)

    # verifica timeouts
    for name, _, _, _ in parsed:
        if name not in results:
            results[name] = "(timeout - sem resposta em 180s)"
            errors[name] = "timeout"

    # síntese grátis: usa o modelo principal (pode ser local) para juntar o melhor
    synth_cfg = dict(cfg or DEFAULT_CONFIG)
    synth = Session(synth_cfg, c)
    synth.system_override = BASE_SYSTEM + " Você é o coordenador de uma equipe de IAs. Sintetize o trabalho de 2+ subagentes em uma resposta final objetiva, mantendo o melhor de cada um e eliminando contradições. Se for código, entregue o código final completo."
    combined = ""
    for name, _, _, _ in parsed:
        combined += f"\n\n--- Resultado de '{name}' ---\n" + (results.get(name) or "")[:4000]
    synth.messages = [{"role": "user", "content": f"Tarefa original: {tarefa}\n\nEstratégia: {estrategia}\n{combined}\n\nAgora sintetize o resultado final da equipe de forma coesa. Se houver código, entregue o código final. Se houver divergência, escolha a melhor abordagem e explique."}]
    try:
        print(c.dim("  🧠 sintetizando equipe..."))
        final = ask_model(synth, False, c, True) or ""
    except Exception as e:
        final = f"(falha na síntese: {e})\n" + combined[:4000]

    out = [c.bold(c.cyan(f"✅ Equipe {estrategia} concluída ({len(parsed)} IAs)")), ""]
    out.append(final.strip() or "(sem síntese)")
    out.append("")
    out.append(c.dim("── Detalhes por agente ──"))
    for name, _, _, _ in parsed:
        out.append("")
        out.append(c.bold(f"🤖 {name}:"))
        out.append((results.get(name) or "")[:2000])
        if name in errors:
            out.append(c.yellow(f" (erro: {errors[name]})"))
    return "\n".join(out)


def tool_team(args, c, cfg=None):
    """Ferramenta 'team': equipe de 2+ IAs colaborando."""
    tarefa = str(args.get("tarefa") or "").strip()
    agentes = args.get("agentes") or []
    estrategia = str(args.get("estrategia") or "paralelo").strip()
    if not isinstance(agentes, list):
        return "Erro: 'agentes' deve ser uma lista (ex.: ['revisor','pesquisador'])."
    # limpa lista
    agentes = [str(a).strip() for a in agentes if str(a).strip()]
    return run_team(tarefa, agentes, estrategia, c, cfg)


def backup_file(path):
    """Salva uma cópia de segurança de um arquivo antes de alterá-lo.

    Retorna o caminho do backup (ou None se não for possível/faltar arquivo).
    Os backups ficam em ~/.send/backups/ com um índice em index.json.
    """
    try:
        if not path.exists() or not path.is_file():
            return None
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        idx = []
        if BACKUP_INDEX.exists():
            try:
                idx = json.loads(BACKUP_INDEX.read_text(encoding="utf-8"))
            except Exception:
                idx = []
        flat = str(path).replace("\\", "_").replace("/", "_").replace(" ", "_")
        name = f"{ts}__{flat}"
        dest = BACKUP_DIR / name
        shutil.copy2(path, dest)
        idx.append({"ts": ts, "original": str(path), "backup": name})
        # mantém só os 100 backups mais recentes
        idx = idx[-100:]
        BACKUP_INDEX.write_text(
            json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
        return dest
    except Exception:
        return None


def list_backups():
    """Lista os backups disponíveis (mais recentes primeiro)."""
    try:
        if not BACKUP_INDEX.exists():
            return []
        idx = json.loads(BACKUP_INDEX.read_text(encoding="utf-8"))
        return list(reversed(idx))
    except Exception:
        return []


def restore_backup(n, c):
    """Restaura o n-ésimo backup (1 = mais recente)."""
    backups = list_backups()
    if not backups:
        return "Nenhum backup encontrado em " + str(BACKUP_DIR)
    if not 1 <= n <= len(backups):
        return (f"Número inválido (1–{len(backups)}).")
    b = backups[n - 1]
    orig = Path(b["original"])
    src = BACKUP_DIR / b["backup"]
    if not src.exists():
        return f"Arquivo de backup não encontrado: {src}"
    orig.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, orig)
    return f"✅ Restaurado: {orig} (backup de {b['ts']})"


def detect_backend(cfg, c):
    """Auto-detecta o backend quando o padrão (LM Studio) não responde.

    Tenta LM Studio (1234) → Ollama (11434). Retorna a URL usada.
    """
    if not cfg.get("auto_backend", True):
        return cfg["base_url"]
    if cfg["base_url"] != DEFAULT_BASE_URL:
        return cfg["base_url"]  # URL customizada: não mexe
    try:
        list_models(cfg["base_url"], provider_api_key(cfg))
        return cfg["base_url"]  # LM Studio responde
    except Exception:
        pass
    try:
        list_models(OLLAMA_URL, provider_api_key(cfg))
        print(c.yellow(f"⚡ LM Studio não respondeu — detectei o Ollama em "
                       f"{OLLAMA_URL} (use /backend para trocar)."))
        return OLLAMA_URL
    except Exception:
        return cfg["base_url"]


def project_tree(max_entries=25, max_depth=2):
    """Árvore curta do diretório atual para dar contexto ao modelo."""
    try:
        root = Path.cwd()
        lines = [f"Projeto atual: {root}"]
        counter = [0]

        def walk(path, depth):
            if counter[0] >= max_entries:
                return
            try:
                entries = sorted(
                    [e for e in path.iterdir() if e.name not in IGNORED_DIRS],
                    key=lambda x: (x.is_file(), x.name.lower()),
                )
            except PermissionError:
                return
            for e in entries:
                if counter[0] >= max_entries:
                    return
                if e.is_dir():
                    lines.append("  " * depth + e.name + "/")
                    counter[0] += 1
                    if depth < max_depth:
                        walk(e, depth + 1)
                else:
                    lines.append("  " * depth + e.name)
                    counter[0] += 1

        walk(root, 1)
        if counter[0] >= max_entries:
            lines.append("  … (truncado)")
        return "\n".join(lines)
    except Exception:
        return ""



def provider_spec(cfg, provider_id=None):
    """Devolve a configuração efetiva de um provider (preset ou customizado)."""
    provider_id = provider_id or cfg.get("provider", "auto")
    spec = dict(PROVIDER_PRESETS.get(provider_id, {}))
    spec.update(cfg.get("providers", {}).get(provider_id, {}))
    spec.setdefault("id", provider_id)
    spec.setdefault("name", provider_id)
    return spec


def provider_api_url(cfg, endpoint, spec=None):
    """Monta uma URL respeitando providers cujo endpoint não usa `/v1`."""
    spec = spec or provider_spec(cfg)
    prefix = spec.get("api_prefix", "/v1").rstrip("/")
    custom_path = spec.get(f"{endpoint.strip('/').replace('/', '_')}_path")
    path = custom_path if custom_path is not None else prefix + "/" + endpoint.lstrip("/")
    if not str(path).startswith("/"):
        path = "/" + str(path)
    return spec["base_url"].rstrip("/") + path


def provider_api_key(cfg, spec=None):
    """Chave efetiva: variável do provider > SEND_API_KEY > chave salva."""
    spec = spec or provider_spec(cfg)
    env_name = spec.get("env_key", "")
    saved = spec.get("api_key", "")
    # O campo legado só pertence ao provider que está ativo. Nunca o reutilize
    # ao trocar (por exemplo, não envie uma chave OpenAI para a Anthropic).
    legacy = cfg.get("api_key", "") if spec.get("id") == cfg.get("provider") else ""
    return ((os.environ.get(env_name) if env_name else None)
            or os.environ.get("SEND_API_KEY") or saved or legacy)


def activate_provider(cfg, provider_id, remember_current=True):
    """Ativa um provider e sincroniza os campos legados base_url/api_key/model."""
    if provider_id not in PROVIDER_PRESETS and provider_id not in cfg.get("providers", {}):
        raise KeyError(provider_id)
    providers = cfg.setdefault("providers", {})
    old_id = cfg.get("provider", "auto")
    # Sempre grava o modelo do provider que está saindo — mesmo se ele ainda
    # não tiver uma entrada em providers{} (caso típico após o 1º activate).
    if remember_current and old_id:
        providers.setdefault(old_id, {})["model"] = cfg.get("model")
    spec = provider_spec(cfg, provider_id)
    cfg["provider"] = provider_id
    cfg["base_url"] = spec["base_url"].rstrip("/")
    # Variáveis de ambiente são resolvidas só no momento da chamada e nunca
    # copiadas para config.json.
    cfg["api_key"] = spec.get("api_key", "")
    cfg["model"] = spec.get("model")
    # Só o preset auto alterna sozinho entre os dois servidores locais.
    cfg["auto_backend"] = provider_id == "auto"
    return spec


def _safe_provider_id(name):
    value = re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-")
    return value or "custom"


def configure_provider(cfg, provider_id, c, input_fn=input):
    """Configura um preset ou cria um provider OpenAI-compatible customizado."""
    providers = cfg.setdefault("providers", {})
    if provider_id == "custom":
        try:
            name = input_fn("Nome do provider: ").strip()
            base_url = input_fn("Base URL (ex.: https://api.exemplo.com): ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not name or not base_url.startswith(("http://", "https://")):
            print(c.yellow("Nome ou URL inválidos; configuração cancelada."))
            return None
        provider_id = _safe_provider_id(name)
        original = provider_id
        n = 2
        while provider_id in PROVIDER_PRESETS or provider_id in providers:
            provider_id, n = f"{original}-{n}", n + 1
        try:
            api_format = input_fn(
                "Formato [openai/anthropic/custom-paths] (padrão: openai): "
            ).strip().lower() or "openai"
        except (EOFError, KeyboardInterrupt):
            api_format = "openai"
        custom_spec = {"name": name, "base_url": base_url.rstrip("/"),
                       "api_key": "", "model": None, "custom": True,
                       "api_format": api_format}
        if api_format in ("custom", "custom-paths"):
            try:
                custom_spec["chat_completions_path"] = input_fn(
                    "Path de chat (padrão: /v1/chat/completions): "
                ).strip() or "/v1/chat/completions"
                custom_spec["models_path"] = input_fn(
                    "Path de modelos (padrão: /v1/models): "
                ).strip() or "/v1/models"
            except (EOFError, KeyboardInterrupt):
                custom_spec["chat_completions_path"] = "/v1/chat/completions"
                custom_spec["models_path"] = "/v1/models"
        providers[provider_id] = custom_spec
    elif provider_id not in PROVIDER_PRESETS:
        return None
    preset = PROVIDER_PRESETS.get(provider_id, {})
    if preset.get("needs_endpoint") and not providers.get(provider_id, {}).get("base_url"):
        try:
            endpoint = input_fn(
                f"Endpoint de {preset['name']} ({preset['endpoint_hint']}): "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            endpoint = ""
        if endpoint:
            providers.setdefault(provider_id, {})["base_url"] = endpoint.rstrip("/")
    spec = provider_spec(cfg, provider_id)
    if not spec.get("local"):
        env_name = spec.get("env_key", "")
        if env_name and os.environ.get(env_name):
            print(c.green(f"✅ Chave encontrada em {env_name}."))
        elif not spec.get("api_key"):
            try:
                key = getpass.getpass(
                    f"API key de {spec['name']} (Enter para configurar depois): "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                key = ""
            if key:
                providers.setdefault(provider_id, {})["api_key"] = key
    activate_provider(cfg, provider_id)
    cfg["setup_complete"] = True
    save_config(cfg)
    return provider_id


def first_run_setup(cfg, c):
    """Assistente exibido apenas na primeira execução interativa."""
    if cfg.get("setup_complete") or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    print()
    panel("✨ PRIMEIRA CONFIGURAÇÃO",
          "Escolha seu provider de IA. LM Studio e Ollama continuam sendo\n"
          "detectados automaticamente e não exigem configuração.", c, width=72)
    choices = [
        "auto", "ollama", "lmstudio", "claude", "openai", "nvidia",
        "gemini", "mistral", "groq", "cohere", "together", "perplexity",
        "deepseek", "xai", "openrouter", "azure", "bedrock", "huggingface",
        "custom",
    ]
    for i, pid in enumerate(choices, 1):
        label = "Provider customizado (OpenAI/Anthropic/paths próprios)" if pid == "custom" \
            else PROVIDER_PRESETS[pid]["name"]
        print(f"  {i}. {label}")
    try:
        raw = input("Escolha [1]: ").strip() or "1"
        idx = int(raw) - 1
        provider_id = choices[idx]
    except (ValueError, IndexError, EOFError, KeyboardInterrupt):
        provider_id = "auto"
    selected = configure_provider(cfg, provider_id, c)
    if selected:
        print(c.green(f"✅ Provider ativo: {provider_spec(cfg)['name']}"))
        print(c.dim("   Use 'provider' para adicionar/trocar e 'model' para trocar o modelo."))
    return bool(selected)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    cfg["providers"] = {}
    data = {}
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.update({k: v for k, v in data.items() if k in cfg})
            # Configurações de versões anteriores já estavam prontas para uso.
            if "setup_complete" not in data:
                cfg["setup_complete"] = True
    except Exception:
        pass
    if cfg.get("provider") != "auto" or cfg.get("providers"):
        try:
            activate_provider(cfg, cfg.get("provider", "auto"), remember_current=False)
        except KeyError:
            cfg["provider"] = "auto"
    if os.environ.get("SEND_BASE_URL"):
        cfg["base_url"] = os.environ["SEND_BASE_URL"].rstrip("/")
    if os.environ.get("SEND_MODEL"):
        cfg["model"] = os.environ["SEND_MODEL"]
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
        # A camada OpenAI-compatible da Anthropic aceita o mesmo payload, mas
        # clientes diretos também esperam estes cabeçalhos.
        if "api.anthropic.com" in url:
            req.add_header("x-api-key", api_key)
            req.add_header("anthropic-version", "2023-06-01")
        if ".openai.azure.com" in url:
            req.add_header("api-key", api_key)
        if "generativelanguage.googleapis.com" in url:
            req.add_header("x-goog-api-key", api_key)
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
    """Compatibilidade legada: consulta um endpoint OpenAI em `/v1/models`."""
    data = http_json(base_url + "/v1/models", api_key=api_key, method="GET")
    return _model_ids(data)


def _model_ids(data):
    out = []
    for m in data.get("data", data.get("models", [])):
        if isinstance(m, str):
            mid = m
        else:
            mid = m.get("id") or m.get("name") or ""
            if mid.startswith("models/"):
                mid = mid.split("/", 1)[1]
        if mid:
            out.append(mid)
    return out


def list_provider_models(cfg):
    data = http_json(provider_api_url(cfg, "models"),
                     api_key=provider_api_key(cfg), method="GET")
    return _model_ids(data)


def resolve_model(cfg, c):
    """Retorna o modelo configurado ou o primeiro oferecido pelo provider."""
    if cfg.get("model"):
        return cfg["model"]
    spec = provider_spec(cfg)
    try:
        models = list_provider_models(cfg)
    except urllib.error.URLError as e:
        local_hint = ("\n  ➜ Inicie o LM Studio ou Ollama e carregue um modelo."
                      if spec.get("local") else
                      "\n  ➜ Verifique a URL, a conexão e a API key do provider.")
        raise ConnectionError(
            f"Não consegui conectar a {spec['name']} em {cfg['base_url']} "
            f"({e.reason}).{local_hint}"
        )
    except Exception as e:
        raise ConnectionError(f"Erro ao consultar {spec['name']} em {cfg['base_url']}: {e}")
    if not models:
        raise ConnectionError(
            f"{spec['name']} respondeu, mas não informou nenhum modelo.\n"
            "  ➜ Use 'model <id>' para definir um modelo manualmente."
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
    "fazer. Nunca invente o conteúdo de arquivos que você não leu. "
    "Para tarefas extensas, repetitivas ou que podem rodar em paralelo, "
    "DESPACHE subagentes automaticamente com a ferramenta 'delegate' "
    "(ex.: revisor, pesquisador, analista) em vez de fazer tudo sozinho."
)

PLAN_SYSTEM = (
    " Você está em MODO PLANO: NÃO execute ferramentas, não edite arquivos e "
    "não rode comandos. Produza apenas um plano claro, passo a passo, com "
    "objetivo, arquivos afetados e ordem de execução. No final, pergunte se o "
    "usuário quer que você execute o plano."
)

WORKFLOW_PLAN_SYSTEM = (
    " Você está na ETAPA 1 (PLANEJAR) de um fluxo de trabalho em 4 etapas: "
    "Planejar → Construir → Verificar → Corrigir. NÃO use ferramentas e NÃO "
    "edite nada ainda. Produza um plano numerado em etapas (1., 2., 3. …) com "
    "objetivo, arquivos afetados e ordem de execução. Se a tarefa for muito "
    "grande (mais de 4 etapas), divida-a em FASES com marcos claros."
)

WORKFLOW_BUILD_SYSTEM = (
    " Você está na ETAPA 2 (CONSTRUIR) do fluxo Planejar → Construir → "
    "Verificar → Corrigir. Execute o plano aprovado passo a passo usando as "
    "ferramentas disponíveis (ler/escrever/editar arquivos, executar comandos "
    "etc.). Não pule etapas."
)

WORKFLOW_VERIFY_SYSTEM = (
    " Você está na ETAPA 3 (VERIFICAR) do fluxo Planejar → Construir → "
    "Verificar → Corrigir. Confira se o que foi construído está correto e "
    "funcionando: rode testes/verificações, leia os arquivos criados, confira "
    "se nada está quebrado. Comece sua resposta exatamente com "
    "'VERIFICAÇÃO OK' (se estiver tudo certo) ou 'PROBLEMAS:' (listando cada "
    "problema encontrado)."
)

WORKFLOW_FIX_SYSTEM = (
    " Você está na ETAPA 4 (CORRIGIR) do fluxo Planejar → Construir → "
    "Verificar → Corrigir. Corrija TODOS os problemas apontados na verificação "
    "usando as ferramentas disponíveis. Depois a verificação será repetida."
)


def system_prompt(cfg, extra="", sess=None):
    parts = [BASE_SYSTEM]
    # Nudge grátis: a cada N turnos lembra de consolidar memória (sem API paga)
    if sess is not None:
        try:
            if _memory_nudge_needed(sess):
                parts.append(" [LEMBRETE: considere usar a ferramenta 'remember' se aprendeu algo útil nesta conversa.]")
        except Exception:
            pass
    mode = cfg.get("mode", "coding")
    if mode == "coding":
        parts.append(CODING_SYSTEM)
    elif mode == "plan":
        parts.append(PLAN_SYSTEM)
    elif mode == "workflow":
        parts.append(
            " Você está em MODO WORKFLOW: cada tarefa passa pelas 4 etapas "
            "Planejar → Construir → Verificar → Corrigir."
        )
    elif mode == "workflow_plan":
        parts.append(WORKFLOW_PLAN_SYSTEM)
    elif mode == "workflow_build":
        parts.append(WORKFLOW_BUILD_SYSTEM)
    elif mode == "workflow_verify":
        parts.append(WORKFLOW_VERIFY_SYSTEM)
    elif mode == "workflow_fix":
        parts.append(WORKFLOW_FIX_SYSTEM)
    mem = memory_summary()
    if mem:
        parts.append(
            "\n\n## Memória de longo prazo (aprendizado acumulado)\n" + mem
        )
        parts.append(MEMORY_PROMPT_HINT)
    if cfg.get("project_context", True) and mode in ("coding", "workflow"):
        tree = project_tree()
        if tree:
            parts.append("\n\n## Estrutura do projeto atual\n" + tree)
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
        "skill": "arquivos",
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
        "skill": "arquivos",
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edita um arquivo existente: substitui um trecho de "
                           "texto por outro. Use replace_all para substituir "
                           "todas as ocorrências. Retorna um diff das mudanças.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Caminho do arquivo (relativo ou absoluto).",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "Trecho exato que será substituído.",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "Texto novo no lugar do antigo.",
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "Se true, substitui todas as ocorrências "
                                       "(padrão: só a primeira).",
                    },
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
        "skill": "arquivos",
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
        "skill": "arquivos",
    },
    {
        "type": "function",
        "function": {
            "name": "find_files",
            "description": "Procura arquivos pelo nome (texto parcial ou padrão "
                           "com * e ?) dentro de uma pasta. Ignora node_modules, "
                           ".git, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Nome ou padrão a procurar (ex.: *.py).",
                    },
                    "path": {
                        "type": "string",
                        "description": "Pasta onde procurar (padrão: atual).",
                    },
                    "max_results": {
                        "type": "number",
                        "description": "Limite de resultados (padrão 50).",
                    },
                },
                "required": ["pattern"],
            },
        },
        "skill": "arquivos",
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
        "skill": "terminal",
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Pesquisa na internet (DuckDuckGo) e retorna os "
                           "principais resultados com título, link e resumo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "O que pesquisar.",
                    },
                    "max_results": {
                        "type": "number",
                        "description": "Quantos resultados (padrão 5, máx 10).",
                    },
                },
                "required": ["query"],
            },
        },
        "skill": "internet",
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Baixa uma página da internet e devolve o texto "
                           "principal (sem HTML). Use para ler notícias, docs, "
                           "tutoriais, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL completa (http ou https).",
                    },
                },
                "required": ["url"],
            },
        },
        "skill": "internet",
    },
    {
        "type": "function",
        "function": {
            "name": "system_info",
            "description": "Mostra informações do PC: sistema operacional, "
                           "processador, memória RAM, disco e Python.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
        "skill": "pc",
    },
    {
        "type": "function",
        "function": {
            "name": "open_file",
            "description": "Abre um arquivo ou pasta no programa padrão do "
                           "sistema (explorador de arquivos, editor etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Caminho do arquivo ou pasta.",
                    },
                },
                "required": ["path"],
            },
        },
        "skill": "pc",
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "Abre uma URL no navegador padrão do usuário.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL completa (http ou https).",
                    },
                },
                "required": ["url"],
            },
        },
        "skill": "pc",
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Mostra o estado do repositório git: branch atual e "
                           "arquivos modificados/não rastreados.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Pasta do repositório (padrão: atual).",
                    }
                },
            },
        },
        "skill": "git",
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Mostra o histórico de commits do repositório.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Pasta do repositório (padrão: atual).",
                    },
                    "n": {
                        "type": "number",
                        "description": "Quantos commits (padrão 10).",
                    },
                },
            },
        },
        "skill": "git",
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Mostra as diferenças pendentes do repositório "
                           "(modificações não commitadas).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Pasta do repositório (padrão: atual).",
                    }
                },
            },
        },
        "skill": "git",
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "Faz git add -A e cria um commit com a mensagem "
                           "informada.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Mensagem do commit.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Pasta do repositório (padrão: atual).",
                    },
                },
                "required": ["message"],
            },
        },
        "skill": "git",
    },
    {
        "type": "function",
        "function": {
            "name": "list_processes",
            "description": "Lista os processos do sistema (os mais pesados) com "
                           "PID e uso de CPU/memória. Aceita um filtro opcional.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "string",
                        "description": "Filtro opcional por nome (ex.: python).",
                    },
                    "n": {
                        "type": "number",
                        "description": "Quantos processos (padrão 15).",
                    },
                },
            },
        },
        "skill": "processos",
    },
    {
        "type": "function",
        "function": {
            "name": "kill_process",
            "description": "Encerra um processo pelo PID ou pelo nome.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pid": {
                        "type": "number",
                        "description": "PID do processo a encerrar.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Nome do processo a encerrar (ex.: "
                                       "notepad).",
                    },
                },
            },
        },
        "skill": "processos",
    },
    {
        "type": "function",
        "function": {
            "name": "read_memory",
            "description": "Lê a memória de longo prazo do SEND (aprendizado "
                           "acumulado em ~/.send/memoria.md).",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
        "skill": "memoria",
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Grava algo na memória de longo prazo do SEND. Use "
                           "quando aprender algo útil: preferências do usuário, "
                           "decisões do projeto, bugs corrigidos, comandos "
                           "importantes. O conteúdo fica salvo em "
                           "~/.send/memoria.md e é lembrado nas próximas "
                           "sessões.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "O que você quer lembrar.",
                    }
                },
                "required": ["content"],
            },
        },
        "skill": "memoria",
    },
    {
        "type": "function",
        "function": {
            "name": "create_skill",
            "description": "CRIA UMA NOVA SKILL personalizada para o futuro. "
                           "Salva um arquivo .md em ~/.send/skills/ e ativa a "
                           "skill. Use quando o usuário pedir algo repetitivo "
                           "ou uma habilidade nova (ex.: 'crie uma skill para "
                           "formatar código', 'crie uma skill que gera "
                           "relatórios'). A skill ficará disponível como "
                           "ferramenta nas próximas conversas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Nome curto da skill (letras minúsculas, "
                                       "números e _).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Frase curta: o que a skill faz.",
                    },
                    "instructions": {
                        "type": "string",
                        "description": "Instruções detalhadas que o modelo deve "
                                       "seguir ao executar a skill.",
                    },
                },
                "required": ["name", "description", "instructions"],
            },
        },
        "skill": "memoria",
    },
    {
        "type": "function",
        "function": {
            "name": "delegate",
            "description": "DELEGA uma tarefa a um subagente especializado "
                           "(ex.: revisor, pesquisador, analista). Use quando "
                           "a tarefa for extensa, repetitiva ou puder ser "
                           "feita em paralelo: o subagente trabalha sozinho "
                           "com as próprias ferramentas e devolve o "
                           "resultado final.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome": {
                        "type": "string",
                        "description": "Nome do subagente (ex.: revisor). "
                                       "Liste com /subagentes.",
                    },
                    "tarefa": {
                        "type": "string",
                        "description": "Tarefa completa e objetiva para o "
                                       "subagente executar.",
                    },
                },
                "required": ["nome", "tarefa"],
            },
        },
        "skill": "subagentes",
    },
    {
        "type": "function",
        "function": {
            "name": "create_subagent",
            "description": "CRIA UM NOVO SUBAGENTE especializado para o "
                           "futuro. Salva um arquivo .md em ~/.send/subagents/ "
                           "e o deixa disponível para delegação imediata. Use "
                           "quando o usuário pedir um papel novo (ex.: "
                           "'crie um subagente que revisa meu código', 'crie "
                           "um subagente pesquisador').",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome": {
                        "type": "string",
                        "description": "Nome curto em minúsculas (ex.: revisor).",
                    },
                    "descricao": {
                        "type": "string",
                        "description": "Frase curta: o que o subagente faz.",
                    },
                    "ferramentas": {
                        "type": "string",
                        "description": "Opcional. Ferramentas permitidas "
                                       "separadas por vírgula (ex.: "
                                       "read_file, list_files). Vazio = sem "
                                       "ferramentas; 'todas' = as mesmas do "
                                       "agente principal.",
                    },
                    "instrucoes": {
                        "type": "string",
                        "description": "O papel e as regras do subagente, "
                                       "detalhados.",
                    },
                },
                "required": ["nome", "descricao", "instrucoes"],
            },
        },
        "skill": "subagentes",
    },
    {
        "type": "function",
        "function": {
            "name": "team",
            "description": "EQUIPE de 2+ subagentes (IAs) trabalhando JUNTAS em paralelo para entregar algo melhor. Cada subagente tem papel diferente e o SEND sintetiza o melhor dos dois. Grátis: usa seus modelos locais (pode ser o mesmo modelo com papéis diferentes ou modelos diferentes se você tiver ex.: 'revisor:qwen2.5-coder-7b'). Use para tarefas grandes que se beneficiam de duas visões (código + revisão, pesquisa + análise).",
            "parameters": {
                "type": "object",
                "properties": {
                    "tarefa": {
                        "type": "string",
                        "description": "Tarefa completa e objetiva para a equipe.",
                    },
                    "agentes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Lista de 2+ subagentes. Pode ser só o nome ('revisor') ou 'nome@model' / 'nome:provider/model' para usar modelos diferentes (ex.: ['revisor:qwen2.5-coder-7b','pesquisador']).",
                    },
                    "estrategia": {
                        "type": "string",
                        "enum": ["paralelo", "debate", "sequencial"],
                        "description": "Como colaboram: paralelo (todos juntos e sintetiza), debate (um propõe, outro critica), sequencial (um após o outro). Padrão: paralelo.",
                    },
                },
                "required": ["tarefa", "agentes"],
            },
        },
        "skill": "subagentes",
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
    backup_file(p)  # cópia de segurança antes de sobrescrever
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


def _dispatch_tool(name, args, c, auto_confirm, cfg=None):
    if name == "read_file":
        return tool_read(args, c)
    if name == "write_file":
        if not auto_confirm:
            if not ask_yes_no(c, f"Escrever arquivo '{args.get('path', '?')}'?"):
                return None
        return tool_write(args, c)
    if name == "edit_file":
        if not auto_confirm:
            if not ask_yes_no(c, f"Editar arquivo '{args.get('path', '?')}'?"):
                return None
        return tool_edit(args, c)
    if name == "list_files":
        return tool_list(args, c)
    if name == "find_files":
        return tool_find(args, c)
    if name == "run_command":
        if not auto_confirm:
            preview = args.get("command", "")[:80]
            if not ask_yes_no(c, f"Executar comando: {preview}…"):
                return None
        return tool_run(args, c)
    if name == "web_search":
        return tool_web_search(args, c)
    if name == "fetch_url":
        return tool_fetch_url(args, c)
    if name == "system_info":
        return tool_system_info(args, c)
    if name == "open_file":
        return tool_open_file(args, c)
    if name == "open_url":
        return tool_open_url(args, c)
    if name == "git_status":
        return tool_git_status(args, c)
    if name == "git_log":
        return tool_git_log(args, c)
    if name == "git_diff":
        return tool_git_diff(args, c)
    if name == "git_commit":
        if not auto_confirm:
            if not ask_yes_no(c, f"Criar commit: '{args.get('message', '')[:60]}'?"):
                return None
        return tool_git_commit(args, c)
    if name == "list_processes":
        return tool_list_processes(args, c)
    if name == "kill_process":
        if not auto_confirm:
            alvo = args.get("pid") or args.get("name") or "?"
            if not ask_yes_no(c, f"Encerrar processo '{alvo}'?"):
                return None
        return tool_kill_process(args, c)
    if name == "read_memory":
        return tool_read_memory(args, c)
    if name == "remember":
        return tool_remember(args, c)
    if name == "create_skill":
        return tool_create_skill(args, c, cfg)
    if name == "delegate":
        return tool_delegate(args, c, cfg)
    if name == "create_subagent":
        return tool_create_subagent(args, c, cfg)
    if name == "team":
        return tool_team(args, c, cfg)
    if name.startswith("mcp_"):
        return tool_mcp_call(name, args, c, cfg)
    if name.startswith("skill_"):
        return tool_custom_skill(name, args, c, cfg)
    return f"Ferramenta desconhecida: {name}"


def execute_tool(name, args, c, auto_confirm, cfg=None):
    """Executa uma ferramenta, disparando os hooks PreToolUse/PostToolUse."""
    run_hooks("PreToolUse", c, cfg, tool=name,
              args=json.dumps(args, ensure_ascii=False)[:2000])
    try:
        result = _dispatch_tool(name, args, c, auto_confirm, cfg)
    except Exception as e:
        result = f"Erro ao executar {name}: {e}"
    run_hooks("PostToolUse", c, cfg, tool=name,
              result=str(result)[:2000])
    return result


# ---------------------------------------------------------------------------
# Implementação das skills
# ---------------------------------------------------------------------------

def _resolve_path(path, default="."):
    p = Path(path or default).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


def tool_edit(args, c):
    p = _resolve_path(args.get("path", ""))
    if not p.exists():
        return f"Erro: arquivo não encontrado: {p}"
    if not p.is_file():
        return f"Erro: '{p}' não é um arquivo."
    old = args.get("old_text", "")
    new = args.get("new_text", "")
    if not old:
        return "Erro: old_text vazio."
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "Erro: arquivo binário, não posso editar."
    if old not in text:
        return (f"Erro: o trecho não foi encontrado no arquivo.\n"
                f"Sugestões próximas: {', '.join(difflib.get_close_matches(old, text.splitlines(), n=3)[:3]) or 'nenhuma'}")
    if args.get("replace_all"):
        n = text.count(old)
        text = text.replace(old, new)
    else:
        n = 1
        text = text.replace(old, new, 1)
    backup_file(p)  # cópia de segurança antes de alterar
    p.write_text(text, encoding="utf-8")
    return f"✅ {n} substituição(ões) feita(s) em {p}"


def tool_find(args, c):
    pattern = args.get("pattern", "")
    base = _resolve_path(args.get("path", "."))
    try:
        max_results = int(args.get("max_results") or 50)
    except (TypeError, ValueError):
        max_results = 50
    max_results = max(1, min(max_results, 200))
    if not base.exists():
        return f"Erro: pasta não encontrada: {base}"
    if not base.is_dir():
        return f"Erro: '{base}' não é uma pasta."
    matches = []
    try:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for f in files:
                if fnmatch.fnmatch(f.lower(), pattern.lower()):
                    matches.append(str(Path(root) / f))
                    if len(matches) >= max_results:
                        break
            if len(matches) >= max_results:
                break
    except PermissionError:
        return "Erro: sem permissão para ler alguma pasta."
    if not matches:
        return f"Nenhum arquivo encontrado com o padrão '{pattern}' em {base}"
    return f"{len(matches)} arquivo(s) encontrado(s):\n" + "\n".join(matches)


class _TextExtractor(html.parser.HTMLParser):
    """Extrai o texto de uma página HTML, pulando script/style."""

    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6",
             "tr", "section", "article", "header", "footer", "blockquote",
             "pre", "ul", "ol"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg", "head"):
            self.skip += 1
        if tag in self.BLOCK and self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg", "head") and self.skip:
            self.skip -= 1
        if tag in self.BLOCK and self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            s = re.sub(r"\s+", " ", data).strip()
            if s:
                self.parts.append(s + " ")

    def text(self):
        raw = "".join(self.parts)
        return re.sub(r"\n\s*\n+", "\n\n", raw).strip()

    def feed_and_text(self, data):
        self.feed(data)
        return self.text()


def _http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)


def _safe_url(url):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def tool_web_search(args, c):
    query = args.get("query", "").strip()
    if not query:
        return "Erro: query vazia."
    try:
        max_results = int(args.get("max_results") or 5)
    except (TypeError, ValueError):
        max_results = 5
    max_results = max(1, min(max_results, 10))
    url = SEARCH_URL.format(q=urllib.parse.quote_plus(query))
    try:
        with _http_get(url) as resp:
            html_text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        return f"Erro ao pesquisar: {e.reason}. Sem internet?"
    except Exception as e:
        return f"Erro ao pesquisar: {e}"

    results = []
    # DuckDuckGo HTML: cada resultado é um <a class="result__a" href="...">
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                         html_text, re.S):
        link = m.group(1)
        if link.startswith("//"):
            link = "https:" + link
        # o DDG usa redirecionamentos /l/?uddg=<url>; extrai o link real
        uddg = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("uddg")
        if uddg:
            link = uddg[0]
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        title = html.unescape(title) if hasattr(html, "unescape") else title
        results.append((title, link))
        if len(results) >= max_results:
            break
    if not results:
        # fallback: qualquer link externo com texto
        for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                             html_text, re.S):
            link = m.group(1)
            if "duckduckgo.com" in link or "duck.co" in link:
                continue
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if title:
                results.append((title, link))
            if len(results) >= max_results:
                break
    if not results:
        return "Nenhum resultado encontrado (ou o site de busca mudou o layout)."
    out = [f"Resultados para: {query}", ""]
    for i, (title, link) in enumerate(results, 1):
        out.append(f"{i}. {title}\n   {link}")
    return "\n".join(out)


def tool_fetch_url(args, c):
    url = _safe_url(args.get("url", "").strip())
    if not url:
        return "Erro: url vazia."
    try:
        with _http_get(url) as resp:
            ctype = resp.headers.get("Content-Type", "")
            data = resp.read(512 * 1024)  # máximo 512 KB
    except urllib.error.URLError as e:
        return f"Erro ao abrir {url}: {e.reason}. Sem internet?"
    except Exception as e:
        return f"Erro ao abrir {url}: {e}"
    if "text" not in ctype and "html" not in ctype:
        return f"({url} — conteúdo do tipo {ctype or 'desconhecido'}, {len(data)} bytes; não é texto)"
    text = _TextExtractor().feed_and_text(data.decode("utf-8", errors="replace"))
    if len(text) > TOOL_OUTPUT_LIMIT:
        text = text[:TOOL_OUTPUT_LIMIT] + "\n… (texto truncado)"
    return f"Conteúdo de {url}:\n\n{text or '(página sem texto legível)'}"


def tool_system_info(args, c):
    lines = [
        f"Sistema     : {platform.system()} {platform.release()}",
        f"Arquitetura : {platform.machine()}",
        f"Processador : {platform.processor() or 'desconhecido'}",
        f"Usuário     : {os.environ.get('USER') or os.environ.get('USERNAME') or '?'}",
        f"Diretório   : {Path.cwd()}",
        f"Python      : {sys.version.split()[0]}",
    ]
    try:
        if os.name == "nt":
            total = shutil.disk_usage(Path.cwd().anchor).total
            lines.append(f"Disco total : {total // (1024**3)} GB")
        else:
            with open("/proc/meminfo") as f:
                for ln in f:
                    if ln.startswith("MemTotal"):
                        kb = int(ln.split()[1])
                        lines.append(f"Memória RAM : {kb // 1024 // 1024} GB")
                        break
            st = os.statvfs(Path.cwd().anchor or "/")
            lines.append(f"Disco total : {st.f_bsize * st.f_blocks // (1024**3)} GB")
    except Exception:
        pass
    return "\n".join(lines)


def tool_open_file(args, c):
    p = _resolve_path(args.get("path", ""))
    if not p.exists():
        return f"Erro: arquivo/pasta não encontrado: {p}"
    try:
        if os.name == "nt":
            os.startfile(str(p))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return f"✅ Aberto: {p}"
    except Exception as e:
        return f"Erro ao abrir: {e}"


def tool_open_url(args, c):
    url = _safe_url(args.get("url", "").strip())
    if not url:
        return "Erro: url vazia."
    try:
        webbrowser.open(url)
        return f"✅ Navegador aberto: {url}"
    except Exception as e:
        return f"Erro ao abrir o navegador: {e}"


# --- Skill: git -------------------------------------------------------------

def _git_cmd(args, *cmd, timeout=60):
    p = _resolve_path(args.get("path", "."))
    proc = subprocess.run(
        ["git", *cmd], cwd=str(p), capture_output=True,
        text=True, timeout=timeout,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return f"(git {cmd[0] if cmd else ''} falhou: {err or 'erro desconhecido'})"
    return out


def tool_git_status(args, c):
    branch = _git_cmd(args, "branch", "--show-current")
    status = _git_cmd(args, "status", "--short")
    if status.startswith("(git branch falhou") or not status:
        full = _git_cmd(args, "status")
        return f"Branch: {branch}\n\n{full}" if full else "Não é um repositório git."
    return f"Branch: {branch}\n\n{status or '(working tree limpo)'}"


def tool_git_log(args, c):
    try:
        n = int(args.get("n") or 10)
    except (TypeError, ValueError):
        n = 10
    n = max(1, min(n, 100))
    out = _git_cmd(args, "log", "--oneline", f"-n{n}")
    return out or "(sem commits ainda)"


def tool_git_diff(args, c):
    stat = _git_cmd(args, "diff", "--stat")
    diff = _git_cmd(args, "diff")
    if not diff:
        return "(nenhuma modificação pendente)"
    body = diff[:TOOL_OUTPUT_LIMIT]
    if len(diff) > TOOL_OUTPUT_LIMIT:
        body += "\n… (diff truncado)"
    return f"{stat}\n\n{body}"


def tool_git_commit(args, c):
    msg = args.get("message", "").strip()
    if not msg:
        return "Erro: mensagem do commit vazia."
    add = _git_cmd(args, "add", "-A")
    if add.startswith("(git"):
        return add
    out = _git_cmd(args, "commit", "-m", msg)
    return out or "Commit criado."


# --- Skill: processos -------------------------------------------------------

def tool_list_processes(args, c):
    filtro = args.get("filter", "").strip().lower()
    try:
        n = int(args.get("n") or 15)
    except (TypeError, ValueError):
        n = 15
    n = max(1, min(n, 50))
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FO", "TABLE"],
                             capture_output=True, text=True).stdout
        lines = out.splitlines()
    else:
        out = subprocess.run(
            ["ps", "-eo", "pid,comm,%cpu,%mem", "--sort=-%cpu"],
            capture_output=True, text=True,
        ).stdout
        lines = out.splitlines()
    header = lines[:1]
    rows = []
    for ln in lines[1:]:
        if not ln.strip():
            continue
        if filtro and filtro not in ln.lower():
            continue
        rows.append(ln)
        if len(rows) >= n:
            break
    if not rows:
        return f"Nenhum processo encontrado{f' com filtro {filtro!r}' if filtro else ''}."
    return "\n".join(header + rows)


def tool_kill_process(args, c):
    pid = args.get("pid")
    name = args.get("name", "").strip()
    if not pid and not name:
        return "Erro: informe pid ou name."
    try:
        if os.name == "nt":
            if pid:
                r = subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                   capture_output=True, text=True)
            else:
                r = subprocess.run(["taskkill", "/F", "/IM", name],
                                   capture_output=True, text=True)
        else:
            if pid:
                r = subprocess.run(["kill", "-9", str(pid)],
                                   capture_output=True, text=True)
            else:
                r = subprocess.run(["pkill", "-9", "-f", name],
                                   capture_output=True, text=True)
        out = (r.stdout or "").strip() or (r.stderr or "").strip()
        if r.returncode != 0:
            return f"Falha ao encerrar: {out or 'erro'}"
        return f"✅ Processo encerrado: {pid or name}"
    except Exception as e:
        return f"Erro ao encerrar processo: {e}"


# --- Skill: memoria ---------------------------------------------------------

def tool_read_memory(args, c):
    text = memory_summary(limit=8000)
    if not text:
        return ("A memória de longo prazo está vazia. Use a ferramenta "
                "'remember' para registrar o que aprender.")
    return f"Memória de longo prazo ({MEMORY_PATH}):\n\n{text}"


def tool_remember(args, c):
    content = args.get("content", "").strip()
    if not content:
        return "Erro: conteúdo vazio."
    if remember_entry(content):
        return f"✅ Lembrei: {content}"
    return f"Erro: não foi possível gravar em {MEMORY_PATH}"


def tool_create_skill(args, c, cfg=None):
    name = re.sub(r"[^a-z0-9_]+", "_",
                  args.get("name", "").strip().lower()).strip("_")
    if not name:
        return "Erro: nome inválido (use letras minúsculas, números e _)."
    if name in SKILLS:
        return f"Erro: '{name}' já é uma skill nativa do SEND."
    desc = args.get("description", "").strip() or "(sem descrição)"
    instr = args.get("instructions", "").strip()
    if not instr:
        return "Erro: instruções vazias. Explique o que a skill deve fazer."
    try:
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        path = SKILLS_DIR / f"{name}.md"
        if path.exists():
            return (f"Erro: já existe uma skill '{name}' em {path}. "
                    f"Use outro nome ou edite o arquivo.")
        path.write_text(
            f"# Skill: {name}\n\nDescrição: {desc}\n\n## Instruções\n\n{instr}\n",
            encoding="utf-8",
        )
    except Exception as e:
        return f"Erro ao criar a skill: {e}"
    # ativa automaticamente
    if cfg is not None:
        skills = list(cfg.get("skills", []))
        if name not in skills:
            skills.append(name)
            cfg["skills"] = skills
            save_config(cfg)
    return (f"✅ Skill '{name}' criada em {path} e ativada!\n"
            f"Descrição: {desc}\n"
            f"Da próxima vez, ela estará disponível como ferramenta "
            f"'skill_{name}' nas conversas.")


def tool_custom_skill(name, args, c, cfg=None):
    """Executa uma skill personalizada: roda um sub-agente com as instruções
    da skill como sistema, sem ferramentas."""
    cs = next((s for s in load_custom_skills()
               if "skill_" + s["name"] == name), None)
    if not cs:
        return f"Skill '{name}' não encontrada. Use create_skill para criá-la."
    tarefa = args.get("tarefa", "")
    if not tarefa:
        return "Erro: tarefa vazia."
    print(c.dim(f"    ⚡ executando skill '{cs['name']}'…"))
    sub_cfg = dict(cfg or DEFAULT_CONFIG)
    sub = Session(sub_cfg, c)
    sub.extra_system = (
        f"Você está executando a skill personalizada '{cs['name']}' "
        f"({cs['description']}). Siga rigorosamente as instruções abaixo.\n\n"
        f"{cs['instructions']}"
    )
    sub.messages = [{"role": "user",
                     "content": "Tarefa para a skill: " + tarefa}]
    try:
        content = ask_model(sub, False, c, False)
    except Exception as e:
        return f"Erro ao executar a skill: {e}"
    return f"[skill:{cs['name']}]\n{content or '(sem resposta)'}"


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
        self.summary = None   # resumo de conversas anteriores (auto-summarize)
        self.mode_override = None   # modo fixo escolhido pelo usuário
        self.outmode_prev = None    # estado anterior (para /outmode off)


# Limite de mensagens antes de resumir a conversa automaticamente
SUMMARY_THRESHOLD = 16
SUMMARY_KEEP = 6


def _estimate_tokens(msgs):
    """Estimativa grátis local: tokens ≈ chars/4 (sem API paga)."""
    total = 0
    for m in msgs:
        c = m.get("content") or ""
        if isinstance(c, str):
            total += len(c) // 4
        # tool_calls também contam
        if m.get("tool_calls"):
            total += len(str(m["tool_calls"])) // 4
    return total

def _proactive_prune(msgs, protect_last_n=6):
    """Poda determinística grátis: resume tool results >8000 chars sem chamar modelo."""
    if len(msgs) <= protect_last_n:
        return msgs, 0
    pruned = 0
    out = []
    for i, m in enumerate(msgs):
        if i >= len(msgs) - protect_last_n:
            out.append(m)
            continue
        if m.get("role") == "tool" and isinstance(m.get("content"), str) and len(m["content"]) > 8000:
            # trunca mantendo início e fim
            c = m["content"]
            pruned += len(c) - 2000
            m = dict(m)
            m["content"] = c[:1000] + "\n… (tool result podado grátis, " + str(len(c)) + " chars -> 2000) …\n" + c[-1000:]
        out.append(m)
    return out, pruned

def summarize_conversation(sess, c):
    """Resume as mensagens antigas da conversa para economizar contexto.

    Mantém as últimas SUMMARY_KEEP mensagens e guarda o resumo em
    sess.summary, que é injetado no prompt de sistema. Retorna True se
    resumiu, False caso contrário.

    Grátis: usa estimativa local de tokens (chars/4) e respeita
    compression_threshold_tokens do config. Se só mensagens, usa fallback 16.
    """
    msgs = sess.messages
    # poda proativa grátis antes de decidir resumir (sem custo)
    if sess.cfg.get("compression_proactive_prune", True):
        msgs, pruned = _proactive_prune(msgs, SUMMARY_KEEP)
        if pruned:
            sess.messages = msgs
            print(c.dim(f"✂ poda proativa: {pruned} chars de tool results antigos removidos (grátis)."))
    # decide por tokens OU por contagem (compatível com modo grátis)
    est_tokens = _estimate_tokens(msgs)
    thresh = sess.cfg.get("compression_threshold_tokens", 20000)
    by_count = len(msgs) > SUMMARY_THRESHOLD
    by_tokens = est_tokens > thresh
    if not (by_count or by_tokens):
        return False
    if sess.summary is not None and len(msgs) <= SUMMARY_THRESHOLD + SUMMARY_KEEP:
        # se já tem resumo, só resume de novo se cresceu bastante
        if est_tokens < thresh * 0.8:
            return False
    old = msgs[: -SUMMARY_KEEP]
    recent = msgs[-SUMMARY_KEEP:]

    # monta o texto a resumir (limita tamanho)
    lines = []
    for m in old:
        role = {"user": "Usuário", "assistant": "SEND",
                "tool": "Ferramenta", "system": "Sistema"}.get(m.get("role"), "?")
        content = m.get("content") or ""
        if isinstance(content, str) and content.strip():
            lines.append(f"{role}: {content[:300]}")
    text = "\n".join(lines)
    if len(text) > 6000:
        text = text[:6000] + "\n…"

    sub_cfg = dict(sess.cfg)
    sub_cfg["mode"] = "chat"
    sub = Session(sub_cfg, c)
    sub.messages = [{
        "role": "user",
        "content": ("Resuma em português as mensagens abaixo desta conversa "
                    "entre usuário e assistente de IA (mantenha decisões, "
                    "preferências, arquivos citados e pendências):\n\n" + text),
    }]
    try:
        summary = ask_model(sub, False, c, True) or ""
    except Exception:
        return False
    summary = summary.strip()
    if not summary:
        return False

    sess.summary = summary
    sess.messages = recent
    n = len(old)
    print(c.dim(f"🧠 Conversa resumida automaticamente "
                f"({n} mensagens → resumo). Use /resumo para ver."))
    return True


def _anthropic_payload(payload):
    """Converte mensagens e tools OpenAI para a API Messages da Anthropic."""
    converted = {
        "model": payload["model"], "stream": True, "max_tokens": 8192,
        "temperature": payload.get("temperature", 0.7), "messages": [],
    }
    for msg in payload["messages"]:
        role = msg.get("role")
        if role == "system":
            converted["system"] = msg.get("content") or ""
            continue
        if role == "assistant" and msg.get("tool_calls"):
            blocks = []
            if msg.get("content"):
                blocks.append({"type": "text", "text": msg["content"]})
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {"_raw": fn.get("arguments", "")}
                blocks.append({"type": "tool_use", "id": tc.get("id"),
                               "name": fn.get("name"), "input": args})
            converted["messages"].append({"role": "assistant", "content": blocks})
        elif role == "tool":
            # A API Messages exige todos os tool_result consecutivos numa
            # única mensagem user — um bloco por chamada.
            block = {"type": "tool_result",
                     "tool_use_id": msg.get("tool_call_id"),
                     "content": str(msg.get("content") or "")}
            prev = converted["messages"][-1] if converted["messages"] else None
            if (prev and prev.get("role") == "user"
                    and isinstance(prev.get("content"), list)
                    and prev["content"]
                    and isinstance(prev["content"][0], dict)
                    and prev["content"][0].get("type") == "tool_result"):
                prev["content"].append(block)
            else:
                converted["messages"].append({"role": "user", "content": [block]})
        elif role in ("user", "assistant"):
            converted["messages"].append(
                {"role": role, "content": msg.get("content") or ""}
            )
    if payload.get("tools"):
        converted["tools"] = [{
            "name": tool["function"]["name"],
            "description": tool["function"].get("description", ""),
            "input_schema": tool["function"].get("parameters", {"type": "object"}),
        } for tool in payload["tools"]]
        converted["tool_choice"] = {"type": "auto"}
    return converted


def call_model(sess, tools_enabled, c, cfg):
    """Chama a API com streaming. Retorna (conteúdo, tool_calls, reasoning)."""
    if sess.model_id is None:
        sess.model_id = resolve_model(cfg, c)
    extra = getattr(sess, "extra_system", "")
    summary = getattr(sess, "summary", None)
    if summary:
        extra = (f"Resumo de mensagens anteriores desta conversa (não "
                 f"responda ao resumo, apenas use como contexto):\n{summary}"
                 + (("\n\n" + extra) if extra else ""))
    system_override = getattr(sess, "system_override", None)
    if system_override:
        system_text = system_override
    else:
        system_text = system_prompt(cfg, extra, sess)
    messages = [{"role": "system", "content": system_text}] + sess.messages
    payload = {
        "model": sess.model_id,
        "messages": messages,
        "stream": True,
        "temperature": cfg["temperature"],
    }
    if tools_enabled:
        custom = getattr(sess, "custom_tools", None)
        payload["tools"] = get_tools(cfg) if custom is None else custom
        payload["tool_choice"] = "auto"
    if cfg["thinking"]:
        payload["reasoning_effort"] = cfg["reasoning_effort"]

    spec = provider_spec(cfg)
    api_format = spec.get("api_format", "openai")
    request_payload = _anthropic_payload(payload) if api_format == "anthropic" else payload
    endpoint = "messages" if api_format == "anthropic" else "chat/completions"
    try:
        stream = stream_sse(provider_api_url(cfg, endpoint), request_payload,
                            provider_api_key(cfg))
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
            request_payload = (_anthropic_payload(payload)
                               if api_format == "anthropic" else payload)
            stream = stream_sse(provider_api_url(cfg, endpoint),
                                request_payload, provider_api_key(cfg))
            return _consume_stream(stream, c, cfg)
        raise


def _consume_stream(stream, c, cfg):
    """Lê um stream SSE e devolve (conteúdo, tool_calls, reasoning)."""
    content_parts = []
    reasoning_parts = []
    tool_calls = {}
    order = []
    printer = MarkdownPrinter(c)
    think_on = False  # indicador "🧠 raciocinando…" visível
    try:
        for raw in stream:
            if raw == "[DONE]":
                break
            try:
                evt = json.loads(raw)
            except Exception:
                continue
            # API Messages nativa (Claude e custom providers Anthropic).
            event_type = evt.get("type", "")
            if event_type == "content_block_start":
                block = evt.get("content_block", {})
                if block.get("type") == "tool_use":
                    idx = evt.get("index", len(order))
                    tool_calls[idx] = {
                        "id": block.get("id", ""),
                        "function": {"name": block.get("name", ""),
                                     "arguments": (json.dumps(block.get("input"))
                                                   if block.get("input") else "")},
                    }
                    order.append(idx)
                continue
            if event_type == "content_block_delta":
                delta = evt.get("delta", {})
                if delta.get("type") == "text_delta":
                    piece = delta.get("text", "")
                    content_parts.append(piece)
                    printer.write(piece)
                    sys.stdout.flush()
                elif delta.get("type") in ("thinking_delta", "signature_delta"):
                    piece = delta.get("thinking", "")
                    if piece and cfg["show_reasoning"]:
                        reasoning_parts.append(piece)
                elif delta.get("type") == "input_json_delta":
                    idx = evt.get("index", 0)
                    if idx in tool_calls:
                        tool_calls[idx]["function"]["arguments"] += delta.get(
                            "partial_json", ""
                        )
                continue
            for ch in evt.get("choices", []):
                delta = ch.get("delta", {}) or {}
                if delta.get("content"):
                    if think_on:
                        sys.stdout.write("\r" + " " * 24 + "\r")
                        sys.stdout.flush()
                        think_on = False
                    piece = delta["content"]
                    content_parts.append(piece)
                    printer.write(piece)
                    sys.stdout.flush()
                if delta.get("reasoning_content") and cfg["show_reasoning"]:
                    piece = delta["reasoning_content"]
                    reasoning_parts.append(piece)
                    if c.enabled and not think_on and not content_parts:
                        sys.stdout.write("\r" + c.dim("🧠 raciocinando… "))
                        sys.stdout.flush()
                        think_on = True
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
        if think_on:
            sys.stdout.write("\r" + " " * 24 + "\r")
            sys.stdout.flush()
        printer.finish()
        return "".join(content_parts), [], "".join(reasoning_parts)

    if think_on:
        sys.stdout.write("\r" + " " * 24 + "\r")
        sys.stdout.flush()
    printer.finish()
    return ("".join(content_parts), [tool_calls[i] for i in order],
            "".join(reasoning_parts))


def _guard_is_failure(result):
    """Heurística local (grátis): detecta falha sem chamar API."""
    if not result:
        return False
    low = result.lower()
    return any(k in low for k in ("erro", "falhou", "falha", "não encontrada", "not found", "exception", "traceback"))

def _guard_check(sess, name, args, result, history, c):
    """Verifica loops; retorna (warn_msg ou None, should_hard_stop bool)."""
    cfg = sess.cfg
    if not cfg.get("guardrails_warnings") and not cfg.get("guardrails_hard_stop"):
        return None, False
    # exact_failure: mesma ferramenta + mesmos args + falha repetida
    exact_count = 0
    same_tool_fail = 0
    idempotent = 0
    # conta de trás pra frente
    for h in reversed(history):
        if h["name"] != name:
            # para same_tool_failure, só conta consecutivos
            if same_tool_fail > 0:
                break
            continue
        # same tool
        if _guard_is_failure(h["result"]) and _guard_is_failure(result):
            same_tool_fail += 1
        elif h["name"] == name and h["result"] == result and not _guard_is_failure(result):
            idempotent += 1
        # exact
        if h["name"] == name and h["args"] == args and _guard_is_failure(h["result"]) and _guard_is_failure(result):
            exact_count += 1
    # thresholds grátis (Hermes usa 2/3/2 para warn)
    warn = None
    hard = False
    if exact_count >= 1:  # já teve 1 antes, agora é 2ª vez igual
        warn = f"⚠ Guardrail: '{name}' falhou 2x com os mesmos argumentos. Tente variar os args ou verifique o caminho."
        if cfg.get("guardrails_hard_stop") and exact_count >= 4:
            hard = True
    elif same_tool_fail >= 2:  # 3ª falha mesma ferramenta (2 anteriores + atual)
        warn = f"⚠ Guardrail: '{name}' falhou {same_tool_fail+1}x seguidas. Considere mudar de estratégia."
        if cfg.get("guardrails_hard_stop") and same_tool_fail >= 7:
            hard = True
    elif idempotent >= 1:
        warn = f"⚠ Guardrail: '{name}' retornou resultado idêntico {idempotent+1}x sem progresso. Evite repetir."
        if cfg.get("guardrails_hard_stop") and idempotent >= 4:
            hard = True
    return warn, hard

def run_agent(sess, tools_enabled, c, auto_confirm):
    """Laço de conversa com ferramentas. Retorna a resposta final."""
    cfg = sess.cfg
    content = ""
    _guard_history = []  # lista de {name, args, result}
    for _ in range(MAX_TOOL_ROUNDS):
        content, calls, reasoning = call_model(sess, tools_enabled, c, cfg)
        if reasoning and getattr(sess, "last_reasoning", "") != reasoning:
            sess.last_reasoning = reasoning
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
            print(c.cyan("  ╭─ ") + tool_icon(name) + " " +
                  c.bold(name) + c.dim(" " + compact_args(args)))
            result = execute_tool(name, args, c, auto_confirm, sess.cfg)
            if result is None:
                result = (
                    "O usuário recusou executar esta ferramenta. "
                    "Explique e prossiga sem executá-la."
                )
            # Guardrails grátis (sem API) — avisa/interrompe loops
            warn, hard = _guard_check(sess, name, args, result, _guard_history, c)
            if warn and cfg.get("guardrails_warnings", True):
                print(c.yellow(f"  {warn}"))
                # injeta aviso no resultado para o modelo perceber (soft warning)
                result = result + "\n\n[AVISO GUARDRAIL: " + warn + " Tente outra abordagem.]"
            if hard and cfg.get("guardrails_hard_stop"):
                print(c.red("  ⛔ Guardrail hard-stop: interrompendo loop."))
                sess.messages.append(
                    {"role": "tool", "tool_call_id": tc["id"] or f"call_{len(sess.messages)}",
                     "content": result + "\n[GUARDRAIL HARD-STOP]"}
                )
                _guard_history.append({"name": name, "args": args, "result": result})
                break
            _guard_history.append({"name": name, "args": args, "result": result})
            prev = result.split("\n")[0][:110]
            print(c.dim("  ╰─ " + (prev or "(sem saída)")))
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
# Modo automático — o SEND escolhe o modo ideal para cada tarefa
# ---------------------------------------------------------------------------

MODE_LABELS = {
    "chat": "💬 CHAT (só conversa)",
    "coding": "🛠 CODING (arquivos + terminal)",
    "plan": "📋 PLAN (planejar sem executar)",
    "workflow": "🔁 WORKFLOW (4 etapas)",
}

# Indícios de tarefa grande → workflow
_WF_HINTS = (
    "app", "aplicativo", "projeto", "site", "sistema", "api", "jogo",
    "dashboard", "backend", "frontend", "módulo", "modulo", "pipeline",
    "do zero", "completo", "completa", "integrado", "automatize",
    "automatizar", "automação", "automatizacao",
)
# Ação forte = o usuário mandou construir/fazer algo
_STRONG_ACTION = (
    "crie", "cria", "criar", "criado", "construa", "construir", "desenvolva",
    "desenvolver", "implemente", "implementar", "faça", "faca", "fazer",
    "monte", "montei", "refatore", "refatorar", "automatize", "monte um",
)
# Pedido explícito de plano → plan
_PLAN_HINTS = (
    "planej", "plano", "planeje", "estratégia", "estrategia", "roadmap",
    "passo a passo", "roteiro", "arquitetura", "como devo", "qual a melhor",
    "que passos", "me dê um plano", "me de um plano", "divida a tarefa",
)
# Início de pergunta simples → chat
_CHAT_STARTS = (
    "o que", "oq", "qual", "quem", "quando", "onde", "por que", "porque",
    "pq", "explique", "me explica", "como funciona", "o que é", "oq e",
    "oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "tudo bem",
    "obrigado", "obrigada", "valeu", "tchau", "ajuda",
)
_CODING_HINTS = (
    "script", "codigo", "código", "arquivo", "função", "funcao", "classe",
    "bug", "erro", "teste", "rode", "execute", "procure", "liste",
    "edite", "escreva", "corrija", "renomeie", "ordene", "compile",
)


def detect_mode(prompt):
    """Escolhe o modo ideal para um prompt (chat/coding/plan/workflow)."""
    p = (prompt or "").strip().lower()
    if not p:
        return "chat"
    # Pergunta/conversa simples → chat
    if len(p) < 160 and p.startswith(_CHAT_STARTS):
        return "chat"
    # Pedido explícito de plano → plan
    if any(h in p for h in _PLAN_HINTS):
        return "plan"
    strong = any(a in p for a in _STRONG_ACTION)
    wf = any(w in p for w in _WF_HINTS)
    # Tarefa grande (ação forte + escopo) ou pedido grande → workflow
    if wf and (strong or len(p) >= 90):
        return "workflow"
    # Tarefa de código → coding
    if strong or any(h in p for h in _CODING_HINTS):
        return "coding"
    # Frase curta genérica → chat; mais longa → coding (tem ferramentas)
    return "chat" if len(p) < 60 else "coding"


def effective_mode(sess, prompt):
    """Modo efetivo para a tarefa. Retorna (modo, foi_auto?).

    - auto_mode ligado e sem modo fixo escolhido → detecta por tarefa
    - modo fixo escolhido (/code, --plan, /workflow…) → respeita
    - auto_mode desligado → usa o modo da config
    """
    cfg = sess.cfg
    if not cfg.get("auto_mode", True):
        return cfg.get("mode", "coding"), False
    ov = getattr(sess, "mode_override", None)
    if ov:
        return ov, False
    return detect_mode(prompt), True


# ---------------------------------------------------------------------------
# Workflow: Planejar → Construir → Verificar → Corrigir
# ---------------------------------------------------------------------------

WORKFLOW_MAX_FIX_CYCLES = 3


def _count_plan_steps(plan):
    return len(re.findall(r"(?m)^\s*(?:etapa|passo|step|fase)?\s*\d+[\.\):]",
                          plan or ""))


def run_workflow(sess, task, c, cfg):
    """Executa uma tarefa no fluxo de 4 etapas:
    1. PLANEJAR  — plano em etapas (divide tarefas grandes em fases)
    2. CONSTRUIR — executa o plano com as ferramentas
    3. VERIFICAR — confere se está tudo funcionando
    4. CORRIGIR  — corrige o que não estiver certo (e reverifica, até 3x)
    """
    auto = getattr(sess, "auto_confirm", cfg["auto_confirm"])
    mode_bak = cfg["mode"]
    task = task.strip()
    if not task:
        return ""

    # ---- 1. PLANEJAR ----
    print()
    panel("📋 ETAPA 1/4 — PLANEJAR", "Separando a tarefa em etapas…", c)
    with Spinner(c, "planejando…"):
        plan_sess = Session(cfg, c)
        cfg["mode"] = "workflow_plan"
        try:
            plan = ask_model(plan_sess, False, c, auto) or ""
        finally:
            cfg["mode"] = mode_bak
    plan = plan.strip()
    if not plan:
        plan = "(o modelo não gerou um plano)"
    n_steps = _count_plan_steps(plan)
    print()
    panel("📋 Plano", plan, c, color="cyan", width=72)
    if n_steps >= 5:
        print(c.yellow(f"  ⚠ Tarefa grande identificada — dividida em {n_steps} "
                       "etapas organizadas por fase."))
    if not auto and sys.stdin.isatty():
        if not ask_yes_no(c, "Aprovar este plano e começar a construir?"):
            print(c.yellow("  Plano recusado pelo usuário. Nada foi construído."))
            sess.messages.append({"role": "user", "content": task})
            sess.messages.append({"role": "assistant",
                                  "content": "Plano recusado pelo usuário."})
            return plan

    # ---- 2. CONSTRUIR ----
    print()
    panel("🔨 ETAPA 2/4 — CONSTRUIR", "Executando o plano passo a passo…", c)
    build_sess = Session(cfg, c)
    build_sess.messages = [
        {"role": "user", "content": task},
        {"role": "assistant", "content": plan},
        {"role": "user", "content": "Agora EXECUTE o plano aprovado acima, "
                                    "passo a passo, usando as ferramentas."},
    ]
    cfg["mode"] = "workflow_build"
    try:
        build_result = ask_model(build_sess, True, c, auto) or ""
    finally:
        cfg["mode"] = mode_bak
    build_summary = build_result.strip()
    if not build_summary:
        for m in reversed(build_sess.messages):
            if m.get("role") == "assistant" and m.get("content"):
                build_summary = m["content"]
                break

    # ---- 3/4. VERIFICAR + CORRIGIR (até 3 ciclos) ----
    report = ""
    for cycle in range(1, WORKFLOW_MAX_FIX_CYCLES + 1):
        print()
        panel("✅ ETAPA 3/4 — VERIFICAR",
              f"Conferindo o que foi construído (ciclo {cycle})…", c, color="green")
        ctx = (f"{task}\n\nO que foi construído até agora:\n"
               f"{build_summary[:3000]}\n")
        if cycle > 1:
            ctx += f"\nCorreções aplicadas no ciclo {cycle - 1}.\n"
        v_sess = Session(cfg, c)
        v_sess.messages = [{
            "role": "user",
            "content": ctx + "\nVerifique se está tudo correto e funcionando. "
                             "Rode testes/verificações com as ferramentas se "
                             "necessário. Comece exatamente com 'VERIFICAÇÃO "
                             "OK' ou 'PROBLEMAS:'.",
        }]
        cfg["mode"] = "workflow_verify"
        try:
            report = ask_model(v_sess, True, c, auto) or ""
        finally:
            cfg["mode"] = mode_bak
        report = report.strip()
        upper = report.upper()
        ok = upper.startswith(("VERIFICAÇÃO OK", "VERIFICACAO OK", "✅"))
        if ok or "PROBLEMAS" not in upper:
            print()
            print(c.green("  ✅ Verificação concluída."))
            print(c.dim(report[:500]))
            break
        # precisa corrigir
        print()
        panel(f"🔧 ETAPA 4/4 — CORRIGIR",
              f"Ciclo de correção {cycle}/{WORKFLOW_MAX_FIX_CYCLES}…", c,
              color="yellow")
        f_sess = Session(cfg, c)
        f_sess.messages = [{
            "role": "user",
            "content": ctx + "\nProblemas encontrados na verificação:\n" +
                       report + "\n\nCorrija TODOS os problemas usando as "
                       "ferramentas.",
        }]
        cfg["mode"] = "workflow_fix"
        try:
            fix_result = ask_model(f_sess, True, c, auto) or ""
        finally:
            cfg["mode"] = mode_bak
        build_summary = build_summary + "\n" + fix_result.strip()
    else:
        print(c.yellow("⚠ Limite de ciclos de correção atingido "
                       f"({WORKFLOW_MAX_FIX_CYCLES})."))

    # histórico da sessão principal
    sess.messages.append({"role": "user", "content": task})
    sess.messages.append({"role": "assistant",
                          "content": (f"[workflow] Plano:\n{plan}\n\n"
                                      f"Verificação:\n{report[:1000]}")})
    return plan


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

# ---------------------------------------------------------------------------
# Comandos do SEND (paleta "/")
# ---------------------------------------------------------------------------

COMMANDS = [
    # (nome, sintaxe, descrição, categoria)
    ("/help", "/help", "Mostra esta ajuda", "básico"),
    ("/skills", "/skills [nome] [on|off]", "Gerencia as skills (nativas e criadas por você)", "básico"),
    ("/memoria", "/memoria", "Mostra a memória de longo prazo (~/.send/memoria.md)", "básico"),
    ("/resumo", "/resumo", "Resume a conversa atual (economiza contexto)", "básico"),
    ("/pensamento", "/pensamento", "Mostra o último pensamento do modelo (expandido)", "básico"),
    ("/clear", "/clear", "Limpa a conversa atual", "básico"),
    ("/exit", "/exit", "Sai do SEND", "básico"),
    ("/provider", "/provider [nome|add]", "Adiciona ou troca o provider de IA", "modelo"),
    ("/model", "/model [nome]", "Lista ou troca o modelo do provider atual", "modelo"),
    ("/models", "/models", "Lista os modelos do provider atual", "modelo"),
    ("/thinking", "/thinking [on|off]", "Liga/desliga o pensamento do modelo", "modelo"),
    ("/backend", "/backend [lmstudio|ollama|url]", "Mostra ou troca o servidor (LM Studio / Ollama)", "modelo"),
    ("/code", "/code", "Modo coding: usa as skills (arquivos, terminal, internet, pc)", "modo"),
    ("/chat", "/chat", "Modo chat: só conversa, sem ferramentas", "modo"),
    ("/plan", "/plan", "Modo plano: só planeja, não executa nada", "modo"),
    ("/workflow", "/workflow", "Modo workflow: Planejar → Construir → Verificar → Corrigir", "modo"),
    ("/automode", "/automode [on|off]", "Modo automático: o SEND escolhe chat/coding/plan/workflow sozinho", "modo"),
    ("/outmode", "/outmode [on|off]", "🔥 OUTMODE: age sem pedir autorização (escreve, executa, commita sozinho)", "modo"),
    ("/tools", "/tools [on|off]", "Liga/desliga as ferramentas manualmente", "modo"),
    ("/status", "/status", "Mostra o estado da sessão", "sessão"),
    ("/config", "/config [chave] [valor]", "Mostra ou altera a configuração", "sessão"),
    ("/save", "/save [arquivo]", "Salva a conversa em ~/.send/sessions/", "sessão"),
    ("/load", "/load arquivo", "Carrega uma conversa salva", "sessão"),
    ("/backups", "/backups [restore n]", "Lista/restaura backups de arquivos alterados", "sistema"),
    ("/contexto", "/contexto [on|off]", "Liga/desliga o contexto do projeto no prompt", "sistema"),
    ("/subagentes", "/subagentes [nome] [tarefa]", "Lista os subagentes ou roda um (ex.: /subagentes revisor revise este código)", "sistema"),
    ("/team", "/team <agentes> <tarefa>", "Equipe de 2+ IAs colaborando (ex.: /team revisor,pesquisador crie uma API) — pode usar 'nome@model' para modelos diferentes", "sistema"),
    ("/mcp", "/mcp [nome|reload]", "Mostra os servidores MCP (ferramentas externas) e reconecta", "sistema"),
    ("/hooks", "/hooks", "Mostra os hooks configurados (~/.send/hooks.json)", "sistema"),
    ("/doctor", "/doctor", "Diagnostica a instalação e a conexão com o servidor", "sistema"),
    ("/update", "/update", "Atualiza o SEND para a versão mais recente", "sistema"),
]

COMMAND_CATEGORIES = ["básico", "modelo", "modo", "sessão", "sistema"]


def build_help_text():
    lines = ["Comandos do SEND — digite / para abrir a paleta:", ""]
    for cat in COMMAND_CATEGORIES:
        lines.append(f"  {cat.upper()}:")
        for name, syntax, desc, ccat in COMMANDS:
            if ccat == cat:
                lines.append(f"    {syntax:<36} {desc}")
        lines.append("")
    lines.append("Dicas:")
    lines.append("  • digite / → paleta de comandos interativa")
    lines.append("  • Tab completa comandos que começam com /")
    lines.append("  • use \\ no fim da linha para continuar em outra linha")
    lines.append("  • Ctrl+C interrompe a resposta; Ctrl+C de novo sai")
    return "\n".join(lines)


HELP_TEXT = build_help_text()


def print_help(c):
    """Ajuda bonita, organizada por categoria com cores."""
    print()
    panel("⚡ SEND — AJUDA", "digite / para a paleta interativa "
          "(com busca)", c, width=74)
    for cat, cmds in _command_groups():
        if not cmds:
            continue
        print()
        print(c.bold(c.magenta("  ◆ " + cat.upper())))
        for name, syntax, desc in cmds:
            syn = syntax[:38].ljust(38)
            print(f"    {c.bold(syn)} {c.dim(desc)}")
    print()
    print(c.bold(c.magenta("  DICAS")))
    print(c.dim("    • digite / → paleta interativa (digite para "
                "filtrar, ↑↓, Enter)"))
    print(c.dim("    • Tab completa comandos e caminhos de arquivos"))
    print(c.dim("    • use \\ no fim da linha para continuar em outra linha"))
    print(c.dim("    • Ctrl+C interrompe a resposta; Ctrl+C de novo sai"))
    print()


def _read_nonblock(fd):
    """Lê 1 byte do stdin sem bloquear; None se não houver nada."""
    import select
    if select.select([sys.stdin], [], [], 0.0)[0]:
        try:
            data = os.read(fd, 1)
            return data.decode(errors="ignore") if data else None
        except OSError:
            return None
    try:
        import fcntl
    except ImportError:  # Windows usa o menu numerado; nunca chega aqui
        return None
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    try:
        try:
            data = os.read(fd, 1)
            return data.decode(errors="ignore") if data else None
        except (BlockingIOError, OSError, ValueError):
            return None
    finally:
        fcntl.fcntl(fd, fcntl.F_SETFL, flags)


def _command_groups():
    """Retorna [(categoria, [(nome, sintaxe, descrição), ...]), ...]."""
    return [(cat, [(n, s, d) for n, s, d, cc in COMMANDS if cc == cat])
            for cat in COMMAND_CATEGORIES]


def _menu_fallback(c, initial_query=""):
    """Paleta numerada para Windows / terminal não-interativo."""
    print()
    panel("⚡ COMANDOS DO SEND",
          "digite o número do comando e Enter · Enter vazio cancela", c,
          width=74)
    nums = []
    n = 1
    for cat, cmds in _command_groups():
        if not cmds:
            continue
        print(c.bold(c.magenta("  ◆ " + cat.upper())))
        for name, syntax, desc in cmds:
            query = initial_query.lower().lstrip("/")
            if query and not name.lower().lstrip("/").startswith(query):
                continue
            syn = syntax[:34].ljust(34)
            print(f"   {n:>2}. {c.bold(syn)} {c.dim(desc)}")
            nums.append((n, name))
            n += 1
    print()
    try:
        r = input(c.dim("  Escolha um número (Enter cancela): ")).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not r:
        return None
    for num, name in nums:
        if str(num) == r:
            return name
    print(c.yellow(f"  Número inválido: {r}"))
    return None


def show_command_menu(c, initial_query=""):
    """Paleta incremental: filtra enquanto digita e aceita ↑/↓, Tab ou Enter."""
    groups = _command_groups()

    # Fallback para Windows/sem TTY: lista numerada
    if os.name == "nt" or not sys.stdin.isatty():
        return _menu_fallback(c, initial_query)

    import select
    import termios
    import tty

    def matches(query, name, syntax, desc):
        if not query:
            return True
        q = query.strip().lower().lstrip("/")
        # O nome recebe prioridade: `p` sugere /provider, /plan etc. A busca
        # por palavras na descrição continua útil para consultas mais longas.
        if name.lower().lstrip("/").startswith(q):
            return True
        hay = f"{name} {syntax} {desc}".lower()
        return len(q) > 1 and all(part in hay for part in q.split())

    def build(query):
        items = []  # ("cat", nome) ou ("cmd", nome, sintaxe, desc)
        for cat, cmds in groups:
            vis = [cmd for cmd in cmds if matches(query, *cmd)]
            if vis:
                items.append(("cat", cat))
                items.extend(("cmd",) + cmd for cmd in vis)
        return items

    def draw(items, sel, query, width, maxh):
        out = []
        title = "  ⚡ COMANDOS DO SEND  "
        if query:
            title += "🔍 " + query + "▌"
        out.append(c.bold(c.cyan(title)))
        if query:
            hint = "  ↑↓ navegar · Enter executar · Esc/q fechar"
        else:
            hint = "  digite para filtrar · ↑↓ navegar · Enter executar · Esc/q fechar"
        out.append(c.dim(hint))
        out.append("")
        max_desc = max(6, width - 47)
        # janela de rolagem em volta do item selecionado
        top = 0
        if len(items) > maxh:
            top = max(0, min(sel - maxh // 2, len(items) - maxh))
        for i, it in enumerate(items[top:top + maxh], start=top):
            if it[0] == "cat":
                out.append(c.bold(c.magenta("  ◆ " + it[1].upper())))
            else:
                _, name, syntax, desc = it
                syn = syntax[:38].ljust(38)
                d = desc[:max_desc]
                if len(desc) > max_desc:
                    d = d[:max(0, max_desc - 1)] + "…"
                mark = "❯" if i == sel else " "
                if i == sel:
                    out.append("\033[48;5;26;1m " + mark + " " + syn + " " + d
                               + "\033[0m")
                else:
                    out.append(" " + mark + " " + c.bold(syn) + " " + c.dim(d))
        if len(items) > maxh:
            out.append(c.dim(f"  … {len(items) - maxh} comando(s) acima/abaixo — "
                             f"filtrando ({len(items)} total)"))
        return out

    def redraw(items, sel, query, drawn):
        lines = draw(items, sel, query, width, maxh)
        sys.stdout.write("\x1b[%dA" % drawn + "\x1b[J")
        sys.stdout.write("\r\n".join(lines) + "\r\n")
        sys.stdout.flush()
        return len(lines)

    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
    except Exception:
        # terminal sem termios (ex.: alguns emuladores/ssh) → fallback numerado
        return _menu_fallback(c, initial_query)
    size = shutil.get_terminal_size((100, 24))
    width = max(60, min(140, size.columns))
    maxh = max(6, size.lines - 8)

    query = initial_query.lstrip("/")
    items = build(query)
    sel = 0
    while items and items[sel][0] != "cmd":
        sel += 1

    sys.stdout.write("\n")
    sys.stdout.flush()
    try:
        tty.setraw(fd)
        lines = draw(items, sel, query, width, maxh)
        sys.stdout.write("\r\n".join(lines) + "\r\n")
        sys.stdout.flush()
        drawn = len(lines) + 1
        while True:
            try:
                ch = os.read(fd, 1).decode(errors="ignore")
            except OSError:
                ch = ""
            if not ch:
                continue
            if ch in ("q", "Q", "\x03"):
                break
            if ch in ("\r", "\t"):
                if items and items[sel][0] == "cmd":
                    name = items[sel][1]
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    return name
                break  # Enter sem seleção → fecha
            if ch == "\x1b":
                seq = ""
                for _ in range(2):
                    b = _read_nonblock(fd)
                    if b is None:
                        select.select([sys.stdin], [], [], 0.3)
                        b = _read_nonblock(fd)
                    if b is None:
                        break
                    seq += b
                if seq == "[A" and items:
                    sel = (sel - 1) % len(items)
                    while items[sel][0] != "cmd":
                        sel = (sel - 1) % len(items)
                elif seq == "[B" and items:
                    sel = (sel + 1) % len(items)
                    while items[sel][0] != "cmd":
                        sel = (sel + 1) % len(items)
                elif seq in ("[C", "[D"):
                    pass
                else:
                    break  # ESC sozinho → cancela
            elif ch in ("\x7f", "\x08"):
                if query:
                    query = query[:-1]
                    items = build(query)
                    sel = 0
                    while items and items[sel][0] != "cmd":
                        sel += 1
            elif ch.isdigit():
                nums = [i for i, it in enumerate(items) if it[0] == "cmd"]
                num = int(ch)
                if 1 <= num <= len(nums):
                    name = items[nums[num - 1]][1]
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    return name
            elif ch.isprintable():
                query += ch
                items = build(query)
                sel = 0
                while items and items[sel][0] != "cmd":
                    sel += 1
            drawn = redraw(items, sel, query, drawn)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            pass
        try:
            sys.stdout.write("\x1b[%dA" % drawn + "\x1b[J")
        except Exception:
            pass
        sys.stdout.write("\r\n")
        sys.stdout.flush()
    return None


def _skill_known(name):
    if name in SKILLS:
        return True
    return any(cs["name"] == name for cs in load_custom_skills())


# Chaves de configuração editáveis pelo usuário via /config
EDITABLE_CONFIG = {
    "base_url": str, "api_key": str, "model": str, "temperature": float,
    "thinking": bool, "reasoning_effort": str, "show_reasoning": bool,
    "auto_confirm": bool, "auto_backend": bool, "project_context": bool,
    "auto_summarize": bool, "mode": str, "mcp_enabled": bool, "hooks": bool,
    "auto_mode": bool, "outmode": bool,
}


def _parse_config_value(key, raw):
    t = EDITABLE_CONFIG[key]
    if t is bool:
        return raw.lower() in ("true", "1", "sim", "yes", "on")
    if t is float:
        return float(raw)
    return raw


def cmd_config(sess, rest, c, tools_enabled):
    cfg = sess.cfg
    parts = rest.split()

    if not parts:
        lines = []
        for k, v in cfg.items():
            if k in ("skills", "providers"):
                continue
            if k == "api_key" and v:
                v = "••••••••"
            mark = "" if k in EDITABLE_CONFIG else c.dim(" (fixa)")
            lines.append(f"{k:<18} = {v}{mark}")
        lines.append("")
        lines.append("Edite com: /config <chave> <valor>")
        lines.append("Ex.: /config temperature 0.3 · /config thinking true")
        panel("⚙ CONFIGURAÇÃO", "\n".join(lines), c, width=70)
        return False, tools_enabled

    key = parts[0]
    if key not in EDITABLE_CONFIG:
        print(c.yellow(f"Chave desconhecida: {key}. "
                       f"Editáveis: {', '.join(sorted(EDITABLE_CONFIG))}"))
        return False, tools_enabled
    if len(parts) < 2:
        print(f"  {key} = {cfg.get(key)}")
        return False, tools_enabled
    raw = " ".join(parts[1:])
    try:
        value = _parse_config_value(key, raw)
    except ValueError:
        print(c.yellow(f"Valor inválido para {key}: {raw!r}"))
        return False, tools_enabled
    cfg[key] = value
    if key in ("base_url", "api_key", "model"):
        active = cfg.setdefault("providers", {}).setdefault(
            cfg.get("provider", "auto"), {}
        )
        active[key] = value
        if key == "base_url":
            cfg["auto_backend"] = False
    save_config(cfg)
    shown = "••••••••" if key == "api_key" and value else value
    print(f"✅ {key} = {shown}")
    return False, tools_enabled


def cmd_backups(sess, rest, c, tools_enabled):
    parts = rest.split()
    backups = list_backups()

    if parts and parts[0] == "restore":
        if len(parts) < 2 or not parts[1].isdigit():
            print("Uso: /backups restore <n>   (n = número da lista)")
            return False, tools_enabled
        n = int(parts[1])
        print(restore_backup(n, c))
        return False, tools_enabled

    if not backups:
        panel("💾 BACKUPS",
              "Nenhum backup ainda.\n\n"
              "Os arquivos alterados pelo SEND são salvos automaticamente\n"
              f"em {BACKUP_DIR} antes de mudar.\n\n"
              "Use: /backups restore <n> para restaurar.", c, width=70)
        return False, tools_enabled
    lines = [f"{i:>3}. {b['ts']}  {b['original']}" for i, b in
             enumerate(backups, 1)]
    lines.append("")
    lines.append("Restaure com: /backups restore <n>")
    panel(f"💾 BACKUPS ({len(backups)})", "\n".join(lines), c, width=74)
    return False, tools_enabled


def cmd_provider(sess, rest, c, tools_enabled):
    """Lista, adiciona ou troca o provider da sessão."""
    cfg = sess.cfg
    configured = cfg.get("providers", {})
    if not rest:
        print(f"Provider atual: {provider_spec(cfg)['name']} ({cfg.get('provider', 'auto')})")
        print("Disponíveis:")
        ids = list(PROVIDER_PRESETS)
        for pid in ids:
            mark = " ← atual" if pid == cfg.get("provider") else ""
            ready = ("local/automático" if PROVIDER_PRESETS[pid].get("local") else
                     ("configurado" if pid in configured or
                      os.environ.get(PROVIDER_PRESETS[pid].get("env_key", "")) else
                      "requer API key"))
            print(f"  • {pid:<12} {PROVIDER_PRESETS[pid]['name']} [{ready}]{mark}")
        for pid, spec in configured.items():
            if pid not in PROVIDER_PRESETS:
                mark = " ← atual" if pid == cfg.get("provider") else ""
                print(f"  • {pid:<12} {spec.get('name', pid)} [customizado]{mark}")
        print("Use: provider <nome> | provider add | provider custom")
        return False, tools_enabled

    arg = rest.strip().lower()
    if arg.startswith("add "):
        arg = arg[4:].strip()
    if arg in ("add", "custom", "novo"):
        arg = "custom"
    if arg not in PROVIDER_PRESETS and arg not in configured and arg != "custom":
        print(c.yellow(f"Provider desconhecido: {arg}. Use /provider para listar."))
        return False, tools_enabled
    selected = configure_provider(cfg, arg, c)
    if not selected:
        return False, tools_enabled
    sess.model_id = None
    spec = provider_spec(cfg)
    key = provider_api_key(cfg, spec)
    if not spec.get("local") and not key:
        env_name = spec.get("env_key")
        hint = f" ou defina {env_name}" if env_name else ""
        print(c.yellow(f"⚠ API key ainda não configurada{hint}."))
    print(c.green(f"✅ Provider ativo: {spec['name']} ({cfg['base_url']})"))
    return False, tools_enabled


def cmd_model(sess, rest, c, tools_enabled):
    """Lista os modelos do provider atual e permite trocar o selecionado."""
    cfg = sess.cfg
    try:
        models = list_provider_models(cfg)
    except Exception as e:
        models = []
        if not rest:
            print(c.yellow(f"⚠ Não foi possível listar modelos: {e}"))
    name = rest.strip()
    if not name:
        current = sess.model_id or cfg.get("model") or "auto"
        print(f"Modelo atual em {provider_spec(cfg)['name']}: {current}")
        for i, model_id in enumerate(models, 1):
            mark = " ← atual" if model_id == current else ""
            print(f"  {i}. {model_id}{mark}")
        if models and sys.stdin.isatty() and sys.stdout.isatty():
            try:
                raw = input("Escolha um número (Enter cancela): ").strip()
                if raw:
                    name = models[int(raw) - 1]
            except (ValueError, IndexError, EOFError, KeyboardInterrupt):
                return False, tools_enabled
        if not name:
            return False, tools_enabled
    if models and name not in models:
        print(c.yellow(f"⚠ '{name}' não aparece na lista do provider. "
                       "O ID será usado mesmo assim."))
    cfg["model"] = name
    cfg.setdefault("providers", {}).setdefault(cfg.get("provider", "auto"), {})["model"] = name
    sess.model_id = name
    save_config(cfg)
    print(f"✅ Modelo definido: {name}")
    return False, tools_enabled


def cmd_backend(sess, rest, c, tools_enabled):
    cfg = sess.cfg
    if not rest:
        print(f"  Servidor atual: {cfg['base_url']}")
        print(f"  Auto-detecção: {'ligada' if cfg.get('auto_backend', True) else 'desligada'}")
        print("  Troque com: /backend lmstudio | ollama | <url>")
        return False, tools_enabled
    arg = rest.strip().lower()
    if arg in ("lmstudio", "ollama"):
        activate_provider(cfg, arg)
    elif arg.startswith("http://") or arg.startswith("https://"):
        pid = "backend-custom"
        cfg.setdefault("providers", {})[pid] = {
            "name": "Backend customizado", "base_url": arg.rstrip("/"),
            "api_key": cfg.get("api_key", ""), "model": None, "custom": True,
        }
        activate_provider(cfg, pid)
    else:
        print(c.yellow("Use: /backend lmstudio | ollama | <url>"))
        return False, tools_enabled
    cfg["setup_complete"] = True
    save_config(cfg)
    sess.model_id = None  # força re-detecção do modelo no novo servidor
    print(f"✅ Servidor: {cfg['base_url']}")
    return False, tools_enabled


def cmd_skills(sess, rest, c, tools_enabled):
    cfg = sess.cfg
    skills = list(cfg.get("skills", SKILL_ORDER))
    parts = rest.split()
    custom = load_custom_skills()

    if not parts:
        lines = []
        for name in SKILL_ORDER:
            mark = "✅" if name in skills else "⬜"
            lines.append(f"{mark} {name:<10} {SKILLS[name]}")
        if custom:
            lines.append("")
            lines.append("⭐ Personalizadas (criadas por você):")
            for cs in custom:
                mark = "✅" if cs["name"] in skills else "⬜"
                lines.append(f"{mark} {cs['name']:<10} {cs['description']}")
        lines.append("")
        lines.append("Use: /skills <nome> [on|off]   (ex.: /skills internet off)")
        lines.append("     /skills on | off          (liga/desliga todas)")
        lines.append("Crie novas skills pedindo ao SEND, ex.:")
        lines.append("  \"crie uma skill para formatar código Python\"")
        panel("🧰 SKILLS DO SEND", "\n".join(lines), c, width=74)
        return False, tools_enabled

    all_on = list(SKILL_ORDER) + [cs["name"] for cs in custom]

    if len(parts) == 1:
        if parts[0] == "on":
            cfg["skills"] = all_on
            save_config(cfg)
            print("✅ Todas as skills ligadas: " + ", ".join(all_on))
        elif parts[0] == "off":
            cfg["skills"] = []
            save_config(cfg)
            print("✅ Todas as skills desligadas — só conversa.")
        elif _skill_known(parts[0]):
            name = parts[0]
            if name in skills:
                skills.remove(name)
                msg = "desligada"
            else:
                skills.append(name)
                msg = "ligada"
            cfg["skills"] = skills
            save_config(cfg)
            print(f"✅ Skill '{name}' {msg}. Ativas: {', '.join(skills) or 'nenhuma'}")
        else:
            print(c.yellow(f"Skill desconhecida: {parts[0]}. "
                           f"Disponíveis: {', '.join(all_on)}"))
        return False, tools_enabled

    if len(parts) == 2 and _skill_known(parts[0]) and parts[1] in ("on", "off"):
        name, state = parts
        if state == "on" and name not in skills:
            skills.append(name)
        elif state == "off" and name in skills:
            skills.remove(name)
        cfg["skills"] = skills
        save_config(cfg)
        print(f"✅ Skill '{name}' {'ligada' if state == 'on' else 'desligada'}. "
              f"Ativas: {', '.join(skills) or 'nenhuma'}")
        return False, tools_enabled

    print(c.yellow("Uso: /skills <nome> [on|off] ou /skills on|off"))
    return False, tools_enabled


def cmd_subagentes(sess, rest, c, tools_enabled):
    """Lista os subagentes ou roda um: /subagentes <nome> <tarefa>."""
    subagents = load_subagents()
    parts = rest.split(None, 1)

    if not parts:
        if not subagents:
            panel("🤝 SUBAGENTES",
                  "Nenhum subagente ainda.\n\n"
                  f"Crie um arquivo .md em {SUBAGENTS_DIR} ou peça ao SEND:\n"
                  "  \"crie um subagente que revisa meu código\"\n\n"
                  "Rode um com: /subagentes <nome> <tarefa>", c, width=72)
            return False, tools_enabled
        lines = []
        for sa in subagents:
            if sa["tools"] is None:
                ftools = "padrão (leitura + internet)"
            elif sa["tools"]:
                ftools = ", ".join(sa["tools"])
            else:
                ftools = "nenhuma (só conversa)"
            lines.append(f"• {sa['name']} — {sa['description']}")
            lines.append(f"    ferramentas: {ftools}")
        lines.append("")
        lines.append("Rode um subagente: /subagentes <nome> <tarefa>")
        lines.append("Crie novos pedindo ao SEND, ex.:")
        lines.append("  \"crie um subagente que revisa meu código\"")
        panel(f"🤝 SUBAGENTES ({len(subagents)})", "\n".join(lines), c,
              width=74)
        return False, tools_enabled

    name = parts[0].lower()
    tarefa = parts[1].strip() if len(parts) > 1 else ""
    if not tarefa:
        sa = next((s for s in subagents if s["name"] == name), None)
        if sa:
            print(f"  {name}: {sa['description']}")
            print(f"  Arquivo: {SUBAGENTS_DIR / (name + '.md')}")
        else:
            print(c.yellow(f"Subagente '{name}' não existe. Use /subagentes "
                           "para listar."))
        return False, tools_enabled
    print()
    print(run_subagent(name, tarefa, c, sess.cfg))
    print()
    return False, tools_enabled


def cmd_team(sess, rest, c, tools_enabled):
    """Equipe de 2+ IAs: /team revisor,pesquisador <tarefa> [--estrategia paralelo|debate|sequencial]."""
    if not rest.strip():
        subagents = load_subagents()
        if subagents:
            names = ", ".join(s["name"] for s in subagents)
            print(f"Subagentes disponíveis: {names}")
        print("Uso: /team <agentes> <tarefa>")
        print("  Ex.: /team revisor,pesquisador crie uma API de tarefas")
        print("       /team revisor@qwen2.5-coder-7b,pesquisador --estrategia debate analise este código")
        print("  Agentes: lista separada por vírgula, pode usar 'nome@model' para modelos diferentes (grátis local).")
        print("  Estratégias: paralelo (padrão), debate, sequencial")
        return False, tools_enabled
    # parse: primeiro token é lista de agentes, resto é tarefa + possível --estrategia
    parts = rest.split(None, 1)
    agentes_raw = parts[0]
    tarefa = parts[1] if len(parts) > 1 else ""
    estrategia = "paralelo"
    # detecta --estrategia no fim da tarefa
    import re as _re
    m = _re.search(r"--estrategia\s+(paralelo|debate|sequencial)\b", tarefa)
    if m:
        estrategia = m.group(1)
        tarefa = _re.sub(r"--estrategia\s+(?:paralelo|debate|sequencial)\b", "", tarefa).strip()
    agentes = [a.strip() for a in agentes_raw.split(",") if a.strip()]
    if len(agentes) < 2:
        print(c.yellow("Equipe precisa de pelo menos 2 agentes separados por vírgula (ex.: revisor,pesquisador)."))
        return False, tools_enabled
    if not tarefa.strip():
        print(c.yellow("Informe a tarefa após os agentes (ex.: /team revisor,pesquisador crie uma API)."))
        return False, tools_enabled
    print()
    print(run_team(tarefa, agentes, estrategia, c, sess.cfg))
    print()
    return False, tools_enabled


def cmd_mcp(sess, rest, c, tools_enabled):
    """Mostra os servidores MCP; /mcp reload reconecta; /mcp <nome> detalha."""
    arg = rest.strip().lower()
    if arg == "reload":
        for name in list(_MCP["servers"]):
            mcp_disconnect(name)
        mcp_start_all(c)
        return False, tools_enabled

    servers = _MCP["servers"] if _MCP.get("started") else {}
    if not servers:
        panel("🔌 MCP",
              "Nenhum servidor MCP configurado.\n\n"
              f"Crie {MCP_CONFIG_PATH} com, ex.:\n"
              '  {"servers": {"arquivos": {"command": "npx", "args": '
              '["-y", "@modelcontextprotocol/server-filesystem", "/"]}}}\n\n'
              "Depois rode /mcp reload. As ferramentas aparecem como\n"
              "mcp_<servidor>_<ferramenta> para o modelo usar.", c, width=76)
        return False, tools_enabled

    lines = []
    for name, srv in servers.items():
        if srv.get("error"):
            lines.append(f"❌ {name} — erro: {srv['error']}")
            continue
        ftools = [t["function"]["name"] for t in srv.get("tools", [])]
        lines.append(f"✅ {name} — {len(ftools)} ferramenta(s)")
        if arg == name:
            for t in ftools:
                lines.append(f"    • {t}")
    if arg not in servers and arg:
        print(c.yellow(f"Servidor MCP desconhecido: {arg}"))
    panel("🔌 MCP", "\n".join(lines), c, width=76)
    return False, tools_enabled


def cmd_hooks(sess, rest, c, tools_enabled):
    """Mostra os hooks configurados em ~/.send/hooks.json."""
    cfg = sess.cfg
    lines = [f"Eventos: {'✅ ligados' if cfg.get('hooks', True) else '⛔ desligados'}"
             f"  (desligue com: /config hooks false)",
             f"Arquivo: {HOOKS_PATH}", ""]
    try:
        if HOOKS_PATH.exists():
            data = json.loads(HOOKS_PATH.read_text(encoding="utf-8"))
            found = False
            for ev in ("SessionStart", "PreToolUse", "PostToolUse",
                       "SessionEnd"):
                cmds = data.get(ev) or []
                if not cmds:
                    continue
                found = True
                lines.append(f"  {ev} ({len(cmds)} comando(s)):")
                for cmd in cmds[:5]:
                    lines.append(f"    • {cmd}")
            if not found:
                lines.append("  Nenhum evento configurado ainda.")
        else:
            lines.append("  Nenhum hook configurado ainda. Exemplo:")
            lines.append('  {"PreToolUse": ["echo tool=$SEND_TOOL >> '
                         '~/.send/hooks.log"],')
            lines.append('   "SessionEnd": ["echo fim >> ~/.send/hooks.log"]}')
    except Exception as e:
        lines.append(c.yellow(f"  Erro lendo hooks.json: {e}"))
    panel("🪝 HOOKS", "\n".join(lines), c, width=76)
    return False, tools_enabled


def handle_command(sess, line, c, tools_enabled):
    """Processa um comando iniciado com '/'. Retorna (sair?, tools_enabled)."""
    cfg = sess.cfg
    cmd = line.split()[0].lower()
    rest = line[len(cmd):].strip()

    if cmd in ("/exit", "/quit"):
        print("Até logo! 👋")
        return True, tools_enabled
    if cmd == "/help":
        print_help(c)
        return False, tools_enabled
    if cmd == "/clear":
        sess.messages = []
        print("🧹 Conversa limpa.")
        return False, tools_enabled
    if cmd == "/provider":
        return cmd_provider(sess, rest, c, tools_enabled)
    if cmd == "/model":
        return cmd_model(sess, rest, c, tools_enabled)
    if cmd == "/models":
        try:
            models = list_provider_models(cfg)
            if not models:
                print(c.yellow(f"⚠ Nenhum modelo informado por {provider_spec(cfg)['name']}."))
            else:
                print(f"Modelos de {provider_spec(cfg)['name']} em {cfg['base_url']}:")
                for m in models:
                    mark = " ← atual" if m == (sess.model_id or cfg["model"]) else ""
                    print(f"  • {m}{mark}")
        except Exception as e:
            print(c.red(f"✗ {e}"))
        return False, tools_enabled
    if cmd == "/code":
        cfg["mode"] = "coding"
        sess.mode_override = "coding"
        save_config(cfg)
        print("🛠 Modo coding ativado (ferramentas disponíveis).")
        return False, True
    if cmd == "/chat":
        cfg["mode"] = "chat"
        sess.mode_override = "chat"
        save_config(cfg)
        print("💬 Modo chat ativado (sem ferramentas).")
        return False, False
    if cmd == "/plan":
        cfg["mode"] = "plan"
        sess.mode_override = "plan"
        save_config(cfg)
        print("📋 Modo plano ativado (só planeja, não executa).")
        return False, False
    if cmd == "/workflow":
        cfg["mode"] = "workflow"
        sess.mode_override = "workflow"
        save_config(cfg)
        print("🔁 Modo workflow ativado: cada tarefa passa pelas 4 etapas")
        print("   📋 Planejar → 🔨 Construir → ✅ Verificar → 🔧 Corrigir")
        return False, True
    if cmd == "/memoria":
        text = memory_summary(limit=8000)
        if not text:
            panel("🧠 MEMÓRIA DE LONGO PRAZO",
                  "A memória ainda está vazia.\n"
                  "O SEND grava aprendizado sozinho com a ferramenta 'remember'.\n"
                  f"Arquivo: {MEMORY_PATH}", c, width=72)
        else:
            panel(f"🧠 MEMÓRIA ({MEMORY_PATH.name})", text, c, width=74)
        return False, tools_enabled
    if cmd == "/pensamento":
        text = (getattr(sess, "last_reasoning", "") or "").strip()
        if not text:
            print(c.yellow("Nenhum pensamento registrado nesta sessão ainda. "
                           "Ative com --thinking e pergunte algo."))
        else:
            panel("🧠 PENSAMENTO DO MODELO", text, c, color="magenta", width=78)
        return False, tools_enabled
    if cmd == "/resumo":
        if sess.summary:
            print(c.bold("🧠 Resumo da conversa (parte resumida):"))
            print(sess.summary)
        if len(sess.messages) <= 2:
            print(c.yellow("A conversa ainda é curta — nada a resumir."))
            return False, tools_enabled
        print(c.dim("Gerando resumo…"))
        n = len(sess.messages)
        if summarize_conversation(sess, c):
            print(c.green(f"✅ Resumo criado ({n} mensagens → resumo)."))
        else:
            print(c.yellow("Não foi possível resumir agora (conversa curta ou "
                           "erro)."))
        return False, tools_enabled
    if cmd == "/config":
        return cmd_config(sess, rest, c, tools_enabled)
    if cmd == "/backups":
        return cmd_backups(sess, rest, c, tools_enabled)
    if cmd == "/backend":
        return cmd_backend(sess, rest, c, tools_enabled)
    if cmd == "/contexto":
        if rest in ("on", "off"):
            cfg["project_context"] = rest == "on"
            save_config(cfg)
            print(f"📂 Contexto do projeto: {'ligado' if rest == 'on' else 'desligado'}")
        else:
            print(f"📂 Contexto do projeto: "
                  f"{'ligado' if cfg.get('project_context', True) else 'desligado'} "
                  f"(use /contexto on|off)")
        return False, tools_enabled
    if cmd == "/thinking":
        if rest in ("on", "off"):
            cfg["thinking"] = rest == "on"
            save_config(cfg)
            print(f"🧠 Pensamento: {'ligado' if cfg['thinking'] else 'desligado'}")
        else:
            print(f"🧠 Pensamento: {'ligado' if cfg['thinking'] else 'desligado'} "
                  f"(use /thinking on ou /thinking off)")
        return False, tools_enabled
    if cmd == "/automode":
        if rest in ("on", "off"):
            cfg["auto_mode"] = rest == "on"
            save_config(cfg)
            if cfg["auto_mode"]:
                print("🤖 Modo automático LIGADO — o SEND escolhe sozinho "
                      "entre chat, coding, plan e workflow para cada tarefa.")
            else:
                print(f"🤖 Modo automático desligado — usando o modo fixo "
                      f"'{cfg['mode']}'. Reative com /automode on.")
        else:
            print(f"🤖 Modo automático: "
                  f"{'ligado' if cfg.get('auto_mode', True) else 'desligado'} "
                  f"(use /automode on|off)")
        return False, tools_enabled
    if cmd == "/outmode":
        if rest in ("on", "off"):
            on = rest == "on"
            cfg["outmode"] = on
            save_config(cfg)
            if on:
                sess.outmode_prev = (bool(cfg.get("auto_confirm")),
                                     bool(cfg.get("auto_save_code")))
                sess.auto_confirm = True
                cfg["auto_save_code"] = True
                print("🔥 OUTMODE LIGADO — o SEND vai AGIR SEM PEDIR "
                      "AUTORIZAÇÃO: escrever/editar arquivos, executar "
                      "comandos, commitar e salvar código sozinho. "
                      "Desligue com /outmode off.")
            else:
                sess.auto_confirm = bool(cfg.get("auto_confirm"))
                if sess.outmode_prev:
                    cfg["auto_save_code"] = sess.outmode_prev[1]
                    sess.outmode_prev = None
                print("🔒 OUTMODE desligado — o SEND volta a pedir "
                      "autorização antes de agir.")
        else:
            print(f"🔥 OUTMODE: {'ligado' if cfg.get('outmode') else 'desligado'} "
                  f"(use /outmode on|off)")
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
        skills = cfg.get("skills", SKILL_ORDER)
        lines = [
            f"Provider     : {provider_spec(cfg)['name']} ({cfg.get('provider', 'auto')})",
            f"Servidor     : {cfg['base_url']}",
            f"Modelo       : {sess.model_id or cfg['model'] or 'auto'}",
            f"Modo         : {cfg['mode']}",
            f"Ferramentas  : {'✅ sim' if tools_enabled else '⛔ não'}",
            f"Pensamento   : {'✅ sim' if cfg['thinking'] else '⛔ não'}",
            f"Modo auto    : {'✅ sim' if cfg.get('auto_mode', True) else '⛔ não'}",
            f"OUTMODE      : {'🔥 sim' if cfg.get('outmode') else '⛔ não'}",
            f"Skills       : {', '.join(skills) if skills else 'nenhuma'}",
            f"MCP          : {mcp_summary(cfg)}",
            f"Config       : {CONFIG_PATH}",
        ]
        panel("🖥 STATUS DA SESSÃO", "\n".join(lines), c, width=70)
        return False, tools_enabled
    if cmd == "/skills":
        return cmd_skills(sess, rest, c, tools_enabled)
    if cmd == "/subagentes":
        return cmd_subagentes(sess, rest, c, tools_enabled)
    if cmd == "/team":
        return cmd_team(sess, rest, c, tools_enabled)
    if cmd == "/mcp":
        return cmd_mcp(sess, rest, c, tools_enabled)
    if cmd == "/hooks":
        return cmd_hooks(sess, rest, c, tools_enabled)
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


def _command_completer(text, state):
    """Autocomplete: comandos que começam com '/' ou caminhos de arquivos."""
    if text.startswith("/"):
        candidates = [name for name, *_ in COMMANDS if name.startswith(text)]
    else:
        # completa caminhos de arquivos/pastas (glob)
        base = text.rsplit("/", 1)[0] + "/" if "/" in text else ""
        try:
            entries = sorted(Path(base or ".").glob(text.split("/")[-1] + "*"))
        except Exception:
            entries = []
        candidates = []
        for e in entries:
            cand = (base + e.name) if base else e.name
            if e.is_dir():
                cand += "/"
            candidates.append(cand)
    if state < len(candidates):
        return candidates[state]
    return None


def _inline_matches(query):
    """Retorna lista de comandos que casam com query (para autocomplete inline)."""
    if not query:
        return []
    q = query.strip().lower().lstrip("/")
    groups = _command_groups()
    out = []
    for cat, cmds in groups:
        for name, syntax, desc in cmds:
            # mesmo critério do show_command_menu
            if not q:
                out.append((name, syntax, desc))
            elif name.lower().lstrip("/").startswith(q):
                out.append((name, syntax, desc))
            elif len(q) > 1 and all(part in f"{name} {syntax} {desc}".lower() for part in q.split()):
                out.append((name, syntax, desc))
    return out[:6]  # mini barra: máximo 6 sugestões


def _draw_inline_box(matches, selected, width):
    """Desenha mini barra inline tipo Claude Code (acima do prompt)."""
    if not matches:
        return []
    lines = []
    # borda superior sutil
    lines.append("  \x1b[2m┌─ autocomplete ─────────────────────\x1b[0m")
    for i, (name, syntax, desc) in enumerate(matches):
        syn = syntax[:34].ljust(34)
        d = desc[: max(10, width - 50)]
        if i == selected:
            # destaque invertido
            lines.append(f"\x1b[48;5;26;1m ❯ {syn} {d}\x1b[0m")
        else:
            lines.append(f"   {syn} \x1b[2m{d}\x1b[0m")
    lines.append("  \x1b[2m└─ ↑↓ navegar · Tab completar · Enter selecionar · Esc fechar\x1b[0m")
    return lines


def _input_with_inline_autocomplete(prompt, c):
    """Input com autocomplete inline tipo Claude Code (mini barra segue o prompt).

    Quando você digita '/' a mini barra aparece logo acima do prompt e filtra
    enquanto você escreve, sem sair da linha. Você continua digitando no mesmo
    lugar, não vai para outra janela.
    Para qualquer outro texto sem '/', comportamento normal com histórico readline.
    """
    import termios
    import tty
    import shutil

    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
    except Exception:
        return input(prompt)

    visible_prompt = prompt.replace("\001", "").replace("\002", "")
    # tamanho do terminal para desenhar box
    try:
        width = shutil.get_terminal_size((100, 24)).columns
    except Exception:
        width = 100

    buf = ""
    selected = 0
    prev_box_lines = 0

    def _redraw():
        nonlocal prev_box_lines
        # limpa box anterior + linha do prompt
        if prev_box_lines:
            sys.stdout.write(f"\x1b[{prev_box_lines + 1}A")  # sobe box+prompt
            sys.stdout.write("\x1b[J")  # limpa abaixo
        else:
            sys.stdout.write("\r\x1b[2K")  # só limpa linha atual
        # desenha box se buf começa com /
        box = []
        if buf.startswith("/"):
            q = buf.split()[0]  # só o token do comando
            matches = _inline_matches(q)
            if matches:
                # ajusta selected dentro do range
                nonlocal_selected = max(0, min(selected, len(matches) - 1))
                box = _draw_inline_box(matches, nonlocal_selected, width)
        # escreve box + prompt + buffer
        if box:
            sys.stdout.write("\r\n".join(box) + "\r\n")
            prev_box_lines = len(box)
        else:
            prev_box_lines = 0
        sys.stdout.write(visible_prompt + buf)
        # posiciona cursor no fim do buffer (simples)
        sys.stdout.flush()

    sys.stdout.write(visible_prompt)
    sys.stdout.flush()
    try:
        tty.setraw(fd)
        while True:
            try:
                ch = os.read(fd, 1).decode(errors="ignore")
            except OSError:
                ch = ""
            if not ch:
                continue
            # Ctrl+C
            if ch == "\x03":
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                raise KeyboardInterrupt
            # Enter
            if ch in ("\r", "\n"):
                # se tem autocomplete ativo e um selecionado, completa?
                # Para inline, Enter confirma o buffer atual (se for comando conhecido, o repl vai tratar)
                # Se o buffer é só "/" e tem seleção, completa para o selecionado
                if buf.startswith("/") and _inline_matches(buf.split()[0]):
                    matches = _inline_matches(buf.split()[0])
                    if matches:
                        # se buf é só prefixo e há seleção, Tab/Enter completa para o comando
                        # mas Enter sem Tab deve enviar o que está no buffer (ex: /help)
                        # só auto-completa se buffer ainda é prefixo e não é comando exato
                        token = buf.split()[0].lower()
                        names = [m[0].lower() for m in matches]
                        if token not in names:
                            # completa para o selecionado
                            buf = matches[selected][0] + (buf[len(token):] if len(buf) > len(token) else "")
                            _redraw()
                            continue
                # limpa box antes de sair
                if prev_box_lines:
                    sys.stdout.write(f"\x1b[{prev_box_lines + 1}A\x1b[J")
                    sys.stdout.write(visible_prompt + buf + "\r\n")
                    sys.stdout.flush()
                else:
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                return buf
            # Tab -> completa
            if ch == "\t":
                if buf.startswith("/"):
                    matches = _inline_matches(buf.split()[0])
                    if matches:
                        token = buf.split()[0]
                        sel_name = matches[selected][0]
                        # substitui token pelo nome completo
                        rest = buf[len(token):]
                        buf = sel_name + rest
                        selected = 0
                        _redraw()
                continue
            # Backspace
            if ch in ("\x7f", "\x08"):
                if buf:
                    buf = buf[:-1]
                    selected = 0
                    _redraw()
                continue
            # Escape -> sequências
            if ch == "\x1b":
                seq = ""
                for _ in range(2):
                    nxt = _read_nonblock(fd)
                    if nxt is None:
                        import select as _sel
                        _sel.select([sys.stdin], [], [], 0.05)
                        nxt = _read_nonblock(fd)
                    if nxt is None:
                        break
                    seq += nxt
                if seq == "[A":  # ↑
                    if buf.startswith("/") and _inline_matches(buf.split()[0]):
                        matches = _inline_matches(buf.split()[0])
                        selected = (selected - 1) % len(matches)
                        _redraw()
                elif seq == "[B":  # ↓
                    if buf.startswith("/") and _inline_matches(buf.split()[0]):
                        matches = _inline_matches(buf.split()[0])
                        selected = (selected + 1) % len(matches)
                        _redraw()
                elif seq == "":
                    # Esc sozinho -> limpa box / cancela autocomplete
                    if prev_box_lines:
                        # limpa box
                        sys.stdout.write(f"\x1b[{prev_box_lines + 1}A\x1b[J")
                        sys.stdout.write(visible_prompt + buf)
                        sys.stdout.flush()
                        prev_box_lines = 0
                    else:
                        # Esc sem box -> cancela linha
                        buf = ""
                        _redraw()
                continue
            # Ctrl+U -> limpa linha
            if ch == "\x15":
                buf = ""
                selected = 0
                _redraw()
                continue
            # Ctrl+L -> limpa box
            if ch == "\x0c":
                _redraw()
                continue
            if ch.isprintable():
                buf += ch
                selected = 0
                _redraw()
                continue
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            pass
        # garante limpeza do box ao sair
        if prev_box_lines:
            try:
                sys.stdout.write(f"\x1b[{prev_box_lines + 1}A\x1b[J")
                sys.stdout.write(visible_prompt + buf)
                sys.stdout.flush()
            except Exception:
                pass


def _input_with_instant_palette(prompt, c):
    """Mantido para compatibilidade: agora delega para inline."""
    return _input_with_inline_autocomplete(prompt, c)


def read_input(prompt, c):
    try:
        if (readline and os.name != "nt" and sys.stdin.isatty()
                and sys.stdout.isatty()):
            line = _input_with_instant_palette(prompt, c)
        else:
            line = input(prompt)
    except EOFError:
        return None
    if line is None:
        return None
    while line.rstrip().endswith("\\"):
        line = line.rstrip()[:-1]
        try:
            more = input(c.dim("  ... "))
        except EOFError:
            break
        line += "\n" + more
    return line


def _rl_prompt(s):
    """Envolve escapes ANSI com \001..\002 para o readline medir o prompt
    corretamente (sem isso, prompts coloridos são redesenhadados errado)."""
    if not readline:
        return s
    return re.sub(r"(\x1b\[[0-9;]*m)", r"\001\1\002", s)


def make_prompt(c, sess):
    badge = (sess.model_id or "?").rsplit("/", 1)[-1][:24]
    mode = sess.cfg["mode"].upper()
    mode_icons = {"CODING": "🛠", "CHAT": "💬", "PLAN": "📋", "WORKFLOW": "🔁"}
    mi = mode_icons.get(mode, "❯")
    think = " 🧠" if sess.cfg["thinking"] else ""
    out = " 🔥" if sess.cfg.get("outmode") else ""
    if c.enabled:
        prompt = (f"{c.bold(c.cyan('send'))}{c.dim('(' + badge + '·')}"
                  f"{mi}{c.dim(mode + ')')}{think}{out} {c.bold('❯')} ")
        return _rl_prompt(prompt)
    return f"send({badge}·{mode}){think}{out} ❯ "


def repl(sess, c, tools_enabled):
    cfg = sess.cfg
    print()
    show_mode = ("auto" if (cfg.get("auto_mode", True)
                            and sess.mode_override is None) else cfg["mode"])
    banner(c, model=(sess.model_id or cfg.get("model") or "auto"),
           mode=show_mode)
    run_hooks("SessionStart", c, sess.cfg, prompt="modo interativo")

    if readline:
        try:
            readline.read_history_file(str(INPUT_HISTORY))
            readline.set_completer(_command_completer)
            readline.set_completer_delims(" \t")
            readline.parse_and_bind("tab: complete")
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
        if line == "/":
            choice = show_command_menu(c)
            if not choice:
                continue
            line = choice
        elif line.startswith("/"):
            command_token = line.split()[0].lower()
            known = {name for name, *_ in COMMANDS}
            # `/p`, `/mo` etc. abrem a mesma paleta já filtrada. No terminal,
            # a busca segue incrementalmente e Tab/Enter aceita a seleção.
            if command_token not in known:
                choice = show_command_menu(c, initial_query=command_token)
                if not choice:
                    continue
                line = choice
        # Os dois comandos de configuração também funcionam sem a barra, como
        # documentado no onboarding (as versões /provider e /model permanecem).
        if line == "provider" or line.startswith("provider "):
            line = "/" + line
        elif line == "model" or line.startswith("model "):
            line = "/" + line
        if line.startswith("/"):
            do_exit, tools_enabled = handle_command(sess, line, c, tools_enabled)
            if do_exit:
                break
            continue

        # resume automaticamente conversas longas para economizar contexto
        if cfg.get("auto_summarize", True) and len(sess.messages) > SUMMARY_THRESHOLD:
            try:
                summarize_conversation(sess, c)
            except Exception:
                pass

        modo, is_auto = effective_mode(sess, line)
        if is_auto:
            print(c.dim("  ↳ modo automático: ") + MODE_LABELS.get(modo, modo))
        if modo == "workflow":
            save_history([{"role": "user", "content": line}])
            try:
                run_workflow(sess, line, c, cfg)
            except urllib.error.URLError as e:
                nice_error(c, "Servidor offline",
                           f"{cfg['base_url']} — o provider está acessível?\n"
                           "Rode 'send --doctor' para diagnosticar.")
            except urllib.error.HTTPError as e:
                print(c.red(f"✗ Erro HTTP {e.code} do servidor:"))
                print(c.red(e.read().decode("utf-8", "replace")[:500]))
            except ConnectionError as e:
                print(c.red(f"✗ {e}"))
            except KeyboardInterrupt:
                print()
            except Exception as e:
                print(c.red(f"✗ Erro: {e}"))
            continue

        old_mode = cfg["mode"]
        cfg["mode"] = modo
        sess.messages.append({"role": "user", "content": line})
        save_history([{"role": "user", "content": line}])
        t0 = time.time()
        try:
            content = ask_model(sess, (modo in ("coding", "workflow")) and tools_enabled, c,
                                getattr(sess, "auto_confirm", cfg["auto_confirm"]))
        except urllib.error.URLError as e:
            nice_error(c, "Servidor offline",
                       f"{cfg['base_url']} — o provider está acessível?\n"
                       "Rode 'send --doctor' para diagnosticar.")
        except urllib.error.HTTPError as e:
            print(c.red(f"✗ Erro HTTP {e.code} do servidor:"))
            print(c.red(e.read().decode("utf-8", "replace")[:500]))
        except ConnectionError as e:
            print(c.red(f"✗ {e}"))
        except KeyboardInterrupt:
            print()
        except Exception as e:
            print(c.red(f"✗ Erro: {e}"))
        else:
            if content:
                dt = time.time() - t0
                tokens = max(1, len(content) // 4)
                print(c.dim(f"    ⏱ {dt:.1f}s · ≈{tokens} tokens"))
                show_thinking_panel(sess, c, cfg)
                offer_save_code(content, c, cfg,
                                getattr(sess, "auto_confirm", cfg["auto_confirm"]))
        finally:
            cfg["mode"] = old_mode
        if sess.messages and sess.messages[-1]["role"] == "assistant":
            save_history([sess.messages[-1]])
        hr(c)

    if readline:
        try:
            readline.write_history_file(str(INPUT_HISTORY))
        except Exception:
            pass
    run_hooks("SessionEnd", c, sess.cfg)
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
    modo, is_auto = effective_mode(sess, prompt)
    if is_auto:
        print(c.dim("  ↳ modo automático: ") + MODE_LABELS.get(modo, modo))
    if modo == "workflow":
        save_history([{"role": "user", "content": prompt}])
        try:
            run_workflow(sess, prompt, c, sess.cfg)
        except urllib.error.URLError as e:
            nice_error(c, "Servidor offline",
                       f"{sess.cfg['base_url']} — o provider está acessível?\n"
                       "Rode 'send --doctor' para diagnosticar.")
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
        return 0

    run_hooks("SessionStart", c, sess.cfg, prompt=prompt[:200])
    old_mode = sess.cfg["mode"]
    sess.cfg["mode"] = modo
    sess.messages.append({"role": "user", "content": prompt})
    save_history([{"role": "user", "content": prompt}])
    t0 = time.time()
    try:
        content = ask_model(sess, (modo in ("coding", "workflow")) and tools_enabled,
                            c, auto_confirm)
    except urllib.error.URLError as e:
        nice_error(c, "Servidor offline",
                   f"{sess.cfg['base_url']} — o provider está acessível?\n"
                   "Rode 'send --doctor' para diagnosticar.")
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
    else:
        if content:
            dt = time.time() - t0
            tokens = max(1, len(content) // 4)
            print(c.dim(f"    ⏱ {dt:.1f}s · ≈{tokens} tokens"))
            show_thinking_panel(sess, c, sess.cfg)
            offer_save_code(content, c, sess.cfg, auto_confirm)
    finally:
        sess.cfg["mode"] = old_mode
    if sess.messages and sess.messages[-1]["role"] == "assistant":
        save_history([sess.messages[-1]])
    run_hooks("SessionEnd", c, sess.cfg)
    return 0


def doctor(cfg, c):
    lines = [
        f"Versão   : {VERSION}",
        f"Python   : {sys.version.split()[0]} ({sys.platform})",
        f"Config   : {CONFIG_PATH} {'✅' if CONFIG_PATH.exists() else '—'}",
        f"Servidor : {cfg['base_url']}",
        f"Modelo   : {cfg['model'] or 'auto (primeiro disponível)'}",
        f"Modo     : {cfg['mode']} · Pensamento: {'ligado' if cfg['thinking'] else 'desligado'}",
    ]
    panel("🔍 SEND — DIAGNÓSTICO", "\n".join(lines), c, width=70)
    print()
    small("Testando conexão", cfg["base_url"], c)
    t0 = time.time()
    try:
        models = list_provider_models(cfg)
        dt = (time.time() - t0) * 1000
        print(c.green(f"  ✅ Conexão OK em {dt:.0f} ms"))
        if models:
            print(f"  Modelos disponíveis ({len(models)}):")
            for m in models:
                print(f"    • {m}")
            return 0
        print(c.yellow("  ⚠ O provider respondeu, mas não informou modelos."))
        print(c.yellow("     Use /model <id> para definir um modelo manualmente."))
        return 1
    except urllib.error.URLError as e:
        spec = provider_spec(cfg)
        if spec.get("local"):
            steps = ("Inicie o LM Studio ou Ollama, carregue um modelo e "
                     "confirme que o servidor local está ativo.")
        else:
            steps = ("Verifique o endpoint, a conexão e a API key. "
                     "Use /provider para reconfigurar.")
        nice_error(c, "Não foi possível conectar",
                   f"{cfg['base_url']} ({e.reason})\n\nComo resolver:\n  {steps}\n"
                   "  Rode 'send --doctor' novamente.")
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
    curl -fsSL https://github.com/contasuportedis-png/SEND/raw/main/install.sh | bash

  Windows (PowerShell):
    irm https://github.com/contasuportedis-png/SEND/raw/main/install.ps1 | iex

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
                    "com providers locais, de nuvem ou customizados.",
        epilog="Exemplos:\n"
               "  send                          modo interativo\n"
               "  send \"explique este código\"   resposta única\n"
               "  send --code \"crie um app\"     modo coding\n"
               "  send --plan \"refatore x\"      modo plano\n"
               "  send --workflow \"crie um app\" Planejar → Construir → Verificar → Corrigir\n"
               "  send --thinking \"pergunta\"    com raciocínio (se o modelo suportar)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("prompt", nargs="*", help="prompt para execução única "
                    "(se omitido, abre o modo interativo)")
    ap.add_argument("-m", "--model", help="ID do modelo (padrão: primeiro "
                    "modelo disponível no provider)")
    ap.add_argument("-u", "--base-url", default=None,
                    help=f"URL do servidor (padrão: {DEFAULT_BASE_URL})")
    ap.add_argument("-c", "--code", action="store_true",
                    help="modo coding: pode ler/escrever arquivos e executar comandos")
    ap.add_argument("-p", "--plan", action="store_true",
                    help="modo plano: só planeja, não executa nada")
    ap.add_argument("-w", "--workflow", action="store_true",
                    help="modo workflow: Planejar → Construir → Verificar → "
                         "Corrigir (divide tarefas grandes em etapas)")
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
    ap.add_argument("--save-code", action="store_true",
                    help="salva blocos de código da resposta em arquivos "
                         "automaticamente (sem perguntar)")
    ap.add_argument("--no-tools", action="store_true",
                    help="desativa as ferramentas nesta sessão")
    ap.add_argument("--auto-mode", dest="auto_mode", action="store_true",
                    help="liga o modo automático (o SEND escolhe "
                         "chat/coding/plan/workflow sozinho)")
    ap.add_argument("--no-auto-mode", dest="auto_mode", action="store_false",
                    help="desliga o modo automático (usa o modo fixo)")
    ap.add_argument("--outmode", action="store_true",
                    help="liga o OUTMODE: age sem pedir autorização")
    ap.set_defaults(auto_mode=None)
    ap.add_argument("--temperature", type=float,
                    help="temperatura do modelo (padrão: 0.7)")
    ap.add_argument("--models", action="store_true",
                    help="lista os modelos disponíveis no provider e sai")
    ap.add_argument("--doctor", action="store_true",
                    help="diagnostica a instalação e a conexão com o provider")
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
    if not args.base_url and not args.doctor and not args.models:
        first_run_setup(cfg, c)
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
    mode_explicit = None
    if args.code:
        cfg["mode"] = "coding"
        mode_explicit = "coding"
    elif args.plan:
        cfg["mode"] = "plan"
        mode_explicit = "plan"
    elif args.workflow:
        cfg["mode"] = "workflow"
        mode_explicit = "workflow"
    elif args.chat:
        cfg["mode"] = "chat"
        mode_explicit = "chat"
    if args.auto_mode is not None:
        cfg["auto_mode"] = args.auto_mode

    if args.models:
        try:
            models = list_provider_models(cfg)
            if not models:
                print(c.yellow(f"⚠ Nenhum modelo informado por {provider_spec(cfg)['name']}."))
                return 1
            print(f"Modelos disponíveis em {cfg['base_url']} ({len(models)}):")
            for m in models:
                mark = " ← atual" if m == cfg["model"] else ""
                print(f"  • {m}{mark}")
            return 0
        except urllib.error.URLError as e:
            print(c.red(f"✗ Não consegui conectar a {provider_spec(cfg)['name']} em "
                        f"{cfg['base_url']} ({e.reason})."))
            print(c.yellow("  Rode 'send --doctor' para ver como resolver."))
            return 2
        except Exception as e:
            print(c.red(f"✗ Erro: {e}"))
            return 1

    if args.doctor:
        return doctor(cfg, c)

    sess = Session(cfg, c)
    # auto-detecta o backend (LM Studio → Ollama) antes da 1ª chamada
    if args.base_url is None:
        cfg["base_url"] = detect_backend(cfg, c)
    try:
        sess.model_id = resolve_model(cfg, c)
    except ConnectionError as e:
        if args.prompt or not sys.stdin.isatty():
            print(c.red("✗ " + str(e)))
            return 2
        print(c.yellow("⚠ " + str(e)))

    # subagentes de exemplo + servidores MCP configurados
    ensure_default_subagents()
    if cfg.get("mcp_enabled", True):
        mcp_start_all(c)

    sess.mode_override = mode_explicit
    if args.no_tools:
        tools_enabled = False
    elif cfg.get("auto_mode", True) and mode_explicit is None:
        # modo automático: ferramentas podem ser necessárias em qualquer modo
        tools_enabled = True
    else:
        tools_enabled = cfg["mode"] in ("coding", "workflow")

    # -y vale só para esta sessão (não vai para a config salva)
    sess.auto_confirm = bool(args.yes) or bool(cfg["auto_confirm"])
    if args.save_code:
        cfg["auto_save_code"] = True
    if args.outmode:
        cfg["outmode"] = True
    if cfg.get("outmode"):
        # OUTMODE: age sem pedir autorização e salva código sem perguntar
        sess.outmode_prev = (sess.auto_confirm, bool(cfg.get("auto_save_code")))
        sess.auto_confirm = True
        cfg["auto_save_code"] = True

    prompt = " ".join(args.prompt).strip()
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read()

    if prompt:
        return one_shot(sess, prompt, c, tools_enabled,
                        getattr(sess, "auto_confirm", cfg["auto_confirm"]))

    return repl(sess, c, tools_enabled)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)

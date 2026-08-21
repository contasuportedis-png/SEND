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
import difflib
import fnmatch
import html.parser
import json
import os
import platform
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

VERSION = "1.3.0"
DEFAULT_BASE_URL = "http://127.0.0.1:1234"
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
# Configuração
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "base_url": DEFAULT_BASE_URL,
    "api_key": "",
    "model": None,                 # None = detecta o primeiro modelo do LM Studio
    "mode": "coding",              # chat | coding | plan | workflow
    "thinking": False,
    "reasoning_effort": "medium",  # low | medium | high
    "show_reasoning": True,
    "auto_confirm": False,         # -y
    "temperature": 0.7,
    "skills": ["arquivos", "terminal", "internet", "pc",
               "git", "processos", "memoria"],
    "auto_backend": True,          # detecta LM Studio → Ollama automaticamente
    "project_context": True,       # injeta a árvore do projeto no contexto
    "auto_summarize": True,        # resume conversas longas automaticamente
}

OLLAMA_URL = "http://127.0.0.1:11434"

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
}

SKILL_ORDER = ["arquivos", "terminal", "internet", "pc",
               "git", "processos", "memoria"]

# Memória de longo prazo (aprendizado) e skills personalizadas
MEMORY_PATH = SEND_HOME / "memoria.md"
SKILLS_DIR = SEND_HOME / "skills"

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
    "Você pode criar novas skills para o futuro com a ferramenta 'create_skill'."
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
    """Grava uma entrada com data na memória de longo prazo."""
    try:
        SEND_HOME.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M")
        entry = f"\n## {ts}\n- {content.strip()}\n"
        with open(MEMORY_PATH, "a", encoding="utf-8") as f:
            f.write(entry)
        return True
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
    return tools


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
        list_models(cfg["base_url"], cfg["api_key"])
        return cfg["base_url"]  # LM Studio responde
    except Exception:
        pass
    try:
        list_models(OLLAMA_URL, cfg["api_key"])
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


def system_prompt(cfg, extra=""):
    parts = [BASE_SYSTEM]
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


def execute_tool(name, args, c, auto_confirm, cfg=None):
    try:
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
        if name.startswith("skill_"):
            return tool_custom_skill(name, args, c, cfg)
        return f"Ferramenta desconhecida: {name}"
    except Exception as e:
        return f"Erro ao executar {name}: {e}"


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


# Limite de mensagens antes de resumir a conversa automaticamente
SUMMARY_THRESHOLD = 16
SUMMARY_KEEP = 6


def summarize_conversation(sess, c):
    """Resume as mensagens antigas da conversa para economizar contexto.

    Mantém as últimas SUMMARY_KEEP mensagens e guarda o resumo em
    sess.summary, que é injetado no prompt de sistema. Retorna True se
    resumiu, False caso contrário.
    """
    msgs = sess.messages
    if len(msgs) <= SUMMARY_THRESHOLD:
        return False
    if sess.summary is not None and len(msgs) <= SUMMARY_THRESHOLD + SUMMARY_KEEP:
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


def call_model(sess, tools_enabled, c, cfg):
    """Chama a API com streaming. Retorna (conteúdo, lista de tool_calls)."""
    if sess.model_id is None:
        sess.model_id = resolve_model(cfg, c)
    extra = getattr(sess, "extra_system", "")
    summary = getattr(sess, "summary", None)
    if summary:
        extra = (f"Resumo de mensagens anteriores desta conversa (não "
                 f"responda ao resumo, apenas use como contexto):\n{summary}"
                 + (("\n\n" + extra) if extra else ""))
    messages = [{"role": "system",
                 "content": system_prompt(cfg, extra)}] + sess.messages
    payload = {
        "model": sess.model_id,
        "messages": messages,
        "stream": True,
        "temperature": cfg["temperature"],
    }
    if tools_enabled:
        payload["tools"] = get_tools(cfg)
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
            result = execute_tool(name, args, c, auto_confirm, sess.cfg)
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
    print(c.bold(c.cyan("📋 ETAPA 1/4 — PLANEJAR")))
    print(c.dim("   Separando a tarefa em etapas…"))
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
    print(c.bold("📋 Plano:"))
    print(plan)
    if n_steps >= 5:
        print(c.yellow(f"⚠ Tarefa grande identificada — dividida em {n_steps} "
                       "etapas organizadas por fase."))
    if not auto and sys.stdin.isatty():
        if not ask_yes_no(c, "Aprovar este plano e começar a construir?"):
            print(c.yellow("Plano recusado pelo usuário. Nada foi construído."))
            sess.messages.append({"role": "user", "content": task})
            sess.messages.append({"role": "assistant",
                                  "content": "Plano recusado pelo usuário."})
            return plan

    # ---- 2. CONSTRUIR ----
    print()
    print(c.bold(c.cyan("🔨 ETAPA 2/4 — CONSTRUIR")))
    print(c.dim("   Executando o plano passo a passo…"))
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
        print(c.bold(c.cyan("✅ ETAPA 3/4 — VERIFICAR")))
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
            print(c.green("✅ Verificação concluída."))
            print(c.dim(report[:500]))
            break
        # precisa corrigir
        print()
        print(c.bold(c.yellow("🔧 ETAPA 4/4 — CORRIGIR")))
        print(c.dim(f"   Ciclo de correção {cycle}/{WORKFLOW_MAX_FIX_CYCLES}…"))
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
    ("/clear", "/clear", "Limpa a conversa atual", "básico"),
    ("/exit", "/exit", "Sai do SEND", "básico"),
    ("/model", "/model [nome]", "Mostra ou troca o modelo (ex.: /model qwen2.5-coder-7b)", "modelo"),
    ("/models", "/models", "Lista os modelos carregados no servidor", "modelo"),
    ("/thinking", "/thinking [on|off]", "Liga/desliga o pensamento do modelo", "modelo"),
    ("/backend", "/backend [lmstudio|ollama|url]", "Mostra ou troca o servidor (LM Studio / Ollama)", "modelo"),
    ("/code", "/code", "Modo coding: usa as skills (arquivos, terminal, internet, pc)", "modo"),
    ("/chat", "/chat", "Modo chat: só conversa, sem ferramentas", "modo"),
    ("/plan", "/plan", "Modo plano: só planeja, não executa nada", "modo"),
    ("/workflow", "/workflow", "Modo workflow: Planejar → Construir → Verificar → Corrigir", "modo"),
    ("/tools", "/tools [on|off]", "Liga/desliga as ferramentas manualmente", "modo"),
    ("/status", "/status", "Mostra o estado da sessão", "sessão"),
    ("/config", "/config [chave] [valor]", "Mostra ou altera a configuração", "sessão"),
    ("/save", "/save [arquivo]", "Salva a conversa em ~/.send/sessions/", "sessão"),
    ("/load", "/load arquivo", "Carrega uma conversa salva", "sessão"),
    ("/backups", "/backups [restore n]", "Lista/restaura backups de arquivos alterados", "sistema"),
    ("/contexto", "/contexto [on|off]", "Liga/desliga o contexto do projeto no prompt", "sistema"),
    ("/doctor", "/doctor", "Diagnostica a instalação e a conexão com o servidor", "sistema"),
    ("/update", "/update", "Atualiza o SEND para a versão mais recente", "sistema"),
]

COMMAND_CATEGORIES = ["básico", "modelo", "modo", "sessão", "sistema"]


def build_help_text():
    lines = ["Comandos do SEND — digite / e Enter para abrir a paleta:", ""]
    for cat in COMMAND_CATEGORIES:
        lines.append(f"  {cat.upper()}:")
        for name, syntax, desc, ccat in COMMANDS:
            if ccat == cat:
                lines.append(f"    {syntax:<36} {desc}")
        lines.append("")
    lines.append("Dicas:")
    lines.append("  • digite / e Enter → paleta de comandos interativa")
    lines.append("  • Tab completa comandos que começam com /")
    lines.append("  • use \\ no fim da linha para continuar em outra linha")
    lines.append("  • Ctrl+C interrompe a resposta; Ctrl+C de novo sai")
    return "\n".join(lines)


HELP_TEXT = build_help_text()


def _read_nonblock(fd):
    """Lê 1 byte do stdin sem bloquear; None se não houver nada.

    Cobre os dois lugares onde bytes podem estar esperando: o fd (via select)
    e os buffers internos do TextIOWrapper (via leitura com fd não-bloqueante).
    """
    import select
    if select.select([sys.stdin], [], [], 0.0)[0]:
        return sys.stdin.read(1)
    try:
        import fcntl
    except ImportError:  # Windows usa o menu numerado; nunca chega aqui
        return None
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    try:
        try:
            return sys.stdin.read(1)
        except (BlockingIOError, OSError, ValueError):
            return None
    finally:
        fcntl.fcntl(fd, fcntl.F_SETFL, flags)


def show_command_menu(c):
    """Paleta de comandos interativa (setas ↑↓ + Enter). Retorna o comando
    escolhido ou None se cancelado."""
    flat = []
    for cat in COMMAND_CATEGORIES:
        flat.append(("cat", cat))
        for name, syntax, desc, ccat in COMMANDS:
            if ccat == cat:
                flat.append(("cmd", name, syntax, desc))

    def draw(idx):
        out = []
        for i, item in enumerate(flat):
            if item[0] == "cat":
                out.append(c.cyan(c.bold("  " + item[1].upper())))
            else:
                marker = c.bold(c.cyan("❯")) if i == idx else " "
                out.append(f" {marker} {item[2]:<34} {c.dim(item[3])}")
        return out

    # Fallback para Windows/sem TTY: lista numerada
    if os.name == "nt" or not sys.stdin.isatty():
        print(c.bold("Comandos do SEND:"))
        nums = []
        n = 1
        for i, item in enumerate(flat):
            if item[0] == "cat":
                print(c.cyan(c.bold("  " + item[1].upper())))
            else:
                print(f"  {n}. {item[2]:<34} {c.dim(item[3])}")
                nums.append((n, item[1]))
                n += 1
        print()
        try:
            r = input(c.dim("Escolha um número (Enter para cancelar): ")).strip()
            if not r:
                return None
            for num, name in nums:
                if str(num) == r:
                    return name
            print(c.yellow(f"Número inválido: {r}"))
            return None
        except (EOFError, KeyboardInterrupt):
            return None

    import select
    import termios
    import tty

    idx = 1  # primeiro comando (índice 0 é o cabeçalho da 1ª categoria)
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    sys.stdout.write("\n")
    try:
        tty.setraw(fd)
        lines = draw(idx)
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()
        while True:
            ch = sys.stdin.read(1)
            if ch in ("q", "Q", "\x03"):
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                return None
            if ch == "\r":
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                selected = flat[idx]
                return selected[1] if selected[0] == "cmd" else None
            if ch == "\x1b":
                # ESC pode ser sozinho (cancelar) ou início de seta (ESC [ A/B)
                seq = ""
                for _ in range(2):
                    b = _read_nonblock(fd)
                    if b is None:
                        # espera um pouco (entrega atrasada do terminal)
                        select.select([sys.stdin], [], [], 0.3)
                        b = _read_nonblock(fd)
                    if b is None:
                        break
                    seq += b
                if seq == "[A":
                    idx = (idx - 1) % len(flat)
                    while flat[idx][0] != "cmd":
                        idx = (idx - 1) % len(flat)
                elif seq == "[B":
                    idx = (idx + 1) % len(flat)
                    while flat[idx][0] != "cmd":
                        idx = (idx + 1) % len(flat)
                elif seq in ("[C", "[D"):
                    pass
                else:
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    return None
            elif ch.isdigit():
                # atalho por número (1-9)
                num = int(ch)
                cmd_items = [i for i in flat if i[0] == "cmd"]
                if 1 <= num <= len(cmd_items):
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    return cmd_items[num - 1][1]
            sys.stdout.write("\r\x1b[K" + ("\x1b[1A\r\x1b[K" * (len(flat) - 1)))
            lines = draw(idx)
            sys.stdout.write("\n".join(lines) + "\n")
            sys.stdout.flush()
    except (KeyboardInterrupt, EOFError):
        return None
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            pass


def _skill_known(name):
    if name in SKILLS:
        return True
    return any(cs["name"] == name for cs in load_custom_skills())


# Chaves de configuração editáveis pelo usuário via /config
EDITABLE_CONFIG = {
    "base_url": str, "api_key": str, "model": str, "temperature": float,
    "thinking": bool, "reasoning_effort": str, "show_reasoning": bool,
    "auto_confirm": bool, "auto_backend": bool, "project_context": bool,
    "auto_summarize": bool, "mode": str,
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
        print(c.bold("Configuração atual:"))
        for k, v in cfg.items():
            if k == "skills":
                continue
            mark = "" if k in EDITABLE_CONFIG else c.dim(" (fixa)")
            print(f"  {k:<18} = {v}{mark}")
        print()
        print("  Edite com: /config <chave> <valor>")
        print(f"  Ex.: /config temperature 0.3 • /config thinking true • "
              f"/config base_url http://127.0.0.1:1234")
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
    save_config(cfg)
    print(f"✅ {key} = {value}")
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
        print("Nenhum backup ainda. Os arquivos alterados pelo SEND são "
              f"salvos automaticamente em {BACKUP_DIR} antes de mudar.")
        print("  Use: /backups restore <n> para restaurar.")
        return False, tools_enabled
    print(c.bold(f"Backups ({len(backups)}):"))
    for i, b in enumerate(backups, 1):
        print(f"  {i:>3}. {b['ts']}  {b['original']}")
    print()
    print("  Restaure com: /backups restore <n>")
    return False, tools_enabled


def cmd_backend(sess, rest, c, tools_enabled):
    cfg = sess.cfg
    if not rest:
        print(f"  Servidor atual: {cfg['base_url']}")
        print(f"  Auto-detecção: {'ligada' if cfg.get('auto_backend', True) else 'desligada'}")
        print("  Troque com: /backend lmstudio | ollama | <url>")
        return False, tools_enabled
    arg = rest.strip().lower()
    if arg == "lmstudio":
        url = DEFAULT_BASE_URL
    elif arg == "ollama":
        url = OLLAMA_URL
    elif arg.startswith("http://") or arg.startswith("https://"):
        url = arg
    else:
        print(c.yellow("Use: /backend lmstudio | ollama | <url>"))
        return False, tools_enabled
    cfg["base_url"] = url.rstrip("/")
    cfg["auto_backend"] = False
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
        print("Skills do SEND:")
        for name in SKILL_ORDER:
            mark = "✅" if name in skills else "⬜"
            print(f"  {mark} {name:<10} {SKILLS[name]}")
        if custom:
            print()
            print("  ⭐ Personalizadas (criadas por você):")
            for cs in custom:
                mark = "✅" if cs["name"] in skills else "⬜"
                print(f"  {mark} {cs['name']:<10} {cs['description']}")
        print()
        print("  Use: /skills <nome> [on|off]   (ex.: /skills internet off)")
        print("       /skills on | off          (liga/desliga todas)")
        print("  Para criar uma nova skill, peça ao SEND:")
        print("    ex.: \"crie uma skill para formatar código Python\"")
        print(f"  Skills criadas ficam em: {SKILLS_DIR}")
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
    if cmd == "/workflow":
        cfg["mode"] = "workflow"
        save_config(cfg)
        print("🔁 Modo workflow ativado: cada tarefa passa pelas 4 etapas")
        print("   📋 Planejar → 🔨 Construir → ✅ Verificar → 🔧 Corrigir")
        return False, True
    if cmd == "/memoria":
        text = memory_summary(limit=8000)
        if not text:
            print("🧠 A memória de longo prazo está vazia.")
            print(f"   Arquivo: {MEMORY_PATH}")
            print("   O SEND grava aprendizado sozinho com a ferramenta "
                  "'remember'.")
        else:
            print(c.bold(f"🧠 Memória de longo prazo ({MEMORY_PATH}):"))
            print(text)
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
        print(f"  Servidor : {cfg['base_url']}")
        print(f"  Modelo   : {sess.model_id or cfg['model'] or 'auto'}")
        print(f"  Modo     : {cfg['mode']}")
        print(f"  Ferramentas: {'sim' if tools_enabled else 'não'}")
        print(f"  Pensamento : {'sim' if cfg['thinking'] else 'não'}")
        print(f"  Skills   : {', '.join(skills) if skills else 'nenhuma'}")
        print(f"  Config   : {CONFIG_PATH}")
        return False, tools_enabled
    if cmd == "/skills":
        return cmd_skills(sess, rest, c, tools_enabled)
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
    print(c.dim("   Digite / para abrir a paleta de comandos • /help • Ctrl+C para sair"))
    print()

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

        if cfg["mode"] == "workflow":
            save_history([{"role": "user", "content": line}])
            try:
                run_workflow(sess, line, c, cfg)
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
            continue

        sess.messages.append({"role": "user", "content": line})
        save_history([{"role": "user", "content": line}])
        t0 = time.time()
        try:
            content = ask_model(sess, tools_enabled and cfg["mode"] != "plan", c,
                                getattr(sess, "auto_confirm", cfg["auto_confirm"]))
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
        else:
            if content:
                dt = time.time() - t0
                tokens = max(1, len(content) // 4)
                print(c.dim(f"    ⏱ {dt:.1f}s · ≈{tokens} tokens"))
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
    if sess.cfg["mode"] == "workflow":
        save_history([{"role": "user", "content": prompt}])
        try:
            run_workflow(sess, prompt, c, sess.cfg)
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
        return 0

    sess.messages.append({"role": "user", "content": prompt})
    save_history([{"role": "user", "content": prompt}])
    t0 = time.time()
    try:
        content = ask_model(sess, tools_enabled and sess.cfg["mode"] != "plan",
                            c, auto_confirm)
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
    else:
        if content:
            dt = time.time() - t0
            tokens = max(1, len(content) // 4)
            print(c.dim(f"    ⏱ {dt:.1f}s · ≈{tokens} tokens"))
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
                    "conectado ao LM Studio (http://127.0.0.1:1234).",
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
                    "modelo carregado no LM Studio)")
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
    if args.code:
        cfg["mode"] = "coding"
    elif args.plan:
        cfg["mode"] = "plan"
    elif args.workflow:
        cfg["mode"] = "workflow"
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

    tools_enabled = (cfg["mode"] in ("coding", "workflow")) and not args.no_tools

    # -y vale só para esta sessão (não vai para a config salva)
    sess.auto_confirm = bool(args.yes) or bool(cfg["auto_confirm"])

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

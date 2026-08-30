#!/usr/bin/env bash
# Testes do SEND — usa um servidor LM Studio simulado (sem precisar do LM Studio).
set -euo pipefail
cd "$(dirname "$0")/.."

# IMPORTANTE: fecha o stdin da suíte inteira. Assim, mesmo rodando dentro de
# um terminal interativo (ex.: via publicar.sh), nenhum `input()` do SEND
# fica esperando resposta do usuário — os testes nunca travam.
exec < /dev/null

# Captura tudo num log: no final, qualquer Traceback (mesmo em testes cujo
# erro é mascarado por `&& echo OK`) faz a suíte falhar de verdade.
_TEST_LOG="$(mktemp)"
exec > >(tee "$_TEST_LOG") 2>&1

echo "== 1. Sintaxe =="
python3 -m py_compile send.py
bash -n install.sh
echo "OK"

echo "== 2. Versão =="
python3 send.py --version

echo "== 3. Mock do LM Studio =="
MOCK_PORT="${SEND_MOCK_PORT:-1234}"
MOCK_PID=""
if curl -s --max-time 1 http://127.0.0.1:${MOCK_PORT}/v1/models 2>/dev/null | grep -q '"qwen2.5-coder-7b"'; then
  echo "Mock já ativo na porta ${MOCK_PORT} — reutilizando"
else
  SEND_MOCK_PORT=${MOCK_PORT} python3 tests/mock_lmstudio.py &
  MOCK_PID=$!
  sleep 1
fi
trap 'if [ -n "$MOCK_PID" ]; then kill $MOCK_PID 2>/dev/null || true; fi' EXIT

export SEND_HOME="$(mktemp -d)"
export SEND_BASE_URL="http://127.0.0.1:${MOCK_PORT}"

echo "== 4. --doctor =="
python3 send.py --doctor

echo "== 5. --models =="
python3 send.py --models

echo "== 6. Resposta única =="
python3 send.py "oi, tudo bem?" < /dev/null > /tmp/send_t6.log 2>&1 && grep -q "Olá! Este é o modelo simulado" /tmp/send_t6.log && echo "OK"

echo "== 7. Tool call (read_file, -y) =="
python3 send.py -y "leia o arquivo README.md e me diga o que ele contem" < /dev/null > /tmp/send_t7.log 2>&1 && grep -q "Resultado da ferramenta" /tmp/send_t7.log && echo "OK"

echo "== 8. Tool call web_search =="
python3 send.py --no-auto-mode -y "pesquise na internet" < /dev/null > /tmp/send_t8.log 2>&1 && grep -q "Resultado da ferramenta" /tmp/send_t8.log && echo "OK"

echo "== 9. Tool call system_info =="
python3 send.py --no-auto-mode -y "informacoes do pc" < /dev/null > /tmp/send_t9.log 2>&1 && grep -q "Resultado da ferramenta" /tmp/send_t9.log && echo "OK"

echo "== 10. Tool call edit_file =="
python3 send.py -y "edite o arquivo" < /dev/null > /tmp/send_t10.log 2>&1 && grep -q "Resultado da ferramenta" /tmp/send_t10.log && echo "OK"

echo "== 11. Tool call find_files =="
python3 send.py -y "procure" < /dev/null > /tmp/send_t11.log 2>&1 && grep -q "Resultado da ferramenta" /tmp/send_t11.log && echo "OK"

echo "== 12. Modo plano =="
python3 send.py --plan "faca um plano" < /dev/null > /tmp/send_t12.log 2>&1 && grep -q "PLANO" /tmp/send_t12.log && echo "OK"

echo "== 13. Pensamento (thinking) =="
python3 send.py --thinking "teste" < /dev/null > /tmp/send_t13.log 2>&1 && grep -q "modelo simulado" /tmp/send_t13.log && echo "OK"

echo "== 14. Skills na config =="
python3 - <<'PY' && echo "OK"
import os, sys, tempfile
sys.path.insert(0, ".")
os.environ["SEND_HOME"] = tempfile.mkdtemp()
import send
cfg = send.load_config()
assert set(cfg["skills"]) == set(send.SKILL_ORDER), cfg["skills"]
tools = send.TOOLS
ALLOWED_ALL = {"read_file","write_file","edit_file","list_files","find_files",
               "run_command","web_search","fetch_url","system_info","open_file",
               "open_url","browser_open","git_status","git_log","git_diff","git_commit",
               "list_processes","kill_process","read_memory","remember",
               "create_skill","delegate","create_subagent","team",
               "create_directory","move_file","copy_file","delete_file",
               "file_stats","grep","run_python","get_env","set_env","read_pdf"}
for _t in tools:
    assert _t["function"]["name"] in ALLOWED_ALL, _t["function"]["name"]
print(f"   {len(tools)} ferramentas válidas OK")
for t in tools:
    assert t["skill"] in send.SKILLS, (t["function"]["name"], t.get("skill"))
print("   todas as ferramentas com skill OK")
PY

echo "== 15. Filtro de skills no payload =="
SEND_HOME=$(mktemp -d) python3 - <<'PY' && echo "OK"
import os, sys
sys.path.insert(0, ".")
import send
cfg = send.load_config()
cfg["skills"] = ["terminal"]
payload_tools = [t for t in send.TOOLS if t.get("skill") in cfg["skills"]]
names = [t["function"]["name"] for t in payload_tools]
assert names == ["run_command", "run_python", "get_env", "set_env"], names
print("   payload com apenas ferramentas de terminal OK")
PY

echo "== 16. Workflow (4 etapas) =="
python3 send.py --workflow -y "crie um app simples" < /dev/null > /tmp/send_wf_test.txt 2>&1
grep -q "ETAPA 1/4 — PLANEJAR" /tmp/send_wf_test.txt && \
  grep -q "VERIFICAÇÃO OK" /tmp/send_wf_test.txt && echo "OK"

echo "== 17. Memória (remember + leitura) =="
SEND_HOME=$(mktemp -d) python3 - <<'PY' && echo "OK"
import os, sys
sys.path.insert(0, ".")
import send
send.SEND_HOME = send.Path(os.environ["SEND_HOME"])
send.MEMORY_PATH = send.SEND_HOME / "memoria.md"
send.SKILLS_DIR = send.SEND_HOME / "skills"
c = send.make_colors()
r = send.tool_remember({"content": "Usuário prefere respostas curtas."}, c)
assert "Lembrei" in r
assert "respostas curtas" in send.memory_summary()
print("   memoria gravada e lida OK")
PY

echo "== 18. Criar skill personalizada =="
SEND_HOME=$(mktemp -d) python3 - <<'PY' && echo "OK"
import os, sys
sys.path.insert(0, ".")
import send
send.SEND_HOME = send.Path(os.environ["SEND_HOME"])
send.MEMORY_PATH = send.SEND_HOME / "memoria.md"
send.SKILLS_DIR = send.SEND_HOME / "skills"
cfg = send.load_config()
c = send.make_colors()
r = send.tool_create_skill({"name": "Formatar Codigo",
                            "description": "formata código com 4 espaços",
                            "instructions": "Use 4 espaços de indentação."},
                           c, cfg)
assert "criada" in r, r
custom = send.load_custom_skills()
assert any(cs["name"] == "formatar_codigo" for cs in custom), custom
assert "formatar_codigo" in cfg["skills"]
tools = send.get_tools(cfg)
assert any(t["function"]["name"] == "skill_formatar_codigo" for t in tools)
print("   skill criada, ativada e convertida em ferramenta OK")
PY

echo "== 19. Git tools =="
python3 - <<'PY' && echo "OK"
import sys
sys.path.insert(0, ".")
import send
c = send.make_colors()
r = send.tool_git_status({}, c)
assert "Branch" in r and r.strip(), r[:100]
r = send.tool_git_log({}, c)
assert r.strip(), "log vazio"
print("   git_status e git_log OK")
PY

echo "== 20. Processos =="
python3 - <<'PY' && echo "OK"
import sys
sys.path.insert(0, ".")
import send
c = send.make_colors()
r = send.tool_list_processes({"filter": "python", "n": 3}, c)
assert "PID" in r or "python" in r.lower() or "Nenhum" in r, r[:100]
print("   list_processes OK")
PY

echo "== 21. Backup automático + restore =="
SEND_HOME=$(mktemp -d) python3 - <<'PY' && echo "OK"
import os, sys, tempfile
sys.path.insert(0, ".")
os.environ["SEND_HOME"] = tempfile.mkdtemp()
import send
send.SEND_HOME = send.Path(os.environ["SEND_HOME"])
send.BACKUP_DIR = send.SEND_HOME / "backups"
send.BACKUP_INDEX = send.BACKUP_DIR / "index.json"
send.MEMORY_PATH = send.SEND_HOME / "memoria.md"
send.SKILLS_DIR = send.SEND_HOME / "skills"
c = send.make_colors()
p = "/tmp/send_backup_test.txt"
open(p, "w").write("original")
send.tool_write({"path": p, "content": "novo"}, c)
assert open(p).read() == "novo"
assert len(send.list_backups()) == 1
send.restore_backup(1, c)
assert open(p).read() == "original"
print("   backup + restore OK")
PY

echo "== 22. Contexto do projeto no prompt =="
python3 - <<'PY' && echo "OK"
import sys
sys.path.insert(0, ".")
import send
sp = send.system_prompt({"mode": "coding", "project_context": True})
assert "Estrutura do projeto" in sp
sp2 = send.system_prompt({"mode": "coding", "project_context": False})
assert "Estrutura do projeto" not in sp2
print("   contexto on/off OK")
PY

echo "== 23. Auto-resumo de conversa longa =="
SEND_HOME=$(mktemp -d) python3 - <<'PY' && echo "OK"
import os, sys
sys.path.insert(0, ".")
import send
cfg = send.load_config()
c = send.make_colors()
sess = send.Session(cfg, c)
for i in range(10):
    sess.messages.append({"role": "user", "content": f"pergunta {i}"})
    sess.messages.append({"role": "assistant", "content": f"resposta {i}"})
assert len(sess.messages) == 20
from unittest.mock import patch as _patch
with _patch.object(send, "ask_model", side_effect=lambda s,t,c_,a: "resumo fake determinístico"):
    ok = send.summarize_conversation(sess, c)
assert ok and len(sess.messages) == 6 and sess.summary == "resumo fake determinístico"
print("   auto-resumo OK")
PY

echo "== 24. /config parse e detect_backend =="
python3 - <<'PY' && echo "OK"
import sys
sys.path.insert(0, ".")
import send
assert send._parse_config_value("temperature", "0.3") == 0.3
assert send._parse_config_value("thinking", "true") is True
assert send._parse_config_value("thinking", "off") is False
cfg = send.load_config()
assert send.detect_backend(cfg, send.make_colors()) == send.DEFAULT_BASE_URL
print("   config + backend OK")
PY

echo "== 25. Blocos de código: detecção + auto-salvar =="
python3 - <<'PY' && echo "OK"
import os, sys, tempfile
sys.path.insert(0, ".")
import send
c = send.make_colors()
content = ("Veja:\n\n```python app.py\nprint('ola')\n```\n\n"
           "```js\nconsole.log('hi')\n```\n")
blocks = send.parse_code_blocks(content)
assert len(blocks) == 2 and blocks[0]["lang"] == "python"
assert blocks[0]["meta"] == "app.py"
used = []
assert send.suggest_filename("python", "app.py", used) == "app.py"
used.append("app.py")
assert send.suggest_filename("python", "app.py", used) == "app_2.py"
assert send.suggest_filename("js", "", []) == "script.js"
td = tempfile.mkdtemp()
saved = send.offer_save_code(content, c, send.load_config(), True, dest_dir=td)
assert len(saved) == 2
assert open(os.path.join(td, "app.py")).read().strip() == "print('ola')"
assert open(os.path.join(td, "script.js")).read().strip() == "console.log('hi')"
assert send.offer_save_code("sem codigo", c, {}, True, dest_dir=td) == []
print("   detecção + auto-salvar OK")
PY

echo "== 26. Painel de pensamento (fora de TTY) =="
python3 - <<'PY' && echo "OK"
import sys
sys.path.insert(0, ".")
import send
c = send.make_colors()
cfg = send.load_config()
class S: pass
sess = S()
sess.last_reasoning = "linha 1\nlinha 2"
send.show_thinking_panel(sess, c, cfg)  # não pode travar nem falhar fora de TTY
print("   painel de pensamento OK")
PY

echo "== 27. Subagentes: padrão + criar + delegar =="
SEND_HOME=$(mktemp -d) python3 - <<'PY' && echo "OK"
import os, sys
sys.path.insert(0, ".")
import send
c = send.make_colors()
send.ensure_default_subagents()
sas = send.load_subagents()
assert [s["name"] for s in sas] == ["analista", "pesquisador", "revisor"]
assert "não existe" in send.tool_delegate({"nome": "xpto", "tarefa": "t"}, c)
r = send.tool_create_subagent({"nome": "tradutor", "descricao": "traduz texto",
                               "instrucoes": "Traduza para ingles.",
                               "ferramentas": "nenhuma"}, c)
assert "criado" in r
tr = next(s for s in send.load_subagents() if s["name"] == "tradutor")
assert tr["tools"] == []
tools = send.get_tools(send.load_config())
names = [t["function"]["name"] for t in tools]
assert "delegate" in names and "create_subagent" in names
print("   subagentes OK")
PY

echo "== 28. MCP: sem servidor não quebra + nome de ferramenta =="
SEND_HOME=$(mktemp -d) python3 - <<'PY' && echo "OK"
import os, sys
sys.path.insert(0, ".")
import send
c = send.make_colors()
send.mcp_start_all(c)
assert send.mcp_tools() == []
assert send.tool_mcp_call("mcp_x_y", {}, c) == "Ferramenta MCP não encontrada: mcp_x_y"
assert send._mcp_tool_name("git server", "list files") == "mcp_git_server_list_files"
print("   mcp sem servidor OK")
PY

echo "== 29. MCP: conexão real com servidor simulado (stdio) =="
cat > /tmp/fake_mcp_server.py <<'PY'
import json, sys
def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try: msg = json.loads(line)
    except Exception: continue
    mid = msg.get("id"); method = msg.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake", "version": "1.0"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [
            {"name": "echo", "description": "Repete o texto",
             "inputSchema": {"type": "object",
                             "properties": {"texto": {"type": "string"}},
                             "required": ["texto"]}}]}})
    elif method == "tools/call":
        args = (msg.get("params") or {}).get("arguments") or {}
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text", "text": "eco: " + str(args.get("texto", ""))}]}})
PY
SEND_HOME=$(mktemp -d) python3 - <<'PY' && echo "OK"
import os, json, sys
sys.path.insert(0, ".")
import send
home = os.environ["SEND_HOME"]
with open(os.path.join(home, "mcp.json"), "w") as f:
    json.dump({"servers": {"fake": {"command": "python3",
                                    "args": ["/tmp/fake_mcp_server.py"]}}}, f)
c = send.make_colors()
send.mcp_start_all(c)
names = [t["function"]["name"] for t in send.mcp_tools()]
assert names == ["mcp_fake_echo"], names
assert send.tool_mcp_call("mcp_fake_echo", {"texto": "oi"}, c) == "eco: oi"
print("   mcp stdio OK")
PY

echo "== 30. Hooks: PreToolUse/PostToolUse + SessionStart/End =="
SEND_HOME=$(mktemp -d) python3 - <<'PY' && echo "OK"
import os, json, sys
sys.path.insert(0, ".")
import send
home = os.environ["SEND_HOME"]
log = os.path.join(home, "hooks.log")
with open(os.path.join(home, "hooks.json"), "w") as f:
    json.dump({"PreToolUse": [f"echo tool=$SEND_TOOL args=$SEND_ARGS >> {log}"],
               "PostToolUse": [f"echo result=$SEND_RESULT >> {log}"],
               "SessionStart": [f"echo inicio >> {log}"],
               "SessionEnd": [f"echo fim >> {log}"]}, f)
c = send.make_colors()
cfg = send.load_config()
send.run_hooks("SessionStart", c, cfg)
send.execute_tool("read_file", {"path": "x"}, c, True, cfg)
send.run_hooks("SessionEnd", c, cfg)
lines = open(log).read().strip().splitlines()
assert lines[0] == "inicio"
assert lines[1] == 'tool=read_file args={"path": "x"}'
assert lines[2].startswith("result=")
assert lines[3] == "fim"
cfg["hooks"] = False
send.run_hooks("SessionStart", c, cfg)
assert len(open(log).read().strip().splitlines()) == 4
print("   hooks OK")
PY

echo "== 31. Delegação E2E via mock (subagente roda e devolve) =="
SEND_HOME=$(mktemp -d) python3 send.py "delegue a revisao do codigo" < /dev/null > /tmp/send_t31.log 2>&1 || true
grep -q "🤖 subagente revisor" /tmp/send_t31.log && echo "OK"

echo "== 32. Paleta de comandos (fallback sem TTY) =="
python3 - <<'PY' && echo "OK"
import builtins, sys
sys.path.insert(0, ".")
import send
c = send.make_colors()
captured = {}
def fake_input(prompt=""):
    captured["prompt"] = prompt
    return "5"
orig = builtins.input
builtins.input = fake_input
try:
    choice = send.show_command_menu(c)
finally:
    builtins.input = orig
assert choice in [cmd[0] for cmd in send.COMMANDS], choice
assert "Escolha um número" in captured["prompt"]
print("   paleta fallback OK")
PY

echo "== 33. Modo automático: detecção por tarefa =="
python3 - <<'PY' && echo "OK"
import sys
sys.path.insert(0, ".")
import send
d = send.detect_mode
cases = [
    ("oi, tudo bem?", "chat"),
    ("o que é um decorator em Python?", "chat"),
    ("crie um app de tarefas completo", "workflow"),
    ("desenvolva um site com backend e frontend", "workflow"),
    ("planeje a refatoração do projeto", "plan"),
    ("procure o arquivo config.py no projeto", "coding"),
    ("crie um script que ordene uma lista", "coding"),
    ("liste os arquivos da pasta", "coding"),
]
for prompt, esperado in cases:
    assert d(prompt) == esperado, (prompt, d(prompt))
cfg = send.load_config()
c = send.make_colors()
sess = send.Session(cfg, c)
m, auto = send.effective_mode(sess, "crie um app de tarefas completo")
assert m == "workflow" and auto is True
sess.mode_override = "coding"
m, auto = send.effective_mode(sess, "oi")
assert m == "coding" and auto is False
sess.mode_override = None
cfg["auto_mode"] = False
m, auto = send.effective_mode(sess, "crie um app")
assert m == cfg["mode"] and auto is False
cfg["auto_mode"] = True
print("   detecção de modo OK")
PY

echo "== 34. /automode e /outmode =="
SEND_HOME=$(mktemp -d) python3 - <<'PY' && echo "OK"
import os, sys
sys.path.insert(0, ".")
import send
c = send.make_colors()
cfg = send.load_config()
assert cfg.get("auto_mode") is True
sess = send.Session(cfg, c)
send.handle_command(sess, "/automode off", c, True)
assert cfg["auto_mode"] is False
send.handle_command(sess, "/automode on", c, True)
assert cfg["auto_mode"] is True
send.handle_command(sess, "/outmode on", c, True)
assert cfg["outmode"] is True
assert sess.auto_confirm is True
assert cfg["auto_save_code"] is True
assert "🔥" in send.make_prompt(c, sess)
send.handle_command(sess, "/outmode off", c, True)
assert cfg["outmode"] is False
assert sess.auto_confirm is False
print("   /automode e /outmode OK")
PY

echo "== 35. E2E: modo automático escolhe workflow/chat sozinho =="
SEND_HOME=$(mktemp -d) python3 send.py "crie um app de tarefas completo" < /dev/null > /tmp/send_wf_test.log 2>&1 || true
grep -q "ETAPA 1/4" /tmp/send_wf_test.log && echo "   workflow OK"
SEND_HOME=$(mktemp -d) python3 send.py "oi" < /dev/null > /tmp/send_chat_test.log 2>&1 || true
grep -q "modelo simulado" /tmp/send_chat_test.log && echo "   chat OK"

echo "== 36. Providers de nuvem, customizados e autocomplete =="
python3 -m unittest tests/test_providers.py

echo "== 37. Permissões por projeto =="
python3 - <<'PY' && echo "OK"
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, ".")
import send
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / ".send.json").write_text(json.dumps({
        "tool_deny": ["write_*", "mcp_*"],
        "tool_allow": ["read_*", "list_files"],
        "command_allow": ["git status"],
    }), encoding="utf-8")
    cfg = send.apply_project_permissions(send.load_config(), root)
    assert send.tool_permission_error("write_file", cfg)
    assert send.tool_permission_error("mcp_test_run", cfg)
    assert send.tool_permission_error("run_command", cfg)
    assert send.tool_permission_error("read_file", cfg) is None
    assert cfg["_project_permissions"]["command_allow"] == ["git status"]
print("   regras locais bloqueiam ferramentas e comandos corretamente")
PY

echo "== 38. Saída para automação (JSON + max-turns) =="
python3 send.py --output-format json --max-turns 1 "oi" > /tmp/send_json_test.log 2>&1
python3 - <<'PY' && echo "OK"
import json
data = json.load(open("/tmp/send_json_test.log", encoding="utf-8"))
assert data["type"] == "result" and data["status"] == "success", data
assert "modelo simulado" in data["response"], data
assert data["turns"] == 1, data
print("   JSON limpo e limite de turnos OK")
PY

echo "== 39. Busca de histórico e agendamentos =="
SEND_HOME=$(mktemp -d) python3 - <<'PY' && echo "OK"
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, ".")
import send
root = Path(os.environ["SEND_HOME"])
send.SEND_HOME = root
send.HISTORY_PATH = root / "history.jsonl"
send.SCHEDULES_PATH = root / "schedules.json"
send.SCHEDULE_LOG_PATH = root / "schedules.jsonl"
send.save_history([{"role": "user", "content": "corrigir bug de autenticação"},
                   {"role": "assistant", "content": "bug corrigido"}])
assert len(send.search_history("autenticação")) == 1
task = send.add_schedule(5, "revisar testes")
assert task["enabled"] and not send.due_schedules()
send.mark_schedule_run(task["id"], now=1000, result="ok")
saved = send.load_schedules()[0]
assert saved["last_run"] == 1000 and saved["next_run"] == 1300
print("   busca e persistência de agendamento OK")
PY

echo
if grep -qE "Traceback|AssertionError|^✗ " "$_TEST_LOG"; then
  echo "❌ A suíte registrou erros (Traceback/AssertionError) — revise acima."
  exit 1
fi
echo "✅ Todos os testes passaram!"

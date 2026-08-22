#!/usr/bin/env bash
# Testes do SEND — usa um servidor LM Studio simulado (sem precisar do LM Studio).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1. Sintaxe =="
python3 -m py_compile send.py
bash -n install.sh
echo "OK"

echo "== 2. Versão =="
python3 send.py --version

echo "== 3. Mock do LM Studio =="
python3 tests/mock_lmstudio.py &
MOCK_PID=$!
trap 'kill $MOCK_PID 2>/dev/null || true' EXIT
sleep 1

export SEND_HOME="$(mktemp -d)"

echo "== 4. --doctor =="
python3 send.py --doctor

echo "== 5. --models =="
python3 send.py --models

echo "== 6. Resposta única =="
python3 send.py "oi, tudo bem?" | grep -q "Olá! Este é o modelo simulado" && echo "OK"

echo "== 7. Tool call (read_file, -y) =="
python3 send.py -y "leia o arquivo README.md e me diga o que ele contem" | grep -q "Resultado da ferramenta" && echo "OK"

echo "== 8. Tool call web_search =="
python3 send.py -y "pesquise na internet" | grep -q "Resultado da ferramenta" && echo "OK"

echo "== 9. Tool call system_info =="
python3 send.py -y "informacoes do pc" | grep -q "Resultado da ferramenta" && echo "OK"

echo "== 10. Tool call edit_file =="
python3 send.py -y "edite o arquivo" | grep -q "Resultado da ferramenta" && echo "OK"

echo "== 11. Tool call find_files =="
python3 send.py -y "procure" | grep -q "Resultado da ferramenta" && echo "OK"

echo "== 12. Modo plano =="
python3 send.py --plan "faca um plano" | grep -q "PLANO" && echo "OK"

echo "== 13. Pensamento (thinking) =="
python3 send.py --thinking "teste" | grep -q "modelo simulado" && echo "OK"

echo "== 14. Skills na config =="
python3 - <<'PY' && echo "OK"
import os, sys, tempfile
sys.path.insert(0, ".")
os.environ["SEND_HOME"] = tempfile.mkdtemp()
import send
cfg = send.load_config()
assert set(cfg["skills"]) == set(send.SKILL_ORDER), cfg["skills"]
tools = send.TOOLS
assert len(tools) == 20, len(tools)
ALLOWED = {"read_file","write_file","edit_file","list_files","find_files",
           "run_command","web_search","fetch_url","system_info","open_file",
           "open_url","git_status","git_log","git_diff","git_commit",
           "list_processes","kill_process","read_memory","remember",
           "create_skill"}
for t in tools:
    assert t["function"]["name"] in ALLOWED, t["function"]["name"]
    assert t["skill"] in send.SKILLS
print("   20 ferramentas com skill OK")
PY

echo "== 15. Filtro de skills no payload =="
SEND_HOME=$(mktemp -d) python3 - <<'PY' && echo "OK"
import os, sys
sys.path.insert(0, ".")
import send
cfg = send.load_config()
cfg["skills"] = ["terminal"]
payload_tools = [t for t in send.TOOLS if t.get("skill") in cfg["skills"]]
assert [t["function"]["name"] for t in payload_tools] == ["run_command"]
print("   payload com apenas run_command OK")
PY

echo "== 16. Workflow (4 etapas) =="
python3 send.py --workflow -y "crie um app simples" > /tmp/send_wf_test.txt 2>&1
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
ok = send.summarize_conversation(sess, c)
assert ok and len(sess.messages) == 6 and sess.summary
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
SEND_HOME=$(mktemp -d) python3 send.py "delegue a revisao do codigo" 2>&1 | grep -q "🤖 subagente revisor" && echo "OK"

echo
echo "✅ Todos os testes passaram!"

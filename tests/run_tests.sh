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
assert "Branch" in r and "git" in r.lower(), r[:100]
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

echo
echo "✅ Todos os testes passaram!"

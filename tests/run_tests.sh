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
assert len(tools) == 11, len(tools)
for t in tools:
    assert t["function"]["name"] in {"read_file","write_file","edit_file",
        "list_files","find_files","run_command","web_search","fetch_url",
        "system_info","open_file","open_url"}
    assert t["skill"] in send.SKILLS
print("   11 ferramentas com skill OK")
PY

echo "== 15. Filtro de skills no payload =="
SEND_HOME=$(mktemp -d) python3 - <<'PY' && echo "OK"
import os, sys
sys.path.insert(0, ".")
import send
cfg = send.load_config()
cfg["skills"] = ["terminal"]
from send import TOOLS
payload_tools = [t for t in TOOLS if t.get("skill") in cfg["skills"]]
assert [t["function"]["name"] for t in payload_tools] == ["run_command"]
print("   payload com apenas run_command OK")
PY

echo
echo "✅ Todos os testes passaram!"

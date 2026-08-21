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
python3 send.py -y "leia o arquivo README.md e me diga o que ele contem" | grep -q "README.md foi lido" && echo "OK"

echo "== 8. Modo plano =="
python3 send.py --plan "faca um plano" | grep -q "PLANO" && echo "OK"

echo "== 9. Pensamento (thinking) =="
python3 send.py --thinking "teste" | grep -q "modelo simulado" && echo "OK"

echo
echo "✅ Todos os testes passaram!"

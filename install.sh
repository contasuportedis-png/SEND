#!/usr/bin/env bash
#
# SEND — instalador para Linux e macOS (testado no Pop!_OS / Ubuntu)
#
# Uso:
#   curl -fsSL https://github.com/contasuportedis-png/SEND/releases/latest/download/install.sh | bash
#
# Opções:
#   SEND_VERSION=latest|v1.0.0  versão a instalar (padrão: latest)
#   Instala em ~/.local/bin/send  (ou /usr/local/bin/send com sudo/root)
#
set -euo pipefail

SEND_VERSION="${SEND_VERSION:-latest}"
BASE_URL="https://github.com/contasuportedis-png/SEND/releases/${SEND_VERSION}/download"
FALLBACK_URL="https://raw.githubusercontent.com/contasuportedis-png/SEND/arena/01a0252e-send/send.py"

echo "⚡ SEND — instalador"

# 1) Python 3 é obrigatório
if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ Python 3 não encontrado. Instale primeiro com:" >&2
  echo "    sudo apt install python3   # Debian / Pop!_OS / Ubuntu" >&2
  exit 1
fi

# 2) Destino da instalação
if [[ "${1:-}" == "--system" || "$(id -u)" == "0" ]]; then
  DEST="/usr/local/bin/send"
else
  DEST="${HOME}/.local/bin/send"
fi
mkdir -p "$(dirname "$DEST")"

# 3) Download (release oficial com fallback para o repositório)
echo "⬇ Baixando SEND ${SEND_VERSION} ..."
if ! curl -fsSL "${BASE_URL}/send.py" -o "${DEST}.tmp" 2>/dev/null; then
  echo "  (usando fallback do repositório)"
  curl -fsSL "${FALLBACK_URL}" -o "${DEST}.tmp"
fi

# 4) Sanidade: deve ser um script Python
head -c 100 "${DEST}.tmp" | grep -q "python3" || { echo "✗ Download inválido." >&2; rm -f "${DEST}.tmp"; exit 1; }

chmod +x "${DEST}.tmp"
mv "${DEST}.tmp" "${DEST}"
mkdir -p "${HOME}/.send"

echo "✅ SEND instalado em: ${DEST}"

# 5) PATH
BIN_DIR="$(dirname "$DEST")"
if [[ ":$PATH:" != *":${BIN_DIR}:"* ]]; then
  echo "⚠ Adicione ${BIN_DIR} ao seu PATH:"
  case "${SHELL:-}" in
    *zsh)  echo '    echo '"'"'export PATH="'${BIN_DIR}':$PATH"'"'"' >> ~/.zshrc && source ~/.zshrc' ;;
    *)     echo '    echo '"'"'export PATH="'${BIN_DIR}':$PATH"'"'"' >> ~/.bashrc && source ~/.bashrc' ;;
  esac
fi

echo
echo "Próximos passos:"
echo "  1. Abra o LM Studio → carregue um modelo → aba 'Developer' → Start Server (porta 1234)"
echo "  2. Verifique a conexão:  send --doctor"
echo "  3. Comece a usar:        send"
echo

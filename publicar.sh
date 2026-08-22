#!/usr/bin/env bash
#
# publicar.sh — publica o SEND no GitHub automaticamente
#
# Rode isto NO SEU PC (Pop!_OS / Ubuntu), não no sandbox:
#
#   1) Baixe o send-v1.6.0.zip (preview "Download do SEND v1.6.0")
#   2) bash publicar.sh
#
# Aceita: bash publicar.sh [caminho-do-zip]   (ou uma pasta com os arquivos)
# Se não passar nada, procura o zip em ~/Downloads e na pasta atual.
#
# O script:
#   • verifica git/gh/python3 e a autenticação no GitHub
#   • clona o repositório (sempre limpo)
#   • aplica o pacote por cima
#   • roda a suíte de testes
#   • faz commit, push para o main, cria a tag vX.Y.Z e o release
#
set -euo pipefail

ARG="${1:-}"
REPO="https://github.com/contasuportedis-png/SEND.git"
WORK="$(mktemp -d)/SEND"
SRC=""

# ---------------------------------------------------------------- origem ---
resolve_abs() {
  # vira um caminho absoluto sem depender do diretório atual
  local p="$1"
  if [[ "$p" != /* ]]; then
    p="$(pwd)/$p"
  fi
  # normaliza (removendo ./ e ..) — readlink -f também resolve symlinks
  readlink -f "$p" 2>/dev/null || echo "$p"
}

if [[ -n "$ARG" ]]; then
  if [[ -f "$ARG" && "$ARG" == *.zip ]]; then
    SRC="$(resolve_abs "$ARG")"
  elif [[ -d "$ARG" && -f "$ARG/send.py" ]]; then
    SRC="$(resolve_abs "$ARG")"
  else
    echo "✗ Não encontrei '$ARG' — passe um .zip ou uma pasta com send.py" >&2
    exit 1
  fi
else
  shopt -s nullglob
  for c in \
    "${HOME}/Downloads/send-"*.zip \
    "${HOME}/Downloads/pacote.zip" \
    ./send-*.zip \
    ./pacote.zip; do
    if [[ -f "$c" ]]; then SRC="$(resolve_abs "$c")"; break; fi
  done
  if [[ -z "$SRC" && -f ./send.py && -f ./README.md ]]; then
    SRC="$(resolve_abs .)"   # já estamos na pasta do projeto
  fi
fi

echo "⚡ Publicador do SEND"
echo "────────────────────────────────────────────"

# 1) Pré-requisitos
for cmd in git gh python3 unzip; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "✗ Faltando: $cmd — instale com: sudo apt install $cmd (gh: https://cli.github.com)" >&2
    exit 1
  fi
done

# 2) Origem existe?
if [[ -z "$SRC" ]]; then
  echo "✗ Não achei o pacote. Baixe o send-v1.6.0.zip e rode de novo," >&2
  echo "  ou passe o caminho: bash publicar.sh /caminho/do/send-v1.6.0.zip" >&2
  exit 1
fi
echo "✅ Pacote: $SRC"

# 3) Autenticação GitHub
if ! gh auth status >/dev/null 2>&1; then
  echo "⚠ Você precisa autenticar no GitHub primeiro:"
  echo "    gh auth login"
  echo "    gh auth setup-git"
  echo "  Depois rode este script de novo."
  exit 1
fi
echo "✅ GitHub autenticado"

# 4) Clona o repositório (limpo)
rm -rf "$(dirname "$WORK")"
echo "⬇ Clonando o repositório…"
git clone --quiet "$REPO" "$WORK"
cd "$WORK"
BRANCH="$(git branch --show-current)"
echo "✅ Clonado (branch: $BRANCH)"
if [[ "$BRANCH" != "main" ]]; then
  git checkout --quiet main
fi

# 5) Aplica o pacote e descobre a versão
echo "📦 Aplicando o pacote…"
if [[ "$SRC" == *.zip ]]; then
  unzip -qo "$SRC"
else
  cp -a "$SRC"/. .
fi
VERSION_LINHA="$(grep -m1 '^VERSION = ' send.py || true)"
VER="$(echo "$VERSION_LINHA" | sed 's/.*"\(.*\)".*/\1/')"
echo "   $VERSION_LINHA"
if [[ -z "$VER" || ! "$VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "✗ Não consegui identificar a versão no send.py — abortando." >&2
  exit 1
fi
echo "   → publicando v${VER}"

# 6) Testes
echo "🧪 Rodando a suíte de testes…"
if ! timeout 600 bash tests/run_tests.sh > /tmp/send_tests.log 2>&1; then
  echo "✗ Testes falharam ou excederam 10 minutos — veja /tmp/send_tests.log" >&2
  tail -20 /tmp/send_tests.log >&2
  exit 1
fi
echo "✅ Testes passaram"

# 7) Commit + push
git add -A
if git diff --cached --quiet; then
  echo "ℹ Nada para commitar (código já está igual) — seguindo para tag/release."
else
  git commit --quiet -m "v${VER}: corrige paleta / que escorregava a cada tecla

fix: corrige bug visual no autocomplete da paleta de comandos (/)
- Corrige cálculo de linhas redesenhadas em show_command_menu (+1 pela quebra extra antes do primeiro desenho)."
  echo "✅ Commit criado"
fi
git push --quiet origin main
echo "✅ Push para o main"

# 8) Tag + release
if git rev-parse "v${VER}" >/dev/null 2>&1; then
  echo "ℹ Tag v${VER} já existe — pulando criação."
else
  git tag "v${VER}"
  git push --quiet origin "v${VER}"
  echo "✅ Tag v${VER} criada"
fi
if gh release view "v${VER}" >/dev/null 2>&1; then
  echo "ℹ Release v${VER} já existe — pulando criação."
else
  gh release create "v${VER}" send.py install.sh install.ps1 \
    --title "SEND v${VER}" \
    --notes "## ⚡ SEND v${VER}

fix: corrige bug visual no autocomplete da paleta de comandos (/)

- Corrige cálculo de linhas redesenhadas em show_command_menu, que fazia
  a paleta escorregar e deixar lixo visual na tela a cada tecla digitada.

### Atualização
\`\`\`bash
send --update
send --version
\`\`\`
A versão exibida deve ser \`SEND ${VER}\`.

**Linux/macOS:** curl -fsSL https://github.com/contasuportedis-png/SEND/raw/main/install.sh | bash
**Windows:** irm https://github.com/contasuportedis-png/SEND/raw/main/install.ps1 | iex" >/dev/null
  echo "✅ Release v${VER} criado"
fi

echo
echo "🎉 Tudo publicado!"
echo "   • main:     https://github.com/contasuportedis-png/SEND"
echo "   • release:  https://github.com/contasuportedis-png/SEND/releases/tag/v${VER}"
echo
echo "No seu terminal, atualize com:  send --update"

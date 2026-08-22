#!/usr/bin/env bash
#
# publicar.sh — publica o SEND v1.4.0 no GitHub automaticamente
#
# Rode isto NO SEU PC (Pop!_OS / Ubuntu), não no sandbox:
#
#   1) Baixe o send-v1.4.0.zip (preview "Download do SEND v1.4.0")
#   2) bash publicar.sh
#
# O script:
#   • verifica git/gh/python3 e a autenticação no GitHub
#   • clona o repositório (ou usa a pasta ./SEND se já existir)
#   • aplica o zip da v1.4.0 por cima
#   • roda a suíte de testes
#   • faz commit, push para o main, cria a tag v1.4.0 e o release
#
set -euo pipefail

ZIP="${1:-}"
REPO="https://github.com/contasuportedis-png/SEND.git"
WORK="$(mktemp -d)/SEND"

# Se não passaram o caminho, procura o zip nos lugares comuns
if [[ -z "$ZIP" ]]; then
  shopt -s nullglob
  cands=(
    "${HOME}/Downloads/send-v1.4.0.zip"
    "${HOME}/Downloads/pacote.zip"
    "${HOME}/Downloads/send-v1.4.0"*.zip
    ./send-v1.4.0.zip
    ./pacote.zip
  )
  for c in "${cands[@]}"; do
    if [[ -f "$c" ]]; then ZIP="$c"; break; fi
  done
fi

echo "⚡ Publicador do SEND v1.4.0"
echo "────────────────────────────────────────────"

# 1) Pré-requisitos
for cmd in git gh python3 unzip; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "✗ Faltando: $cmd — instale com: sudo apt install $cmd (gh: https://cli.github.com)" >&2
    exit 1
  fi
done

# 2) Zip existe?
if [[ ! -f "$ZIP" ]]; then
  echo "✗ Zip não encontrado em: $ZIP" >&2
  echo "  Baixe o send-v1.4.0.zip pelo preview do Arena e rode de novo," >&2
  echo "  ou passe o caminho: bash publicar.sh /caminho/do/send-v1.4.0.zip" >&2
  exit 1
fi

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

# 5) Aplica a v1.4.0
echo "📦 Aplicando o pacote v1.4.0…"
unzip -qo "$ZIP"
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
if ! bash tests/run_tests.sh > /tmp/send_tests.log 2>&1; then
  echo "✗ Testes falharam — veja /tmp/send_tests.log" >&2
  tail -20 /tmp/send_tests.log >&2
  exit 1
fi
echo "✅ Testes passaram"

# 7) Commit + push
git add -A
if git diff --cached --quiet; then
  echo "ℹ Nada para commitar (código já está igual) — seguindo para tag/release."
else
  git commit --quiet -m "v${VER}: atualização do SEND

- Banner de boas-vindas com logo ASCII em gradiente
- Markdown colorido no streaming (títulos, negrito, código, listas)
- Painéis com bordas para status/config/skills/memoria/backups/doctor/workflow
- Ferramentas com ícones e preview do resultado
- Spinner de carregamento; prompt com ícone do modo (🛠 💬 📋 🔁)
- Paleta de comandos com seleção destacada; erros em painel vermelho"
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

### ✨ Novidades
- Pensamento do modelo minimizável/expansível (Enter expande, /pensamento)
- Blocos de código em moldura com a linguagem
- Código salvo direto no computador (pergunta antes, ou --save-code)
- Banner ASCII, painéis, markdown colorido, ícones, spinner

### 🧪 Testes automatizados passando

**Linux/Pop!_OS:** \`curl -fsSL https://github.com/contasuportedis-png/SEND/raw/main/install.sh | bash\`
**Windows:** \`irm https://github.com/contasuportedis-png/SEND/raw/main/install.ps1 | iex\`" >/dev/null
  echo "✅ Release v${VER} criado"
fi

echo
echo "🎉 Tudo publicado!"
echo "   • main:     https://github.com/contasuportedis-png/SEND"
echo "   • release:  https://github.com/contasuportedis-png/SEND/releases/tag/v${VER}"
echo
echo "No seu terminal, atualize com:  send --update"

# ⚡ SEND — Assistente de IA no Terminal

Um CLI de IA no estilo **Claude Code / Gemini CLI**, que roda **100% local** e
grátis usando os modelos que você já instalou no
[LM Studio](https://lmstudio.ai/). Funciona no **Linux (Pop!_OS, Ubuntu…)**,
**Windows** e macOS.

Digite `send` no terminal e comece a conversar:

```bash
$ send
⚡ SEND v1.0.0 — assistente de IA no terminal (LM Studio)

send(qwen2.5-coder-7b·CODING) ❯ crie um script que renomeie todos os arquivos .txt para .md
```

---

## 📦 Instalação

### Linux / Pop!_OS / Ubuntu

```bash
curl -fsSL https://github.com/contasuportedis-png/SEND/raw/arena/01a0252e-send/install.sh | bash
```

Isso instala em `~/.local/bin/send` (adicione ao PATH se for preciso), baixa o
script, e deixa tudo pronto. Depois:

```bash
send --doctor     # testa a conexão com o LM Studio
send              # abre o assistente
```

### Windows (PowerShell)

```powershell
irm https://github.com/contasuportedis-png/SEND/raw/arena/01a0252e-send/install.ps1 | iex
```

Instala em `%USERPROFILE%\.send\` e cria o comando `send` (adicione ao PATH se
pedir). Abra um **novo terminal** e use `send --doctor` e depois `send`.

> Os mesmos arquivos (`send.py`, `install.sh`, `install.ps1`) também estão
> disponíveis na página de [Releases](https://github.com/contasuportedis-png/SEND/releases).

> Pré-requisito (os dois sistemas): **Python 3** instalado e o **LM Studio**
> com o servidor local ligado.

---

## 🚀 Conexão automática com o LM Studio

O SEND se conecta sozinho ao servidor local do LM Studio em
`http://127.0.0.1:1234`:

1. Abra o **LM Studio** e **carregue um modelo** (ex.: `Qwen2.5 Coder 7B`,
   `Llama 3.1`, `DeepSeek R1 Distill`…).
2. Clique na aba **Developer** (Servidor Local) e depois em **Start Server**
   (porta `1234`).
3. Rode `send` — ele detecta automaticamente o primeiro modelo carregado.

Se o servidor estiver em outra porta/URL, configure com:

```bash
send --base-url http://127.0.0.1:5000 "pergunta"   # uma vez
# ou permanentemente:
send config set base_url http://127.0.0.1:5000
```

---

## 🧠 Modos de uso

| Modo | Flag | O que faz |
|---|---|---|
| **Chat** | `--chat` / `/chat` | Só conversa, sem ferramentas |
| **Coding** (padrão) | `--code` / `/code` | Pode **ler e escrever arquivos**, listar diretórios e **executar comandos** no seu terminal |
| **Plano** | `--plan` / `/plan` | **Pensa antes de agir**: produz só um plano passo a passo, sem executar nada |

### Pensamento (thinking) — sim ou não

Alguns modelos (ex.: DeepSeek R1, Qwen3) raciocinam antes de responder. O SEND
suporta isso, e você controla com **sim ou não**:

```bash
send --thinking "explique a complexidade deste código"   # liga
send --no-thinking "explique a complexidade deste código" # desliga
```

No modo interativo: `/thinking on` / `/thinking off`.

> Requisito: o modelo precisa ter raciocínio habilitado no LM Studio
> (alguns modelos têm um seletor "Thinking" na página de chat) e a porta
> precisa estar exposta no servidor local.

---

## 💻 Exemplos

```bash
send                                    # modo interativo
send "o que é um decorator em Python?"  # resposta única
send --code "crie um jogo da velha em Python"
send --plan "refatore meu projeto para usar classes"
send --thinking "compare dois algoritmos de ordenação"
send --models                           # lista os modelos do LM Studio
send --doctor                           # diagnostica a instalação
send --update                           # atualiza para a versão mais recente
send --install                          # mostra como instalar em outra máquina
```

### Comandos dentro do SEND

```
/help     /exit   /clear   /model [nome]   /models
/code     /chat   /plan    /thinking on|off /tools on|off
/status   /save [arquivo]  /load arquivo   /update   /doctor
```

---

## ⚙️ Como funciona

- **Um único arquivo** (`send.py`) — sem dependências, só a biblioteca padrão
  do Python. Funciona offline, sem instalar pacotes.
- Fala com o LM Studio pela **API compatível com OpenAI** (`/v1/chat/completions`)
  com **streaming** (as respostas aparecem conforme são geradas).
- Em **modo coding** usa *function calling*: lê/escreve arquivos, lista pastas e
  roda comandos (sempre perguntando antes de escrever/executar, a menos que você
  use `-y`).
- Configuração e histórico ficam em `~/.send/` (`config.json`, `history.jsonl`).
- Suporta também qualquer servidor compatível com a API da OpenAI: basta trocar
  `--base-url` (e `--api-key` via `SEND_API_KEY`, se precisar).

### Verificar se funciona com qualquer modelo

```bash
send --doctor
```

---

## 🔄 Atualizar

```bash
send --update
```

Baixa a versão mais recente do repositório e substitui o arquivo atual.

---

## 🛠 Desenvolvimento

```bash
git clone https://github.com/contasuportedis-png/SEND.git
cd SEND
./send.py --doctor        # ou: python3 send.py --doctor
```

Testes rápidos (sem precisar do LM Studio):

```bash
python3 -m py_compile send.py && echo "sintaxe OK"
python3 send.py --version
```

---

## 📄 Licença

MIT — veja [LICENSE](LICENSE).

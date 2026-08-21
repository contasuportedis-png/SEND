# ⚡ SEND — Assistente de IA no Terminal

Um CLI de IA no estilo **Claude Code / Gemini CLI**, que roda **100% local** e
grátis usando os modelos que você já instalou no
[LM Studio](https://lmstudio.ai/) (ou no [Ollama](https://ollama.com/)).
Funciona no **Linux (Pop!_OS, Ubuntu…)**, **Windows** e macOS.

Digite `send` no terminal e comece a conversar:

```bash
$ send
⚡ SEND v1.3.0 — assistente de IA no terminal (LM Studio)

send(qwen2.5-coder-7b·CODING) ❯ crie um script que renomeie todos os arquivos .txt para .md
```

---

## 📦 Instalação

### Opção 1 — Git clone (recomendada: o código fica no seu PC)

```bash
git clone https://github.com/contasuportedis-png/SEND.git
cd SEND
make install            # instala em ~/.local/bin/send (Linux/macOS)
# ou, para todos os usuários do PC:
# sudo make install-system
```

Sem `make`? É só copiar o arquivo (funciona em qualquer sistema):

```bash
mkdir -p ~/.local/bin
cp send.py ~/.local/bin/send
chmod +x ~/.local/bin/send
```

Confira que `~/.local/bin` está no seu PATH (Pop!_OS / Ubuntu):

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Pronto:

```bash
send --doctor     # testa a conexão com o LM Studio
send              # abre o assistente
```

> Para atualizar depois do clone: `cd SEND && git pull && make install`

### Opção 2 — Comando único (sem clonar)

**Linux / Pop!_OS / Ubuntu:**

```bash
curl -fsSL https://github.com/contasuportedis-png/SEND/raw/main/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://github.com/contasuportedis-png/SEND/raw/main/install.ps1 | iex
```

Instala em `%USERPROFILE%\.send\` e cria o comando `send` (adicione ao PATH se
pedir). Abra um **novo terminal** e use `send --doctor` e depois `send`.

> Os mesmos arquivos (`send.py`, `install.sh`, `install.ps1`) também estão
> disponíveis na página de [Releases](https://github.com/contasuportedis-png/SEND/releases).

> Pré-requisito (os dois sistemas): **Python 3** instalado e o **LM Studio**
> com o servidor local ligado (ou o **Ollama** rodando — o SEND detecta
> automaticamente os dois).

## 🔄 Backend automático: LM Studio **ou** Ollama

O SEND tenta o LM Studio (`http://127.0.0.1:1234`) primeiro; se não estiver
rodando, **detecta sozinho o Ollama** (`http://127.0.0.1:11434`) e avisa.
Para trocar manualmente:

```
/backend                # mostra o servidor atual
/backend lmstudio       # volta para o LM Studio (1234)
/backend ollama         # usa o Ollama (11434)
/backend http://127.0.0.1:5000   # servidor compatível com a API OpenAI
```

A auto-detecção pode ser desligada com `/config auto_backend false`.

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

## 🔁 Modo Workflow: Planejar → Construir → Verificar → Corrigir

Igual ao Hermes/Claude: para tarefas maiores, o SEND trabalha em **4 etapas**:

```bash
send --workflow "crie um aplicativo de tarefas"   # uma vez
# ou dentro do SEND:
/workflow
```

1. **📋 Planejar** — separa a tarefa em etapas numeradas. Se a tarefa for
   **muito grande** (5+ etapas), ela é dividida em fases com marcos. O SEND
   **pede sua aprovação** antes de construir (a menos que use `-y`).
2. **🔨 Construir** — executa o plano passo a passo usando as skills
   (arquivos, terminal, git…).
3. **✅ Verificar** — confere se está tudo funcionando: roda testes, lê os
   arquivos criados, procura erros.
4. **🔧 Corrigir** — se a verificação apontar problemas, corrige e **reverifica**
   (até 3 ciclos de correção).

```bash
send --workflow "crie um app de tarefas em Python"      # com aprovação do plano
send --workflow -y "crie um app de tarefas em Python"   # sem perguntar
```

## 🧠 Memória de longo prazo (aprende sozinho)

O SEND tem um arquivo de memória (`~/.send/memoria.md`) que **aprende com o
tempo**:

- Toda conversa começa com a memória resumida no contexto do modelo;
- Quando o SEND descobre algo útil (suas preferências, decisões do projeto,
  bugs corrigidos), ele **grava sozinho** com a ferramenta `remember`;
- Você vê tudo com `/memoria` e o arquivo pode ser editado à mão.

```
/memoria        # mostra a memória acumulada
```

## 🧠 Resumo automático de conversas longas

Modelos locais têm contexto limitado — por isso o SEND **resume sozinho**
conversas longas (16+ mensagens): o trecho antigo vira um resumo que continua
no contexto, sem perder as decisões importantes.

```
/resumo         # resume a conversa agora (e mostra o resumo atual)
```

A conversa nunca "estoura" o contexto: você pode conversar por horas.
Desligue com `/config auto_summarize false`.

## 💾 Backups automáticos (nunca perca um arquivo)

Antes de **escrever ou editar** qualquer arquivo, o SEND salva uma cópia em
`~/.send/backups/`:

```
/backups              # lista os backups (mais recentes primeiro)
/backups restore 1    # restaura o backup 1 (o mais recente)
```

Se uma edição der errado, o arquivo original volta em um comando.

## 📁 Contexto do projeto e estatísticas

- O SEND injeta no prompt a **árvore do projeto atual** (pastas e arquivos,
  ignorando `node_modules`, `.git` etc.) para entender com o que está
  trabalhando — desligue com `/contexto off`.
- Ao final de cada resposta, mostra o **tempo e o tamanho**:
  `⏱ 1.2s · ≈340 tokens`.
- Configure tudo com `/config` (temperatura, thinking, auto-resumo, etc.).

## ⭐ Criar novas skills (o SEND aprende habilidades novas)

Peça ao SEND para criar uma skill e ele salva um arquivo `.md` em
`~/.send/skills/` que **fica disponível para sempre** — nas próximas conversas
a skill vira uma ferramenta própria (`skill_<nome>`):

```
"crie uma skill para formatar código Python"
"crie uma skill que gera relatórios em markdown"
"crie uma skill para revisar meu código procurando bugs"
```

Cada skill criada aparece em `/skills` (⭐ Personalizadas), pode ser
ligada/desligada (`/skills <nome> off`) e é executada como uma ferramenta
quando você pedir. Formato do arquivo:

```markdown
# Skill: formatar
Descrição: formata código com 4 espaços
## Instruções
Sempre use 4 espaços de indentação e remova linhas em branco extras.
```

## 🧰 Skills — o que o SEND sabe fazer

O SEND tem **7 skills** que podem ser ligadas e desligadas individualmente
com `/skills`:

| Skill | O que faz | Ferramentas |
|---|---|---|
| **arquivos** | Lê, escreve, **edita**, lista e **procura** arquivos no PC | `read_file`, `write_file`, `edit_file`, `list_files`, `find_files` |
| **terminal** | Executa comandos no seu terminal | `run_command` |
| **internet** | **Pesquisa na web** e lê o conteúdo de páginas | `web_search`, `fetch_url` |
| **pc** | **Abre arquivos e links** no sistema e mostra **informações do PC** | `open_file`, `open_url`, `system_info` |
| **git** | Opera repositórios git | `git_status`, `git_log`, `git_diff`, `git_commit` |
| **processos** | Lista e encerra processos do sistema | `list_processes`, `kill_process` |
| **memoria** | Aprende com o tempo e cria novas skills | `read_memory`, `remember`, `create_skill` |

```bash
/skills                      # lista as skills ativas (nativas + criadas)
/skills internet off         # desliga a pesquisa na internet
/skills git on               # liga a skill do git
/skills on | /skills off     # liga/desliga todas
```

Exemplos de uso:

```bash
send "pesquise na internet o que é LM Studio"        # usa a skill internet
send "procure o arquivo config.py no projeto"        # usa find_files
send "mostre as informações do meu PC"               # usa system_info
send "edite o arquivo notas.txt trocando 'velho' por 'novo'"  # usa edit_file
send "abra o site do LM Studio no navegador"         # usa open_url
send "mostre o status do git e o log"                # usa a skill git
send "liste os processos pesados"                    # usa a skill processos
send "lembre que eu uso Pop!_OS"                     # grava na memória
```

> Dica: em modelos menores, desligar skills que não precisa deixa as
> respostas mais rápidas e evita chamadas de ferramentas desnecessárias.

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
send --workflow "crie um app de tarefas"        # 4 etapas: planejar→construir→verificar→corrigir
send --thinking "compare dois algoritmos de ordenação"
send "pesquise na internet sobre LM Studio"     # skill internet
send "mostre as informações do meu PC"          # skill pc
send "procure o arquivo config.py"              # skill arquivos
send "crie uma skill para revisar meu código"   # cria skill personalizada
send --models                           # lista os modelos do LM Studio
send --doctor                           # diagnostica a instalação
send --update                           # atualiza para a versão mais recente
send --install                          # mostra como instalar em outra máquina
```

### Comandos dentro do SEND — paleta `/`

Digite **`/`** e dê Enter: abre uma **paleta de comandos interativa**
(navegue com as setas ↑↓ ou digite o número, Enter executa, Esc fecha).
Também funciona o **Tab** para autocompletar comandos.

```
/help     /skills [nome] [on|off]   /memoria   /resumo   /clear   /exit
/model [nome]   /models   /thinking on|off   /backend [lmstudio|ollama|url]
/code     /chat   /plan   /workflow   /tools on|off
/status   /config [chave] [valor]   /save [arquivo]  /load arquivo
/backups [restore n]   /contexto [on|off]   /update   /doctor
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

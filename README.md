# ⚡ SEND — Assistente de IA no Terminal

Um CLI de IA no estilo **Claude Code / Gemini CLI**, que roda **100% local** e
grátis usando os modelos que você já instalou no
[LM Studio](https://lmstudio.ai/) (ou no [Ollama](https://ollama.com/)).
Funciona no **Linux (Pop!_OS, Ubuntu…)**, **Windows** e macOS.

Digite `send` no terminal e comece a conversar:

```bash
$ send
⚡ SEND v1.16.0 — assistente de IA no terminal (local ou na nuvem)

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

## 📱 SEND App — interface gráfica cross-platform

Digite `/app` dentro do SEND e ele abre uma **interface gráfica completa no navegador** — funciona em **Windows, Linux (Pop!_OS) e Mac**, sem instalar nada (só o navegador):

```
send        # terminal normal
/app        # abre http://127.0.0.1:8765 no navegador
```

- **Sidebar** com todas as Skills, Comandos e Providers clicáveis
- **Autocomplete dinâmico**: 34 comandos + fuzzy + subcomandos (`/provider` sugere providers reais)
- **Chat com IA** local ou nuvem, streaming, indicador animado
- **Quick actions**: /code, /chat, /plan, /workflow, /team, /memoria
- Código renderizado, histórico local com ↑↓
- Tema escuro moderno com acento ciano→roxo

Opções: `/app --port 8765 --no-browser` (porta customizada, não abre navegador).

## 🎨 Interface do terminal

- **Banner ASCII** com gradiente ciano→magenta + chips `[v1.16.0] [modelo] [modo]`
- **Markdown real**: h1 `▐ CAIXA-ALTA` ciano · h2 `▎Subtítulo` magenta · código inline com fundo sutil
- **Blocos de código arredondados** com chip `[python]]` colorido por linguagem e trilho lateral
- **Prompt com chip por modo**: 🛠 coding · 💬 chat · 📋 plano · 🔁 workflow (cores fixas)
- **Tool calls com duração**: `╰─ ✓ 0.8s primeira linha`
- **Workflow com progresso**: `[▰▰▱▱] 2/4`
- **Spinner com cronômetro** após 5s
- **Divisor em gradiente de pontos** entre respostas

> Tudo respeita `NO_COLOR` e cai para texto puro fora de terminal interativo.

## 🧠 Pensamento do modelo (minimizar / expandir)

Quando o modelo raciocina (ex.: DeepSeek R1, Qwen3 com `--thinking`), o SEND
mostra um indicador discreto enquanto pensa e, ao terminar, uma linha
**minimizada**:

```
🧠 Pensamento do modelo (3 linhas) — [Enter] expandir · [q] pular
```

- **Enter** (ou espaço/e) → expande o pensamento completo num painel roxo
- **q** → deixa minimizado
- A qualquer momento, **`/pensamento`** mostra o último pensamento expandido

## 💾 Código salvo direto no computador

Quando o modelo escreve código, o SEND pergunta se quer **salvar no disco**:

```
💾 Bloco de código (python) — salvar como 'app.py'? (s/N/caminho)
```

- **s** → salva com o nome sugerido (usa o nome da cerca ```python app.py```,
  senão um padrão por linguagem: `main.py`, `script.js`, `index.html`…)
- **digite um caminho** → salva onde você quiser
- Com **`-y`** ou **`--save-code`** → salva tudo automaticamente, sem perguntar
- Nomes repetidos viram `app_2.py`, `app_3.py`…

```bash
send --save-code "crie um script que ordene uma lista"   # salva sozinho
```

## 🔌 Providers de IA e configuração inicial

Na primeira execução interativa, o SEND pergunta qual provider você deseja usar.
A lista inclui **Ollama, LM Studio, Claude (Anthropic), OpenAI, NVIDIA NIM,
Google Gemini, Mistral AI, Groq, Cohere, Together AI, Perplexity, DeepSeek,
xAI (Grok), OpenRouter, Azure OpenAI, AWS Bedrock e Hugging Face Inference**.
Também é possível cadastrar qualquer provider customizado, informando nome,
endpoint, API key e paths próprios. Os formatos OpenAI-compatible e Anthropic
Messages são suportados; endpoints OpenAI-compatible funcionam sem adaptação.

A chave pode ser informada no assistente ou pela variável de ambiente indicada
pelo serviço, como `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
`NVIDIA_API_KEY`, `COHERE_API_KEY`, `TOGETHER_API_KEY`, `XAI_API_KEY` ou
`HF_TOKEN`. Variáveis de ambiente não são copiadas para o `config.json`.

Dois comandos ficam disponíveis durante toda a sessão, com ou sem `/`:

```text
provider                 # lista providers e mostra o atual
provider openai          # adiciona/ativa um preset
provider add             # cria um provider customizado
model                    # lista modelos do provider atual e permite escolher
model gpt-5              # troca diretamente pelo ID
```

> Se o provider já tem API key salva (`/provider nvidia` já configurado), o SEND mostra um menu: `1. Reescrever API key / 2. Excluir configuração / 3. Sair`.

### 🔐 Keyring opcional e política de comandos

- `/config use_keyring true` → guarda as API keys no **keyring do sistema** (o config.json guarda só o marcador `__keyring__`). O config.json recebe `chmod 600` automaticamente.
- `/config command_deny ["git push.*"]` → bloqueia comandos que casarem com o regex.
- `/config command_allow ["echo .*","ls .*"]` → se não-vazio, **só** esses comandos passam.

### 🔐 Permissões por projeto

Além da configuração global, cada projeto pode ter um `.send.json` na raiz,
versionável no Git. Ele restringe as ferramentas e comandos daquele projeto;
as regras locais nunca ampliam permissões globais e `deny` sempre vence.

```json
{
  "tool_allow": ["read_*", "list_files", "git_*"],
  "tool_deny": ["write_file", "delete_file", "mcp_*"],
  "command_allow": ["git status", "git diff.*"],
  "command_deny": ["git push.*"]
}
```

Use `/permissions` para ver as regras globais e as carregadas do projeto atual.

### ⚙️ Automação e CI/CD

Use `--print` para obter somente a resposta, sem banner ou elementos da interface.
Para integrações, `--output-format json` retorna um objeto parseável com status,
resposta, modelo e número de turnos; `stream-json` retorna o mesmo objeto como
um evento NDJSON final. `--max-turns` limita as iterações do agente.

```bash
send --print "explique este erro"
send --output-format json --max-turns 3 "revise este projeto"
send --print --output-format stream-json "liste riscos desta mudança"
```

### ⏰ Agendamentos e histórico pesquisável

O SEND pode guardar tarefas recorrentes localmente. No terminal interativo:

```text
/agendar add 60 revise os testes e gere um resumo
/agendar                         # lista as tarefas
/buscar autenticação              # busca nas conversas anteriores
```

Para executar tarefas vencidas, use um cron ou timer do sistema:

```bash
send --run-scheduled
# Exemplo de cron a cada 5 minutos:
# */5 * * * * /caminho/para/send --run-scheduled >> ~/.send/scheduled.log 2>&1
```

Por segurança, tarefas agendadas respeitam as permissões globais e do
`.send.json` do projeto; elas não ativam o `outmode` automaticamente.

### 🤖 /agentes — modelo por modo

Defina qual modelo cada modo usa — o SEND troca **sozinho** quando você alterna `/code`, `/chat`, `/plan` ou liga thinking:

```
/agentes                              # mostra a tabela atual
/agentes codigo qwen2.5-coder-7b      # coding usa esse modelo
/agentes chat gemma-3-4b              # chat usa outro
/agentes plano llama3.1               # plan usa outro
/agentes pensamento deepseek-r1       # usado quando --thinking on
/agentes codigo auto                  # volta ao modelo global
```

Só lista modelos dos providers que você já conectou. Prioridade: `pensamento` (thinking on) > modo atual > modelo global.

### 🔁 Retry/backoff automático

Erros HTTP 429/5xx ou queda de rede são retentados até 3 vezes com espera crescente (500ms → 1s → 2s) antes de mostrar erro. Configure com `/config api_max_retries N`.

### ↩ Retomar sessão

```bash
send --continue    # ou -C: retoma a conversa salva mais recente

### Paleta e autocomplete de comandos

Digite `/` e a **mini barra inline** aparece **abaixo do prompt** (tipo Claude Code) — continue digitando para filtrar (`/p` sugere `/provider`; `/m` sugere `/model`) sem sair da linha e sem apagar o histórico acima. Ela mostra até 6 sugestões por vez com `··· X abaixo/acima` e `✅` nos providers conectados, `↑/↓` navega, `Tab` completa, `Enter` seleciona. Subcomandos também funcionam: `/provider ` lista providers (`auto`, `openai`... com host e modelo), `/model ` lista modelos do provider atual (com cache), `/skills `, `/config `, `/team ` etc.
`/help` exibe a lista completa com uma descrição breve de cada comando.

**Extras da linha de digitação:** **Ctrl+R** busca no histórico das suas mensagens dentro da linha (↑↓ navega, Enter usa, Esc cancela); atalhos **1–6** pulam direto para uma sugestão; busca **fuzzy** (`/prv` já acha `/provider`).

## 🔄 Backend automático: LM Studio **ou** Ollama

A opção padrão continua totalmente automática: o SEND tenta o LM Studio
(`http://127.0.0.1:1234`) primeiro; se não estiver rodando, **detecta sozinho o
Ollama** (`http://127.0.0.1:11434`) e avisa. Nenhuma chave ou configuração é
necessária para esses providers locais.
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
tempo** (limitada a ~2200 chars com poda automática e lembrete a cada 10 turnos):

- Toda conversa começa com a memória resumida no contexto do modelo;
- Quando o SEND descobre algo útil (suas preferências, decisões do projeto,
  bugs corrigidos), ele **grava sozinho** com a ferramenta `remember`;
- Você vê tudo com `/memoria` e o arquivo pode ser editado à mão.

```
/memoria        # mostra a memória acumulada
```

## 🧠 Resumo automático de conversas longas

Modelos locais têm contexto limitado — por isso o SEND **resume sozinho**
conversas longas (16+ mensagens **ou** ~20k tokens, com poda proativa de tool results grandes): o trecho antigo vira um resumo que continua
no contexto, sem perder as decisões importantes. Limite configurável com `compression_threshold_tokens`.

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

## 🤝 Subagentes — delegação de tarefas especializadas

O SEND tem **subagentes**: agentes menores com papel, instruções e
ferramentas próprias que recebem tarefas delegadas e devolvem o resultado.

Vêm 3 prontos (criados na primeira execução em `~/.send/subagents/`):

| Subagente | O que faz | Ferramentas |
|---|---|---|
| **revisor** | revisa código procurando bugs, falhas de segurança e melhorias | `read_file`, `list_files`, `find_files` |
| **pesquisador** | pesquisa na internet e reúne informações com fontes | `web_search`, `fetch_url` |
| **analista** | separa problemas complexos em partes e propõe soluções | `read_file`, `list_files`, `find_files` |

O agente principal **delega sozinho** quando a tarefa é extensa ou
repetitiva (ferramenta `delegate`), ou você delega na mão:

```
/subagentes                      # lista os subagentes
/subagentes revisor revise este código   # roda um subagente direto
"crie um subagente que revisa meu código"  # cria um novo (ferramenta create_subagent)
```

Cada subagente é um arquivo `.md` editável — dê novas instruções, troque as
ferramentas (`Ferramentas: read_file, list_files`), ou use `nenhuma` para
subagentes só de conversa e `todas` para liberar as mesmas do principal:

```markdown
# Subagente: revisor
Descrição: revisa código procurando bugs e melhorias
Ferramentas: read_file, list_files, find_files
## Instruções
Você é um revisor experiente. Leia os arquivos, liste problemas numerados…
```

> 🔒 Por padrão os subagentes usam **ferramentas seguras** (leitura, busca,
> internet) e nunca perguntam antes de usá-las — só dê `run_command` a um
> subagente se você confia nele.

## 👥 Equipe de IAs — 2+ subagentes colaborando

Use `team` para colocar 2+ IAs trabalhando **juntas em paralelo** e o SEND sintetiza o melhor de cada uma. Grátis por padrão (mesmo modelo local com papéis diferentes) ou modelos diferentes por agente (`nome@model` ou `nome:provider/model`):

```
/team revisor,pesquisador crie uma API de tarefas
/team revisor@qwen2.5-coder-7b,pesquisador:openai/gpt-4o analise este código --estrategia debate
```

Estratégias: `paralelo` (padrão, todos juntos), `debate` (um propõe, outro critica) e `sequencial` (um após o outro vendo o anterior). Também funciona pedindo ao SEND: `"use a equipe revisor+pesquisador em paralelo"`.

## 🔌 MCP — ferramentas de servidores externos

O SEND fala o **Model Context Protocol** (MCP) via stdio: você conecta
servidores externos e as ferramentas deles viram ferramentas do SEND
automaticamente (`mcp_<servidor>_<ferramenta>`).

Configure em `~/.send/mcp.json`:

```json
{
  "servers": {
    "arquivos": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/"]
    },
    "busca": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"]
    }
  }
}
```

Comandos:

```
/mcp               # mostra os servidores conectados e quantas ferramentas
/mcp reload        # reconecta depois de editar o mcp.json
/mcp arquivos      # lista as ferramentas de um servidor
/config mcp_enabled false   # desliga o MCP sem apagar a config
```

> Requisito: o servidor MCP precisa estar instalado na máquina (ex.:
> `npm install -g @modelcontextprotocol/server-filesystem`). O SEND usa o
> transporte **stdio** (JSON-RPC 2.0) — servidores que só falam HTTP
> streamable ainda não são suportados. No Windows, use `npx.cmd` em
> `command` se `npx` não for encontrado.

## 🪝 Hooks — comandos automáticos em eventos

O SEND pode rodar comandos do seu sistema em eventos da sessão
(`~/.send/hooks.json`):

```json
{
  "SessionStart": ["notify-send 'SEND iniciou'"],
  "PreToolUse": ["echo \"$SEND_TOOL $SEND_ARGS\" >> ~/.send/hooks.log"],
  "PostToolUse": ["echo \"$SEND_RESULT\" >> ~/.send/hooks.log"],
  "SessionEnd": ["notify-send 'SEND encerrou'"]
}
```

Variáveis disponíveis: `SEND_EVENT`, `SEND_TOOL`, `SEND_ARGS`,
`SEND_RESULT`, `SEND_PROMPT`. Desligue com `/config hooks false`.

## 🌿 Worktree isolado por sessão

Cada sessão pode rodar em um `git worktree` separado para não colidir arquivos quando 2 agentes trabalham no mesmo repo:

```
/worktree on     # liga — cria worktree em ~/.send/worktrees/sess-... a partir do remote tip
/worktree off    # desliga — volta ao diretório atual
```

Desligado por padrão (`worktree_sync` controla se branch vem do `origin/HEAD` ou do `HEAD` local).

## 🛡️ Scan de segurança local

Antes de executar comandos no terminal, o SEND escaneia localmente (sem API) `pipe-to-shell` (`curl | bash`), `rm -rf /` e homograph, e avisa. Desative com `/config security_scan false`.

## 🧰 Skills — o que o SEND sabe fazer

O SEND tem **8 skills** que podem ser ligadas e desligadas individualmente
com `/skills`:

| Skill | O que faz | Ferramentas |
|---|---|---|
| **arquivos** | Lê, escreve, **edita**, lista, procura, cria/move/copiar/deleta arquivos, stats, grep em conteúdo e lê PDFs | `read_file`, `write_file`, `edit_file`, `list_files`, `find_files`, `create_directory`, `move_file`, `copy_file`, `delete_file`, `file_stats`, `grep`, `read_pdf` |
| **terminal** | Executa comandos, snippets Python e gerencia variáveis de ambiente da sessão | `run_command`, `run_python`, `get_env`, `set_env` |
| **internet** | **Pesquisa na web** e lê o conteúdo de páginas | `web_search`, `fetch_url` |
| **pc** | **Abre arquivos e links** no sistema, **navega no browser** e mostra **informações do PC** | `open_file`, `open_url`, `browser_open`, `system_info` |
| **git** | Opera repositórios git | `git_status`, `git_log`, `git_diff`, `git_commit` |
| **processos** | Lista e encerra processos do sistema | `list_processes`, `kill_process` |
| **memoria** | Aprende com o tempo e cria novas skills | `read_memory`, `remember`, `create_skill` |
| **subagentes** | Delega tarefas a subagentes, cria novos e monta **equipes de 2+ IAs** | `delegate`, `create_subagent`, `team` |

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

## 🤖 Modo automático — o SEND escolhe o modo sozinho

**Ligado por padrão.** Você não precisa alternar entre chat, coding, plan e
workflow: o SEND analisa cada tarefa e decide sozinho:

| Sua mensagem | O SEND usa |
|---|---|
| `oi`, `o que é um decorator?` | 💬 **chat** — só conversa |
| `procure o arquivo config.py` | 🛠 **coding** — arquivos + terminal |
| `planeje a refatoração do projeto` | 📋 **plan** — planeja sem executar |
| `crie um app de tarefas completo` | 🔁 **workflow** — as 4 etapas |

Você vê a escolha na hora (`↳ modo automático: 🛠 CODING …`). Se quiser forçar
um modo, use `/code`, `/chat`, `/plan`, `/workflow` (ou as flags `--code`,
`--plan`…) — o modo escolhido passa a valer. Para desligar a escolha
automática:

```
/automode on|off        # ou: send --auto-mode / send --no-auto-mode
```

Além disso, o SEND **despacha subagentes automaticamente**: tarefas extensas
ou repetitivas são delegadas sozinhas (revisor, pesquisador, analista…) com a
ferramenta `delegate` — sem você precisar pedir.

## 🔥 OUTMODE — o SEND age sem pedir autorização

O OUTMODE é o modo "manda ver": o SEND **não pergunta nada** — escreve,
edita, executa comandos, faz commit e salva código **direto**, sem pedir sua
confirmação. Só ligue se confiar (é você quem decide):

```
/outmode on     # 🔥 ligado — age sem pedir autorização
/outmode off    # 🔒 desligado — volta a pedir (padrão)
```

Com o OUTMODE ligado o prompt fica com um 🔥 e ele também salva os blocos de
código sem perguntar. Em uma execução única:

```bash
send --outmode "crie um script e rode os testes"
```

> ⚠️ Use com cuidado: comandos que ele executar rodam de verdade no seu PC.

## 🧠 Modos de uso (quando o automático está desligado)

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
send "delegue a revisão do código ao subagente revisor"   # delega a um subagente
send "/team revisor,pesquisador crie uma API de tarefas"  # equipe de 2+ IAs em paralelo
send --continue                         # retoma a última conversa salva
send /app                               # abre a interface gráfica no navegador
send --models                           # lista os modelos do LM Studio
send --doctor                           # diagnostica a instalação
send --update                           # atualiza para a versão mais recente
send --install                          # mostra como instalar em outra máquina
```

### Comandos dentro do SEND — paleta `/`

Digite **`/`** e dê Enter: abre uma **paleta de comandos interativa** com
busca — digite para filtrar (ex.: `mcp` mostra só o `/mcp`), navegue com as
setas ↑↓ (ou 1-9), Enter executa, Esc/q fecha. Também funciona o **Tab** para
autocompletar comandos.

```
/help     /skills [nome] [on|off]   /memoria   /resumo   /pensamento   /clear   /exit
/provider [nome|add]   /model [nome]   /models   /thinking on|off
/backend [lmstudio|ollama|url]
/code     /chat   /plan   /workflow   /tools on|off
/automode [on|off]   /outmode [on|off]
/status   /config [chave] [valor]   /save [arquivo]  /load arquivo
/backups [restore n]   /contexto [on|off]   /subagentes [nome] [tarefa]   /team <agentes> <tarefa>
/worktree [on|off]   /agentes [modo] [modelo]   /app [--port N] [--no-browser]
/mcp [nome|reload]   /hooks   /update   /doctor
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
- Configuração e histórico ficam em `~/.send/` (`config.json` com permissão `600`, `history.jsonl`).
- `/app` serve uma interface gráfica local via HTTP (`127.0.0.1`) — sem npm/Electron.
- Segurança: scan local antes de executar comandos, bloqueio SSRF em fetch_url, aviso de caminho fora do projeto, allowlist/denylist de comandos.
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

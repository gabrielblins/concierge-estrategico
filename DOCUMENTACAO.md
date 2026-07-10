# Concierge Estratégico — Documentação do Projeto

> Um bot de Telegram que transforma as conversas de uma equipe de startup em uma
> **base estratégica viva**: mantém o Business Model Canvas atualizado
> automaticamente, alerta quando a equipe contradiz decisões validadas,
> **participa da conversa como um colega**, aprende com os **materiais de
> referência da equipe** e mostra tudo num **Mini App visual** dentro do
> próprio Telegram.

---

## 1. Visão geral

### O problema

No começo de um projeto de inovação, as equipes usam frameworks estratégicos —
**Business Model Canvas**, Canvas de Hipóteses, Design Thinking — para
organizar premissas, propostas de valor e riscos. Essas ferramentas são ótimas
no arranque, mas têm um problema crônico: **ninguém as mantém atualizadas.**

Com o tempo, a equipe continua decidindo e mudando de direção — só que isso
acontece **nas conversas do dia a dia**, enquanto os canvas congelam no
passado. O resultado: decisões tomadas sobre hipóteses já superadas,
retrabalho e perda de foco.

### A solução

Um bot de Telegram que **vive dentro do grupo da equipe** e:

1. **Registra e estrutura** — extrai das mensagens os itens estratégicos
   (decisões, hipóteses, premissas, riscos, tarefas, aprendizados) e gerencia
   o ciclo de vida deles (ativo → validado → descartado/superado).
2. **Mantém o canvas vivo** — reconstrói o Business Model Canvas a partir
   dos itens que valem *agora*.
3. **Guarda a coerência** — quando alguém propõe algo que contradiz uma
   decisão validada, intervém com um alerta fundamentado.
4. **Participa como colega** — responde quando mencionado e, raramente e com
   critério, contribui espontaneamente: conecta ideias a decisões passadas,
   traz conhecimento dos materiais, faz perguntas socráticas, sintetiza
   discussões longas.
5. **Aprende com os materiais da equipe** — livros, manuais e frameworks
   enviados por `/upload` são classificados automaticamente e passam a
   fundamentar as análises de cada módulo.
6. **Fala na voz que a equipe escolher** — mentor direto, coach, conselheiro
   zen, consultor formal, ou uma personalidade descrita livremente.
7. **Mostra o canvas de verdade** — `/canvas` abre um Mini App dentro do
   Telegram com a grade visual do BMC e drill-down nos itens.

Tudo com **consentimento e transparência**: só age após `/start`, avisa que
monitora, explica cada alerta (`/why`) e apaga tudo sob demanda (`/forget`).

**Frase-síntese:** *transforma conversas de Telegram em uma base estratégica
viva — e devolve essa base à equipe como um colega que lembra, questiona e
mostra o caminho.*

---

## 2. Principais features

| Feature | O que faz |
|---|---|
| **Extração automática** | Mensagens → itens estratégicos tipados (decisão, hipótese, premissa, risco, tarefa, aprendizado) via LLM. |
| **Ciclo de vida dos itens** | Reconciliação automática: itens são promovidos a `validated` ou marcados `discarded`/`superseded` conforme a equipe evolui. |
| **Canvas vivo** | Os 9 blocos do BMC re-sintetizados a partir dos itens ativos + validados. |
| **Guardião de coerência** | Detecta contradições com o que foi validado/descartado; alerta só com confiança ≥ 0.75; pré-filtro barato evita custo em conversa trivial. |
| **Participante de conversa** | Responde menções como colega (com toda a base + materiais como contexto). Contribuições espontâneas passam por 3 portões: cooldown, pré-filtro, relevância autoavaliada. Guardião tem prioridade — 1 voz por mensagem. |
| **Materiais tipados (RAG)** | `/upload` de PDF/TXT/MD/DOCX ou texto colado; o LLM classifica (guia de canvas, guia de validação, metodologia, framework próprio, geral) e cada tipo alimenta só os módulos certos. `/materials` lista o catálogo. |
| **Personalidade** | `/personality` com presets (mentor, coach, zen, formal) ou descrição livre. Alertas do guardião e falas do participante já nascem na voz (injeção de prompt, custo zero); respostas de comandos são reescritas com fallback seguro. |
| **Canvas Mini App** | `/canvas` posta um botão que abre a grade visual do BMC dentro do Telegram (mobile e desktop), com drill-down nos itens. Servidor separado, initData validado por HMAC. |
| **Dois provedores de LLM** | OpenAI ou Google Gemini via `LLM_PROVIDER` — zero mudança de código. |
| **Transparência & consentimento** | `/start` ativa e avisa; `/why` explica alertas; `/forget` apaga SQLite **e** vetores; comandos exigem ativação prévia. |

---

## 3. Como funciona — os três caminhos de fala

Cada mensagem do grupo percorre um funil que decide **se e como** o bot fala.
No máximo **uma voz por mensagem**:

```
mensagem chega
   │
   ├─ é MENÇÃO (@bot ou reply ao bot)?
   │    └─ sim → PARTICIPANTE responde como colega
   │             (conversa recente + base estratégica + materiais + voz)
   │
   └─ não → GUARDIÃO avalia coerência
        │     pré-filtro barato (sem LLM) → contradiz item validado?
        │     confiança ≥ 0.75 → ⚠️ alerta fundamentado
        │
        └─ guardião calou → PARTICIPANTE espontâneo (raro)
              portão 1: habilitado? modo ≠ silent? cooldown ≥ 10 msgs?
              portão 2: mensagem substantiva? (sem LLM)
              portão 3: LLM decide-e-gera; só posta se relevância ≥ 0.75
              tipos: conexão · conhecimento · pergunta · síntese

em paralelo (lote): a cada BATCH_SIZE mensagens (ou /sync)
   extrai itens → reconcilia status → re-sintetiza o canvas
```

**Custo em regime:** mensagem trivial = 0 chamadas de LLM; no pior caso,
1 chamada de "voz" (guardião OU participante) por mensagem + o sync em lote.

---

## 4. Arquitetura

```
                     Telegram (grupo)
                       │           │ /canvas → link direto do Mini App
                       ▼           ▼
┌────────────────────────────┐   ┌──────────────────────────────┐
│  Bot (concierge.main)      │   │  Mini App (concierge.webapp) │
│  handlers puros + glue     │   │  FastAPI · initData HMAC     │
└────────────┬───────────────┘   │  grade BMC + drill-down      │
             ▼                   └──────────────┬───────────────┘
┌────────────────────────────┐                  │ só leitura
│  Orchestrator              │                  │
│  menção/guardião/partici-  │                  │
│  pante/sync (o funil §3)   │                  │
└─┬────┬────┬────┬────┬──────┘                  │
  ▼    ▼    ▼    ▼    ▼                         │
Extract Recon Canvas Guard Participant          │
  or    ciler Updater ian   + Stylist           │
  └──────┴─────┬┴──────┴──────┘                 │
               ▼                                │
     ┌──────────────────┐   ┌───────────────┐  │
     │ Google ADK       │   │ MaterialService│ │
     │ (LlmAgents│Runner)│   │ parse+classify │ │
     └──────────────────┘   └───────┬───────┘  │
               │                    ▼           │
               ▼            ┌──────────────┐   │
     ┌──────────────────┐   │ ChromaDB     │   │
     │ SQLite (WAL) ◄───┼───┤ RAG tipado   │   │
     │ base estratégica │◄──┘              │   │
     └──────────▲───────┘   └──────────────┘   │
                └───────────────────────────────┘
```

### Componentes (um arquivo, uma responsabilidade)

| Componente | Arquivo | Responsabilidade |
|---|---|---|
| Bot Layer | `bot.py` | Handlers puros + glue do Telegram. Zero lógica de negócio. |
| Orchestrator | `orchestrator.py` | O funil do §3: menção, guardião, participante, sync com RAG tipado por módulo. |
| Extractor | `extractor.py` | Lote de mensagens → itens estratégicos. |
| Reconciler | `reconciler.py` | Transições de status (valida/supera itens) — o que torna a base *viva*. |
| Canvas Updater | `updater.py` | Itens vivos → blocos do BMC. |
| Guardian | `guardian.py` | Pré-filtro barato + verdicto de contradição (com a voz injetada). |
| Participant | `participant.py` | `consider` (decide-e-gera espontâneo) e `respond` (menções). |
| Stylist | `stylist.py` | Presets de personalidade + reescrita fail-safe de respostas. |
| MaterialService | `materials.py` | Parsers (PDF/DOCX/TXT/MD), classificação LLM, tabela de roteamento tipo→módulos. |
| Knowledge Base | `knowledge.py` | ChromaDB: chunks com metadata de tipo, consultas filtradas. |
| Storage | `storage.py` | SQLite (WAL) — fonte da verdade, com migrações automáticas. |
| Agent Framework | `agents/` | Google ADK: `model_factory.py` (modelo por provedor), `definitions.py` (`LlmAgents` por papel), `executor.py` (`AgentExecutor`), `funnel.py` (`MessageFunnelAgent` determinístico). |
| Web App | `webapp/` | FastAPI: `auth.py` (HMAC do initData), `server.py` (API read-only), `static/index.html` (grade). |

### A camada de agentes (Google ADK)

Toda a lógica fala com **uma interface**: `AgentExecutor.run_validated(agent,
user_text, schema) -> dict | None`. Cada `LlmAgent` é montado por
`definitions.build_agents(model)`; a saída passa por validação Pydantic com
retry-uma-vez-e-descarta (**nunca grava lixo**). Trocar OpenAI ↔ Gemini
continua sendo uma variável de ambiente (`LLM_PROVIDER`): `openai` roteia via
LiteLLM, `gemini` usa o suporte nativo do ADK.

---

## 5. A base estratégica viva (modelo de dados)

**`strategic_items` é a fonte da verdade; o canvas é uma projeção.**

| Tabela | Para quê |
|---|---|
| `projects` | Um por grupo: `mode`, `personality`, marcador de cooldown do participante. |
| `messages` | Buffer bruto (idempotente por `telegram_msg_id`). |
| `strategic_items` | Decisões/hipóteses/etc. com `status`, origem e linhagem (`superseded_by`). |
| `canvas_blocks` | Os 9 blocos — projeção dos itens `active`+`validated`. |
| `interventions` | Log de alertas do guardião (alimenta `/why`). |
| `knowledge_docs` | Catálogo dos materiais com `material_type`. |

```
extraído → [active] ──reconciler──► [validated]
              │                          │ sustenta canvas + guardião
              ▼                          ▼
         [discarded]              alguém contradiz → ⚠️ alerta
              ▲
   substituído → [superseded]
```

- O **canvas** projeta `active` + `validated`; o **guardião** defende
  `validated` + `discarded` ("esse caminho já foi descartado").
- Nada se apaga de fato (exceto `/forget`) — a linhagem preserva o histórico.

### Roteamento de materiais (o "incremental")

| Tipo detectado | Alimenta | Capacidade destravada |
|---|---|---|
| guia de canvas | Updater, Participante | canvas segue o manual |
| guia de validação | Guardião, Reconciler, Participante | cobra experimentos |
| metodologia | Extractor, Guardião, Participante | análises com os conceitos |
| framework próprio | todos | lente de tudo |
| geral | Guardião, Participante | contexto geral |

---

## 6. Comandos e interações

| Comando | Efeito |
|---|---|
| `/start` | Ativa no grupo + aviso de monitoramento (consentimento) |
| `/sync` | Força a atualização do canvas agora |
| `/status` | Canvas atual em texto (na voz configurada) |
| `/canvas` | Botão que abre o **Mini App visual** do canvas |
| `/upload` | (arquivo com legenda, reply a arquivo, ou texto colado) adiciona material |
| `/materials` | Lista materiais e capacidades destravadas |
| `/personality` | Define a voz (presets ou texto livre; `reset` limpa) |
| `/why` | Explica o último alerta (motivo + confiança) |
| `/forget` | Apaga tudo: SQLite + vetores |
| **@menção / reply** | O participante responde como colega |

Comandos de consulta/gestão exigem `/start` antes.

---

## 7. Decisões técnicas

| Decisão | Escolha | Motivo |
|---|---|---|
| Linguagem | Python 3.14 | Ecossistema de bots e LLM |
| Bot | `python-telegram-bot` 22.x | Long-polling, retry embutido |
| Agentes | Google ADK (`google-adk==2.3.0`) — `LlmAgents` + `Runner` + `AgentExecutor` + `MessageFunnelAgent` determinístico | Framework padrão para orquestração de agentes, com retry/validação embutidos |
| LLM | OpenAI **ou** Gemini | `LLM_PROVIDER` — flexibilidade total (OpenAI via `litellm==1.83.7`, Gemini nativo no ADK) |
| Estado | SQLite em **WAL** | Zero-config + leitura concorrente pelo webapp |
| RAG | ChromaDB com metadata | Consultas filtradas por tipo de material |
| Web | FastAPI + página única sem framework | Leve, testável com TestClient |
| Validação LLM | Pydantic via `AgentExecutor.run_validated` | Retry-uma-vez-e-descarta em todo lugar |
| Mini App em grupos | **Link direto** (`t.me/bot/app?startapp=`) | Botões `web_app` não funcionam em grupos; o `chat_id` chega **assinado** no `initData` |

### Segurança e resiliência

- **Mini App:** todo dado exige `initData` com HMAC válido (chave derivada do
  token do bot), janela de 1h contra replay, servidor só-leitura. Fallback de
  `initData` para clientes Desktop (hash/sessionStorage) e `no-store` na página.
- **Falha de LLM em qualquer caminho de fala → silêncio** (nunca posta erro).
- **Idempotência** por `telegram_msg_id`; migrações automáticas de schema.
- **Custo:** pré-filtros sem LLM + lote + limiares + cooldown do participante.

### Config (env)

`LLM_PROVIDER` · `OPENAI_API_KEY/MODEL` · `GEMINI_API_KEY/MODEL` ·
`BATCH_SIZE` (15) · `CONFIDENCE_THRESHOLD` (0.75) ·
`PARTICIPATION_ENABLED/COOLDOWN/THRESHOLD` (true/10/0.75) ·
`WEBAPP_APP_NAME/PORT` — detalhes no [SETUP.md](SETUP.md).

### Qualidade

- **133 testes**, todos sem rede (`FakeAdkModel`/executor fake para os agentes,
  Chroma efêmero, SQLite em memória, TestClient), construídos com TDD.
- ~1.800 linhas em **25 módulos** pequenos e focados.
- Cada feature passou por review por tarefa + review final de branch — o
  processo pegou, antes do merge: um bug de cooldown com espaços de id
  distintos, uma regressão na janela de segurança do initData e respostas com
  JSON cru.

---

## 8. Como rodar (resumo)

```bash
# 1) bot
source .venv/bin/activate && set -a; source .env; set +a
PYTHONPATH=src python -m concierge.main

# 2) canvas visual (opcional)
PYTHONPATH=src python -m concierge.webapp
cloudflared tunnel --url http://localhost:8080
# registre no @BotFather (/newapp) e defina WEBAPP_APP_NAME
```

Guia completo (BotFather, privacy mode, roteiro de demo): **[SETUP.md](SETUP.md)**.

---

## 9. Roadmap

- Verificação de *membership* do chat no Mini App (`getChatMember` por requisição).
- `textContent` no drill-down (hardening XSS do conteúdo LLM).
- Atribuição precisa da mensagem-origem por item (`/why` cirúrgico).
- `source_items` populado por bloco (drill-down por bloco, não geral).
- Aprendizado de preferência do participante ("fale menos/mais").
- Múltiplos frameworks além do BMC.

---

## 10. Mapa do código

```
src/concierge/
├── bot.py            # handlers do Telegram + funil de mensagem
├── orchestrator.py   # menção · guardião · participante · sync
├── extractor.py      # mensagens → itens
├── reconciler.py     # ciclo de vida dos itens
├── updater.py        # itens → canvas
├── guardian.py       # coerência (pré-filtro + verdicto)
├── participant.py    # colega de conversa (consider/respond)
├── stylist.py        # personalidade (presets + restyle)
├── materials.py      # parsers + classificação + roteamento
├── knowledge.py      # RAG tipado (ChromaDB)
├── storage.py        # SQLite WAL (fonte da verdade)
├── canvas.py · models.py · config.py · main.py
├── agents/           # Google ADK: model_factory + definitions + executor + funnel
└── webapp/           # Mini App: auth HMAC + API + página BMC
```

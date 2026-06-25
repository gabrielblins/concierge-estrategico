# Strategic Concierge Bot — Design

**Data:** 2026-06-25
**Contexto:** Projeto de hackathon. Bot concierge inteligente para acompanhamento estratégico de startups e projetos de inovação, integrado ao Telegram.

---

## 1. Problema e Proposta

Empreendedores usam frameworks estratégicos (Business Model Canvas, Canvas de Hipóteses, Design Thinking, etc.) no início de um projeto, mas raramente mantêm esses materiais atualizados. Com o tempo, as decisões continuam sendo tomadas nas conversas da equipe, enquanto os documentos estratégicos ficam desatualizados — levando a decisões baseadas em hipóteses já superadas.

A proposta é um **bot de Telegram** que:

1. **Acompanha as conversas** do grupo e extrai itens estratégicos (decisões, hipóteses, premissas, riscos, tarefas, aprendizados).
2. **Atualiza automaticamente** os frameworks/canvas do projeto a partir desses itens.
3. **Atua como guardião da coerência**, intervindo quando a equipe contradiz hipóteses validadas, retoma caminhos descartados ou ignora premissas.
4. **Usa uma base de conhecimento personalizada** (livros, manuais, frameworks) para fundamentar suas análises no método de trabalho da própria equipe.
5. **É transparente por design** — explica por que interveio (`/why`) e permite remoção de dados (`/forget`).

Frase-síntese: *transforma conversas de Telegram em uma base estratégica viva, mantendo canvas, hipóteses, premissas e decisões sempre atualizadas, e alertando a equipe quando as discussões se afastam da estratégia definida.*

---

## 2. Decisões Técnicas

| Decisão | Escolha | Motivo |
|---|---|---|
| Linguagem | Python | Ecossistema maduro de bots e LLM |
| Bot framework | `python-telegram-bot` | Retry/backoff embutido, long-polling simples |
| LLM | OpenAI / GPT (saída JSON estruturada) | Preferência do usuário; bom para raciocínio estratégico |
| Estado estratégico | SQLite | Zero-config, simples, suficiente para o escopo |
| RAG (base de conhecimento) | Vector store (ChromaDB) | Busca semântica nos materiais de referência |
| Validação de saída LLM | Pydantic | Garante que nada malformado entre no banco |
| Modo de operação | Híbrido (passivo em lote + ativo seletivo) | Equilibra ruído, custo e valor |
| Framework estratégico inicial | Business Model Canvas | Um framework no MVP; arquitetura permite outros |

---

## 3. Arquitetura

```
Telegram (grupo)
      │  long-polling
      ▼
┌─────────────────────────────────────────────┐
│  Bot Layer (python-telegram-bot)            │
│  - recebe mensagens, comandos               │
│  - envia alertas e respostas                │
│  - SEM lógica de negócio                    │
└───────────────┬─────────────────────────────┘
                ▼
┌─────────────────────────────────────────────┐
│  Orchestrator (core)                        │
│  decide: enfileirar? sincronizar? checar?   │
└──┬──────────────┬───────────────┬───────────┘
   ▼              ▼               ▼
┌────────┐  ┌────────────┐  ┌──────────────┐
│Extractor│ │Canvas       │ │Coherence     │
│(GPT)    │ │Updater (GPT)│ │Guardian (GPT)│
└────┬────┘  └─────┬──────┘  └──────┬───────┘
     │             │                │
     ▼             ▼                ▼
┌─────────────────────────────────────────────┐
│  Storage Layer                              │
│  SQLite (estado) + ChromaDB (RAG)           │
└─────────────────────────────────────────────┘
```

### Componentes (isolados e testáveis)

1. **Bot Layer** — interface com Telegram. Apenas I/O de mensagens e comandos. Sem lógica de negócio.
2. **Orchestrator** — roteamento do modo híbrido. Decide se a mensagem só vai pra fila, dispara sync em lote, ou aciona o guardião.
3. **Extractor** — recebe um lote de mensagens, retorna itens estruturados (JSON validado por Pydantic).
4. **Canvas Updater** — pega itens extraídos + estado atual e re-sintetiza os blocos afetados do canvas.
5. **Coherence Guardian** — compara mensagens/decisões novas contra o estado validado/descartado e detecta contradições com score de confiança.
6. **Knowledge Base (RAG)** — materiais de referência em vector store, consultados pelo Guardian e pelo Updater.
7. **Storage** — SQLite (estado) + ChromaDB (embeddings).
8. **LLMClient** — interface única para chamadas ao GPT. Permite *fake* nos testes.

---

## 4. Modelo de Dados (SQLite)

Princípio central: tudo que a equipe define vira um **registro estratégico versionado e rastreável**. Cada item carrega sua origem (mensagem que o gerou) — isso alimenta o `/why`.

```
projects
  id, telegram_chat_id, name, framework_type, created_at, mode
  -- mode: 'silent' | 'moderate' | 'active' (default 'moderate')

messages
  id, project_id, telegram_msg_id (único), author, text, ts, processed
  -- buffer bruto; 'processed' marca o que já virou item

strategic_items
  id, project_id, type, content, status, confidence,
  source_message_id, created_at, updated_at, superseded_by
  -- type:   'decision' | 'hypothesis' | 'premise' | 'risk' | 'task' | 'learning'
  -- status: 'active' | 'validated' | 'discarded' | 'superseded'
  -- source_message_id → alimenta o /why
  -- superseded_by → item que substituiu este (histórico vivo)

canvas_blocks
  id, project_id, block_name, content, updated_at, source_items (json)
  -- block_name (BMC): 'value_proposition', 'customer_segments',
  --   'channels', 'customer_relationships', 'revenue_streams',
  --   'key_resources', 'key_activities', 'key_partnerships', 'cost_structure'
  -- content: texto sintetizado do bloco
  -- source_items: ids dos strategic_items que sustentam o bloco

interventions
  id, project_id, message_id, item_id, reason, confidence, sent_at
  -- log de cada alerta do Guardian → alimenta /why e auditoria

knowledge_docs
  id, project_id, filename, uploaded_at, chunk_count
  -- metadados; chunks/embeddings vivem no vector store
```

### Decisões de modelagem

- **`strategic_items` é a fonte da verdade.** O canvas é uma *projeção* desses itens. Quando uma hipótese muda de status, o bloco dependente é re-sintetizado.
- **Nada é deletado de fato.** Itens descartados/substituídos viram `status='discarded'` ou `'superseded'`. É isso que permite o Guardian dizer *"esse caminho já foi descartado por causa da premissa X"*.
- **`source_message_id` em tudo.** Toda afirmação rastreia sua origem — sem isso, `/why` e a transparência não funcionam.
- **`mode` por projeto.** Permite silenciar um grupo sem mudar código.

---

## 5. Fluxo de Dados e Modo Híbrido

### Caminho passivo (atualização do canvas) — em lote

```
1. Cada mensagem → salva em `messages` (processed=false)
2. Gatilho de sync dispara quando:
   - acumulam N mensagens não processadas (default N=15), OU
   - alguém roda /sync manualmente, OU
   - passam X minutos desde o último sync com mensagens pendentes
3. Extractor recebe o lote → itens estruturados (JSON validado)
4. Itens novos entram em strategic_items; itens que contradizem/
   atualizam itens antigos marcam o anterior como 'superseded'
5. Canvas Updater re-sintetiza apenas os blocos afetados
6. Mensagens marcadas processed=true
```

### Caminho ativo (guardião de coerência) — por mensagem, seletivo

```
1. A cada mensagem nova, Orchestrator faz um pré-filtro BARATO
   (heurística + classificação leve): "isso parece decisão,
   proposta ou direcionamento?" Se não, ignora — economiza API.
2. Se sim → Coherence Guardian:
   - busca itens 'validated'/'discarded' relevantes (SQLite)
   - busca contexto de método na base de conhecimento (RAG)
   - pergunta ao GPT: há contradição? com qual item? confiança 0-1?
3. Se confiança ≥ limiar (default 0.75) E modo ≠ 'silent' → envia
   alerta e registra em `interventions`
4. Senão → silêncio (pode logar para auditoria)
```

### Controle de ruído e custo

- **Pré-filtro barato:** a maioria das mensagens ("ok", "concordo") nunca chega ao GPT caro.
- **Limiar de confiança:** evita alertas em cima de ambiguidade. Melhor calar do que irritar.
- **Sync em lote:** corta drasticamente as chamadas de API vs. reprocessar o canvas a cada mensagem.

### Comandos do bot

| Comando | Ação |
|---|---|
| `/start` | Ativa o bot no grupo + aviso de monitoramento (consentimento) |
| `/sync` | Força atualização do canvas agora |
| `/status` | Mostra o estado atual do canvas / itens principais |
| `/check` | Roda checagem de coerência sob demanda |
| `/why` | Explica a última intervenção (item + mensagem de origem) |
| `/forget` | Remove dados do projeto (transparência) |
| `/upload` | (respondendo a um arquivo) adiciona material à base de conhecimento |

---

## 6. Privacidade e Transparência (diferencial)

- **Consentimento explícito:** o bot só age em grupos onde foi adicionado e ativado via `/start`. A primeira mensagem avisa claramente que está monitorando as conversas.
- **`/why`:** explica a última intervenção — qual item estratégico e qual mensagem de origem motivaram o alerta. Baseado em `interventions` + `source_message_id`.
- **`/forget`:** remove todos os dados do projeto (mensagens, itens, canvas, base de conhecimento).
- Toda intervenção é registrada e auditável.

---

## 7. Tratamento de Erros e Resiliência

- **Falha de API OpenAI:** o caminho passivo (sync) é retentável — mensagens ficam `processed=false` e entram no próximo sync. O caminho ativo **falha em silêncio** (não intervém); nunca posta erro no grupo.
- **JSON malformado do GPT:** Extractor e Guardian validam com schema Pydantic. Falha → 1 retry → se falhar de novo, descarta o lote com log. Nunca grava lixo em `strategic_items`.
- **Falha de envio Telegram:** retry/backoff do `python-telegram-bot`; erros logados, não propagados.
- **Idempotência:** `telegram_msg_id` único — reprocessar o mesmo update não duplica. Sync é seguro de rodar duas vezes.
- **Custo descontrolado:** pré-filtro + batch são a proteção primária; teto simples de chamadas/hora por projeto como guarda-chuva.
- **Concorrência:** execução single-process com lock leve por projeto durante o sync, evitando dois syncs simultâneos corromperem o canvas.

---

## 8. Estratégia de Testes

Camadas isoladas → cada uma testável sem o Telegram real. TDD nas camadas core.

- **Storage:** unitários em SQLite em memória — CRUD de itens, transição de status (`active→superseded`), projeção de canvas.
- **Extractor / Guardian:** chamada GPT atrás da interface `LLMClient`. Nos testes, um *fake* devolve respostas fixas → testa parsing, validação de schema e lógica de decisão (limiar) sem gastar API.
- **Orchestrator:** roteamento híbrido — "mensagem trivial não chama GPT", "N mensagens disparam sync", "confiança baixa não intervém".
- **Bot Layer:** testes finos com mocks do `python-telegram-bot`.
- **End-to-end manual (demo):** roteiro fixo de mensagens mostrando extração → canvas atualizado → contradição → alerta → `/why`.

Regra geral: **toda lógica de negócio testável sem rede.**

---

## 9. Fora do Escopo (MVP do hackathon)

- Múltiplos frameworks simultâneos (começa só com BMC; arquitetura permite extensão).
- Modo configurável por grupo via comando (campo `mode` existe, mas UI de troca fica como roadmap).
- Multi-tenant / múltiplos processos / fila distribuída.
- Interface web para visualizar o canvas (foco no Telegram).

---

## 10. Roadmap Futuro (pitch)

- Suporte a múltiplos frameworks (Canvas de Hipóteses, Design Thinking, jornadas, personas).
- Visualização web do canvas vivo.
- Controles de privacidade granulares e papéis (quem pode `/forget`).
- Resumos periódicos automáticos ("o que mudou na estratégia esta semana").

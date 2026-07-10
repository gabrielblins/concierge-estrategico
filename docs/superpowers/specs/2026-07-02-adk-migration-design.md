# Migração para Google ADK — Design

**Data:** 2026-07-02
**Contexto:** O concierge usa uma camada LLM própria (`llm/`: LLMClient + OpenAI/Gemini + `call_validated`). Esta migração torna o **Google ADK (Agent Development Kit)** o framework principal de agentes: toda inteligência vira **LlmAgents** do ADK executados via **Runner**, e a orquestração da conversa vira um **agente orquestrador ADK determinístico** (custom `BaseAgent`). Pesquisa: google-adk **2.3.0** + litellm 1.83.7 instalam e convivem com a suite no Python 3.14; `output_schema` do ADK tem bugs conhecidos com OpenAI/LiteLLM (issues #217/#4573) → mantemos a validação Pydantic própria.

---

## 1. Decisões (aprovadas)

| Decisão | Escolha |
|---|---|
| Profundidade | Orquestração ADK completa — estilo **A**: Workflows/custom agents **determinísticos** (portões como código no grafo), LlmAgents nas pontas |
| Modelos | Config-driven: `LLM_PROVIDER=gemini` → string nativa ADK; `openai` → `LiteLlm("openai/<model>")`. Validação Pydantic nossa cobre ambos |
| Testes | Contratos públicos preservados; fachadas finas + `AgentExecutor` injetável (fake nos testes). Testes do executor usam um **FakeAdkModel** (`BaseLlm` custom) rodando o Runner real sem rede |
| Branch | `feat/adk-migration` |

## 2. Arquitetura

### Novo pacote `src/concierge/agents/`

- **`model_factory.py`** — `agent_model(settings)`: `gemini` → `settings.gemini_model` (string nativa); `openai` → `LiteLlm(model=f"openai/{settings.openai_model}")`. `configure_env(settings)` exporta as chaves que o ADK/litellm leem (`GOOGLE_API_KEY` ← `GEMINI_API_KEY`; `OPENAI_API_KEY` já vem do ambiente).
- **`definitions.py`** — `build_agents(model) -> dict[str, LlmAgent]` com os 8 agentes: `extractor`, `reconciler`, `canvas_updater`, `guardian`, `participant_consider`, `participant_respond`, `stylist`, `material_classifier`. `instruction` = os SYSTEM prompts atuais movidos verbatim (com o sufixo de voz aplicado dinamicamente quando houver personalidade — ver §4).
- **`executor.py`** — `AgentExecutor`:
  - Mantém **um event loop dedicado numa thread de fundo** (`run_coroutine_threadsafe(...).result()`) — os contratos síncronos atuais rodam dentro do loop do python-telegram-bot, onde `asyncio.run()` não funciona.
  - `run_text(agent, user_text) -> str | None` — cria sessão (`InMemorySessionService`), roda via `Runner.run_async`, concatena o texto do evento final; `None` em exceção.
  - `run_validated(agent, user_text, schema) -> BaseModel | None` — `run_text` + `json.loads` + `schema.model_validate`, com a semântica consagrada **retry-1x-e-descarta-para-None**. É o sucessor do `call_validated`.
- **`funnel.py`** — `MessageFunnelAgent(BaseAgent)`: o orquestrador ADK do caminho de mensagem não-menção. `_run_async_impl` lê insumos pré-carregados do `ctx.session.state` (`text`, `known_items`, `window`, `materials_guardian`, `materials_participant`, `style`, `gates`: mode/enabled/cooldown_ok/prefilter_ok/threshold) e decide deterministicamente: portões do guardião → roda o sub-agente guardian → se contradiz com confiança ≥ limiar grava `decision="alert"`; senão portões do participante → roda `participant_consider` → se relevante grava `decision="contribution"`; senão `decision="none"`. Resultado em `ctx.session.state["result"]` (`{decision, text, reason, confidence}`). Sub-agentes: `[guardian, participant_consider]`.

### O que muda nos módulos existentes

- **Fachadas (contratos idênticos, corpo delega ao executor):** `extractor.py`, `updater.py`, `reconciler.py`, `guardian.py` (`check`; `looks_strategic` continua puro/sem LLM), `participant.py` (`consider`/`respond`), `stylist.py` (`restyle`), `materials.py` (`classify`). Cada fachada monta o mesmo user-prompt de hoje e chama `executor.run_validated(agents[...], user, Schema)`.
- **`orchestrator.py`:**
  - Construtor passa a receber `(storage, executor, agents, knowledge, settings)` — mas para preservar os testes, as fachadas continuam sendo os colaboradores (`extractor`, `updater`, `guardian`, `participant`, `reconciler`, `stylist` implícito no bot) e ganham o executor por injeção nas próprias fachadas. Orchestrator **mantém todas as assinaturas atuais**.
  - `check_coherence` + `participate` continuam existindo (bot.py intocado), mas internamente o caminho não-menção pode ser servido pelo `MessageFunnelAgent` via `handle_message` (novo método usado pelos próprios `check_coherence`/`participate` compat) — na prática: orchestrator pré-carrega os insumos no session state e roda o funil via executor; os dois métodos legados extraem do resultado a parte que lhes cabe.
  - `run_sync` vira um **pipeline de agentes**: `extractor` → persiste itens → `reconciler` → aplica transições → `canvas_updater` → upserts. As escritas de DB entre estágios permanecem no orchestrator (persistência não é decisão de agente).
- **`llm/` REMOVIDO** (client, openai_client, gemini_client, factory) junto com seus testes; substituído por `agents/`.
- **`main.py`** — constrói `configure_env` → `agent_model` → `build_agents` → `AgentExecutor` → fachadas com executor → orchestrator. `_check_credentials` inalterado.
- **Intocados:** `bot.py` (exceto nenhuma mudança obrigatória), `storage.py`, `knowledge.py`, `webapp/`, `models.py`, `config.py`.

## 3. Testes

- **`FakeAdkModel(BaseLlm)`** em conftest: modelo fake com respostas enfileiradas que o **Runner real** consome — os testes do executor exercitam ADK de verdade sem rede.
- **`fake_executor`** (factory em conftest): substitui o `fake_llm` nos testes das fachadas — devolve objetos validados/None conforme roteiro e grava `.calls` (agent_name, user_text, schema).
- Testes de negócio (orchestrator, bot, workflows do funil) preservam as asserções atuais; muda só a construção dos colaboradores.
- Funil: testes unitários do `MessageFunnelAgent` com sub-agentes fake (portões: silent, cooldown, prefilter, threshold; prioridade do guardião; 1 voz).

## 4. Personalidade e materiais no mundo ADK

- Voz: o sufixo de estilo continua sendo **injeção no prompt** — as fachadas anexam o sufixo à `instruction` dinâmica (ADK permite instruction por-invocação via prompt do usuário; para simplicidade, o sufixo entra no fim do user-prompt como hoje o guardian faz no system). Semântica preservada: julgamento neutro, só a redação muda.
- RAG tipado: inalterado — as fachadas continuam recebendo `context`/`materials` como texto e anexando ao user-prompt.

## 5. Erros e invariantes (inalterados)

- Falha de agente/JSON inválido → retry 1x → `None` → **silêncio** (nunca posta erro).
- Mensagem trivial → **zero** chamadas (portões antes de qualquer agente).
- 1 voz por mensagem; prioridade do guardião; `/forget`, consentimento, idempotência — tudo igual.

## 6. Dependências

`google-adk==2.3.0` + `litellm==1.83.7` (via extra `google-adk[extensions]`) pinados. Aviso não-fatal de opentelemetry (conflito de resolver com chromadb) aceito — suite verde comprovada.

## 7. Riscos e mitigação

- **API 2.3.0 divergir do desenho** (BaseAgent custom, extração do texto final, FakeAdkModel): a Task 1 do plano é um **spike verificador** que prova cada suposição num teste real e corrige o plano antes das demais tasks.
- **Latência**: cada chamada ganha o overhead de sessão do Runner — aceitável (chamadas já custam segundos de LLM).
- **Custo zero preservado**: portões continuam antes de qualquer execução de agente.

## 8. Fora do escopo

- Ferramentas/`tools` do ADK, transferência LLM-driven, `adk web`/CLI, deploy Vertex.
- Migrar o Stylist/classifier para workflows (são chamadas únicas — LlmAgent direto).

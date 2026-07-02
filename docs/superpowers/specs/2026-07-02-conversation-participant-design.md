# Conversation Participant — Design

**Data:** 2026-07-02
**Contexto:** Hoje o bot só fala quando comandado ou quando o guardião detecta contradição. Esta feature o torna um **participante da conversa**: alguém que conecta ideias, traz conhecimento dos materiais, faz perguntas que aprofundam e sintetiza discussões — ajudando na circulação de ideias e troca de conhecimento da equipe. Construída sobre o master atual (materiais tipados + personalidade).

---

## 1. Proposta

O bot contribui na conversa por dois caminhos:

- **Menção (sempre responde):** mensagem contém `@username_do_bot` ou é *reply* a uma mensagem do bot → resposta direta e conversacional, apoiada na conversa recente, na base estratégica e nos materiais. Funciona mesmo em modo `silent` (a pessoa chamou explicitamente).
- **Proativo (raro, três portões em série):** contribuição espontânea somente quando os três portões passam:
  1. **Cooldown/config:** `participation_enabled` ligado, modo ≠ `silent`, e ≥ `PARTICIPATION_COOLDOWN` mensagens (default 10) desde a última contribuição espontânea.
  2. **Pré-filtro barato (sem LLM):** mensagem substantiva (`looks_strategic(text)` e `len(text) >= 20`).
  3. **Autoavaliação:** o LLM retorna `should_contribute` + `relevance`; posta só se `should_contribute` e `relevance >= PARTICIPATION_THRESHOLD` (default 0.75).

**Anti-colisão:** uma voz por mensagem. Menção pula o guardião. No caminho normal, o guardião tem prioridade — o participante só é consultado se o guardião calou.

## 2. Tipos de contribuição (proativo)

| Kind | O quê |
|---|---|
| `connection` | Liga o que está sendo dito a um item estratégico existente ("isso conversa com a hipótese validada X") |
| `knowledge` | Traz um trecho relevante dos materiais de referência ("o manual de validação sugere Y para esse caso") |
| `question` | Pergunta socrática que aprofunda uma discussão rasa/unilateral |
| `synthesis` | Resume pontos e posições quando um tópico se estende |

O LLM escolhe o tipo (ou nenhum). A contribuição sai pronta, na língua da conversa e na voz da personalidade do projeto.

## 3. Componentes

### 3.1 Novo `src/concierge/participant.py`

- `ContributionKind(str, Enum)`: `connection`, `knowledge`, `question`, `synthesis` (em `models.py`).
- `Contribution(BaseModel)` (em `models.py`): `should_contribute: bool`, `relevance: float`, `kind: ContributionKind | None = None`, `text: str = ""`.
- `Participant(llm)`:
  - `consider(window, items, materials, style="") -> Contribution | None` — caminho proativo; prompt instrui "contribua SÓ se agregar de verdade, senão should_contribute=false", com os 4 tipos exemplificados. Usa `call_validated`; `None` → silêncio.
  - `respond(window, items, materials, mention_text, style="") -> str | None` — caminho menção; sempre gera resposta (schema `StyledText` reutilizado para a saída `{text}`); `None` → silêncio.
  - `style` não-vazio → sufixo no SYSTEM (mesma mecânica do guardião; a fala nasce na voz, sem Stylist, sem custo extra).
- `window` = lista de dicts `{author, text}` (mais antiga → mais recente).

### 3.2 Mudanças em módulos existentes

- **`storage.py`**:
  - `recent_messages(project_id, limit=15) -> list[dict]` (`id, author, text`, ordenado do mais antigo ao mais recente dentro da janela).
  - Coluna `projects.last_participation_msg_id INTEGER` (nullable, + guard de migração) com `set_last_participation(project_id, message_id)` e `messages_since(project_id, message_id | None) -> int` (contagem de mensagens com id maior; `None` → total).
- **`materials.py`**: `ROUTING` ganha o módulo `"participant"` em TODOS os tipos (o participante circula qualquer conhecimento). `types_for_module("participant")` retorna os 5 tipos.
- **`config.py`**: `participation_enabled: bool = True` (env `PARTICIPATION_ENABLED`, "true"/"false"), `participation_cooldown: int = 10` (env `PARTICIPATION_COOLDOWN`), `participation_threshold: float = 0.75` (env `PARTICIPATION_THRESHOLD`). `.env.example` atualizado.
- **`orchestrator.py`** (construtor ganha `participant=None`, backward-compatible):
  - `participate(project_id, message_id, text) -> str | None` — os 3 portões; ao contribuir, chama `set_last_participation` e retorna o texto.
  - `respond_mention(project_id, message_id, text) -> str | None` — sem portões; monta contexto e responde.
  - Ambos montam: janela (`recent_messages`), itens `ACTIVE`+`VALIDATED`, RAG com `types_for_module("participant")` (query = texto da mensagem), `get_personality` como `style`. `knowledge=None` e `participant=None` suportados (retornam `None`).
- **`bot.py`**:
  - `_is_mention(text, entities_usernames, reply_to_is_bot) -> bool` — helper puro.
  - `on_message` nova ordem: ingest → se menção: `respond_mention` (e NÃO roda guardião) → senão guardião → se guardião calou: `participate` → sync. Menção com projeto inexistente → responde `NOT_STARTED`.
  - O username do bot é obtido no startup (`post_init` do PTB) e fica disponível para `_is_mention`.
- **`main.py`**: constrói `Participant(llm)` e passa ao Orchestrator.

## 4. Tratamento de erros

- LLM falha/JSON inválido em `consider`/`respond` → `None` → **silêncio** (invariante: o bot nunca posta erro no grupo).
- Cooldown/portões nunca bloqueiam guardião ou sync.
- Menção sem `/start` → `NOT_STARTED` (pessoa chamou, merece resposta).
- RAG indisponível → contexto de materiais vazio; o participante segue com janela + itens.

## 5. Custo em regime

- Mensagem trivial: **0** chamadas extras (pré-filtro).
- Substantiva com cooldown ativo ou guardião falando: **0**.
- Substantiva, guardião calado, cooldown vencido: **1** chamada (`consider` decide e gera junto).
- Menção: **1** chamada.

## 6. Testes

- Portões de `participate`: enabled=false, modo silent, cooldown não vencido, pré-filtro reprova, `should_contribute=false`, `relevance` abaixo do limiar → todos `None` (e sem chamada LLM nos portões 1–2).
- Contribuição válida → texto retornado + `last_participation_msg_id` atualizado (cooldown reinicia).
- `respond_mention` → responde com janela/itens/materiais no prompt; estilo injetado no SYSTEM.
- `_is_mention` puro: mention entity, reply-ao-bot, negativos.
- Fail-safe: LLM erro → `None` nos dois caminhos.
- Tudo com fakes/in-memory, sem rede.

## 7. Fora do escopo

- Participação por DM/privado (só grupos com `/start`).
- Aprendizado de preferência ("fale menos/mais") — roadmap.
- Threads/tópicos do Telegram (janela é linear).

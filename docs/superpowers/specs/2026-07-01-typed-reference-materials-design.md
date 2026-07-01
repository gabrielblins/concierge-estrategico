# Feature A: Typed Reference Materials — Design

**Data:** 2026-07-01
**Contexto:** O concierge estratégico (bot de Telegram, master atual) tem um `KnowledgeBase` (ChromaDB) construído e testado, mas sem fio: nenhum comando ingere material e só o Guardião consulta o RAG. Esta feature entrega a "base de conhecimento personalizada" do pitch original, com um mecanismo **incremental**: cada material adicionado destrava capacidades específicas nos módulos do bot.

---

## 1. Proposta

O usuário envia materiais de referência (livros, manuais, frameworks) pelo chat. O bot:

1. **Extrai o texto** (PDF, TXT/MD, DOCX ou texto colado na mensagem).
2. **Classifica automaticamente o tipo** do material via LLM.
3. **Ingere no ChromaDB** com o tipo na metadata dos chunks.
4. **Anuncia a capacidade destravada** no chat (ex: "📚 Detectei: guia de validação → o guardião agora cobra experimentos antes de validar hipóteses").

A partir daí, cada módulo do bot consulta apenas os materiais do(s) tipo(s) relevante(s) para ele — o bot "pensa" segundo os métodos da equipe, e cada novo material amplia uma capacidade específica.

## 2. Taxonomia de tipos e roteamento

`MaterialType` (enum, str):

| Tipo | Roteado para | Capacidade anunciada |
|---|---|---|
| `canvas_guide` | CanvasUpdater | "o canvas passa a seguir as definições deste manual" |
| `validation_guide` | Guardian + Reconciler | "o guardião agora cobra experimentos; validações seguem este método" |
| `methodology` | Extractor + Guardian | "as análises passam a usar os conceitos deste método" |
| `custom_framework` | todos (Extractor, Updater, Guardian, Reconciler) | "este framework vira lente de todas as análises" |
| `generic` | Guardian | "material disponível como contexto geral" |

O roteamento é uma tabela estática `ROUTING: dict[MaterialType, set[Module]]` em `materials.py`. A classificação em tipo desconhecido/falha → fallback `generic` (nunca trava a ingestão).

## 3. Componentes

### 3.1 Novo módulo `src/concierge/materials.py`

- `extract_text(filename: str, data: bytes) -> str` — despacha por extensão:
  - `.pdf` → `pypdf` (concatena texto das páginas)
  - `.txt`, `.md` → decodifica UTF-8 (com fallback latin-1)
  - `.docx` → `python-docx` (parágrafos)
  - Extensão não suportada → `MaterialError` com mensagem amigável.
- `classify(llm: LLMClient, filename: str, text: str) -> MaterialType` — chama `call_validated` com um schema `ClassificationResult(material_type: MaterialType)`, enviando o nome do arquivo + os primeiros ~2000 caracteres. Retorno `None` → `generic`.
- `MaterialService(llm, knowledge, storage)` — orquestra: `add_material(project_id, filename, data | text) -> (MaterialType, chunk_count)`; grava em `knowledge_docs` com o tipo; devolve o que o handler precisa para o anúncio.
- `CAPABILITIES: dict[MaterialType, str]` — textos de anúncio (tabela acima).

### 3.2 Mudanças em módulos existentes

- **`models.py`**: enum `MaterialType`; schema `ClassificationResult`.
- **`storage.py`**: `knowledge_docs` ganha coluna `material_type TEXT NOT NULL DEFAULT 'generic'`; métodos `add_knowledge_doc(project_id, filename, material_type, chunk_count) -> int` e `list_knowledge_docs(project_id) -> list[dict]`.
- **`knowledge.py`**:
  - `ingest(...)` ganha parâmetro `material_type: str = "generic"`, gravado na metadata de cada chunk.
  - `query(...)` ganha parâmetro `material_types: list[str] | None = None` — quando presente, aplica filtro `where={"material_type": {"$in": [...]}}` do Chroma.
  - Novo `delete(project_id)` — apaga a coleção do projeto (usado pelo `/forget`).
- **`extractor.py`, `updater.py`, `reconciler.py`**: cada um ganha parâmetro opcional `context: str = ""` no método principal, anexado ao prompt do usuário como bloco `REFERENCE MATERIAL:` (o Guardião já tem `method_context` — permanece como está).
- **`orchestrator.py`**: em `run_sync` e `check_coherence`, consulta o `knowledge` com o filtro de tipos do módulo-alvo e injeta o `context`. O texto de consulta é: em `run_sync`, os últimos 1500 caracteres do transcript do lote (uma consulta por módulo, com o filtro daquele módulo); em `check_coherence`, o texto da mensagem (comportamento atual, agora com filtro). O filtro de cada módulo é derivado da tabela `ROUTING` invertida (módulo → tipos que o alimentam). `knowledge=None` continua suportado (context vazio).
- **`bot.py`**:
  - Handler de **documento**: qualquer arquivo enviado com legenda `/upload` (ou respondido com `/upload`) → baixa via API do Telegram, chama `MaterialService.add_material`, responde com o anúncio de capacidade.
  - `/upload <texto colado>` → ingere o texto da própria mensagem.
  - **`/materials`** → lista `list_knowledge_docs`: "📚 manual-bmc.pdf — guia de canvas → o canvas segue este manual".
  - **`/forget`** → além do SQLite, chama `knowledge.delete(project_id)`.
  - Todos exigem `/start` (portão de consentimento existente).

## 4. Fluxo de dados (upload)

```
arquivo/texto no chat
  → bot baixa bytes (limite: 20 MB, o teto do Bot API)
  → extract_text()            [erro → mensagem amigável, aborta]
  → classify() via LLM        [falha → 'generic']
  → knowledge.ingest(type)    [chunks com metadata]
  → storage.add_knowledge_doc
  → resposta: "📚 Detectei: <tipo> → <capacidade>"
```

## 5. Tratamento de erros

- Parser falhou / formato não suportado → resposta amigável no chat, nada é gravado.
- Classificação falhou (LLM erro/JSON inválido) → tipo `generic`, ingestão continua.
- Arquivo acima do limite → aviso com o limite.
- Consulta RAG falha em `run_sync`/`check_coherence` → `context=""` (módulos funcionam sem material, comportamento atual preservado).

## 6. Testes

- Parsers: fixtures mínimos (PDF de 1 página gerado no teste, txt, docx) → texto extraído.
- `classify`: LLM fake com resposta válida e inválida (fallback generic).
- `KnowledgeBase`: ingest com tipo + query filtrada por tipo (Chroma efêmero); `delete`.
- Roteamento: tabela cobre todos os `MaterialType`.
- Orchestrator: com knowledge fake, verifica que cada módulo recebe contexto filtrado pelo tipo certo.
- Handlers: puros, com service fake — anúncio correto, `/materials` lista, `/forget` chama delete.

## 7. Dependências novas

`pypdf`, `python-docx` (pinadas em requirements.txt, wheels compatíveis com Python 3.14).

## 8. Fora do escopo

- OCR de PDFs escaneados.
- Reclassificação/remoção de material individual (só `/forget` global).
- UI de gestão de materiais (fica no Mini App futuramente).

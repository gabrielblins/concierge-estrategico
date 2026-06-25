# Concierge Estratégico — Documentação do Projeto

> Um bot de Telegram que transforma as conversas de uma equipe de startup em uma
> **base estratégica viva**: mantém o Business Model Canvas atualizado
> automaticamente e alerta a equipe quando as discussões contradizem decisões já
> validadas.

---

## 1. Visão geral

### O problema

No começo de um projeto de inovação, as equipes usam frameworks estratégicos —
**Business Model Canvas**, Canvas de Hipóteses, Design Thinking, mapas de
personas — para organizar premissas, propostas de valor, segmentos de cliente e
riscos. Essas ferramentas são ótimas no arranque, mas têm um problema crônico:
**ninguém as mantém atualizadas.**

Com o tempo, a equipe continua decidindo, mudando de direção e levantando
hipóteses — só que isso acontece **nas conversas do dia a dia**, enquanto os
canvas e documentos ficam congelados no passado. O resultado: decisões tomadas
com base em hipóteses já superadas, retrabalho, e perda de foco.

### A solução

Um bot de Telegram que **acompanha as conversas do grupo** e faz três coisas:

1. **Registra e estrutura** — extrai das mensagens os itens estratégicos
   (decisões, hipóteses, premissas, riscos, tarefas, aprendizados).
2. **Mantém o canvas vivo** — atualiza automaticamente o Business Model Canvas a
   partir desses itens.
3. **Guarda a coerência** — quando alguém propõe algo que contradiz uma decisão
   ou hipótese já validada, o bot intervém com um alerta.

Tudo isso respeitando **consentimento e transparência**: o bot só age em grupos
onde foi explicitamente ativado, avisa que está monitorando, explica *por que*
interveio (`/why`) e permite apagar todos os dados (`/forget`).

**Frase-síntese:** *transforma conversas de Telegram em uma base estratégica
viva, mantendo canvas, hipóteses e decisões sempre atualizados, e alertando a
equipe quando as discussões se afastam da estratégia definida.*

---

## 2. Principais features

| Feature | O que faz |
|---|---|
| **Extração automática** | Lê as mensagens do grupo e identifica itens estratégicos (decisões, hipóteses, premissas, riscos, tarefas, aprendizados) usando um LLM. |
| **Canvas vivo** | Reconstrói o Business Model Canvas (9 blocos) a partir dos itens estratégicos atuais. |
| **Ciclo de vida dos itens** | Itens nascem `active`; o sistema os promove a `validated` ou marca como `discarded`/`superseded` conforme a equipe evolui. O canvas reflete só o que vale *agora*. |
| **Guardião de coerência** | Detecta quando uma nova mensagem contradiz uma decisão/hipótese validada e posta um alerta — mas só quando tem confiança alta. |
| **Filtro de custo** | Mensagens triviais ("ok", "kkk") nunca chegam ao LLM caro: um pré-filtro barato por palavras-chave decide o que vale analisar. |
| **Base de conhecimento (RAG)** | A equipe pode alimentar o bot com materiais de referência (livros, manuais, frameworks); o guardião usa esse contexto para fundamentar as análises. |
| **Dois provedores de LLM** | Funciona com **OpenAI** ou **Google Gemini**, escolhido por uma variável de ambiente (`LLM_PROVIDER`). |
| **Transparência & consentimento** | `/start` ativa e avisa; `/why` explica o último alerta; `/forget` apaga tudo; comandos exigem ativação prévia. |
| **Modo silencioso** | Cada projeto tem um modo (`silent`/`moderate`/`active`) que pode suprimir intervenções. |

---

## 3. Como funciona — os dois modos

O sistema opera em **modo híbrido**: um caminho *passivo* (em lote) e um caminho
*ativo* (por mensagem). Os dois rodam a partir do mesmo handler de mensagens.

### Caminho passivo — manter o canvas (em lote)

Roda quando acumulam mensagens suficientes (ou via `/sync`). É o que mantém o
canvas atualizado.

```
1. Cada mensagem do grupo é salva (não processada ainda).
2. Quando o nº de mensagens não-processadas atinge BATCH_SIZE (padrão 15),
   dispara um "sync".
3. SYNC:
   a. Extractor lê o lote → itens estratégicos estruturados (JSON).
   b. Itens novos entram como 'active'.
   c. Reconciler compara os novos com os itens existentes e decide
      transições: promover a 'validated' ou marcar antigos como
      'superseded'/'discarded'.
   d. Canvas Updater re-sintetiza os blocos do BMC a partir dos itens
      que valem agora (active + validated).
   e. As mensagens do lote são marcadas como processadas.
```

### Caminho ativo — guardião de coerência (por mensagem, seletivo)

Roda a cada mensagem, mas é **seletivo** para não gerar ruído nem custo:

```
1. A cada mensagem nova:
   - Se o projeto está em modo 'silent' → ignora.
   - PRÉ-FILTRO BARATO (sem LLM): a mensagem parece uma decisão/proposta/
     direcionamento? (busca palavras como "vamos", "priorizar", "hipótese",
     "descartar", "pivot", "segmento"...) Se não → ignora.
2. Se passou no pré-filtro:
   - Busca os itens 'validated' e 'discarded' do projeto.
   - Busca contexto de método na base de conhecimento (RAG), se houver.
   - Pergunta ao LLM: esta mensagem contradiz algo? Com qual item?
     Qual a confiança (0–1)?
3. Se contradiz E confiança ≥ CONFIDENCE_THRESHOLD (padrão 0.75)
   E modo ≠ silent → posta o alerta no grupo e registra a intervenção.
4. Caso contrário → silêncio.
```

**Por que esse desenho controla ruído e custo:** o pré-filtro elimina a maioria
das mensagens antes de gastar uma chamada de LLM; o limiar de confiança evita
alertas em cima de ambiguidade ("melhor calar do que irritar"); e o sync em lote
evita reprocessar o canvas a cada mensagem.

---

## 4. Arquitetura

O sistema é dividido em camadas com responsabilidades isoladas. Cada unidade tem
um propósito único e se comunica por interfaces bem definidas.

```
                       Telegram (grupo)
                            │  long-polling
                            ▼
┌──────────────────────────────────────────────────────┐
│  Bot Layer  (bot.py)                                   │
│  recebe mensagens/comandos, envia respostas/alertas    │
│  — handlers puros (testáveis sem Telegram)             │
└───────────────────────────┬────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────┐
│  Orchestrator  (orchestrator.py)                       │
│  o "cérebro": decide enfileirar / sincronizar / checar │
└───┬──────────┬──────────┬──────────┬──────────┬────────┘
    ▼          ▼          ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐
│Extractor│ │Recon-  │ │Canvas    │ │Guardian│ │Knowledge │
│         │ │ciler   │ │Updater   │ │        │ │Base (RAG)│
└────┬────┘ └───┬────┘ └────┬─────┘ └───┬────┘ └────┬─────┘
     │          │           │           │           │
     └──────────┴─────┬─────┴───────────┘           │
                      ▼                              ▼
            ┌──────────────────┐          ┌──────────────────┐
            │  LLMClient        │          │  ChromaDB         │
            │  (OpenAI│Gemini)  │          │  (vetores RAG)    │
            └──────────────────┘          └──────────────────┘
                      │
                      ▼
            ┌──────────────────┐
            │  Storage (SQLite) │
            │  base estratégica │
            └──────────────────┘
```

### Componentes (e o arquivo de cada um)

| Componente | Arquivo | Responsabilidade |
|---|---|---|
| **Bot Layer** | `bot.py` | Interface com Telegram. Handlers *puros* (recebem o orchestrator + ids, devolvem texto) — sem lógica de negócio, testáveis sem rede. |
| **Orchestrator** | `orchestrator.py` | Roteamento do modo híbrido: `ingest_message`, `should_sync`, `run_sync` (passivo), `check_coherence` (ativo). |
| **Extractor** | `extractor.py` | Lote de mensagens → itens estratégicos (JSON validado). |
| **Reconciler** | `reconciler.py` | Decide transições de status (promover a `validated`, supersedir antigos) — é o que torna o guardião eficaz. |
| **Canvas Updater** | `updater.py` | Itens vivos → blocos do BMC. Filtra nomes de bloco inválidos. |
| **Guardian** | `guardian.py` | Pré-filtro barato (`looks_strategic`, sem LLM) + checagem de contradição (`check`, com LLM). |
| **Knowledge Base** | `knowledge.py` | RAG: ingestão e consulta de materiais de referência via ChromaDB. |
| **Storage** | `storage.py` | Persistência em SQLite (a "fonte da verdade"). |
| **LLMClient** | `llm/` | Interface única para o LLM, com implementações OpenAI e Gemini e um *factory* que escolhe pelo `LLM_PROVIDER`. |
| **Config** | `config.py` | Lê variáveis de ambiente para um `Settings`. |
| **Main** | `main.py` | Ponto de entrada: monta tudo, valida credenciais, inicia o polling. |

### A camada de LLM (o que permite trocar OpenAI ↔ Gemini)

Toda a lógica de negócio conversa com **uma única interface**:

```python
class LLMClient:
    def complete_json(self, system: str, user: str) -> dict: ...
```

- `OpenAILLMClient` e `GeminiLLMClient` implementam essa interface.
- `call_validated(client, system, user, schema)` é o **ponto único de
  validação**: chama o LLM, valida a saída com um schema Pydantic e, se vier
  inválida, tenta **uma vez** de novo e descarta se falhar (nunca grava lixo no
  banco).
- `build_llm(settings)` é o *factory*: lê `LLM_PROVIDER` e devolve o cliente
  certo, validando só a chave do provedor escolhido.

Como Extractor, Reconciler, Updater e Guardian só conhecem a interface,
**trocar de provedor não muda uma linha da lógica de negócio** — só a variável
de ambiente.

---

## 5. A base estratégica viva (modelo de dados)

Tudo é persistido em **SQLite**. O princípio central: **`strategic_items` é a
fonte da verdade; o canvas é apenas uma projeção dela.**

| Tabela | Para quê |
|---|---|
| `projects` | Um projeto por grupo do Telegram. Guarda o `mode` (silent/moderate/active). |
| `messages` | Buffer bruto das conversas. `processed` marca o que já virou item. `telegram_msg_id` é único (idempotência). |
| `strategic_items` | O coração: cada decisão/hipótese/premissa/risco/tarefa/aprendizado, com `status` e `source_message_id` (origem). |
| `canvas_blocks` | Os 9 blocos do BMC — uma *projeção* dos itens. |
| `interventions` | Log de cada alerta do guardião (alimenta o `/why` e a auditoria). |
| `knowledge_docs` | Metadados dos materiais de referência (os vetores ficam no ChromaDB). |

### Ciclo de vida de um item estratégico

```
        extraído
           │
           ▼
       [ active ] ──── reconciler promove ────► [ validated ]
           │                                          │
           │ reconciler descarta              alguém contradiz
           ▼                                          │
      [ discarded ]                                   ▼
           ▲                              guardião dispara alerta
           │
   substituído por item novo ──► [ superseded ]
```

- O **canvas** projeta itens `active` + `validated` (o que vale agora).
- O **guardião** compara contra itens `validated` + `discarded` (o que já foi
  decidido ou rejeitado) — é por isso que o Reconciler é essencial: sem ele,
  nada chegaria a `validated` e o guardião não teria o que defender.
- **Nada é apagado de fato** (exceto via `/forget`): itens viram `discarded` ou
  `superseded`. É isso que permite o guardião dizer *"esse caminho já foi
  descartado por causa da premissa X"*.

---

## 6. Comandos do bot

| Comando | Efeito |
|---|---|
| `/start` | Ativa o bot no grupo e mostra o aviso de monitoramento (consentimento). |
| `/sync` | Força a atualização do canvas agora (sem esperar o `BATCH_SIZE`). |
| `/status` | Mostra o Business Model Canvas atual. |
| `/why` | Explica o último alerta de coerência (motivo + confiança). |
| `/forget` | Apaga todos os dados do projeto. |

`/status`, `/sync`, `/why` e `/forget` exigem `/start` antes — se o projeto não
foi ativado, o bot pede para rodar `/start` primeiro (portão de consentimento).

---

## 7. Decisões técnicas

| Decisão | Escolha | Motivo |
|---|---|---|
| Linguagem | Python 3.14 | Ecossistema maduro de bots e LLM. |
| Bot framework | `python-telegram-bot` 22.x | Long-polling simples, retry/backoff embutidos. |
| LLM | OpenAI **ou** Gemini (configurável) | Flexibilidade; saída JSON estruturada nos dois. |
| Estado | SQLite | Zero-config, suficiente para o escopo. |
| RAG | ChromaDB | Busca semântica local nos materiais de referência. |
| Validação de saída do LLM | Pydantic | Garante que nada malformado entre no banco (retry-uma-vez-e-descarta). |
| Framework estratégico | Business Model Canvas (9 blocos) | Um framework no MVP; a arquitetura permite outros. |

### Resiliência e segurança

- **Falha do LLM** no caminho ativo → **silêncio** (nunca posta erro no grupo).
  No caminho passivo → as mensagens ficam pendentes e entram no próximo sync.
- **JSON malformado** → valida com Pydantic, tenta 1 vez, descarta com log.
  Nunca grava lixo.
- **Idempotência** → `telegram_msg_id` único; reprocessar o mesmo update não
  duplica nada.
- **Controle de custo** → pré-filtro barato + sync em lote + limiar de
  confiança. Mensagens triviais não custam chamada de API.
- **Consentimento** → o bot só age após `/start`, e avisa que está monitorando.

### Qualidade

- **61 testes** automatizados, todos passando.
- Toda a lógica de negócio é **testável sem rede** (clientes de LLM são
  injetados como *fakes*/stubs nos testes; banco em memória).
- Construído com TDD, em camadas pequenas e focadas (~810 linhas de código no
  total).

---

## 8. Como rodar (resumo)

```bash
# 1. ambiente
python3.14 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. configurar (escolha o provedor)
cp .env.example .env
#   edite: TELEGRAM_TOKEN, LLM_PROVIDER=openai|gemini, e a chave do provedor

# 3. rodar
set -a; source .env; set +a
PYTHONPATH=src python -m concierge.main
```

O guia detalhado de instalação, criação do bot no BotFather (incluindo desligar
o "privacy mode"), e um roteiro de teste ao vivo estão em **[SETUP.md](SETUP.md)**.

---

## 9. Fora do escopo do MVP (roadmap)

- `/upload` (ingestão de documentos pela conversa) e `/check` (checagem sob
  demanda) — a lógica de RAG já existe e é testada; falta só o "fio" do comando.
- Múltiplos frameworks simultâneos (hoje: só BMC).
- Visualização web do canvas vivo.
- Atribuição mais precisa da mensagem-origem de cada item (`source_message_id`).
- `/forget` também remover os vetores do ChromaDB (hoje limpa só o SQLite).

---

## 10. Mapa rápido do código

```
src/concierge/
├── bot.py            # handlers do Telegram + comandos
├── orchestrator.py   # cérebro: modo híbrido (passivo + ativo)
├── extractor.py      # mensagens → itens estratégicos
├── reconciler.py     # transições de status dos itens
├── updater.py        # itens → blocos do canvas
├── guardian.py       # pré-filtro + detecção de contradição
├── knowledge.py      # RAG (ChromaDB)
├── storage.py        # SQLite (fonte da verdade)
├── canvas.py         # nomes dos 9 blocos do BMC
├── models.py         # enums + schemas Pydantic
├── config.py         # Settings (variáveis de ambiente)
├── main.py           # ponto de entrada
└── llm/
    ├── client.py         # interface LLMClient + call_validated
    ├── openai_client.py  # implementação OpenAI
    ├── gemini_client.py  # implementação Gemini
    └── factory.py        # build_llm (escolhe pelo LLM_PROVIDER)
```

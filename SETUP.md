# Setup & Live Testing Guide — Strategic Concierge Bot

This guide takes you from a fresh clone to a running bot in a real Telegram group, then through a scripted demo that exercises every feature.

---

## 1. Prerequisites

- **Python 3.14** (the bot's pinned dependencies build only on 3.14 here).
  Check: `python3.14 --version` → `Python 3.14.x`.
- A **Telegram account** (to create the bot and a test group).
- An **OpenAI API key** with credits (the bot calls GPT for extraction, canvas
  updates, reconciliation, and coherence checks).
- ~80 MB free disk for the local embedding model (downloaded once on first
  RAG use).

---

## 2. Install

From the repo root:

```bash
# Create and activate the virtualenv (one time)
python3.14 -m venv .venv
source .venv/bin/activate

# Install pinned dependencies (verified to build on Python 3.14)
pip install --upgrade pip
pip install -r requirements.txt
```

Verify the install:

```bash
pytest -q                       # expect: 60 passed
PYTHONPATH=src python -c "import concierge.main; print('imports ok')"
```

Pinned versions: `python-telegram-bot==22.8`, `openai==2.44.0`,
`google-genai==2.10.0`, `pydantic==2.13.4`, `chromadb==1.5.9`, `pytest==9.1.1`.

---

## 3. Create the Telegram bot

1. In Telegram, open a chat with **@BotFather**.
2. Send `/newbot`. Choose a name and a username (must end in `bot`,
   e.g. `my_concierge_bot`).
3. BotFather replies with an **HTTP API token** like
   `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`. Copy it.
4. **Allow the bot to read group messages.** By default Telegram bots only see
   commands and @mentions in groups. Send BotFather:
   - `/setprivacy` → select your bot → **Disable**.
   This turns off "privacy mode" so the bot receives every text message — which
   it needs, since it analyses the whole conversation.

> If you skip step 4, the bot will only ever see `/start`, `/status`, etc. and
> never the actual discussion, so the passive sync and guardian won't fire.

---

## 4. Configure credentials

Copy the example env file and fill it in:

```bash
cp .env.example .env
```

Edit `.env`. You choose the **LLM provider** with `LLM_PROVIDER` — set it to
`openai` or `gemini`, and fill in only that provider's key.

**Using Gemini (Google AI Studio key):**

```
TELEGRAM_TOKEN=123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LLM_PROVIDER=gemini
GEMINI_API_KEY=...your-gemini-key...
GEMINI_MODEL=gemini-3.5-flash
DB_PATH=concierge.db
CHROMA_PATH=./chroma
BATCH_SIZE=15
CONFIDENCE_THRESHOLD=0.75
```

**Using OpenAI instead:**

```
TELEGRAM_TOKEN=123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...your-key...
OPENAI_MODEL=gpt-4o-mini
DB_PATH=concierge.db
CHROMA_PATH=./chroma
BATCH_SIZE=15
CONFIDENCE_THRESHOLD=0.75
```

> Get a Gemini key from **Google AI Studio** (aistudio.google.com → "Get API
> key"). The default model `gemini-3.5-flash` is fast and supports JSON output;
> switch to `gemini-2.5-flash` via `GEMINI_MODEL` if your key lacks 3.5 access.

**Tuning knobs for testing:**

| Variable | Default | What it does | Demo tip |
|---|---|---|---|
| `LLM_PROVIDER` | `openai` | Which LLM backend to use (`openai` or `gemini`) | Set to `gemini` to use your Gemini key |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Gemini model id (when provider is gemini) | Fall back to `gemini-2.5-flash` if 3.5 isn't available on your key |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model id (when provider is openai) | — |
| `BATCH_SIZE` | 15 | Messages buffered before an automatic canvas sync | Set to **3** so the canvas updates after just a few messages instead of waiting for 15 |
| `CONFIDENCE_THRESHOLD` | 0.75 | Minimum confidence for the guardian to post an alert | Lower to ~0.6 if you want the guardian to speak up more eagerly during a demo |

Export the variables into your shell before running:

```bash
set -a; source .env; set +a
```

The bot fails fast with a clear message if `TELEGRAM_TOKEN` or the **chosen
provider's** key is empty (e.g. `LLM_PROVIDER=gemini` with no `GEMINI_API_KEY`),
or if `LLM_PROVIDER` is set to something other than `openai`/`gemini`.

---

## 5. Run the bot

With the venv active and `.env` exported:

```bash
PYTHONPATH=src python -m concierge.main
```

You should see python-telegram-bot start long-polling (no errors). Leave this
running — it's your bot process. `Ctrl+C` to stop.

State is persisted to `concierge.db` (SQLite) and `./chroma` (vectors), so
stopping and restarting keeps the project's strategic base.

---

## 6. First live test (5 minutes)

1. **Create a test group** in Telegram and **add your bot** to it.
   (Search its `@username`, add as member. For groups, you may need to promote
   it or just ensure privacy mode is disabled per step 3.)
2. In the group, send **`/start`**.
   → The bot replies with the monitoring/consent notice. The project is now
   active for this group.
3. Send a few real strategic messages, e.g.:
   - `vamos focar nas pequenas empresas como segmento inicial`
   - `acho que SMBs vão pagar pela economia de tempo`
   - `nossa proposta de valor é economizar tempo no planejamento`
   With `BATCH_SIZE=3`, after the third message the bot runs a sync.
4. Send **`/status`**.
   → The bot shows the auto-built Business Model Canvas (customer_segments,
   value_proposition, etc.) derived from your messages.
5. **Trigger the guardian.** Send a message that contradicts what was decided:
   - `acho que devemos priorizar enterprise e abandonar os SMBs`
   → If the guardian's confidence ≥ threshold, it replies with a
   ⚠️ coherence alert.
6. Send **`/why`**.
   → The bot explains its last intervention (the reason + confidence).
7. Send **`/forget`**.
   → All data for the group is erased; `/status` now tells you to `/start` again.

---

## 7. Command reference

| Command | Effect |
|---|---|
| `/start` | Activate the bot in this group, show the consent/monitoring notice |
| `/sync` | Force a canvas update now (instead of waiting for `BATCH_SIZE`) |
| `/status` | Show the current Business Model Canvas |
| `/why` | Explain the last coherence alert (reason + confidence) |
| `/forget` | Erase all stored data for this group |
| `/upload` | (arquivo com legenda, reply a arquivo, ou texto colado) adiciona material de referência |
| `/materials` | lista os materiais ingeridos e as capacidades destravadas |

`/status`, `/sync`, `/why`, and `/forget` require `/start` first — if the
project isn't active, they reply asking you to `/start`.

---

## 8. How the two modes behave (what to expect)

- **Passive (canvas) — batched.** Every text message is stored. A sync runs
  when `BATCH_SIZE` unprocessed messages accumulate, or when you send `/sync`.
  A sync: extracts strategic items → reconciles their status
  (active/validated/discarded/superseded) → re-synthesizes the canvas.
- **Active (guardian) — per message, selective.** Each message first passes a
  cheap keyword pre-filter (no LLM). Only messages that look like a
  decision/direction reach the LLM, which judges whether they contradict a
  **validated** or **discarded** item. It alerts only above
  `CONFIDENCE_THRESHOLD`. Trivial chatter ("ok", "kkk") never costs an API call.

> The guardian compares against *validated/discarded* items. Those statuses are
> produced by the reconciler during a sync. So the guardian gets sharper after
> the team has discussed enough for the bot to mark some hypotheses validated.
> For a quick demo, send a clear, decisive batch first (so something gets
> validated), *then* send the contradicting message.

---

## 9. Cost & safety notes

- Each sync and each non-trivial message can call the OpenAI API. With
  `BATCH_SIZE=3` and an active group, costs add up — keep an eye on usage, or
  raise `BATCH_SIZE` and `CONFIDENCE_THRESHOLD` during long sessions.
- The bot only acts in groups where `/start` was sent, and announces that it is
  monitoring. `/forget` erases SQLite data for the group.
- `/forget` now clears both the SQLite records and the group's ChromaDB vector collection.

---

## 10. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Missing required environment variable(s): TELEGRAM_TOKEN ...` | `.env` not exported. Run `set -a; source .env; set +a`. |
| Bot sees `/start` but ignores normal messages | Privacy mode still on. BotFather → `/setprivacy` → Disable. Re-add the bot to the group. |
| `InvalidToken` error on startup | Token copied wrong. Re-copy from BotFather. |
| Canvas never updates | Not enough messages to hit `BATCH_SIZE`. Send `/sync`, or lower `BATCH_SIZE`. |
| Guardian never alerts | Nothing is `validated` yet, or confidence below threshold. Send a decisive batch first; lower `CONFIDENCE_THRESHOLD`. |
| First RAG/embedding use hangs briefly | One-time ~80 MB model download to `~/.cache/chroma`. Wait it out; subsequent runs are fast. |
| LLM auth/quota errors | Check the chosen provider's key (`OPENAI_API_KEY` or `GEMINI_API_KEY`) and account credits/quota. Extraction/guardian fail silently (no group spam) but the canvas won't update. |
| `Unknown LLM_PROVIDER '...'` on startup | `LLM_PROVIDER` must be exactly `openai` or `gemini`. |
| Gemini `404`/model-not-found | Your key lacks access to `gemini-3.5-flash`. Set `GEMINI_MODEL=gemini-2.5-flash`. |

---

## 11. Resetting between tests

```bash
# Stop the bot (Ctrl+C), then:
rm -f concierge.db          # wipe the strategic base
rm -rf chroma               # wipe RAG vectors
# Restart: PYTHONPATH=src python -m concierge.main
```

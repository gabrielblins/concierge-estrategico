# PPGEEC2327 - TÓPICOS ESPECIAIS EM PROCESSAMENTO INTELIGENTE DA INFORMAÇÃO - T01 (2026.1 - 5T3456) <br> [Link para o vídeo de apresentação]()

## Discentes:
- Gabriel Barros Lins Lelis de Oliveira.
- Luiz de França Afonso Ferreira Filho.



# Strategic Concierge Bot

Telegram bot that turns team conversations into a living strategic base:
extracts decisions/hypotheses/premises, keeps a Business Model Canvas updated,
and alerts the team when discussions contradict validated strategy.

## Setup

Agent framework: **Google ADK** (`LlmAgents` + `Runner` + `AgentExecutor`, plus a
deterministic `MessageFunnelAgent`) — pinned via `google-adk==2.3.0` /
`litellm==1.83.7`.

    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env   # set TELEGRAM_TOKEN, pick LLM_PROVIDER (openai|gemini), fill that provider's key

## Run

    python -m concierge.main

## Test

    pytest

## Commands

- `/start` — activate the bot in a group (shows monitoring notice)
- `/sync` — force a canvas update now
- `/status` — show the current canvas
- `/why` — explain the last coherence alert
- `/forget` — delete all project data
- `/upload` — (arquivo com legenda, reply a arquivo, ou texto colado) adiciona material de referência
- `/materials` — lista os materiais ingeridos e as capacidades destravadas
- `/personality` — define a voz do bot (presets: mentor, coach, zen, formal — ou descrição livre; `reset` limpa)
- /canvas — abre o Mini App com o Business Model Canvas visual

## Participation

Mention the bot (`@your_bot`) or reply to one of its messages and it answers
as a team member, drawing on the conversation, the strategic base, and the
uploaded materials. It also makes rare spontaneous contributions (connections,
material knowledge, questions, synthesis) gated by relevance and a cooldown —
tune with `PARTICIPATION_ENABLED`, `PARTICIPATION_COOLDOWN`,
`PARTICIPATION_THRESHOLD`.

## Canvas Mini App

Run the web app alongside the bot and expose it via an HTTPS tunnel:

    PYTHONPATH=src python -m concierge.webapp        # serves on WEBAPP_PORT (8080)
    cloudflared tunnel --url http://localhost:8080   # public HTTPS URL

Register the Mini App with @BotFather (`/newapp`, pick a short name, set the
tunnel URL) and put the short name in `WEBAPP_APP_NAME`. Then `/canvas` in the
group posts a button that opens the live canvas inside Telegram.

## Privacy

The bot only acts in groups where it was added and activated via `/start`,
and announces that it is monitoring. `/why` explains every intervention;
`/forget` erases all stored data.

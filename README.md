# Strategic Concierge Bot

Telegram bot that turns team conversations into a living strategic base:
extracts decisions/hypotheses/premises, keeps a Business Model Canvas updated,
and alerts the team when discussions contradict validated strategy.

## Setup

    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env   # fill in TELEGRAM_TOKEN and OPENAI_API_KEY

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

## Privacy

The bot only acts in groups where it was added and activated via `/start`,
and announces that it is monitoring. `/why` explains every intervention;
`/forget` erases all stored data.

import sqlite3
import chromadb
from concierge.config import Settings
from concierge.storage import Storage
from concierge.extractor import Extractor
from concierge.updater import CanvasUpdater
from concierge.guardian import Guardian
from concierge.knowledge import KnowledgeBase
from concierge.orchestrator import Orchestrator
from concierge.reconciler import Reconciler
from concierge.llm.openai_client import OpenAILLMClient
from concierge.bot import build_application


def main():
    settings = Settings.from_env()
    missing = [
        name
        for name, value in (
            ("TELEGRAM_TOKEN", settings.telegram_token),
            ("OPENAI_API_KEY", settings.openai_api_key),
        )
        if not value
    ]
    if missing:
        raise SystemExit(
            "Missing required environment variable(s): "
            + ", ".join(missing)
            + ". Copy .env.example to .env, fill these in, and export them "
            "(e.g. `set -a; source .env; set +a`) before running."
        )
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    storage = Storage(conn)
    storage.init_schema()
    llm = OpenAILLMClient(settings.openai_api_key)
    knowledge = KnowledgeBase(chromadb.PersistentClient(path=settings.chroma_path))
    orchestrator = Orchestrator(
        storage=storage,
        extractor=Extractor(llm),
        updater=CanvasUpdater(llm),
        guardian=Guardian(llm),
        knowledge=knowledge,
        settings=settings,
        reconciler=Reconciler(llm),
    )
    app = build_application(orchestrator, settings.telegram_token)
    app.run_polling()


if __name__ == "__main__":
    main()

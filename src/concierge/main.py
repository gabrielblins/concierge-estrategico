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
from concierge.participant import Participant
from concierge.llm.factory import build_llm
from concierge.bot import build_application
from concierge.materials import MaterialService
from concierge.stylist import Stylist


def _check_credentials(settings):
    required = [("TELEGRAM_TOKEN", settings.telegram_token)]
    provider = settings.llm_provider.strip().lower()
    if provider == "openai":
        required.append(("OPENAI_API_KEY", settings.openai_api_key))
    elif provider == "gemini":
        required.append(("GEMINI_API_KEY", settings.gemini_api_key))
    else:
        raise SystemExit(
            f"Unknown LLM_PROVIDER '{settings.llm_provider}'. "
            "Valid options: openai, gemini."
        )
    missing = [name for name, value in required if not value]
    if missing:
        raise SystemExit(
            "Missing required environment variable(s): "
            + ", ".join(missing)
            + ". Copy .env.example to .env, fill these in, and export them "
            "(e.g. `set -a; source .env; set +a`) before running."
        )


def main():
    settings = Settings.from_env()
    _check_credentials(settings)
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    storage = Storage(conn)
    storage.init_schema()
    llm = build_llm(settings)
    knowledge = KnowledgeBase(chromadb.PersistentClient(path=settings.chroma_path))
    orchestrator = Orchestrator(
        storage=storage,
        extractor=Extractor(llm),
        updater=CanvasUpdater(llm),
        guardian=Guardian(llm),
        knowledge=knowledge,
        settings=settings,
        reconciler=Reconciler(llm),
        participant=Participant(llm),
    )
    material_service = MaterialService(llm, knowledge, storage)
    stylist = Stylist(llm)
    app = build_application(orchestrator, settings.telegram_token, material_service, stylist)
    app.run_polling()


if __name__ == "__main__":
    main()

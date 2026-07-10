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
from concierge.agents.definitions import build_agents
from concierge.agents.executor import AgentExecutor
from concierge.agents.model_factory import agent_model, configure_env
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
    configure_env(settings)
    model = agent_model(settings)
    agents = build_agents(model)
    executor = AgentExecutor()
    knowledge = KnowledgeBase(chromadb.PersistentClient(path=settings.chroma_path))
    orchestrator = Orchestrator(
        storage=storage,
        extractor=Extractor(executor, agents["extractor"]),
        updater=CanvasUpdater(executor, agents["canvas_updater"]),
        guardian=Guardian(executor, agents["guardian"]),
        knowledge=knowledge,
        settings=settings,
        reconciler=Reconciler(executor, agents["reconciler"]),
        participant=Participant(executor, agents["participant_consider"], agents["participant_respond"]),
    )
    material_service = MaterialService(executor, agents["material_classifier"], knowledge, storage)
    stylist = Stylist(executor, agents["stylist"])
    app = build_application(orchestrator, settings.telegram_token, material_service, stylist)
    app.run_polling()


if __name__ == "__main__":
    main()

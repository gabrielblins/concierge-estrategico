import sqlite3
import chromadb
from concierge.config import Settings
from concierge.storage import Storage
from concierge.extractor import Extractor
from concierge.updater import CanvasUpdater
from concierge.guardian import Guardian
from concierge.knowledge import KnowledgeBase
from concierge.orchestrator import Orchestrator
from concierge.llm.openai_client import OpenAILLMClient
from concierge.bot import build_application


def main():
    settings = Settings.from_env()
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
    )
    app = build_application(orchestrator, settings.telegram_token)
    app.run_polling()


if __name__ == "__main__":
    main()

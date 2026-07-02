import os
from dataclasses import dataclass


@dataclass
class Settings:
    telegram_token: str
    openai_api_key: str
    db_path: str = "concierge.db"
    chroma_path: str = "./chroma"
    batch_size: int = 15
    confidence_threshold: float = 0.75
    llm_provider: str = "openai"
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    participation_enabled: bool = True
    participation_cooldown: int = 10
    participation_threshold: float = 0.75
    webapp_app_name: str = ""
    webapp_port: int = 8080

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            telegram_token=os.environ.get("TELEGRAM_TOKEN", ""),
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            db_path=os.environ.get("DB_PATH", "concierge.db"),
            chroma_path=os.environ.get("CHROMA_PATH", "./chroma"),
            batch_size=int(os.environ.get("BATCH_SIZE", "15")),
            confidence_threshold=float(os.environ.get("CONFIDENCE_THRESHOLD", "0.75")),
            llm_provider=os.environ.get("LLM_PROVIDER", "openai"),
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"),
            participation_enabled=(
                os.environ.get("PARTICIPATION_ENABLED", "true").lower() != "false"
            ),
            participation_cooldown=int(os.environ.get("PARTICIPATION_COOLDOWN", "10")),
            participation_threshold=float(
                os.environ.get("PARTICIPATION_THRESHOLD", "0.75")
            ),
            webapp_app_name=os.environ.get("WEBAPP_APP_NAME", ""),
            webapp_port=int(os.environ.get("WEBAPP_PORT", "8080")),
        )

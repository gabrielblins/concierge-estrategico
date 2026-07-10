import os


def configure_env(settings) -> None:
    """Export the env vars ADK/litellm read for the configured provider."""
    if settings.gemini_api_key:
        os.environ.setdefault("GOOGLE_API_KEY", settings.gemini_api_key)


def agent_model(settings):
    """Return the ADK model spec for the configured provider."""
    provider = settings.llm_provider.strip().lower()
    if provider == "gemini":
        return settings.gemini_model
    from google.adk.models.lite_llm import LiteLlm

    return LiteLlm(model=f"openai/{settings.openai_model}")

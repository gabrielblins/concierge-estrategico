from concierge.llm.client import LLMError
from concierge.llm.openai_client import OpenAILLMClient
from concierge.llm.gemini_client import GeminiLLMClient


def build_llm(settings):
    provider = settings.llm_provider.strip().lower()
    if provider == "openai":
        if not settings.openai_api_key:
            raise LLMError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set.")
        return OpenAILLMClient(settings.openai_api_key, settings.openai_model)
    if provider == "gemini":
        if not settings.gemini_api_key:
            raise LLMError("LLM_PROVIDER=gemini but GEMINI_API_KEY is not set.")
        return GeminiLLMClient(settings.gemini_api_key, settings.gemini_model)
    raise LLMError(
        f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Valid options: openai, gemini."
    )

import json
from google import genai
from google.genai import types
from concierge.llm.client import LLMClient, LLMError


class GeminiLLMClient(LLMClient):
    def __init__(self, api_key: str, model: str = "gemini-3.5-flash"):
        self.model = model
        self._client = genai.Client(api_key=api_key)

    def complete_json(self, system: str, user: str) -> dict:
        try:
            resp = self._client.models.generate_content(
                model=self.model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                ),
            )
            return json.loads(resp.text)
        except Exception as e:
            raise LLMError(str(e)) from e

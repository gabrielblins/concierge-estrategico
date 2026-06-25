import json
from openai import OpenAI
from concierge.llm.client import LLMClient, LLMError


class OpenAILLMClient(LLMClient):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.model = model
        self._client = OpenAI(api_key=api_key)

    def complete_json(self, system: str, user: str) -> dict:
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            content = resp.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            raise LLMError(str(e)) from e

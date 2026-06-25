from abc import ABC, abstractmethod

from pydantic import BaseModel, ValidationError


class LLMError(Exception):
    pass


class LLMClient(ABC):
    @abstractmethod
    def complete_json(self, system: str, user: str) -> dict:
        ...


class FakeLLMClient(LLMClient):
    def __init__(self, responses=None, error=None):
        self._responses = list(responses or [])
        self._error = error
        self.calls = []

    def complete_json(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        if self._error is not None:
            raise self._error
        if not self._responses:
            raise LLMError("no more fake responses queued")
        return self._responses.pop(0)


def call_validated(client, system, user, schema):
    for _ in range(2):
        try:
            raw = client.complete_json(system, user)
            return schema.model_validate(raw)
        except (LLMError, ValidationError):
            continue
    return None

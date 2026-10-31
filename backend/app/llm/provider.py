import os
from typing import Protocol

from app.llm.openai_compat import OpenAICompatProvider
from app.llm.stub import StubProvider, stub_provider


class Provider(Protocol):
    async def extract(self, masked_text: str, schema: dict, case_id: str | None = None) -> dict: ...
    async def rewrite(self, template: str, facts: dict, language: str, tone: str, case_id: str | None = None) -> str: ...


_openai_provider: OpenAICompatProvider | None = None


def get_provider_name() -> str:
    return os.environ.get("LLM_PROVIDER", "stub").strip().lower() or "stub"


def get_provider() -> Provider:
    global _openai_provider
    name = get_provider_name()
    if name == "stub":
        return stub_provider
    if _openai_provider is None:
        _openai_provider = OpenAICompatProvider(preset_name=name)
    return _openai_provider


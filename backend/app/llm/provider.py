import os
from typing import Protocol

from app.llm.openai_compat import OpenAICompatProvider
from app.llm.stub import StubProvider, stub_provider


class Provider(Protocol):
    async def extract(self, masked_text: str, schema: dict, case_id: str | None = None) -> dict: ...
    async def rewrite(self, template: str, facts: dict, language: str, tone: str, case_id: str | None = None) -> str: ...


_openai_provider: OpenAICompatProvider | None = None


def get_provider_name() -> str:
    raw = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if raw:
        return raw
    # If a Sarvam API key is available, main provider is Sarvam AI.
    # Stub is only a fallback when no API key is configured.
    from app.llm.openai_compat import get_sarvam_api_keys
    if get_sarvam_api_keys():
        return "sarvam"
    return "stub"


def get_provider() -> Provider:
    global _openai_provider
    name = get_provider_name()
    if name == "stub":
        return stub_provider
    if _openai_provider is None:
        _openai_provider = OpenAICompatProvider(preset_name=name)
    return _openai_provider


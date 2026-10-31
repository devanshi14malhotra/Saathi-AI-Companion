import json
import os
import re
import time
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import cfg_mgr
from app.db.core import execute, utc_now_iso
from app.llm.prompts import build_extraction_system_prompt, build_rewrite_prompt
from app.llm.schemas import Extraction, post_process_extraction
from app.llm.stub import StubProvider

THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)
FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S | re.I)


def clean_json_text(raw: str) -> str:
    s = THINK_RE.sub("", raw or "").strip()
    m = FENCE_RE.search(s)
    if m:
        s = m.group(1).strip()
    first = s.find("{")
    last = s.rfind("}")
    if first != -1 and last != -1 and last > first:
        return s[first : last + 1]
    return s


def get_sarvam_api_keys() -> list[str]:
    """
    Returns all configured Sarvam API keys in priority order:
    Supports SARVAM_API_KEY (single or comma-separated) + SARVAM_API_KEY_2.
    """
    keys: list[str] = []
    raw1 = os.environ.get("SARVAM_API_KEY", "").strip()
    raw2 = os.environ.get("SARVAM_API_KEY_2", "").strip()
    for part in raw1.split(","):
        k = part.strip()
        if k and k not in keys:
            keys.append(k)
    if raw2 and raw2 not in keys:
        keys.append(raw2)
    return keys


class OpenAICompatProvider:
    def __init__(self, preset_name: str = "sarvam") -> None:
        self.preset_name = preset_name
        self._stub_fallback = StubProvider()

    def _get_preset(self) -> dict[str, Any]:
        presets = cfg_mgr.llm.get("provider_presets", {})
        preset = dict(presets.get(self.preset_name, presets.get("sarvam", {})))
        if os.environ.get("LLM_BASE_URL"):
            preset["base_url"] = os.environ["LLM_BASE_URL"].rstrip("/")
        return preset

    def _build_headers(self, preset: dict[str, Any], api_key: str, alt_auth: bool = False) -> dict[str, str]:
        auth_header = preset.get("auth_header", "api-subscription-key")
        headers = {"Content-Type": "application/json"}
        if not alt_auth and auth_header.lower() == "api-subscription-key":
            headers["api-subscription-key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    async def _post_chat(
        self,
        messages: list[dict[str, str]],
        case_id: str | None = None,
        kind: str = "extract",
    ) -> str:
        preset = self._get_preset()
        base_url = str(preset.get("base_url", "https://api.sarvam.ai")).rstrip("/")
        chat_path = str(preset.get("chat_path", "/v1/chat/completions"))
        url = f"{base_url}{chat_path}"
        timeout_s = float(preset.get("timeout_s", 20))

        keys = get_sarvam_api_keys()
        if not keys:
            raise RuntimeError("No SARVAM_API_KEY configured in .env")

        last_err: Exception | None = None
        for api_key in keys:
            payload: dict[str, Any] = {
                "model": preset.get("model", "sarvam-105b"),
                "messages": messages,
                "temperature": float(preset.get("temperature", 0.0)),
                "max_tokens": int(preset.get("max_tokens", 800)),
            }
            if preset.get("reasoning_effort"):
                payload["reasoning_effort"] = preset["reasoning_effort"]

            t0 = time.perf_counter()
            try:
                async with httpx.AsyncClient(timeout=timeout_s) as client:
                    r = await client.post(url, headers=self._build_headers(preset, api_key, alt_auth=False), json=payload)
                    if r.status_code in (401, 403):
                        r = await client.post(url, headers=self._build_headers(preset, api_key, alt_auth=True), json=payload)
                    if r.status_code == 400 and "reasoning_effort" in payload:
                        payload.pop("reasoning_effort", None)
                        r = await client.post(url, headers=self._build_headers(preset, api_key, alt_auth=False), json=payload)

                ms = int((time.perf_counter() - t0) * 1000)
                if r.status_code in (401, 402, 403, 429) or r.status_code >= 500:
                    # Try next Sarvam key in pool (Account 2 failover)
                    last_err = RuntimeError(f"Sarvam HTTP {r.status_code}")
                    continue

                r.raise_for_status()
                data = r.json()
                usage = data.get("usage", {})
                tokens_in = int(usage.get("prompt_tokens", 0) or 0)
                tokens_out = int(usage.get("completion_tokens", 0) or 0)
                execute(
                    "INSERT INTO llm_usage(ts, case_id, kind, tokens_in, tokens_out, latency_ms) VALUES (?, ?, ?, ?, ?, ?)",
                    (utc_now_iso(), case_id or "", kind, tokens_in, tokens_out, ms),
                )
                choices = data.get("choices", [])
                if not choices:
                    return ""
                return str(choices[0].get("message", {}).get("content", "") or "")
            except Exception as e:
                last_err = e
                continue

        raise last_err or RuntimeError("All configured Sarvam API keys failed")

    async def extract(self, masked_text: str, schema: dict, case_id: str | None = None) -> dict[str, Any]:
        sys_prompt = build_extraction_system_prompt(schema)
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": masked_text},
        ]
        retries = int(cfg_mgr.llm.get("extract_retries", 1))
        for attempt in range(retries + 1):
            try:
                content = await self._post_chat(messages, case_id=case_id, kind="extract")
                cleaned = clean_json_text(content)
                parsed = json.loads(cleaned)
                validated = Extraction.model_validate(parsed)
                return post_process_extraction(validated).model_dump()
            except (json.JSONDecodeError, ValidationError, httpx.HTTPError, Exception):
                if attempt >= retries:
                    return await self._stub_fallback.extract(masked_text, schema, case_id=case_id)
        return await self._stub_fallback.extract(masked_text, schema, case_id=case_id)

    async def rewrite(self, template: str, facts: dict, language: str, tone: str, case_id: str | None = None) -> str:
        rendered = template.format(**facts)
        sys_prompt = build_rewrite_prompt(language, tone)
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": rendered},
        ]
        try:
            content = await self._post_chat(messages, case_id=case_id, kind="rewrite")
            cleaned = THINK_RE.sub("", content or "").strip()
            return cleaned or rendered
        except Exception:
            return rendered

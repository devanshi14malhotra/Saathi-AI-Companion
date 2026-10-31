import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "backend"))

from app.llm.openai_compat import clean_json_text  # noqa: E402
from app.llm.prompts import build_extraction_system_prompt, build_rewrite_prompt  # noqa: E402
from app.llm.schemas import Extraction  # noqa: E402


async def main() -> int:
    load_dotenv(ROOT_DIR / ".env")
    api_key = os.environ.get("SARVAM_API_KEY", "").strip()
    if not api_key:
        print("STATUS: SKIPPED (SARVAM_API_KEY is not configured in .env)")
        print("Note: A skipped run is not a pass. Configure SARVAM_API_KEY in .env to run live provider verification.")
        return 2

    with open(ROOT_DIR / "config" / "llm.yaml", "r", encoding="utf-8") as f:
        llm_cfg = yaml.safe_load(f)
    preset = llm_cfg["provider_presets"]["sarvam"]
    base_url = os.environ.get("LLM_BASE_URL", preset["base_url"]).rstrip("/")
    url = f"{base_url}{preset['chat_path']}"
    model = preset["model"]

    # Step 1: Test auth style A (api-subscription-key), fallback style B (Bearer)
    auth_style = "api-subscription-key"
    headers = {"Content-Type": "application/json", "api-subscription-key": api_key}
    sys_prompt = build_extraction_system_prompt(Extraction.model_json_schema())

    async with httpx.AsyncClient(timeout=25.0) as client:
        probe_payload = {
            "model": model,
            "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": "My ₹500 payment failed"}],
            "temperature": 0.0,
            "max_tokens": 400,
        }
        r = await client.post(url, headers=headers, json=probe_payload)
        if r.status_code in (401, 403):
            auth_style = "Authorization: Bearer"
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            r = await client.post(url, headers=headers, json=probe_payload)
        if r.status_code in (401, 403):
            print("ERROR: Both auth styles returned 401/403. Check SARVAM_API_KEY.")
            return 1
        print(f"Auth style verified: {auth_style}")

        # Step 2: 20 complaints (7 EN, 7 Hinglish, 6 Hindi from S1-S20)
        with open(ROOT_DIR / "seeds" / "scenarios.yaml", "r", encoding="utf-8") as f:
            scen_data = yaml.safe_load(f)["scenarios"][:20]

        samples: list[str] = []
        for idx, s in enumerate(scen_data):
            if idx < 7:
                samples.append(s["variants"][0].get("text") or s["variants"][0].get("first_text"))
            elif idx < 14:
                v = s["variants"][1] if len(s["variants"]) > 1 else s["variants"][0]
                samples.append(v.get("text") or v.get("first_text"))
            else:
                if "hindi_variant" in s:
                    samples.append(s["hindi_variant"]["text"])
                else:
                    samples.append(s["variants"][0].get("text") or s["variants"][0].get("first_text"))

        valid = 0
        latencies_ms: list[float] = []
        for text in samples:
            t0 = time.perf_counter()
            resp = await client.post(
                url,
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
                    "temperature": 0.0,
                    "max_tokens": 800,
                },
            )
            ms = (time.perf_counter() - t0) * 1000
            latencies_ms.append(ms)
            try:
                content = resp.json()["choices"][0]["message"]["content"]
                parsed = json.loads(clean_json_text(content))
                Extraction.model_validate(parsed)
                valid += 1
            except Exception:
                pass

        print(f"Schema-valid JSON on first try: {valid}/20")

        # Step 3: One rewrite call
        t0 = time.perf_counter()
        rw_resp = await client.post(
            url,
            headers=headers,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": build_rewrite_prompt("hinglish", "empathetic")},
                    {
                        "role": "user",
                        "content": "Aapka ₹500 ka BSES Electricity (TXN-1001) payment debit ke baad fail ho gaya tha. Maine ₹500 ka refund RF-9001 start kar diya hai.",
                    },
                ],
                "temperature": 0.0,
                "max_tokens": 300,
            },
        )
        rw_ms = int((time.perf_counter() - t0) * 1000)
        rw_text = rw_resp.json()["choices"][0]["message"]["content"] if rw_resp.status_code == 200 else "FAILED"
        print(f"Rewrite result ({rw_ms} ms): {rw_text}")

        latencies_ms.sort()
        p50 = int(statistics.median(latencies_ms))
        p95 = int(latencies_ms[min(len(latencies_ms) - 1, int(len(latencies_ms) * 0.95))])
        print(f"Latency p50: {p50} ms | p95: {p95} ms")

        if valid >= 18:
            return 0
        print("Advice: keep Sarvam for rewrite only; use a different OpenAI-compatible model for extract via llm.yaml")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))


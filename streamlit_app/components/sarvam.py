"""
Sarvam AI Integration Service for Paytm Saathi.
Supports:
- Dual-Account API Key Pooling with automatic failover (Account 1 -> Account 2)
- Text-to-Speech (bulbul:v1) in Hindi, English, Hinglish
- Speech-to-Text (saaras:v1)
- Chat Completion (sarvam-30b / sarvam-2b)
"""

import base64
import os
import time
from typing import Any
import httpx
import streamlit as st


from pathlib import Path
from dotenv import load_dotenv

# Ensure .env is loaded
_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


def get_configured_keys() -> list[str]:
    """Retrieves all active Sarvam keys from .env and os.environ."""
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH, override=True)

    keys: list[str] = []
    k1 = os.environ.get("SARVAM_API_KEY", "").strip()
    k2 = os.environ.get("SARVAM_API_KEY_2", "").strip()

    for raw in [k1, k2]:
        for part in raw.split(","):
            token = part.strip()
            if token and token not in keys:
                keys.append(token)
    return keys


def check_sarvam_health(api_key: str) -> dict[str, Any]:
    """Tests key validity against Sarvam API with a minimal completion or TTS ping."""
    if not api_key:
        return {"ok": False, "msg": "API Key is empty"}

    url = "https://api.sarvam.ai/v1/chat/completions"
    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "model": "sarvam-105b",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
        "temperature": 0.0,
    }

    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            latency_ms = int((time.perf_counter() - t0) * 1000)

            if resp.status_code == 200:
                return {"ok": True, "msg": f"Active & Connected ({latency_ms}ms)", "code": 200}
            elif resp.status_code in (401, 403):
                return {"ok": False, "msg": f"Unauthorized / Invalid Key (HTTP {resp.status_code})", "code": resp.status_code}
            elif resp.status_code in (402, 429):
                return {"ok": False, "msg": f"Credits Exhausted / Rate Limited (HTTP {resp.status_code})", "code": resp.status_code}
            else:
                return {"ok": False, "msg": f"HTTP {resp.status_code}: {resp.text[:100]}", "code": resp.status_code}
    except Exception as e:
        return {"ok": False, "msg": f"Network Error: {str(e)}"}


def text_to_speech(
    text: str,
    language_code: str = "hi-IN",
    speaker: str = "priya",
) -> bytes | None:
    """
    Synthesizes speech using Sarvam bulbul:v3 with dual-account failover.
    Returns raw audio WAV bytes or None if unavailable.
    """
    keys = get_configured_keys()
    if not keys:
        return None

    # Sanitize and truncate text for TTS (limit to ~400 chars for latency)
    clean_text = text.replace("**", "").replace("#", "").strip()[:400]
    if not clean_text:
        return None

    url = "https://api.sarvam.ai/text-to-speech"
    payload = {
        "inputs": [clean_text],
        "target_language_code": language_code,
        "speaker": speaker if speaker in ("priya", "rahul", "aditya", "neha", "anushka", "simran", "ritu") else "priya",
        "model": "bulbul:v3",
    }

    for idx, key in enumerate(keys):
        headers = {
            "api-subscription-key": key,
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=12.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    audios = data.get("audios", [])
                    if audios:
                        return base64.b64decode(audios[0])
                elif resp.status_code in (401, 402, 403, 429):
                    # Failover to next key
                    continue
        except Exception:
            continue

    return None


def speech_to_text(
    audio_bytes: bytes,
    language_code: str = "unknown",
) -> str | None:
    """
    Transcribes audio using Sarvam saaras:v3 with dual-account failover.
    """
    keys = get_configured_keys()
    if not keys or not audio_bytes:
        return None

    url = "https://api.sarvam.ai/speech-to-text"
    for key in keys:
        headers = {"api-subscription-key": key}
        files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
        data = {"model": "saaras:v3", "language_code": language_code or "unknown"}
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(url, headers=headers, files=files, data=data)
                if resp.status_code == 200:
                    res = resp.json()
                    return res.get("transcript", "")
                elif resp.status_code in (401, 402, 403, 429):
                    continue
        except Exception:
            continue

    return None


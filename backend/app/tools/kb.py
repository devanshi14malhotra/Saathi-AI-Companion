"""BM25 Knowledge Base search over seeds/help_articles/*.md."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from app.core.config import SEEDS_DIR
from app.tools.client import record_audit, record_case_event

_KB_DOCS: list[dict[str, Any]] = []
_BM25: BM25Okapi | None = None


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _ensure_kb_loaded() -> None:
    global _KB_DOCS, _BM25
    if _KB_DOCS and _BM25 is not None:
        return
    kb_dir: Path = SEEDS_DIR / "help_articles"
    docs: list[dict[str, Any]] = []
    corpus: list[list[str]] = []
    if kb_dir.exists():
        for md_path in sorted(kb_dir.glob("*.md")):
            raw = md_path.read_text(encoding="utf-8")
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            title = lines[0].lstrip("# ").strip() if lines else md_path.stem
            body = " ".join(lines[1:]) if len(lines) > 1 else raw
            doc = {
                "doc_id": md_path.stem,
                "title": title,
                "steps": body,
                "tokens": _tokenize(title + " " + body),
            }
            docs.append(doc)
            corpus.append(doc["tokens"])
    _KB_DOCS = docs
    if corpus:
        _BM25 = BM25Okapi(corpus)


def search_kb(query: str, top_k: int = 2, case_id: str | None = None, actor: str = "saathi") -> list[dict[str, Any]]:
    _ensure_kb_loaded()
    if not _KB_DOCS or _BM25 is None:
        return []
    q_tokens = _tokenize(query)
    scores = _BM25.get_scores(q_tokens) if q_tokens else [0.0] * len(_KB_DOCS)
    ranked = sorted(zip(_KB_DOCS, scores), key=lambda x: x[1], reverse=True)[:top_k]
    results = [
        {
            "doc_id": doc["doc_id"],
            "title": doc["title"],
            "steps": doc["steps"],
            "score": round(float(sc), 3),
        }
        for doc, sc in ranked
    ]
    record_audit(
        actor=actor,
        action="search_kb",
        params={"query": query, "top_k": top_k},
        result={"outcome": "success", "hits": [r["doc_id"] for r in results]},
        idem_key=None,
        case_id=case_id,
    )
    if case_id:
        record_case_event(
            case_id=case_id,
            badge="[TOOL]",
            evt_type="tool_call",
            summary=f"search_kb → top hit {results[0]['doc_id'] if results else 'none'}",
            payload={"tool": "search_kb", "query": query, "results": results},
            latency_ms=4,
            status="ok",
        )
    return results


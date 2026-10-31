"""Saathi v6.0 FastAPI Entrypoint — Mounts /api/* and /mock/{ledger,refunds,crm,notify}."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.console import router as console_router
from app.api.customer import router as customer_router
from app.api.demo import router as demo_router
from app.api.eval import router as eval_router
from app.api.stream import router as stream_router
from app.api.trust import router as trust_router
from app.core.config import cfg_mgr
from app.db.core import init_core_db
from app.llm.provider import get_provider_name
from app.mocks.crm.app import crm_app
from app.mocks.crm.db import crm_db
from app.mocks.crm.seed import seed_crm
from app.mocks.ledger.app import ledger_app
from app.mocks.ledger.db import ledger_db
from app.mocks.ledger.seed import seed_ledger
from app.mocks.notify.app import notify_app
from app.mocks.notify.db import notify_db
from app.mocks.notify.seed import seed_notify
from app.mocks.refunds.app import refunds_app
from app.mocks.refunds.db import refunds_db
from app.mocks.refunds.seed import seed_refunds


def ensure_all_dbs_initialized() -> None:
    """Initializes all 5 SQLite databases on module import and startup (Pitfall 1 & 2 guard)."""
    init_core_db(cfg_mgr.get_default_autonomy())
    ledger_db.init_db()
    if not ledger_db.query_one("SELECT id FROM users LIMIT 1"):
        seed_ledger()
    refunds_db.init_db()
    if not refunds_db.query_one("SELECT date_str FROM bank_holidays LIMIT 1"):
        seed_refunds()
    crm_db.init_db()
    if not crm_db.query_one("SELECT id FROM customers LIMIT 1"):
        seed_crm()
    notify_db.init_db()


ensure_all_dbs_initialized()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_all_dbs_initialized()
    yield


app = FastAPI(
    title="Saathi v6.0 — Autonomous AI Customer-Service Teammate",
    version="6.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the 4 mock downstream services
app.mount("/mock/ledger", ledger_app)
app.mount("/mock/refunds", refunds_app)
app.mount("/mock/crm", crm_app)
app.mount("/mock/notify", notify_app)

# Include REST & SSE routers
app.include_router(customer_router)
app.include_router(console_router)
app.include_router(demo_router)
app.include_router(eval_router)
app.include_router(trust_router)
app.include_router(stream_router)


@app.get("/api/health")
async def get_health():
    return {
        "status": "ok",
        "version": "6.0.0",
        "llm_provider": get_provider_name(),
    }


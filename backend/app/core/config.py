import contextvars
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from app.db.core import execute, query_all, query_one, utc_now_iso

ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")

CONFIG_DIR = ROOT_DIR / "config"
SEEDS_DIR = ROOT_DIR / "seeds"

# Runtime eval context overrides (only active when SAATHI_ENV == "eval")
_eval_ablate_ctx: contextvars.ContextVar[set[str] | None] = contextvars.ContextVar("eval_ablate", default=None)
_eval_arm_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("eval_arm", default=None)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def is_eval_env() -> bool:
    return os.environ.get("SAATHI_ENV", "").strip().lower() == "eval"


def get_ablate_flags() -> set[str]:
    if not is_eval_env():
        return set()
    ctx_val = _eval_ablate_ctx.get()
    if ctx_val is not None:
        return ctx_val
    raw = os.environ.get("SAATHI_ABLATE", "").strip()
    if not raw:
        return set()
    flags = {part.strip().lower() for part in raw.split(",") if part.strip()}
    if "all" in flags:
        return {"no_verify", "no_policy", "no_guard", "no_idem", "no_gate", "all"}
    return flags


def set_eval_ablate(ablate: str | None) -> contextvars.Token:
    if not ablate:
        return _eval_ablate_ctx.set(None)
    flags = {part.strip().lower() for part in ablate.split(",") if part.strip()}
    if "all" in flags:
        flags = {"no_verify", "no_policy", "no_guard", "no_idem", "no_gate", "all"}
    return _eval_ablate_ctx.set(flags)


def reset_eval_ablate(token: contextvars.Token) -> None:
    _eval_ablate_ctx.reset(token)


def is_break_policy() -> bool:
    if not is_eval_env():
        return False
    return os.environ.get("SAATHI_BREAK_POLICY", "").strip() in ("1", "true", "yes")


def get_eval_arm() -> str:
    if not is_eval_env():
        return "C"
    ctx_val = _eval_arm_ctx.get()
    if ctx_val:
        return ctx_val.upper()
    raw = os.environ.get("SAATHI_ARM", "C").strip().upper()
    return raw if raw in ("A", "B", "C") else "C"


def set_eval_arm(arm: str | None) -> contextvars.Token:
    return _eval_arm_ctx.set(arm.upper() if arm else None)


def reset_eval_arm(token: contextvars.Token) -> None:
    _eval_arm_ctx.reset(token)


@dataclass
class PolicyConfig:
    ceiling: int = 25000
    min_auto_confidence: float = 0.70
    confidence_weights: dict[str, float] = field(
        default_factory=lambda: {"understanding": 0.3, "evidence": 0.3, "policy": 0.2, "risk": 0.2}
    )
    velocity_max_auto_refunds_24h: int = 3
    velocity_max_auto_amount_24h: int = 15000
    modes: dict[str, dict[str, int]] = field(
        default_factory=lambda: {
            "suggest": {"auto_cap": 0},
            "guarded": {"auto_cap": 5000},
            "autonomous": {"auto_cap": 25000},
        }
    )
    autonomy: dict[str, str] = field(
        default_factory=lambda: {
            "payment_failure": "guarded",
            "refund": "guarded",
            "settlement": "guarded",
            "app_assistance": "autonomous",
            "fraud": "suggest",
            "fallback": "suggest",
        }
    )
    locked: list[str] = field(default_factory=lambda: ["fraud"])


class ConfigManager:
    def __init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        self.thresholds = _load_yaml(CONFIG_DIR / "thresholds.yaml")
        self.autonomy_cfg = _load_yaml(CONFIG_DIR / "autonomy.yaml")
        self.routing = _load_yaml(CONFIG_DIR / "routing.yaml")
        self.llm = _load_yaml(CONFIG_DIR / "llm.yaml")
        self.templates = _load_yaml(CONFIG_DIR / "templates.yaml")
        self.tat_rules = _load_yaml(CONFIG_DIR / "tat_rules.yaml")
        self.lanes = _load_yaml(CONFIG_DIR / "lanes.yaml")
        self.sensitive = _load_yaml(CONFIG_DIR / "sensitive.yaml")
        self.baselines = _load_yaml(CONFIG_DIR / "baselines.yaml")
        self.services = _load_yaml(CONFIG_DIR / "services.yaml")
        self.pricing = _load_yaml(CONFIG_DIR / "pricing.yaml")
        self.base_seeds = _load_yaml(SEEDS_DIR / "base.yaml")
        self.scenarios_data = _load_yaml(SEEDS_DIR / "scenarios.yaml")
        self.redteam_data = _load_yaml(SEEDS_DIR / "redteam.yaml")

    def get_default_autonomy(self) -> dict[str, str]:
        return dict(self.autonomy_cfg.get("defaults", {}))

    def get_autonomy_modes(self) -> dict[str, str]:
        defaults = self.get_default_autonomy()
        rows = query_all("SELECT key, value FROM config_state WHERE key LIKE 'autonomy:%'")
        for r in rows:
            agent_name = r["key"].split(":", 1)[1]
            defaults[agent_name] = r["value"]
        return defaults

    def set_autonomy_mode(self, agent: str, mode: str, actor: str) -> str:
        locked = self.autonomy_cfg.get("locked", ["fraud"])
        if agent in locked:
            raise ValueError("Agent autonomy is locked")
        if mode not in self.autonomy_cfg.get("modes", {}):
            raise ValueError(f"Unknown mode: {mode}")
        current = self.get_autonomy_modes().get(agent, "guarded")
        execute(
            "INSERT OR REPLACE INTO config_state(key, value) VALUES (?, ?)",
            (f"autonomy:{agent}", mode),
        )
        execute(
            "INSERT INTO config_audit(ts, actor, key, old, new) VALUES (?, ?, ?, ?, ?)",
            (utc_now_iso(), actor, f"autonomy:{agent}", current, mode),
        )
        return current

    def get_killswitches(self) -> dict[str, bool]:
        result = {
            "all": False,
            "payment_failure": False,
            "refund": False,
            "settlement": False,
            "app_assistance": False,
            "fraud": False,
        }
        rows = query_all("SELECT key, value FROM config_state WHERE key LIKE 'paused:%'")
        for r in rows:
            scope = r["key"].split(":", 1)[1]
            result[scope] = r["value"] == "1"
        return result

    def is_agent_paused(self, agent: str) -> bool:
        ks = self.get_killswitches()
        return bool(ks.get("all") or ks.get(agent))

    def set_killswitch(self, scope: str, paused: bool, actor: str) -> bool:
        valid_scopes = {"all", "payment_failure", "refund", "settlement", "app_assistance", "fraud"}
        if scope not in valid_scopes:
            raise ValueError(f"Invalid scope: {scope}")
        old_val = "1" if self.get_killswitches().get(scope, False) else "0"
        new_val = "1" if paused else "0"
        execute(
            "INSERT OR REPLACE INTO config_state(key, value) VALUES (?, ?)",
            (f"paused:{scope}", new_val),
        )
        execute(
            "INSERT INTO config_audit(ts, actor, key, old, new) VALUES (?, ?, ?, ?, ?)",
            (utc_now_iso(), actor, f"paused:{scope}", old_val, new_val),
        )
        return paused

    def get_policy_config(self, override_autonomy: dict[str, str] | None = None) -> PolicyConfig:
        autonomy = override_autonomy if override_autonomy is not None else self.get_autonomy_modes()
        return PolicyConfig(
            ceiling=int(self.thresholds.get("ceiling", 25000)),
            min_auto_confidence=float(self.thresholds.get("min_auto_confidence", 0.70)),
            confidence_weights=dict(
                self.thresholds.get(
                    "confidence_weights",
                    {"understanding": 0.3, "evidence": 0.3, "policy": 0.2, "risk": 0.2},
                )
            ),
            velocity_max_auto_refunds_24h=int(self.thresholds.get("velocity_max_auto_refunds_24h", 3)),
            velocity_max_auto_amount_24h=int(self.thresholds.get("velocity_max_auto_amount_24h", 15000)),
            modes=dict(self.autonomy_cfg.get("modes", {})),
            autonomy=autonomy,
            locked=list(self.autonomy_cfg.get("locked", ["fraud"])),
        )

    def get_personas(self) -> dict[str, dict[str, Any]]:
        personas = {}
        for p in self.base_seeds.get("personas", []):
            personas[p["id"]] = p
        # Hidden cohort personas U-301..U-330 for incident simulation
        for idx in range(301, 331):
            pid = f"U-{idx}"
            if pid not in personas:
                personas[pid] = {
                    "id": pid,
                    "name": f"Cohort User {idx}",
                    "first_name": f"User{idx}",
                    "role": "consumer",
                    "type": "consumer",
                    "language": "hinglish" if idx % 2 == 0 else "en",
                    "hidden": True,
                    "upi_id": f"user{idx}@paytm",
                    "phone": f"+91 980000{idx:04d}",
                    "email": f"user{idx}@example.com",
                    "address": "Sector 62, Noida",
                    "kyc_status": "FULL_KYC",
                    "device_info": {"model": "Redmi Note 12", "os": "Android 13", "app_version": "9.4.1"},
                }
        return personas

    def compute_lane(self, agent: str, triggers: list[str]) -> str:
        red_triggers = set(self.lanes.get("red_triggers", ["T1", "T8"]))
        red_agents = set(self.lanes.get("red_agents", ["fraud"]))
        amber_agents = set(self.lanes.get("amber", ["payment_failure", "refund", "settlement"]))
        if agent in red_agents or any(t in red_triggers for t in triggers):
            return "red"
        if agent in amber_agents:
            return "amber"
        return "green"


cfg_mgr = ConfigManager()


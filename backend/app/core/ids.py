import threading

_lock = threading.Lock()

_DEFAULTS = {
    "case": 1040,
    "refund": 9000,
    "recon": 8000,
    "ticket": 7000,
    "approval": 0,
    "eval": 0,
    "incident": 0,
    "claim": 0,
    "lock": 5000,
    "txn": 2000,
}

_PREFIXES = {
    "case": "C-",
    "refund": "RF-",
    "recon": "RC-",
    "ticket": "TK-",
    "approval": "AP-",
    "eval": "EV-",
    "incident": "INC-",
    "claim": "CMP-",
    "lock": "LK-",
    "txn": "TXN-",
}

_counters = dict(_DEFAULTS)


def reset_ids(preserve_eval: bool = True) -> None:
    with _lock:
        eval_val = _counters.get("eval", 0)
        _counters.clear()
        _counters.update(_DEFAULTS)
        if preserve_eval:
            _counters["eval"] = eval_val


def set_min_counter(kind: str, val: int) -> None:
    with _lock:
        if val > _counters.get(kind, _DEFAULTS.get(kind, 0)):
            _counters[kind] = val


def next_id(kind: str) -> str:
    with _lock:
        _counters[kind] = _counters.get(kind, _DEFAULTS.get(kind, 0)) + 1
        return f"{_PREFIXES[kind]}{_counters[kind]}"


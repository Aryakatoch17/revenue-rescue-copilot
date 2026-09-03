from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIAGNOSIS_CACHE = ROOT / "data" / "diagnosis_cache.json"
LINK_CACHE = ROOT / "data" / "razorpay_link_cache.json"


def fingerprint(record: dict) -> str:
    notes = (record.get("notes") or "").replace(" | FORCE_RZP_ERROR", "")
    parts = [
        str(record.get("id") or ""),
        str(record.get("record_type") or ""),
        str(record.get("error_code") or ""),
        str(record.get("error_description") or ""),
        notes,
    ]
    return "|".join(parts)


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def get_diagnosis(record: dict) -> dict | None:
    key = fingerprint(record)
    row = _load(DIAGNOSIS_CACHE).get(key)
    if not row:
        return None
    out = dict(row)
    src = out.get("source") or "llm"
    if not str(src).endswith("_cache"):
        out["source"] = f"{src}_cache"
    return out


def put_diagnosis(record: dict, result: dict) -> None:
    data = _load(DIAGNOSIS_CACHE)
    stored = {
        "cause": result["cause"],
        "confidence": result.get("confidence"),
        "rationale": result.get("rationale"),
        "source": result.get("source") or "llm",
    }
    data[fingerprint(record)] = stored
    _save(DIAGNOSIS_CACHE, data)


def get_link(record_id: str, action: str) -> dict | None:
    return _load(LINK_CACHE).get(f"{record_id}:{action}")


def put_link(record_id: str, action: str, payload: dict) -> None:
    data = _load(LINK_CACHE)
    data[f"{record_id}:{action}"] = {
        "link_id": payload.get("link_id"),
        "short_url": payload.get("short_url"),
        "mode": payload.get("mode"),
    }
    _save(LINK_CACHE, data)


def cache_stats() -> dict:
    return {
        "diagnoses": len(_load(DIAGNOSIS_CACHE)),
        "links": len(_load(LINK_CACHE)),
    }

import json

from app.cache import fingerprint, get_diagnosis
from app.db import connect
from app.diagnosis import AGENT_FIELDS, agent_view, diagnose
from app.seed import seed


def test_agent_view_strips_hidden_cause():
    rec = {
        "id": "atr_001",
        "record_type": "payment_failed",
        "amount_paise": 100,
        "error_code": "X",
        "error_description": "Bank is currently down",
        "notes": "npci",
        "opted_out": 0,
        "true_cause": "bank_down",
    }
    view = agent_view(rec)
    assert "true_cause" not in view
    assert set(view) <= set(AGENT_FIELDS)
    blob = json.dumps(view)
    assert "true_cause" not in blob
    assert "bank_down" not in blob  # label itself must not be copied as a field value


def test_diagnose_does_not_use_hidden_cause_as_input():
    rec = {
        "id": "atr_poison",
        "record_type": "checkout_abandoned",
        "amount_paise": 49900,
        "error_code": None,
        "error_description": None,
        "notes": "user closed sheet",
        "opted_out": 0,
        "true_cause": "fraud_flag",  # would inflate accuracy if leaked
    }
    out = diagnose(rec)
    # Must not parrot the hidden label when metadata says abandoned cart.
    assert out["cause"] != "fraud_flag"


def test_reseed_fingerprints_match_baked_cache():
    seed()
    conn = connect()
    rows1 = [dict(r) for r in conn.execute("SELECT * FROM records ORDER BY id").fetchall()]
    conn.close()
    seed()
    conn = connect()
    rows2 = [dict(r) for r in conn.execute("SELECT * FROM records ORDER BY id").fetchall()]
    conn.close()
    assert [r["id"] for r in rows1] == [r["id"] for r in rows2]
    hits = 0
    for a, b in zip(rows1, rows2, strict=True):
        assert fingerprint(a) == fingerprint(b)
        assert a["true_cause"] == b["true_cause"]
        # amount jitter is seeded (Random(42)); still not part of cache key
        cached = get_diagnosis(a)
        if cached:
            hits += 1
    assert hits >= 50


def test_diagnose_fails_closed_without_calling_groq(monkeypatch):
    monkeypatch.setattr("app.diagnosis.settings.diagnosis_mode", "live")
    monkeypatch.setattr("app.diagnosis.settings.allow_live_llm", False)
    monkeypatch.setattr("app.diagnosis.llm_configured", lambda: True)

    def boom(*_a, **_k):
        raise AssertionError("Groq must not be called")

    monkeypatch.setattr("app.diagnosis._llm_diagnose", boom)
    rec = {
        "id": "atr_001",
        "record_type": "payment_failed",
        "error_code": "GATEWAY_ERROR",
        "error_description": "Issuer unavailable / NPCI timeout",
        "notes": "UPI collect expired at NPCI",
        "opted_out": 0,
        "amount_paise": 189900,
        "true_cause": "bank_down",
    }
    out = diagnose(rec)
    assert out.get("cause")
    assert "groq" not in (out.get("source") or "") or "cache" in (out.get("source") or "")

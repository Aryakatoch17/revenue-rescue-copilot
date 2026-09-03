from app.cache import get_diagnosis, put_diagnosis
from app.diagnosis import diagnose


def test_cache_replay_does_not_need_live_llm():
    rec = {
        "id": "atr_cache",
        "record_type": "payment_failed",
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Card expired",
        "notes": "token",
        "opted_out": 0,
        "amount_paise": 10000,
    }
    put_diagnosis(
        rec,
        {
            "cause": "instrument_expired",
            "confidence": 0.9,
            "rationale": "baked",
            "source": "llm",
        },
    )
    hit = get_diagnosis(rec)
    assert hit["cause"] == "instrument_expired"
    assert hit["source"] == "llm_cache"
    out = diagnose(rec)
    assert out["cause"] == "instrument_expired"
    assert "cache" in out["source"]

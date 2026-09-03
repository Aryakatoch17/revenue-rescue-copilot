"""Bake Groq diagnoses once. Judges replay the cache.

  DIAGNOSIS_MODE=live python -m app.bake
"""

from __future__ import annotations

import time

from app.cache import cache_stats, put_diagnosis
from app.config import settings
from app.db import connect
from app.diagnosis import _llm_diagnose, rule_diagnose
from app.llm import llm_configured
from app.seed import seed


def bake() -> dict:
    n = seed()
    conn = connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM records ORDER BY id").fetchall()]
    conn.close()
    llm = 0
    rules = 0
    use_groq = llm_configured()  # bake always hits Groq when a key exists
    for rec in rows:
        rec.pop("true_cause", None)
        if use_groq:
            try:
                result = _llm_diagnose(rec)
                llm += 1
                time.sleep(2.2)  # stay under Groq free ~30 RPM
            except Exception:
                result = rule_diagnose(rec)
                rules += 1
        else:
            result = rule_diagnose(rec)
            rules += 1
        put_diagnosis(rec, result)
    return {
        "records": n,
        "groq": llm,
        "rules": rules,
        "model": settings.groq_model if use_groq else None,
        **cache_stats(),
    }


if __name__ == "__main__":
    print(bake())

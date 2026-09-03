from __future__ import annotations

import json
import re

from app.cache import get_diagnosis, put_diagnosis
from app.config import settings
from app.enums import Cause
from app.llm import chat_json, llm_configured

# Never include true_cause. This is the only dict that may go to Groq, rules, or cache lookup.
AGENT_FIELDS = (
    "id",
    "record_type",
    "amount_paise",
    "error_code",
    "error_description",
    "notes",
    "opted_out",
)

SYSTEM = """You are a payments recovery diagnostician for Indian Razorpay merchants.
Given a failed/at-risk transaction, classify the MOST LIKELY root cause.
Return JSON only:
{"cause": "<enum>", "confidence": 0.0-1.0, "rationale": "one sentence"}

cause MUST be one of:
bank_down, insufficient_funds, instrument_expired, mandate_paused,
checkout_abandoned, invoice_unpaid, customer_cancelled, fraud_flag

Rules:
- Prefer instrument_expired if card/UPI token expiry or "card expired" appears.
- Prefer insufficient_funds for NSF, E001, "not enough balance".
- Prefer bank_down for gateway/issuer/NPCI/timeout/5xx/BANK_OFFLINE.
- Prefer mandate_paused for eNACH/mandate/subscription authorization paused.
- Prefer checkout_abandoned when there is no capture and the cart was left.
- Prefer invoice_unpaid for overdue B2B invoices without a hard decline.
- Prefer customer_cancelled for explicit revoke/cancel/unsubscribe.
- Prefer fraud_flag for fraud, blocked, RBI, velocity, stolen.
Do not invent other cause strings.
"""

ERROR_HINTS: list[tuple[re.Pattern, Cause]] = [
    (re.compile(r"fraud|stolen|blocked.?bin|velocity", re.I), Cause.FRAUD_FLAG),
    (re.compile(r"cancel|unsubscrib|revok|customer.?request", re.I), Cause.CUSTOMER_CANCELLED),
    (re.compile(r"mandat|enach|nach.?pause|paused", re.I), Cause.MANDATE_PAUSED),
    (re.compile(r"expir|invalid.?card|instrument.?invalid|token.?dead", re.I), Cause.INSTRUMENT_EXPIRED),
    (re.compile(r"insufficient|nsf|e001|no.?balance|funds", re.I), Cause.INSUFFICIENT_FUNDS),
    (re.compile(r"timeout|bank.?down|npci|issuer.?unavailable|offline|5\d\d|gateway", re.I), Cause.BANK_DOWN),
    (re.compile(r"abandon|checkout|cart", re.I), Cause.CHECKOUT_ABANDONED),
    (re.compile(r"invoice|overdue|receivable", re.I), Cause.INVOICE_UNPAID),
]


def agent_view(record: dict) -> dict:
    return {k: record[k] for k in AGENT_FIELDS if k in record}


def rule_diagnose(record: dict) -> dict:
    rec = agent_view(record)
    blob = " ".join(
        str(rec.get(k) or "")
        for k in ("error_code", "error_description", "notes", "record_type")
    )
    for pat, cause in ERROR_HINTS:
        if pat.search(blob):
            return {
                "cause": cause.value,
                "confidence": 0.72,
                "rationale": f"Rule match on '{pat.pattern[:40]}…' in payment metadata.",
                "source": "rules",
            }
    fallback = {
        "payment_failed": Cause.INSUFFICIENT_FUNDS,
        "subscription_failed": Cause.MANDATE_PAUSED,
        "checkout_abandoned": Cause.CHECKOUT_ABANDONED,
        "invoice_overdue": Cause.INVOICE_UNPAID,
    }
    cause = fallback.get(rec.get("record_type"), Cause.INVOICE_UNPAID)
    return {
        "cause": cause.value,
        "confidence": 0.45,
        "rationale": "Weak signal; fell back to record type prior.",
        "source": "rules",
    }


def _llm_diagnose(record: dict) -> dict:
    payload = agent_view(record)
    assert "true_cause" not in payload
    data = chat_json(system=SYSTEM, user=json.dumps(payload), temperature=0)
    cause = Cause(data["cause"])
    return {
        "cause": cause.value,
        "confidence": float(data.get("confidence", 0.5)),
        "rationale": str(data.get("rationale", ""))[:400],
        "source": "groq",
    }


def diagnose(record: dict) -> dict:
    rec = agent_view(record)
    mode = settings.diagnosis_mode
    if mode != "live" or not settings.allow_live_llm:
        cached = get_diagnosis(rec)
        if cached:
            return cached
        return rule_diagnose(rec)

    cached = get_diagnosis(rec)
    if cached:
        return cached
    if not llm_configured():
        return rule_diagnose(rec)
    try:
        result = _llm_diagnose(rec)
        put_diagnosis(rec, result)
        return result
    except Exception as exc:  # noqa: BLE001
        fallback = rule_diagnose(rec)
        fallback["rationale"] = f"Groq failed ({exc}); {fallback['rationale']}"
        fallback["source"] = "rules_fallback"
        return fallback

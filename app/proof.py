from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone

from app.config import settings
from app.db import connect, init_db, row_to_dict
from app.enums import Action, Outcome
from app.razorpay_exec import RazorpayExecutor
from app.seed import seed

# Cap brand-new Payment Link creates so judges mashing the button don't burn test-mode quota.
_PROOF_CREATE_TIMES: list[float] = []
_PROOF_MAX_PER_HOUR = 25


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_batch() -> None:
    init_db()
    conn = connect()
    n = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    conn.close()
    if n == 0:
        seed()


def verify_signature(body: bytes, signature: str | None) -> bool:
    secret = settings.razorpay_webhook_secret
    if not secret or not signature:
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def _action_for(rec: dict) -> Action:
    if rec["record_type"] == "checkout_abandoned":
        return Action.CART_REMINDER_LINK
    if rec["record_type"] == "invoice_overdue":
        return Action.INVOICE_LINK
    if rec["record_type"] == "subscription_failed":
        return Action.REMANDATE_LINK
    return Action.UPDATE_INSTRUMENT_LINK


def _is_stop(cause: str) -> bool:
    return cause in {"customer_cancelled", "fraud_flag"}


def _rate_limit_ok() -> bool:
    cutoff = time.time() - 3600
    while _PROOF_CREATE_TIMES and _PROOF_CREATE_TIMES[0] < cutoff:
        _PROOF_CREATE_TIMES.pop(0)
    return len(_PROOF_CREATE_TIMES) < _PROOF_MAX_PER_HOUR


def _find_open_proof(conn, record_id: str) -> dict | None:
    row = conn.execute(
        """
        SELECT * FROM decisions
        WHERE record_id=? AND policy='proof' AND outcome=?
          AND razorpay_link_id IS NOT NULL
        ORDER BY created_at DESC LIMIT 1
        """,
        (record_id, Outcome.AWAITING_PAYMENT.value),
    ).fetchone()
    return row_to_dict(row)


def start_live_proof(record_id: str) -> dict:
    """Cold-start safe: seeds batch if empty; reuses an open unpaid link when possible."""
    _ensure_batch()
    init_db()
    conn = connect()
    rec = conn.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
    if not rec:
        conn.close()
        raise KeyError(record_id)
    rec = dict(rec)
    if _is_stop(rec.get("true_cause", "")):
        conn.close()
        raise ValueError("Cannot open live proof on cancelled/fraud rows — pick another record.")

    existing = _find_open_proof(conn, record_id)
    if existing and existing.get("razorpay_link_id"):
        conn.close()
        return {
            "decision": existing,
            "pay_url": existing.get("razorpay_short_url"),
            "link_id": existing.get("razorpay_link_id"),
            "mode": "reused",
            "reused": True,
            "hint": "Reusing an unpaid proof link for this record (safe under judge mash / refresh).",
        }

    action = _action_for(rec)
    rzp = RazorpayExecutor()
    if not rzp.live:
        conn.close()
        raise RuntimeError(
            "Razorpay test keys are not configured on this host. "
            "Batch eval (Reseed / Run baseline+agent) still works fully. "
            "Live proof needs RAZORPAY_KEY_ID + RAZORPAY_KEY_SECRET."
        )

    if not _rate_limit_ok():
        # Prefer any recent open proof on any record rather than failing hard.
        any_open = row_to_dict(
            conn.execute(
                """
                SELECT * FROM decisions
                WHERE policy='proof' AND outcome=? AND razorpay_link_id IS NOT NULL
                ORDER BY created_at DESC LIMIT 1
                """,
                (Outcome.AWAITING_PAYMENT.value,),
            ).fetchone()
        )
        conn.close()
        if any_open:
            return {
                "decision": any_open,
                "pay_url": any_open.get("razorpay_short_url"),
                "link_id": any_open.get("razorpay_link_id"),
                "mode": "reused_rate_limit",
                "reused": True,
                "hint": "New link rate limit hit — reusing an existing unpaid proof link.",
            }
        raise RuntimeError(
            "Too many new Payment Links in the last hour (protects Razorpay test quota). "
            "Reuse an existing unpaid proof or try again later. Batch eval is unaffected."
        )

    rz = rzp.create_recovery_link(rec, action, force_fresh=True, live_ok=True)
    if rz.get("error") or not rz.get("link_id"):
        # Last resort: any unpaid proof already in DB
        any_open = row_to_dict(
            conn.execute(
                """
                SELECT * FROM decisions
                WHERE policy='proof' AND outcome=? AND razorpay_link_id IS NOT NULL
                  AND razorpay_link_id NOT LIKE 'plink_test_%'
                ORDER BY created_at DESC LIMIT 1
                """,
                (Outcome.AWAITING_PAYMENT.value,),
            ).fetchone()
        )
        if any_open:
            conn.close()
            return {
                "decision": any_open,
                "pay_url": any_open.get("razorpay_short_url"),
                "link_id": any_open.get("razorpay_link_id"),
                "mode": "reused_after_error",
                "reused": True,
                "hint": f"Create failed ({rz.get('error')}). Reusing an existing unpaid proof link.",
            }
        conn.close()
        raise RuntimeError(
            (rz.get("error") or "Razorpay payment_links.create failed")
            + " — batch eval still works. Wait for Razorpay test-link quota reset, "
            "or pay an existing unpaid link from your Razorpay test dashboard."
        )

    # If create returned a reused account link after quota error, still record it.
    if rz.get("mode") == "razorpay_test":
        _PROOF_CREATE_TIMES.append(time.time())

    decision_id = f"proof_{uuid.uuid4().hex[:12]}"
    run_id = f"run_proof_{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT INTO runs (id, policy, started_at, at_risk_paise, recovered_paise) VALUES (?,?,?,?,0)",
        (run_id, "proof", _now(), rec["amount_paise"]),
    )
    conn.execute(
        """
        INSERT INTO decisions (
            id, run_id, record_id, policy, diagnosed_cause, diagnosis_confidence,
            diagnosis_rationale, proposed_action, proposed_channel, message_body,
            supervisor_allowed, supervisor_status, rule_ids, supervisor_reason,
            razorpay_link_id, razorpay_short_url, outcome, recovered_paise,
            action_match, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            decision_id,
            run_id,
            rec["id"],
            "proof",
            None,
            None,
            "Live proof: real Razorpay test Payment Link (no diagnosis needed).",
            action.value,
            "email",
            f"Pay this recovery link: {rz.get('short_url')}",
            1,
            "allowed",
            json.dumps(["live_proof"]),
            "Awaiting Razorpay paid status (poll or webhook).",
            rz.get("link_id"),
            rz.get("short_url"),
            Outcome.AWAITING_PAYMENT.value,
            0,
            None,
            _now(),
        ),
    )
    conn.commit()
    out = row_to_dict(conn.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone())
    conn.close()
    return {
        "decision": out,
        "pay_url": rz.get("short_url"),
        "link_id": rz.get("link_id"),
        "mode": rz.get("mode"),
        "reused": False,
        "hint": "Open pay_url → Razorpay test card → Poll paid? (works without watching the video).",
    }


def mark_payment_link_paid(link_id: str, *, source: str, payment_id: str | None = None) -> dict | None:
    init_db()
    conn = connect()
    dec = row_to_dict(
        conn.execute(
            "SELECT * FROM decisions WHERE razorpay_link_id=? ORDER BY created_at DESC LIMIT 1",
            (link_id,),
        ).fetchone()
    )
    if not dec:
        conn.close()
        return None
    if dec["outcome"] == Outcome.RECOVERED.value:
        conn.close()
        return dec
    rec = dict(conn.execute("SELECT * FROM records WHERE id=?", (dec["record_id"],)).fetchone())
    reason = f"Recovered via Razorpay ({source})" + (f" payment={payment_id}" if payment_id else "")
    conn.execute(
        """
        UPDATE decisions SET outcome=?, recovered_paise=?, supervisor_reason=?,
               message_body=? WHERE id=?
        """,
        (
            Outcome.RECOVERED.value,
            rec["amount_paise"],
            reason,
            (dec.get("message_body") or "") + f"\n[{source}] paid",
            dec["id"],
        ),
    )
    conn.execute(
        "UPDATE runs SET recovered_paise=? WHERE id=?",
        (rec["amount_paise"], dec["run_id"]),
    )
    conn.commit()
    out = row_to_dict(conn.execute("SELECT * FROM decisions WHERE id=?", (dec["id"],)).fetchone())
    conn.close()
    return out


def poll_payment_link(link_id: str) -> dict:
    rz = RazorpayExecutor()
    if not rz.live or not rz._client:
        return {
            "status": "unavailable",
            "paid": False,
            "detail": "Razorpay keys missing on host — cannot poll. Batch eval is fine.",
        }
    try:
        link = rz._client.payment_link.fetch(link_id)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "paid": False, "detail": str(exc)[:300]}
    status = link.get("status")
    paid = status == "paid"
    decision = None
    if paid:
        decision = mark_payment_link_paid(link_id, source="api_poll", payment_id=str(link.get("id")))
    return {
        "status": status,
        "paid": paid,
        "amount": link.get("amount"),
        "decision": decision,
        "raw_id": link.get("id"),
    }


def ingest_webhook(body: bytes, signature: str | None) -> dict:
    verified = verify_signature(body, signature)
    try:
        payload = json.loads(body.decode() or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid json"}

    event = payload.get("event") or ""
    init_db()
    conn = connect()
    eid = f"wh_{uuid.uuid4().hex[:16]}"
    entity = (
        (payload.get("payload") or {}).get("payment_link", {}) or {}
    ).get("entity") or {}
    link_id = entity.get("id")
    conn.execute(
        """
        INSERT INTO webhook_events (id, event, payment_link_id, signature_ok, payload, created_at)
        VALUES (?,?,?,?,?,?)
        """,
        (
            eid,
            event,
            link_id,
            int(verified or not settings.razorpay_webhook_secret),
            json.dumps(payload)[:8000],
            _now(),
        ),
    )
    conn.commit()
    conn.close()

    decision = None
    if link_id and event in {"payment_link.paid", "payment_link.partially_paid"}:
        if verified or not settings.razorpay_webhook_secret:
            payment_id = None
            payments = entity.get("payments") or []
            if payments:
                payment_id = str(payments[0])
            decision = mark_payment_link_paid(
                link_id, source=f"webhook:{event}", payment_id=payment_id
            )

    return {
        "ok": True,
        "event": event,
        "verified": verified,
        "link_id": link_id,
        "decision": decision,
    }


def recent_webhooks(limit: int = 10) -> list[dict]:
    init_db()
    conn = connect()
    rows = [
        row_to_dict(r)
        for r in conn.execute(
            "SELECT * FROM webhook_events ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    ]
    conn.close()
    return rows


def proof_candidates() -> list[dict]:
    _ensure_batch()
    conn = connect()
    rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT id, customer_name, amount_paise, record_type, true_cause, error_description
            FROM records
            WHERE true_cause NOT IN ('customer_cancelled','fraud_flag')
            ORDER BY id
            LIMIT 12
            """
        ).fetchall()
    ]
    conn.close()
    return rows


def latest_open_proof() -> dict | None:
    init_db()
    conn = connect()
    row = row_to_dict(
        conn.execute(
            """
            SELECT * FROM decisions
            WHERE policy='proof' AND outcome=? AND razorpay_link_id IS NOT NULL
            ORDER BY created_at DESC LIMIT 1
            """,
            (Outcome.AWAITING_PAYMENT.value,),
        ).fetchone()
    )
    conn.close()
    return row

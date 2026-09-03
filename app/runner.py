from __future__ import annotations

import json
import random
import re
import uuid
from datetime import datetime, timezone

from app.db import connect, init_db, row_to_dict
from app.diagnosis import diagnose
from app.enums import Action, Cause, Channel, Outcome, Policy
from app.intervention import baseline_propose, propose
from app.razorpay_exec import RazorpayExecutor
from app.simulator import simulate
from app.supervisor import evaluate

HARD_STOP_RE = re.compile(
    r"fraud|stolen|cancel|unsubscrib|revok|do not retry|do not send",
    re.I,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hard_stop(record: dict) -> bool:
    blob = " ".join(
        str(record.get(k) or "")
        for k in ("error_code", "error_description", "notes")
    )
    return bool(HARD_STOP_RE.search(blob))


def _public_record(record: dict) -> dict:
    return {k: v for k, v in record.items() if k != "true_cause"}


def run_policy(policy: Policy, seed: int = 7) -> dict:
    init_db()
    rng = random.Random(seed)
    rzp = RazorpayExecutor()
    run_id = f"run_{policy.value}_{uuid.uuid4().hex[:8]}"
    conn = connect()
    records = [dict(r) for r in conn.execute("SELECT * FROM records ORDER BY id").fetchall()]
    if not records:
        conn.close()
        raise RuntimeError("No records. Seed the batch first.")

    at_risk = sum(r["amount_paise"] for r in records)
    conn.execute(
        "INSERT INTO runs (id, policy, started_at, at_risk_paise) VALUES (?,?,?,?)",
        (run_id, policy.value, _now(), at_risk),
    )
    conn.commit()

    recovered = 0
    diag_ok = 0
    diag_n = 0
    illegal = 0

    for rec in records:
        rec["force_razorpay_error"] = "FORCE_RZP_ERROR" in (rec.get("notes") or "")
        decision = _process_one(conn, rzp, rng, run_id, rec, policy)
        recovered += decision["recovered_paise"]
        illegal += int(decision["outcome"] == Outcome.VIOLATION.value)
        if policy == Policy.AGENT and decision.get("diagnosed_cause"):
            diag_n += 1
            if decision["diagnosed_cause"] == rec["true_cause"]:
                diag_ok += 1

    conn.execute(
        """
        UPDATE runs SET finished_at=?, recovered_paise=?, diagnosis_correct=?,
               diagnosis_total=?, illegal_contacts=? WHERE id=?
        """,
        ( _now(), recovered, diag_ok, diag_n, illegal, run_id),
    )
    conn.commit()
    run = row_to_dict(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
    conn.close()
    return run


def _process_one(conn, rzp, rng, run_id, rec, policy: Policy) -> dict:
    if policy == Policy.AGENT:
        dgn = diagnose(_public_record(rec))
        cause = Cause(dgn["cause"])
        proposal = propose(_public_record(rec), cause)
    else:
        dgn = {
            "cause": None,
            "confidence": None,
            "rationale": "Baseline: ignore diagnosis, one email + generic link.",
            "source": "baseline",
        }
        cause = None
        proposal = baseline_propose(rec)

    action = Action(proposal["action"])
    channel = Channel(proposal["channel"])
    gate = evaluate(
        cause=cause,
        action=action,
        channel=channel,
        amount_paise=rec["amount_paise"],
        opted_out=bool(rec["opted_out"]),
        hard_stop=_hard_stop(rec),
    )

    decision_id = f"dec_{uuid.uuid4().hex[:12]}"
    outcome = Outcome.POLICY_DENIED
    recovered_paise = 0
    link_id = None
    short_url = None
    action_match = None
    message = proposal.get("body") or ""

    if gate.status == "queued":
        outcome = Outcome.QUEUED
    elif not gate.allowed:
        outcome = Outcome.POLICY_DENIED
    elif gate.status == "skipped":
        outcome = Outcome.SKIPPED
        sim = simulate(
            true_cause=Cause(rec["true_cause"]),
            action=action,
            channel=channel,
            amount_paise=rec["amount_paise"],
            rng=rng,
        )
        action_match = sim.action_match
        if sim.violation:
            outcome = Outcome.VIOLATION
    else:
        rz = rzp.create_recovery_link(rec, action)
        if rz.get("error"):
            outcome = Outcome.RAZORPAY_ERROR
            message = f"{message}\n[Razorpay] {rz['error']}"
        else:
            link_id, short_url = rz.get("link_id"), rz.get("short_url")
            if short_url:
                message = message.replace("{link}", short_url)
            sim = simulate(
                true_cause=Cause(rec["true_cause"]),
                action=action,
                channel=channel,
                amount_paise=rec["amount_paise"],
                rng=rng,
            )
            action_match = sim.action_match
            if sim.violation:
                outcome = Outcome.VIOLATION
            elif sim.recovered:
                outcome = Outcome.RECOVERED
                recovered_paise = rec["amount_paise"]
            else:
                outcome = Outcome.NOT_RECOVERED

    row = {
        "id": decision_id,
        "run_id": run_id,
        "record_id": rec["id"],
        "policy": policy.value,
        "diagnosed_cause": dgn.get("cause"),
        "diagnosis_confidence": dgn.get("confidence"),
        "diagnosis_rationale": dgn.get("rationale"),
        "proposed_action": action.value,
        "proposed_channel": channel.value,
        "message_body": message,
        "supervisor_allowed": int(gate.allowed),
        "supervisor_status": gate.status,
        "rule_ids": json.dumps(gate.rule_ids),
        "supervisor_reason": gate.reason,
        "razorpay_link_id": link_id,
        "razorpay_short_url": short_url,
        "outcome": outcome.value,
        "recovered_paise": recovered_paise,
        "action_match": None if action_match is None else int(action_match),
        "created_at": _now(),
    }
    conn.execute(
        f"""
        INSERT INTO decisions ({", ".join(row)})
        VALUES ({", ".join("?" for _ in row)})
        """,
        tuple(row.values()),
    )
    conn.commit()
    return row


def approve_decision(decision_id: str, approve: bool, seed: int = 7) -> dict:
    init_db()
    conn = connect()
    dec = row_to_dict(
        conn.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
    )
    if not dec:
        conn.close()
        raise KeyError(decision_id)
    if dec["outcome"] != Outcome.QUEUED.value:
        conn.close()
        return dec
    rec = dict(conn.execute("SELECT * FROM records WHERE id=?", (dec["record_id"],)).fetchone())
    rec["force_razorpay_error"] = "FORCE_RZP_ERROR" in (rec.get("notes") or "")

    if not approve:
        conn.execute(
            "UPDATE decisions SET outcome=?, supervisor_reason=? WHERE id=?",
            (Outcome.POLICY_DENIED.value, "Human denied high-value outreach.", decision_id),
        )
        conn.commit()
        out = row_to_dict(conn.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone())
        _recompute_run(conn, dec["run_id"])
        conn.close()
        return out

    rzp = RazorpayExecutor()
    action = Action(dec["proposed_action"])
    channel = Channel(dec["proposed_channel"])
    rz = rzp.create_recovery_link(rec, action)
    rng = random.Random(seed + int(decision_id[-8:], 16) % 10_000)
    message = dec["message_body"] or ""
    link_id = None
    short_url = None
    recovered_paise = 0
    action_match = None

    if rz.get("error"):
        outcome = Outcome.RAZORPAY_ERROR
        message = f"{message}\n[Razorpay] {rz['error']}"
    else:
        link_id, short_url = rz.get("link_id"), rz.get("short_url")
        if short_url:
            message = message.replace("{link}", short_url)
        sim = simulate(
            true_cause=Cause(rec["true_cause"]),
            action=action,
            channel=channel,
            amount_paise=rec["amount_paise"],
            rng=rng,
        )
        action_match = sim.action_match
        if sim.violation:
            outcome = Outcome.VIOLATION
        elif sim.recovered:
            outcome = Outcome.RECOVERED
            recovered_paise = rec["amount_paise"]
        else:
            outcome = Outcome.NOT_RECOVERED

    conn.execute(
        """
        UPDATE decisions SET outcome=?, recovered_paise=?, razorpay_link_id=?,
               razorpay_short_url=?, message_body=?, action_match=?,
               supervisor_reason=? WHERE id=?
        """,
        (
            outcome.value,
            recovered_paise,
            link_id,
            short_url,
            message,
            None if action_match is None else int(action_match),
            "Human approved high-value recovery.",
            decision_id,
        ),
    )
    conn.commit()
    _recompute_run(conn, dec["run_id"])
    out = row_to_dict(conn.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone())
    conn.close()
    return out


def _recompute_run(conn, run_id: str) -> None:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(recovered_paise),0),
               SUM(CASE WHEN outcome='violation' THEN 1 ELSE 0 END)
        FROM decisions WHERE run_id=?
        """,
        (run_id,),
    ).fetchone()
    conn.execute(
        "UPDATE runs SET recovered_paise=?, illegal_contacts=? WHERE id=?",
        (row[0], row[1], run_id),
    )
    conn.commit()


def approve_all_queued(run_id: str, approve: bool = True) -> list[dict]:
    init_db()
    conn = connect()
    ids = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM decisions WHERE run_id=? AND outcome=?",
            (run_id, Outcome.QUEUED.value),
        ).fetchall()
    ]
    conn.close()
    return [approve_decision(i, approve) for i in ids]


def latest_runs() -> list[dict]:
    init_db()
    conn = connect()
    rows = [row_to_dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY started_at DESC").fetchall()]
    conn.close()
    return rows


def run_detail(run_id: str) -> dict:
    init_db()
    conn = connect()
    run = row_to_dict(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
    decisions = [
        row_to_dict(r)
        for r in conn.execute(
            """
            SELECT d.*, rec.customer_name, rec.amount_paise, rec.record_type,
                   rec.true_cause, rec.error_code, rec.error_description, rec.notes
            FROM decisions d JOIN records rec ON rec.id = d.record_id
            WHERE d.run_id=? ORDER BY rec.id
            """,
            (run_id,),
        ).fetchall()
    ]
    conn.close()
    return {"run": run, "decisions": decisions}


def record_stats() -> dict:
    init_db()
    conn = connect()
    n = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    risk = conn.execute("SELECT COALESCE(SUM(amount_paise),0) FROM records").fetchone()[0]
    by = [
        dict(r)
        for r in conn.execute(
            "SELECT true_cause, COUNT(*) n, SUM(amount_paise) paise FROM records GROUP BY true_cause"
        ).fetchall()
    ]
    conn.close()
    return {"count": n, "at_risk_paise": risk, "by_cause": by}

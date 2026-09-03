from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.config import settings
from app.enums import Action, Cause, Channel, LINK_ACTIONS

VOICE_MIN_INR = 20_000
LOW_AOV_VOICE_INR = 2_000


@dataclass
class GateResult:
    allowed: bool
    status: str
    rule_ids: list[str] = field(default_factory=list)
    reason: str = ""


def evaluate(
    *,
    cause: Cause | None,
    action: Action,
    channel: Channel,
    amount_paise: int,
    opted_out: bool,
    hard_stop: bool = False,
    attempt_count: int = 0,
) -> GateResult:
    rules: list[str] = []
    amount_inr = amount_paise / 100

    if opted_out:
        rules.append("opt_out")
        return GateResult(False, "policy_denied", rules, "Customer opted out. No contact.")

    stop_needed = hard_stop or cause in {Cause.CUSTOMER_CANCELLED, Cause.FRAUD_FLAG}
    if stop_needed or action == Action.STOP:
        rules.append("hard_stop")
        if action != Action.STOP:
            return GateResult(
                False,
                "policy_denied",
                rules,
                "Stop required for cancelled/fraud. Outreach denied.",
            )
        return GateResult(True, "skipped", rules, "Stop action allowed. No outreach.")

    if attempt_count >= settings.max_attempts:
        rules.append("max_attempts")
        return GateResult(
            False,
            "policy_denied",
            rules,
            f"Attempt cap {settings.max_attempts} already reached.",
        )

    if channel == Channel.VOICE and amount_inr < VOICE_MIN_INR:
        rules.append("voice_min_amount")
        return GateResult(
            False,
            "policy_denied",
            rules,
            f"Voice only if amount ≥ ₹{VOICE_MIN_INR:,}.",
        )

    if channel == Channel.VOICE and amount_inr < LOW_AOV_VOICE_INR:
        rules.append("voice_low_aov")
        return GateResult(False, "policy_denied", rules, "Voice forbidden on low AOV.")

    if action == Action.WAIT_AUTO_RETRY and channel not in {Channel.SYSTEM, Channel.NONE}:
        rules.append("bank_down_no_nag")
        return GateResult(
            False,
            "policy_denied",
            rules,
            "Bank/NPCI outage: system retry only, do not nag the customer.",
        )

    if action in LINK_ACTIONS and channel in {Channel.NONE, Channel.SYSTEM}:
        rules.append("link_needs_channel")
        return GateResult(
            False,
            "policy_denied",
            rules,
            "Link actions need email or SMS (or voice if high value).",
        )

    if amount_inr >= settings.approval_threshold_inr:
        rules.append("human_approval")
        return GateResult(
            True,
            "queued",
            rules,
            f"Amount ₹{amount_inr:,.0f} ≥ ₹{settings.approval_threshold_inr:,} — queued for human approval.",
        )

    rules.append("pass")
    return GateResult(True, "allowed", rules, "Within attempt, amount, and contact bounds.")


def gate_to_json(gate: GateResult) -> dict:
    return {
        "allowed": gate.allowed,
        "status": gate.status,
        "rule_ids": gate.rule_ids,
        "reason": gate.reason,
    }

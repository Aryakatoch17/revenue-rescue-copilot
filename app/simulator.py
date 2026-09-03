from __future__ import annotations

import random
from dataclasses import dataclass

from app.enums import Action, Cause, Channel, CORRECT_ACTION

# Channel only matters after the action matches the hidden cause.
CHANNEL_MULT = {
    Channel.SYSTEM: 1.0,
    Channel.NONE: 0.0,
    Channel.EMAIL: 0.82,
    Channel.SMS: 0.95,
    Channel.VOICE: 1.08,
}


@dataclass
class SimResult:
    recovered: bool
    p_recover: float
    action_match: bool
    violation: bool
    note: str


def simulate(
    *,
    true_cause: Cause,
    action: Action,
    channel: Channel,
    amount_paise: int,
    rng: random.Random,
) -> SimResult:
    if true_cause in {Cause.CUSTOMER_CANCELLED, Cause.FRAUD_FLAG}:
        if action != Action.STOP:
            return SimResult(
                False, 0.0, False, True, "Illegal contact on cancelled/fraud case."
            )
        return SimResult(False, 0.0, True, False, "Correct stop. No recovery expected.")

    if action == Action.STOP:
        return SimResult(False, 0.0, False, False, "Stopped a recoverable case.")

    match = CORRECT_ACTION[true_cause] == action
    if not match:
        p = 0.03
        recovered = rng.random() < p
        return SimResult(
            recovered,
            p,
            False,
            False,
            "Wrong action for true cause — recovery near zero.",
        )

    base = 0.70
    if true_cause == Cause.BANK_DOWN and action == Action.WAIT_AUTO_RETRY:
        base = 0.78
        channel_p = 1.0
    elif true_cause == Cause.INSUFFICIENT_FUNDS:
        base = 0.66
        channel_p = CHANNEL_MULT.get(channel, 0.5)
    else:
        channel_p = CHANNEL_MULT.get(channel, 0.5)
        if channel == Channel.VOICE and amount_paise < 2_000_000:
            channel_p *= 0.4

    p = min(0.92, base * channel_p)
    recovered = rng.random() < p
    return SimResult(
        recovered,
        p,
        True,
        False,
        "Action matched hidden cause.",
    )

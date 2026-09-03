from app.enums import Action, Cause, Channel
from app.simulator import simulate
from app.supervisor import evaluate
import random


def test_supervisor_blocks_voice_on_low_aov():
    g = evaluate(
        cause=Cause.CHECKOUT_ABANDONED,
        action=Action.CART_REMINDER_LINK,
        channel=Channel.VOICE,
        amount_paise=40_000,
        opted_out=False,
    )
    assert g.allowed is False
    assert "voice_min_amount" in g.rule_ids


def test_supervisor_queues_high_value():
    g = evaluate(
        cause=Cause.INVOICE_UNPAID,
        action=Action.INVOICE_LINK,
        channel=Channel.EMAIL,
        amount_paise=8_500_000,
        opted_out=False,
    )
    assert g.status == "queued"
    assert "human_approval" in g.rule_ids


def test_supervisor_hard_stop_blocks_outreach():
    g = evaluate(
        cause=Cause.FRAUD_FLAG,
        action=Action.CART_REMINDER_LINK,
        channel=Channel.EMAIL,
        amount_paise=100_000,
        opted_out=False,
        hard_stop=True,
    )
    assert g.allowed is False
    assert g.status == "policy_denied"


def test_simulator_wrong_action_almost_never_recovers():
    rng = random.Random(0)
    hits = 0
    for _ in range(200):
        s = simulate(
            true_cause=Cause.INSTRUMENT_EXPIRED,
            action=Action.CART_REMINDER_LINK,
            channel=Channel.VOICE,
            amount_paise=500_000,
            rng=rng,
        )
        hits += int(s.recovered)
        assert s.action_match is False
    assert hits < 20


def test_simulator_matching_action_recovers_often():
    rng = random.Random(0)
    hits = 0
    for _ in range(200):
        s = simulate(
            true_cause=Cause.INSTRUMENT_EXPIRED,
            action=Action.UPDATE_INSTRUMENT_LINK,
            channel=Channel.EMAIL,
            amount_paise=500_000,
            rng=rng,
        )
        hits += int(s.recovered)
        assert s.action_match is True
    assert hits > 80

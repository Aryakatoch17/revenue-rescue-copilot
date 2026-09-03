from __future__ import annotations

import json

from app.config import settings
from app.enums import Action, Cause, Channel, CORRECT_ACTION
from app.llm import chat_json, llm_configured

SYSTEM = """You write a short recovery message for an Indian customer.
Return JSON only: {"subject": "...", "body": "..."}
Language: simple English, or light Hinglish if channel is voice.
Never promise a discount. Never mention fraud. Include the payment link placeholder {{link}}.
Keep body under 360 characters.
"""

DEFAULT_CHANNEL = {
    Action.WAIT_AUTO_RETRY: Channel.SYSTEM,
    Action.DELAY_RETRY: Channel.SMS,
    Action.UPDATE_INSTRUMENT_LINK: Channel.EMAIL,
    Action.REMANDATE_LINK: Channel.SMS,
    Action.CART_REMINDER_LINK: Channel.EMAIL,
    Action.INVOICE_LINK: Channel.EMAIL,
    Action.STOP: Channel.NONE,
}


def propose(record: dict, cause: Cause) -> dict:
    action = CORRECT_ACTION[cause]
    amount_inr = record["amount_paise"] / 100
    channel = DEFAULT_CHANNEL[action]
    if action == Action.INVOICE_LINK and amount_inr >= 20_000:
        channel = Channel.VOICE
    elif action == Action.UPDATE_INSTRUMENT_LINK and amount_inr >= 20_000:
        channel = Channel.SMS

    send_after_hours = 0
    if action == Action.WAIT_AUTO_RETRY:
        send_after_hours = 2
    elif action == Action.DELAY_RETRY:
        send_after_hours = 48

    message = _message(record, action, channel)
    return {
        "action": action.value,
        "channel": channel.value,
        "send_after_hours": send_after_hours,
        "subject": message["subject"],
        "body": message["body"],
    }


def baseline_propose(record: dict) -> dict:
    return {
        "action": Action.CART_REMINDER_LINK.value,
        "channel": Channel.EMAIL.value,
        "send_after_hours": 0,
        "subject": "Complete your Razorpay payment",
        "body": f"Hi {record['customer_name']}, your payment of ₹{record['amount_paise']/100:,.0f} is pending. Pay here: {{link}}",
    }


def _message(record: dict, action: Action, channel: Channel) -> dict:
    name = record["customer_name"]
    amt = f"₹{record['amount_paise']/100:,.0f}"
    templates = {
        Action.WAIT_AUTO_RETRY: (
            "Retry scheduled",
            f"System will auto-retry {amt} after the bank/NPCI window. No customer ping.",
        ),
        Action.DELAY_RETRY: (
            "We'll try again shortly",
            f"Hi {name}, the last debit for {amt} didn't go through (likely balance). We'll retry in 48h, or pay now: {{link}}",
        ),
        Action.UPDATE_INSTRUMENT_LINK: (
            "Update your card / UPI",
            f"Hi {name}, your saved instrument looks expired. Update it and complete {amt}: {{link}}",
        ),
        Action.REMANDATE_LINK: (
            "Restart your mandate",
            f"Hi {name}, your eMandate is paused so {amt} couldn't be collected. Re-authorize here: {{link}}",
        ),
        Action.CART_REMINDER_LINK: (
            "Your cart is waiting",
            f"Hi {name}, you left items worth {amt}. Finish checkout: {{link}}",
        ),
        Action.INVOICE_LINK: (
            "Invoice overdue",
            f"Hi {name}, invoice {amt} is overdue. Pay securely: {{link}}",
        ),
        Action.STOP: ("Stopped", "No message."),
    }
    subject, body = templates[action]
    if not settings.live_copy or not llm_configured() or action in {Action.STOP, Action.WAIT_AUTO_RETRY}:
        return {"subject": subject, "body": body}
    try:
        data = chat_json(
            system=SYSTEM,
            user=json.dumps(
                {
                    "name": name,
                    "amount": amt,
                    "action": action.value,
                    "channel": channel.value,
                }
            ),
            temperature=0.4,
        )
        return {
            "subject": str(data.get("subject") or subject)[:120],
            "body": str(data.get("body") or body)[:500],
        }
    except Exception:
        return {"subject": subject, "body": body}

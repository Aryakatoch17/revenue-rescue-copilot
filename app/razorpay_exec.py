from __future__ import annotations

import uuid

from app.cache import get_link, put_link
from app.config import settings
from app.enums import Action

DESCRIPTIONS = {
    Action.UPDATE_INSTRUMENT_LINK: "Update payment instrument",
    Action.REMANDATE_LINK: "Re-authorize eMandate",
    Action.CART_REMINDER_LINK: "Complete checkout",
    Action.INVOICE_LINK: "Pay overdue invoice",
    Action.DELAY_RETRY: "Retry delayed payment",
    Action.WAIT_AUTO_RETRY: "Scheduled auto-retry",
}


def _contact(record: dict) -> str:
    phone = str(record.get("phone") or "")
    digits = "".join(c for c in phone if c.isdigit())[-10:]
    if len(digits) == 10 and len(set(digits)) >= 4:
        return "+91" + digits
    n = int("".join(c for c in record["id"] if c.isdigit()) or "1")
    return f"+91{9812345100 + (n % 8000)}"


def _stub(record: dict, action: Action) -> dict:
    fake_id = f"plink_test_{record['id']}_{action.value[:6]}"
    return {
        "link_id": fake_id,
        "short_url": f"https://rzp.io/i/{fake_id[-8:]}",
        "mode": "stub",
        "error": None,
    }


class RazorpayExecutor:
    def __init__(self) -> None:
        self.live = bool(settings.razorpay_key_id and settings.razorpay_key_secret)
        self._client = None
        if self.live:
            import razorpay

            self._client = razorpay.Client(
                auth=(settings.razorpay_key_id, settings.razorpay_key_secret)
            )

    def create_recovery_link(
        self,
        record: dict,
        action: Action,
        *,
        force_fresh: bool = False,
        live_ok: bool | None = None,
    ) -> dict:
        """Batch defaults to stubs. Only live_ok/force_fresh burns Razorpay test-link quota."""
        if action in {Action.STOP, Action.WAIT_AUTO_RETRY}:
            return {
                "link_id": None,
                "short_url": None,
                "mode": "none",
                "error": None,
            }
        if record.get("force_razorpay_error"):
            return {
                "link_id": None,
                "short_url": None,
                "mode": "error",
                "error": "Simulated Razorpay 5xx on payment_links.create",
            }

        if not force_fresh:
            cached = get_link(record["id"], action.value)
            if cached and cached.get("link_id") and not str(cached["link_id"]).startswith(
                "plink_test_"
            ):
                return {
                    "link_id": cached.get("link_id"),
                    "short_url": cached.get("short_url"),
                    "mode": str(cached.get("mode") or "cached"),
                    "error": None,
                }

        allow_live = (
            live_ok
            if live_ok is not None
            else (force_fresh or settings.razorpay_live_batch)
        )
        if not (self.live and allow_live):
            # Prefer any previously cached real link for this record/action.
            cached = get_link(record["id"], action.value)
            if cached and cached.get("link_id") and not str(cached["link_id"]).startswith(
                "plink_test_"
            ):
                return {
                    "link_id": cached["link_id"],
                    "short_url": cached.get("short_url"),
                    "mode": "cached",
                    "error": None,
                }
            stub = _stub(record, action)
            put_link(record["id"], action.value, stub)
            return stub

        amount = int(record["amount_paise"])
        desc = DESCRIPTIONS.get(action, "Recovery payment")
        try:
            payload = {
                "amount": amount,
                "currency": "INR",
                "accept_partial": False,
                "description": f"{desc} · {record['id']}",
                "customer": {
                    "name": record["customer_name"],
                    "email": record["email"],
                    "contact": _contact(record),
                },
                "notify": {"sms": False, "email": False},
                "reminder_enable": False,
                "notes": {
                    "rescue_record_id": record["id"],
                    "action": action.value,
                },
            }
            link = self._client.payment_link.create(payload)
            result = {
                "link_id": link.get("id"),
                "short_url": link.get("short_url"),
                "mode": "razorpay_test",
                "error": None,
            }
            put_link(record["id"], action.value, result)
            return result
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
            reused = self._reuse_existing_unpaid()
            if reused:
                reused["error"] = None
                reused["mode"] = "reused_account_link"
                put_link(record["id"], action.value, reused)
                return reused
            return {
                "link_id": None,
                "short_url": None,
                "mode": "error",
                "error": err[:400],
            }

    def _reuse_existing_unpaid(self) -> dict | None:
        """When test-mode create quota is exhausted, reuse an unpaid link already on the account."""
        if not self._client:
            return None
        try:
            page = self._client.payment_link.all({"count": 40})
        except Exception:  # noqa: BLE001
            return None
        items = page.get("items") or page.get("payment_links") or []
        for link in items:
            if link.get("status") in {"created", "issued", "partially_paid"} and link.get("id"):
                return {
                    "link_id": link.get("id"),
                    "short_url": link.get("short_url"),
                    "mode": "reused_account_link",
                    "error": None,
                }
        return None

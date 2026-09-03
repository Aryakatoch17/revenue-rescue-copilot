from __future__ import annotations

import random
from datetime import datetime, timezone

from app.db import connect, init_db
from app.enums import Cause, RecordType

CUSTOMERS = [
    ("Asha Mehta", "asha{i}@mail.test", "+919812345{i:03d}"),
    ("Rahul Iyer", "rahul{i}@mail.test", "+919823456{i:03d}"),
    ("Fatima Khan", "fatima{i}@mail.test", "+919834567{i:03d}"),
    ("Vikram Shah", "vikram{i}@mail.test", "+919845678{i:03d}"),
    ("Neelam Rao", "neelam{i}@mail.test", "+919856789{i:03d}"),
    ("Arjun Nair", "arjun{i}@mail.test", "+919867890{i:03d}"),
]

# (true_cause, record_type, amount_inr, error_code, error_description, notes, opted_out)
# Mix of obvious and slightly noisy signals. Hidden cause is never shown to the LLM prompt as true_cause.
SPEC: list[tuple] = [
    (Cause.BANK_DOWN, RecordType.PAYMENT_FAILED, 1899, "GATEWAY_ERROR", "Issuer unavailable / NPCI timeout", "UPI collect expired at NPCI", False),
    (Cause.BANK_DOWN, RecordType.PAYMENT_FAILED, 5400, "BAD_REQUEST_ERROR", "Bank is currently down", "retry later from dashboard", False),
    (Cause.BANK_DOWN, RecordType.SUBSCRIPTION_FAILED, 799, "SERVER_ERROR", "5xx from issuing bank", "", False),
    (Cause.BANK_DOWN, RecordType.PAYMENT_FAILED, 12500, "GATEWAY_ERROR", "timeout waiting for authorization", "HDFC switch flap", False),
    (Cause.BANK_DOWN, RecordType.PAYMENT_FAILED, 299, "GATEWAY_ERROR", "NPCI UPI 91 — bank offline", "", False),
    (Cause.BANK_DOWN, RecordType.PAYMENT_FAILED, 4500, "SERVER_ERROR", "issuer_unavailable", "", False),
    (Cause.BANK_DOWN, RecordType.PAYMENT_FAILED, 2100, "GATEWAY_ERROR", "Could not reach bank", "", False),
    (Cause.BANK_DOWN, RecordType.SUBSCRIPTION_FAILED, 1999, "GATEWAY_ERROR", "NPCI downtime window", "subscription charge", False),
    (Cause.INSUFFICIENT_FUNDS, RecordType.PAYMENT_FAILED, 2499, "BAD_REQUEST_ERROR", "Payment failed due to insufficient funds", "E001", False),
    (Cause.INSUFFICIENT_FUNDS, RecordType.PAYMENT_FAILED, 899, "GATEWAY_ERROR", "Not enough balance in account", "", False),
    (Cause.INSUFFICIENT_FUNDS, RecordType.SUBSCRIPTION_FAILED, 499, "BAD_REQUEST_ERROR", "NSF on mandate debit", "salary cycle 1st", False),
    (Cause.INSUFFICIENT_FUNDS, RecordType.PAYMENT_FAILED, 15999, "BAD_REQUEST_ERROR", "insufficient funds", "", False),
    (Cause.INSUFFICIENT_FUNDS, RecordType.PAYMENT_FAILED, 670, "GATEWAY_ERROR", "UPI declined — no balance", "", False),
    (Cause.INSUFFICIENT_FUNDS, RecordType.PAYMENT_FAILED, 3200, "BAD_REQUEST_ERROR", "E001 insufficient", "second fail same card", False),
    (Cause.INSUFFICIENT_FUNDS, RecordType.SUBSCRIPTION_FAILED, 999, "BAD_REQUEST_ERROR", "debit failed: funds", "", False),
    (Cause.INSUFFICIENT_FUNDS, RecordType.PAYMENT_FAILED, 7800, "GATEWAY_ERROR", "account does not have sufficient balance", "", False),
    (Cause.INSTRUMENT_EXPIRED, RecordType.PAYMENT_FAILED, 4500, "BAD_REQUEST_ERROR", "Card expired", "Visa •4242", False),
    (Cause.INSTRUMENT_EXPIRED, RecordType.SUBSCRIPTION_FAILED, 1299, "BAD_REQUEST_ERROR", "saved instrument invalid", "token_dead", False),
    (Cause.INSTRUMENT_EXPIRED, RecordType.PAYMENT_FAILED, 22000, "BAD_REQUEST_ERROR", "Expired card, please update", "high value", False),
    (Cause.INSTRUMENT_EXPIRED, RecordType.PAYMENT_FAILED, 750, "BAD_REQUEST_ERROR", "instrument_expired", "", False),
    (Cause.INSTRUMENT_EXPIRED, RecordType.PAYMENT_FAILED, 5600, "BAD_REQUEST_ERROR", "Your card has expired", "", False),
    (Cause.INSTRUMENT_EXPIRED, RecordType.SUBSCRIPTION_FAILED, 2499, "BAD_REQUEST_ERROR", "token expired for recurring", "", False),
    (Cause.INSTRUMENT_EXPIRED, RecordType.PAYMENT_FAILED, 18999, "BAD_REQUEST_ERROR", "invalid card — expiry", "", False),
    (Cause.MANDATE_PAUSED, RecordType.SUBSCRIPTION_FAILED, 599, "BAD_REQUEST_ERROR", "eMandate paused by customer bank", "", False),
    (Cause.MANDATE_PAUSED, RecordType.SUBSCRIPTION_FAILED, 1499, "BAD_REQUEST_ERROR", "NACH mandate is paused", "fitness club", False),
    (Cause.MANDATE_PAUSED, RecordType.SUBSCRIPTION_FAILED, 799, "BAD_REQUEST_ERROR", "subscription: mandate paused", "", False),
    (Cause.MANDATE_PAUSED, RecordType.SUBSCRIPTION_FAILED, 2499, "BAD_REQUEST_ERROR", "enach paused — cannot debit", "", False),
    (Cause.MANDATE_PAUSED, RecordType.SUBSCRIPTION_FAILED, 399, "BAD_REQUEST_ERROR", "mandate_paused", "", False),
    (Cause.MANDATE_PAUSED, RecordType.SUBSCRIPTION_FAILED, 8999, "BAD_REQUEST_ERROR", "eNACH authorization paused", "B2B SaaS seat", False),
    (Cause.CHECKOUT_ABANDONED, RecordType.CHECKOUT_ABANDONED, 1299, None, None, "cart: 2 SKUs, dropped on UPI sheet", False),
    (Cause.CHECKOUT_ABANDONED, RecordType.CHECKOUT_ABANDONED, 499, None, None, "abandoned checkout — no payment entity", False),
    (Cause.CHECKOUT_ABANDONED, RecordType.CHECKOUT_ABANDONED, 3400, None, None, "left cart after address step", False),
    (Cause.CHECKOUT_ABANDONED, RecordType.CHECKOUT_ABANDONED, 899, None, None, "checkout abandoned on payment page", False),
    (Cause.CHECKOUT_ABANDONED, RecordType.CHECKOUT_ABANDONED, 1599, None, None, "drop-off: UPI intent cancelled by user", False),
    (Cause.CHECKOUT_ABANDONED, RecordType.CHECKOUT_ABANDONED, 2199, None, None, "abandoned cart 18 hours", False),
    (Cause.CHECKOUT_ABANDONED, RecordType.CHECKOUT_ABANDONED, 650, None, None, "checkout_abandoned", False),
    (Cause.INVOICE_UNPAID, RecordType.INVOICE_OVERDUE, 85000, None, None, "B2B invoice INV-2041 overdue 21 days", False),
    (Cause.INVOICE_UNPAID, RecordType.INVOICE_OVERDUE, 42000, None, None, "overdue invoice — net 15", False),
    (Cause.INVOICE_UNPAID, RecordType.INVOICE_OVERDUE, 12500, None, None, "receivable aging 45d", False),
    (Cause.INVOICE_UNPAID, RecordType.INVOICE_OVERDUE, 67000, None, None, "overdue invoice for annual plan", False),
    (Cause.INVOICE_UNPAID, RecordType.INVOICE_OVERDUE, 8800, None, None, "invoice unpaid, no bounce yet", False),
    (Cause.INVOICE_UNPAID, RecordType.INVOICE_OVERDUE, 31000, None, None, "B2B overdue — finance controller cc'd", False),
    (Cause.INVOICE_UNPAID, RecordType.INVOICE_OVERDUE, 5400, None, None, "overdue invoice reminder eligible", False),
    (Cause.CUSTOMER_CANCELLED, RecordType.SUBSCRIPTION_FAILED, 799, "BAD_REQUEST_ERROR", "Customer cancelled the subscription", "do not retry", False),
    (Cause.CUSTOMER_CANCELLED, RecordType.SUBSCRIPTION_FAILED, 499, "BAD_REQUEST_ERROR", "revoked mandate at bank", "unsubscribe confirmed", False),
    (Cause.CUSTOMER_CANCELLED, RecordType.PAYMENT_FAILED, 1299, "BAD_REQUEST_ERROR", "customer requested cancellation", "", False),
    (Cause.CUSTOMER_CANCELLED, RecordType.SUBSCRIPTION_FAILED, 1999, "BAD_REQUEST_ERROR", "unsubscribed in app", "", False),
    (Cause.CUSTOMER_CANCELLED, RecordType.INVOICE_OVERDUE, 25000, None, None, "customer cancelled contract — still in overdue queue (trap)", False),
    (Cause.FRAUD_FLAG, RecordType.PAYMENT_FAILED, 48000, "BAD_REQUEST_ERROR", "Blocked BIN — suspected fraud", "velocity spike", False),
    (Cause.FRAUD_FLAG, RecordType.PAYMENT_FAILED, 9200, "GATEWAY_ERROR", "stolen card reported", "", False),
    (Cause.FRAUD_FLAG, RecordType.CHECKOUT_ABANDONED, 15000, None, None, "fraud_flag on device graph — do not send link", False),
    (Cause.FRAUD_FLAG, RecordType.PAYMENT_FAILED, 3300, "BAD_REQUEST_ERROR", "RBI / fraud block", "", False),
    (Cause.FRAUD_FLAG, RecordType.PAYMENT_FAILED, 21000, "BAD_REQUEST_ERROR", "velocity: suspected fraud", "", False),
    # noisy / slightly off-copy so LLM has work
    (Cause.BANK_DOWN, RecordType.PAYMENT_FAILED, 999, "GATEWAY_ERROR", "Could not complete authorization in time", "looks like timeout not NSF", False),
    (Cause.INSUFFICIENT_FUNDS, RecordType.PAYMENT_FAILED, 4100, "GATEWAY_ERROR", "Issuer declined the transaction", "declined — actually NSF", False),
    (Cause.INSTRUMENT_EXPIRED, RecordType.PAYMENT_FAILED, 2700, "BAD_REQUEST_ERROR", "Please use another method", "old token", False),
    (Cause.MANDATE_PAUSED, RecordType.SUBSCRIPTION_FAILED, 1599, "BAD_REQUEST_ERROR", "Unable to charge subscription", "bank paused nach", False),
    (Cause.CHECKOUT_ABANDONED, RecordType.CHECKOUT_ABANDONED, 399, None, None, "user closed sheet", False),
    (Cause.INVOICE_UNPAID, RecordType.INVOICE_OVERDUE, 18500, None, None, "net-30 slipped", False),
]

FORCE_FAIL_INDEX = 18  # high-value expired card — used for graceful Razorpay failure in agent after approve? 
# We'll mark one low-value record for forced razorpay error via notes sentinel.


def seed(n: int | None = None) -> int:
    init_db()
    rows = SPEC if n is None else SPEC[: max(50, min(n, len(SPEC)))]
    conn = connect()
    conn.execute("DELETE FROM decisions")
    conn.execute("DELETE FROM runs")
    conn.execute("DELETE FROM records")
    now = datetime.now(timezone.utc).isoformat()
    rng = random.Random(42)
    for i, spec in enumerate(rows, start=1):
        cause, rtype, amount_inr, code, desc, notes, opted = spec
        tpl = CUSTOMERS[i % len(CUSTOMERS)]
        rec_id = f"atr_{i:03d}"
        force = i == 12  # insufficient funds row — simulated API failure
        extra = " | FORCE_RZP_ERROR" if force else ""
        conn.execute(
            """
            INSERT INTO records (
                id, customer_name, email, phone, amount_paise, record_type,
                error_code, error_description, notes, opted_out, true_cause, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                rec_id,
                tpl[0],
                tpl[1].format(i=i),
                tpl[2].format(i=i),
                int(amount_inr * 100) + rng.randint(0, 80),
                rtype.value,
                code,
                desc,
                notes + extra,
                1 if opted else 0,
                cause.value,
                now,
            ),
        )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    conn.close()
    return int(count)

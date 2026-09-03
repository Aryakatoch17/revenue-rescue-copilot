import json

from app.db import connect, init_db
from app.enums import Outcome
from app.proof import ingest_webhook
from app.seed import seed


def test_webhook_marks_awaiting_decision_paid():
    seed()
    init_db()
    conn = connect()
    conn.execute("DELETE FROM decisions WHERE id='dec_wh_test'")
    conn.execute("DELETE FROM runs WHERE id='run_wh_test'")
    rec = dict(conn.execute("SELECT id, amount_paise FROM records ORDER BY id LIMIT 1").fetchone())
    conn.execute(
        "INSERT INTO runs (id, policy, started_at, at_risk_paise) VALUES ('run_wh_test','proof',datetime('now'),?)",
        (rec["amount_paise"],),
    )
    conn.execute(
        """
        INSERT INTO decisions (
          id, run_id, record_id, policy, proposed_action, proposed_channel, message_body,
          supervisor_allowed, supervisor_status, rule_ids, supervisor_reason,
          razorpay_link_id, razorpay_short_url, outcome, recovered_paise, created_at
        ) VALUES (
          'dec_wh_test','run_wh_test',?,'proof','update_instrument_link','email','pay',
          1,'allowed','[]','await','plink_demo_1','https://rzp.io/i/x',?,0,datetime('now')
        )
        """,
        (rec["id"], Outcome.AWAITING_PAYMENT.value),
    )
    conn.commit()
    conn.close()

    body = json.dumps(
        {
            "event": "payment_link.paid",
            "payload": {"payment_link": {"entity": {"id": "plink_demo_1", "payments": ["pay_1"]}}},
        }
    ).encode()
    out = ingest_webhook(body, signature=None)
    assert out["ok"] is True
    assert out["decision"]["outcome"] == Outcome.RECOVERED.value
    assert out["decision"]["recovered_paise"] == rec["amount_paise"]

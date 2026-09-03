from concurrent.futures import ThreadPoolExecutor

from app.ops import BusyError, exclusive, status
from app.proof import start_live_proof
from app.seed import seed


def test_exclusive_rejects_concurrent():
    entered = []

    def slow():
        with exclusive("slow"):
            entered.append(1)
            import time

            time.sleep(0.2)

    with ThreadPoolExecutor(2) as pool:
        f1 = pool.submit(slow)
        import time

        time.sleep(0.05)
        f2 = pool.submit(slow)
        e1 = e2 = None
        try:
            f1.result()
        except Exception as exc:  # noqa: BLE001
            e1 = exc
        try:
            f2.result()
        except Exception as exc:  # noqa: BLE001
            e2 = exc
    assert e1 is None
    assert isinstance(e2, BusyError)
    assert status()["busy"] is False


def test_proof_reuses_open_link_without_new_create(monkeypatch):
    seed()
    calls = {"n": 0}

    class FakeExec:
        live = True

        def create_recovery_link(self, *a, **k):
            calls["n"] += 1
            return {
                "link_id": "plink_reuse_1",
                "short_url": "https://rzp.io/i/reuse",
                "mode": "razorpay_test",
                "error": None,
            }

    monkeypatch.setattr("app.proof.RazorpayExecutor", FakeExec)
    first = start_live_proof("atr_017")
    second = start_live_proof("atr_017")
    assert first["link_id"] == "plink_reuse_1"
    assert second["reused"] is True
    assert calls["n"] == 1

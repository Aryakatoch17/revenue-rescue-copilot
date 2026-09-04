# Revenue Rescue Copilot — Razorpay AI Buildathon Track 03

Diagnose why a rupee slipped, pick a **bounded action** (not just a channel), execute it in **Razorpay test mode**, and show **₹ recovered vs a naive baseline** on 50+ synthetic cases.

The LLM proposes. A Python **supervisor** is the authority. Recovery in the simulator depends on **whether the action matches the hidden true cause**, not on “voice converts at 70%.”

## Loop

1. Detect at-risk money (failed payment, failed subscription/mandate, abandoned checkout, overdue invoice).
2. Diagnose a fixed cause enum (Groq Llama if `GROQ_API_KEY` is set and mode is `live`, otherwise baked cache or rules).
3. Propose `{action, channel, message}`.
4. **Supervisor (code):** opt-out, cancelled/fraud hard-stop, attempt cap, voice floor, bank-down no-nag, human queue ≥ ₹20,000.
5. Execute: Razorpay Payment Link (`payment_links.create`) when a link is required. Without keys, a clearly labeled stub id is used.
6. Simulate the customer from **cause × action**.
7. Audit every step. Compare to baseline: one email + generic link, same stop-rules.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# optional: GROQ_API_KEY, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET (test)
# Judges: leave DIAGNOSIS_MODE=cache (default). No Groq quota required.

python -c "from app.seed import seed; print(seed())"
uvicorn app.main:app --reload --port 8000
# open http://127.0.0.1:8000
```

Bake Groq diagnoses **once** on your laptop. Commit `data/diagnosis_cache.json`. After that, every Run both is local:

```bash
python -m app.bake
```


**Mash-safe behaviour**
- Reseed / Run both / Approve / Proof take a process lock → concurrent clicks get **HTTP 409 Busy**.
- Run both **auto-seeds** if the DB is empty.
- Live proof works **cold** (no prior batch). Unpaid links are **reused** per record; new creates capped (~25/hour) so judges don’t burn Razorpay test quota.
- Refresh restores open proof from the API + browser `localStorage`.
- If Razorpay keys are missing, live proof returns a clear 503; **batch lift still works**.


Tests:

```bash
pip install pytest
pytest -q
```

## Demo (4 minutes)

1. Open the UI — read the **cause → action** matrix (not channel picker).
2. **Reseed** → **Run baseline + agent** → read **lift live**.
3. Open a win / stop / Razorpay error in the audit.
4. **Approve** a ≥ ₹20k queue item.
5. **Live proof:** open a fresh Payment Link → pay with Razorpay test card → **Poll paid?** (or configure webhook to `/api/webhooks/razorpay`).

Do not quote a scripted recovery %. The number is generated live vs baseline.

## Differentiation

Most Track 03 demos are “AI sends SMS.” Rescue is **action selection under a policy kernel**, with **₹ lift vs baseline** and a **real Razorpay paid path** for one proof transaction. Batch recovery is still simulated (causal); live proof is not.

## Why diagnosis matters

| Hidden cause | Correct action | Wrong action |
|---|---|---|
| `bank_down` | `wait_auto_retry` (system, no nag) | SMS now |
| `insufficient_funds` | `delay_retry` | Immediate generic link as if cart drop |
| `instrument_expired` | `update_instrument_link` | Retry same instrument |
| `mandate_paused` | `remandate_link` | Normal charge reminder |
| `checkout_abandoned` | `cart_reminder_link` | Voice on low AOV (blocked) |
| `invoice_unpaid` | `invoice_link` (+ human if high value) | Ignore aging |
| `customer_cancelled` / `fraud_flag` | `stop` | Any outreach = violation |

## Layout

- `app/supervisor.py` — deterministic policy kernel
- `app/diagnosis.py` / `app/intervention.py` — propose only
- `app/simulator.py` — causal recovery
- `app/razorpay_exec.py` — test-mode Payment Links
- `app/runner.py` — batch + approve
- `app/static/index.html` — demo UI
- `app/main.py` — FastAPI


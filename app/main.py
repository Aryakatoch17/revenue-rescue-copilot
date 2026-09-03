from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.cache import cache_stats
from app.config import settings
from app.db import init_db
from app.enums import CORRECT_ACTION, Policy
from app.ops import BusyError, exclusive, status as ops_status
from app.proof import (
    ingest_webhook,
    latest_open_proof,
    poll_payment_link,
    proof_candidates,
    recent_webhooks,
    start_live_proof,
)
from app.runner import (
    approve_all_queued,
    approve_decision,
    latest_runs,
    record_stats,
    run_detail,
    run_policy,
)
from app.seed import seed

STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if record_stats()["count"] == 0:
        seed()
    yield


app = FastAPI(title="Revenue Rescue Copilot", version="0.3.0", lifespan=lifespan)


class RunBody(BaseModel):
    policy: Policy = Policy.AGENT
    seed: int = 7


class ApproveBody(BaseModel):
    approve: bool = True


class ProofBody(BaseModel):
    record_id: str = "atr_017"


class PollBody(BaseModel):
    link_id: str


def _busy_http(exc: BusyError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": str(exc), "busy": True, "op": exc.op, **ops_status()},
    )


def _ensure_records() -> None:
    if record_stats()["count"] == 0:
        seed()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def api_health():
    return {
        "ok": True,
        **ops_status(),
        "records": record_stats()["count"],
        "razorpay_configured": bool(settings.razorpay_key_id and settings.razorpay_key_secret),
        "diagnosis_mode": settings.diagnosis_mode,
        "allow_live_llm": settings.allow_live_llm,
    }


@app.post("/api/seed")
def api_seed():
    try:
        with exclusive("reseed"):
            n = seed()
            return {"records": n, **record_stats()}
    except BusyError as exc:
        return _busy_http(exc)


@app.get("/api/stats")
def api_stats():
    open_proof = latest_open_proof()
    return {
        **record_stats(),
        **ops_status(),
        "diagnosis_mode": settings.diagnosis_mode,
        "allow_live_llm": settings.allow_live_llm,
        "groq_model": settings.groq_model,
        "groq_configured": bool(settings.groq_api_key),
        "razorpay_configured": bool(settings.razorpay_key_id and settings.razorpay_key_secret),
        "webhook_secret_set": bool(settings.razorpay_webhook_secret),
        "cache": cache_stats(),
        "open_proof": {
            "link_id": open_proof.get("razorpay_link_id") if open_proof else None,
            "pay_url": open_proof.get("razorpay_short_url") if open_proof else None,
            "record_id": open_proof.get("record_id") if open_proof else None,
        },
    }


@app.get("/api/matrix")
def api_matrix():
    return [{"cause": c.value, "action": a.value} for c, a in CORRECT_ACTION.items()]


@app.post("/api/runs")
def api_run(body: RunBody):
    try:
        with exclusive(f"run:{body.policy.value}"):
            _ensure_records()
            return run_policy(body.policy, seed=body.seed)
    except BusyError as exc:
        return _busy_http(exc)


@app.post("/api/runs/both")
def api_run_both(body: RunBody):
    try:
        with exclusive("run_both"):
            _ensure_records()
            baseline = run_policy(Policy.BASELINE, seed=body.seed)
            agent = run_policy(Policy.AGENT, seed=body.seed)
            return {"baseline": baseline, "agent": agent}
    except BusyError as exc:
        return _busy_http(exc)


@app.get("/api/runs")
def api_runs():
    return latest_runs()


@app.get("/api/runs/{run_id}")
def api_run_detail(run_id: str):
    data = run_detail(run_id)
    if not data["run"]:
        raise HTTPException(404, "run not found")
    return data


@app.post("/api/runs/{run_id}/approve-all")
def api_approve_all(run_id: str, body: ApproveBody):
    try:
        with exclusive("approve"):
            return approve_all_queued(run_id, body.approve)
    except BusyError as exc:
        return _busy_http(exc)


@app.post("/api/decisions/{decision_id}/resolve")
def api_resolve(decision_id: str, body: ApproveBody):
    try:
        with exclusive("approve"):
            return approve_decision(decision_id, body.approve)
    except BusyError as exc:
        return _busy_http(exc)
    except KeyError:
        raise HTTPException(404, "decision not found")


@app.get("/api/proof/candidates")
def api_proof_candidates():
    return proof_candidates()


@app.post("/api/proof/start")
def api_proof_start(body: ProofBody):
    try:
        with exclusive("proof"):
            return start_live_proof(body.record_id)
    except BusyError as exc:
        return _busy_http(exc)
    except KeyError:
        raise HTTPException(404, "record not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@app.post("/api/proof/poll")
def api_proof_poll(body: PollBody):
    return poll_payment_link(body.link_id)


@app.get("/api/webhooks/recent")
def api_webhooks_recent():
    return recent_webhooks()


@app.post("/api/webhooks/razorpay")
async def api_razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
):
    body = await request.body()
    return ingest_webhook(body, x_razorpay_signature)

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)


def _get(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or default).strip().strip('"').strip("'")


class Settings:
    groq_api_key: str = _get("GROQ_API_KEY")
    groq_model: str = _get("GROQ_MODEL", "openai/gpt-oss-20b") or "openai/gpt-oss-20b"
    razorpay_key_id: str = _get("RAZORPAY_KEY_ID")
    razorpay_key_secret: str = _get("RAZORPAY_KEY_SECRET")
    database_path: str = _get("DATABASE_PATH", "data/rescue.db") or "data/rescue.db"
    approval_threshold_inr: int = int(_get("APPROVAL_THRESHOLD_INR", "20000") or "20000")
    max_attempts: int = int(_get("MAX_ATTEMPTS", "2") or "2")
    cooldown_hours: int = int(_get("COOLDOWN_HOURS", "2") or "2")
    # cache = replay baked Groq diagnoses (default, judge-safe)
    # live = call Groq then write cache
    # rules = never call Groq
    diagnosis_mode: str = (_get("DIAGNOSIS_MODE", "cache") or "cache").lower()
    live_copy: bool = _get("LIVE_COPY", "0").lower() in {"1", "true", "yes"}
    # diagnose() will not call Groq unless this is on. Bake uses _llm_diagnose() directly.
    allow_live_llm: bool = _get("ALLOW_LIVE_LLM", "0").lower() in {"1", "true", "yes"}
    razorpay_webhook_secret: str = _get("RAZORPAY_WEBHOOK_SECRET")
    # Batch runs stub Payment Links by default (avoids Razorpay test-mode 30/day create cap).
    # Live proof still creates/reuses real links.
    razorpay_live_batch: bool = _get("RAZORPAY_LIVE_BATCH", "0").lower() in {
        "1",
        "true",
        "yes",
    }


settings = Settings()

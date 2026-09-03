from __future__ import annotations

import json
import re

from openai import OpenAI

from app.config import settings

GROQ_BASE = "https://api.groq.com/openai/v1"
_JSON_RE = re.compile(r"\{.*\}", re.S)


def llm_configured() -> bool:
    return bool(settings.groq_api_key)


def groq_client() -> OpenAI:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set")
    return OpenAI(
        api_key=settings.groq_api_key,
        base_url=GROQ_BASE,
        timeout=30.0,
    )


def parse_json_object(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = _JSON_RE.search(raw)
        if not m:
            raise
        data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise ValueError("LLM did not return a JSON object")
    return data


def chat_json(*, system: str, user: str, temperature: float = 0) -> dict:
    client = groq_client()
    kwargs = dict(
        model=settings.groq_model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    try:
        resp = client.chat.completions.create(
            **kwargs, response_format={"type": "json_object"}
        )
    except Exception:
        resp = client.chat.completions.create(**kwargs)
    content = resp.choices[0].message.content or ""
    return parse_json_object(content)

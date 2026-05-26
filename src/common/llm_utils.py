from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from typing import Any, Callable


SYSTEM_MESSAGE = (
    "你是一个严谨的科研论文筛选助手。你必须只输出合法 JSON，"
    "不得输出 Markdown、解释性前后缀或额外文本。"
)


def retry_call(
    fn: Callable[[], Any],
    *,
    label: str,
    max_retries: int,
    initial_wait: float,
    max_wait: float,
) -> Any:
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            wait = min(max_wait, initial_wait * (2 ** (attempt - 1)))
            wait *= 0.8 + random.random() * 0.4
            logging.warning(
                "%s failed on attempt %d/%d: %s; retrying in %.1fs",
                label,
                attempt,
                max_retries,
                exc,
                wait,
            )
            time.sleep(wait)
    raise RuntimeError(f"{label} failed after {max_retries} attempts: {last_exc}") from last_exc


def extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for idx, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[idx:])
            return parsed
        except json.JSONDecodeError:
            continue
    raise ValueError(f"Model output did not contain valid JSON: {text[:500]}")


def create_openai_client():
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("Please install openai first: pip install openai") from exc

    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required.")

    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "timeout": float(os.environ.get("AI_PAPER_SELECTOR_TIMEOUT", "180")),
        "max_retries": 0,
        "default_headers": {
            "User-Agent": os.environ.get("AI_PAPER_SELECTOR_USER_AGENT", "ai-paper-selector/0.1")
        },
    }
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def call_llm_json(
    client: Any,
    *,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> Any:
    request: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        request["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**request)
    content = response.choices[0].message.content
    if not content:
        raise ValueError("Model returned empty content")
    return extract_json(content)

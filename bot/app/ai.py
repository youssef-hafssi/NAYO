"""Gemini, structured output only. Anything that isn't valid JSON for AIResult is retried once, then an error."""

from __future__ import annotations

import logging
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from .prompts import SYSTEM_PROMPT, build_user_turn

log = logging.getLogger("nayo.ai")

Intent = Literal[
    "confirm", "cancel", "provide_details", "question", "change_quantity", "new_order", "add_or_new_order",
    "complaint", "other",
]


class AIResult(BaseModel):
    reply: str = Field(max_length=700)
    intent: Intent
    city: str | None = Field(default=None, max_length=80)
    address: str | None = Field(default=None, max_length=300)
    quantity: int | None = None
    needs_human: bool = False


class AIError(Exception):
    pass


class AI(Protocol):
    def run(self, context: dict, history: list[tuple[str, str]], last_message: str) -> AIResult: ...


class GeminiAI:
    def __init__(
        self,
        api_key: str,
        model: str,
        client: Any = None,
        *,
        fallback_model: str = "",
        timeout_s: float = 20,
        thinking_budget: int | None = 0,
    ):
        if client is None:
            from google import genai
            from google.genai import types

            # Hard time limit per call: an overloaded model must fail fast, never keep a client waiting minutes.
            client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))
        self._client = client
        self._model = model
        # Attempt 1 → main model, attempt 2 → fallback (when the main one is overloaded or returned bad JSON).
        self._models = (model, fallback_model or model)
        self._thinking_budget = thinking_budget

    def run(self, context: dict, history: list[tuple[str, str]], last_message: str) -> AIResult:
        from google.genai import types

        prompt = build_user_turn(context, history, last_message)
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=AIResult,
            temperature=0.3,
            max_output_tokens=600,
        )
        # The task is classification + one short sentence: "thinking" only adds seconds of latency.
        # Only the main model gets this setting — "lite" models reject it (400 INVALID_ARGUMENT).
        main_config = config.model_copy(
            update={"thinking_config": types.ThinkingConfig(thinking_budget=self._thinking_budget)}
        ) if self._thinking_budget is not None else config
        last_err: Exception | None = None
        for attempt, model in enumerate(self._models, 1):
            try:
                cfg = main_config if attempt == 1 else config
                resp = self._client.models.generate_content(model=model, contents=prompt, config=cfg)
                result = AIResult.model_validate_json(resp.text or "")
                return _clean(result)
            except ValidationError as e:
                last_err = e
                log.warning("Gemini %s returned invalid JSON (attempt %d): %s", model, attempt, e.errors()[:2])
            except Exception as e:  # network / quota / overloaded (503) / timeout
                last_err = e
                log.warning("Gemini %s call failed (attempt %d): %s %s", model, attempt, type(e).__name__, str(e)[:120])
        raise AIError(str(last_err))


def _clean(r: AIResult) -> AIResult:
    def blank(v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None

    return r.model_copy(update={"reply": r.reply.strip(), "city": blank(r.city), "address": blank(r.address)})

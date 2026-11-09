"""Gemini layer with a fake client: JSON validation, single retry, errors."""

import pytest

from app.ai import AIError, GeminiAI


class Resp:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append((model, contents, config))
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return Resp(out)


class FakeClient:
    def __init__(self, outputs):
        self.models = FakeModels(outputs)


GOOD = '{"reply":"Merci !","intent":"provide_details","city":" Agadir ","address":"","quantity":null,"needs_human":false}'


def test_valid_json():
    c = FakeClient([GOOD])
    r = GeminiAI("k", "m", client=c).run({"order_number": "NAYO-1"}, [], "agadir")
    assert (r.intent, r.city, r.address) == ("provide_details", "Agadir", None)
    model, contents, config = c.models.calls[0]
    assert model == "m" and "<<<\nagadir\n>>>" in contents
    assert config.response_mime_type == "application/json"


def test_retries_once_on_invalid_json():
    c = FakeClient(["not json", GOOD])
    assert GeminiAI("k", "m", client=c).run({}, [], "x").intent == "provide_details"
    assert len(c.models.calls) == 2


def test_unknown_intent_is_invalid():
    c = FakeClient(['{"reply":"x","intent":"give_discount","needs_human":false}'] * 2)
    with pytest.raises(AIError):
        GeminiAI("k", "m", client=c).run({}, [], "x")


def test_api_down_raises_after_retry():
    c = FakeClient([RuntimeError("503"), RuntimeError("503")])
    with pytest.raises(AIError):
        GeminiAI("k", "m", client=c).run({}, [], "x")


def test_second_attempt_uses_fallback_model():
    c = FakeClient([RuntimeError("503 high demand"), GOOD])
    r = GeminiAI("k", "main-model", client=c, fallback_model="backup-model").run({}, [], "x")
    assert r.intent == "provide_details"
    assert [call[0] for call in c.models.calls] == ["main-model", "backup-model"]
    assert c.models.calls[1][2].thinking_config is None  # lite fallback models reject a thinking config


def test_thinking_disabled_by_default():
    c = FakeClient([GOOD])
    GeminiAI("k", "m", client=c).run({}, [], "x")
    assert c.models.calls[0][2].thinking_config.thinking_budget == 0

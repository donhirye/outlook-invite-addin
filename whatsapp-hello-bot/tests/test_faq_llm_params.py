"""Regression: model-specific Responses API temperature / reasoning.effort."""

import os

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""

import pytest

from app.faq_service import (
    FAQ_LLM_TEMPERATURE,
    build_faq_llm_create_kwargs,
    call_faq_llm_with_param_fallback,
)


@pytest.mark.parametrize(
    "model,effort,expect_temp,expect_reasoning",
    [
        ("gpt-4o-mini", "minimal", True, None),
        ("gpt-4o-mini", "none", True, None),
        ("gpt-4o-mini", "", True, None),
        ("gpt-4.1", "low", True, None),
        ("gpt-5.6-luna", "minimal", False, {"effort": "minimal"}),
        ("gpt-5.2", "low", False, {"effort": "low"}),
        ("gpt-5.2", "none", False, None),
        ("o3-mini", "medium", False, {"effort": "medium"}),
        ("o1", "", False, None),
    ],
)
def test_build_faq_llm_create_kwargs_model_matrix(
    model, effort, expect_temp, expect_reasoning
):
    kwargs = build_faq_llm_create_kwargs(
        model=model,
        instructions="sys",
        user_input="q",
        temperature=FAQ_LLM_TEMPERATURE,
        reasoning_effort=effort,
    )
    assert kwargs["model"] == model
    assert kwargs["instructions"] == "sys"
    assert kwargs["input"] == "q"
    if expect_temp:
        assert kwargs["temperature"] == FAQ_LLM_TEMPERATURE
    else:
        assert "temperature" not in kwargs
    if expect_reasoning is None:
        assert "reasoning" not in kwargs
    else:
        assert kwargs["reasoning"] == expect_reasoning


def test_fallback_strips_temperature_then_succeeds():
    calls: list[dict] = []

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(dict(kwargs))
            if "temperature" in kwargs:
                raise RuntimeError(
                    "Unsupported parameter: 'temperature' is not supported with this model."
                )
            return {"ok": True}

    class FakeClient:
        responses = FakeResponses()

    # Simulate a misconfigured call that still includes temperature for a reasoning model.
    out = call_faq_llm_with_param_fallback(
        FakeClient(),
        {
            "model": "gpt-5.6-luna",
            "instructions": "sys",
            "input": "q",
            "temperature": 0,
            "reasoning": {"effort": "minimal"},
        },
    )
    assert out == {"ok": True}
    assert len(calls) == 2
    assert "temperature" in calls[0]
    assert "temperature" not in calls[1]
    assert calls[1].get("reasoning") == {"effort": "minimal"}


def test_fallback_strips_reasoning_then_succeeds():
    calls: list[dict] = []

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(dict(kwargs))
            if "reasoning" in kwargs:
                raise RuntimeError(
                    "Unsupported value: 'minimal' is not supported for reasoning.effort."
                )
            return {"ok": True}

    class FakeClient:
        responses = FakeResponses()

    out = call_faq_llm_with_param_fallback(
        FakeClient(),
        {
            "model": "gpt-4o-mini",
            "instructions": "sys",
            "input": "q",
            "temperature": 0,
            "reasoning": {"effort": "minimal"},
        },
    )
    assert out == {"ok": True}
    assert len(calls) == 2
    assert "reasoning" in calls[0]
    assert "reasoning" not in calls[1]
    assert calls[1].get("temperature") == 0


def test_fallback_strips_both_when_error_mentions_both():
    calls: list[dict] = []

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(dict(kwargs))
            if "temperature" in kwargs or "reasoning" in kwargs:
                raise RuntimeError(
                    "Unsupported parameters: temperature and reasoning are not allowed."
                )
            return {"ok": True}

    class FakeClient:
        responses = FakeResponses()

    out = call_faq_llm_with_param_fallback(
        FakeClient(),
        {
            "model": "gpt-5",
            "temperature": 0,
            "reasoning": {"effort": "minimal"},
            "input": "q",
        },
    )
    assert out == {"ok": True}
    assert len(calls) == 2
    assert "temperature" not in calls[1]
    assert "reasoning" not in calls[1]


def test_fallback_reraises_unrelated_errors():
    class FakeResponses:
        def create(self, **kwargs):
            raise RuntimeError("rate limit exceeded")

    class FakeClient:
        responses = FakeResponses()

    with pytest.raises(RuntimeError, match="rate limit"):
        call_faq_llm_with_param_fallback(
            FakeClient(),
            {"model": "gpt-4o-mini", "temperature": 0, "input": "q"},
        )

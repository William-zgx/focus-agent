from __future__ import annotations

import json

import httpx
import pytest

import focus_agent.decision_models as decision_models
from focus_agent.config import ConfiguredModel, ModelCatalogConfig, ProviderConfig, Settings
from focus_agent.decision_models import (
    DecisionModelConfigurationError,
    DecisionModelHTTPError,
    DecisionModelResponseError,
    DecisionModelTransportError,
    evaluate_decision_model,
)


def _settings(*, protocol: str = "system_one", second_provider: bool = False) -> Settings:
    providers = [
        ProviderConfig(
            id="acme",
            base_url_env="ACME_BASE_URL",
            api_key_env="ACME_API_KEY",
        )
    ]
    models = [ConfiguredModel(id="acme:decision-v1", protocol=protocol)]
    resolved_env = {
        "ACME_BASE_URL": "https://decision.example/v1",
        "ACME_API_KEY": "test-secret",
    }
    if second_provider:
        providers.append(
            ProviderConfig(
                id="other",
                base_url_env="OTHER_BASE_URL",
                api_key_env="OTHER_API_KEY",
            )
        )
        models.append(ConfiguredModel(id="other:decision-v2", protocol=protocol))
        resolved_env.update(
            {
                "OTHER_BASE_URL": "https://other.example/v1",
                "OTHER_API_KEY": "other-secret",
            }
        )
    return Settings(
        model="acme:decision-v1",
        model_catalog=ModelCatalogConfig(
            providers=tuple(providers),
            models=tuple(models),
        ),
        resolved_env=resolved_env,
    )


def _questions() -> dict[str, dict[str, object]]:
    return {
        "team": {
            "type": "choice",
            "instructions": "Choose the owning team.",
            "criteria": {"billing": "Billing", "support": "Support"},
        },
        "urgency": {
            "type": "score",
            "instructions": "Score urgency.",
            "criteria": ["Normal", "Timely", "Immediate"],
        },
        "duplicate": {
            "type": "noul",
            "instructions": "Is this a duplicate?",
        },
    }


def _response() -> dict[str, object]:
    return {
        "model": "decision-v1-served",
        "answers": {
            "team": {
                "type": "choice",
                "choice": "billing",
                "confidence": 0.9,
                "probabilities": {"billing": 0.9, "support": 0.1},
            },
            "urgency": {
                "type": "score",
                "score": 1.75,
                "confidence": 0.8,
                "probabilities": {"0": 0.05, "1": 0.1, "2": 0.85},
            },
            "duplicate": {"type": "noul", "noul": 0.2},
        },
        "usage": {"input_tokens": 100, "output_tokens": 12},
    }


def _mock_client(monkeypatch: pytest.MonkeyPatch, handler) -> httpx.Client:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(decision_models, "shared_sync_http_client", lambda: client)
    return client


def test_evaluate_sends_typed_payload_and_parses_all_answer_types(monkeypatch):
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["Authorization"]
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_response(), request=request)

    client = _mock_client(monkeypatch, handler)
    try:
        result = evaluate_decision_model(
            settings=_settings(),
            model_id="acme:decision-v1",
            state={"message": "Please review this billing issue."},
            questions=_questions(),
            timeout_seconds=2,
        )
    finally:
        client.close()

    assert seen["url"] == "https://decision.example/v1/systemone"
    assert seen["authorization"] == "Bearer test-secret"
    assert seen["payload"] == {
        "model": "decision-v1",
        "state": {"message": "Please review this billing issue."},
        "questions": _questions(),
    }
    assert result.model == "decision-v1-served"
    assert result.answers["team"].choice == "billing"
    assert result.answers["urgency"].score == 1.75
    assert result.answers["duplicate"].noul == 0.2
    assert result.usage == {"input_tokens": 100, "output_tokens": 12}


def test_evaluate_resolves_another_configured_provider_and_model(monkeypatch):
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["Authorization"]
        seen["model"] = json.loads(request.content)["model"]
        return httpx.Response(200, json=_response(), request=request)

    client = _mock_client(monkeypatch, handler)
    try:
        evaluate_decision_model(
            settings=_settings(second_provider=True),
            model_id="other:decision-v2",
            state={},
            questions=_questions(),
            timeout_seconds=1,
        )
    finally:
        client.close()

    assert seen == {
        "url": "https://other.example/v1/systemone",
        "authorization": "Bearer other-secret",
        "model": "decision-v2",
    }


def test_evaluate_rejects_chat_protocol_before_network(monkeypatch):
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500, request=request)

    client = _mock_client(monkeypatch, handler)
    try:
        with pytest.raises(DecisionModelConfigurationError, match="system_one"):
            evaluate_decision_model(
                settings=_settings(protocol="chat"),
                model_id="acme:decision-v1",
                state={},
                questions=_questions(),
                timeout_seconds=1,
            )
    finally:
        client.close()

    assert called is False


def test_evaluate_reports_missing_endpoint_or_key_without_network():
    settings = _settings()
    settings.resolved_env = {"ACME_API_KEY": "test-secret"}
    with pytest.raises(DecisionModelConfigurationError, match="base URL"):
        evaluate_decision_model(
            settings=settings,
            model_id="acme:decision-v1",
            state={},
            questions=_questions(),
            timeout_seconds=1,
        )

    settings.resolved_env = {"ACME_BASE_URL": "https://decision.example/v1"}
    with pytest.raises(DecisionModelConfigurationError, match="API key"):
        evaluate_decision_model(
            settings=settings,
            model_id="acme:decision-v1",
            state={},
            questions=_questions(),
            timeout_seconds=1,
        )


def test_evaluate_preserves_http_status_for_fallback(monkeypatch):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, request=request)

    client = _mock_client(monkeypatch, handler)
    try:
        with pytest.raises(DecisionModelHTTPError) as raised:
            evaluate_decision_model(
                settings=_settings(),
                model_id="acme:decision-v1",
                state={},
                questions=_questions(),
                timeout_seconds=1,
            )
    finally:
        client.close()

    assert raised.value.status_code == 429
    assert calls == 1
    assert "test-secret" not in str(raised.value)


def test_evaluate_maps_transport_failure_without_request_details(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    client = _mock_client(monkeypatch, handler)
    try:
        with pytest.raises(DecisionModelTransportError) as raised:
            evaluate_decision_model(
                settings=_settings(),
                model_id="acme:decision-v1",
                state={},
                questions=_questions(),
                timeout_seconds=1,
            )
    finally:
        client.close()

    assert "test-secret" not in str(raised.value)
    assert "connection failed" not in str(raised.value)


def test_evaluate_rejects_invalid_probabilities(monkeypatch):
    payload = _response()
    payload["answers"]["team"]["probabilities"] = {"billing": 0.4, "support": 0.4}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    client = _mock_client(monkeypatch, handler)
    try:
        with pytest.raises(DecisionModelResponseError, match="sum to one"):
            evaluate_decision_model(
                settings=_settings(),
                model_id="acme:decision-v1",
                state={},
                questions=_questions(),
                timeout_seconds=1,
            )
    finally:
        client.close()


def test_evaluate_rejects_missing_answer(monkeypatch):
    payload = _response()
    del payload["answers"]["duplicate"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    client = _mock_client(monkeypatch, handler)
    try:
        with pytest.raises(DecisionModelResponseError, match="do not match questions"):
            evaluate_decision_model(
                settings=_settings(),
                model_id="acme:decision-v1",
                state={},
                questions=_questions(),
                timeout_seconds=1,
            )
    finally:
        client.close()

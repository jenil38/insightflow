"""Route-level integration tests for POST /datasets/{id}/agent/ask.

These go through the real FastAPI app (auth, get_owned_dataset, the exception
handlers) with only the provider mocked, to prove the wiring in tool_agent.py
and main.py actually works end to end -- the service's own loop logic is
already covered by test_tool_agent_service.py.
"""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest
from app import models
from app.core.config import settings
from app.database import SessionLocal

SALES_CSV = (
    b"date,region,product,units,price,revenue\n"
    b"2024-01-01,North,Widget,10,100,1000\n"
    b"2024-01-02,South,Gadget,20,50,1000\n"
    b"2024-01-03,East,Widget,15,100,1500\n"
    b"2024-01-04,West,Gadget,25,50,1250\n"
)


@pytest.fixture(autouse=True)
def _configured_agent(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key")


@pytest.fixture
def auth_and_dataset(client):
    client.post(
        "/auth/register",
        json={
            "email": "route-agent@example.com",
            "password": "StrongPass1!",
            "full_name": "Route Agent User",
        },
    )
    tokens = client.post(
        "/auth/login",
        json={"email": "route-agent@example.com", "password": "StrongPass1!"},
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    dataset_id = client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": ("sales.csv", io.BytesIO(SALES_CSV), "text/csv")},
    ).json()["id"]
    return headers, dataset_id


def _mock_response(
    status_code: int = 200, json_data: dict | None = None, text: str = ""
):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


def _tool_call_response(tool_name: str, arguments: dict, call_id: str = "call_1"):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


def _plain_answer_response(text: str):
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": text, "tool_calls": None},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
    }


# ----------------------------------------------------------------- happy path


@patch("app.services.chat_service.requests.post")
def test_ask_returns_the_answer_and_the_step_trace(mock_post, client, auth_and_dataset):
    headers, dataset_id = auth_and_dataset
    mock_post.side_effect = [
        _mock_response(200, _tool_call_response("get_dataset_overview", {})),
        _mock_response(200, _plain_answer_response("The dataset has 4 rows.")),
    ]

    response = client.post(
        f"/datasets/{dataset_id}/agent/ask",
        headers=headers,
        json={"question": "How many rows?", "allow_actions": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["answer"] == "The dataset has 4 rows."
    assert body["allow_actions"] is False
    assert len(body["steps"]) == 1
    assert body["steps"][0]["tool_name"] == "get_dataset_overview"
    assert body["steps"][0]["status"] == "ok"
    # The trace fields the UI renders must actually reach the client.
    assert body["steps"][0]["arguments"] == {}
    assert body["steps"][0]["duration_seconds"] is not None
    assert body["total_prompt_tokens"] == 150
    assert body["total_completion_tokens"] == 30

    # Persisted for real, not just returned.
    db = SessionLocal()
    try:
        run = db.query(models.AgentRun).filter(models.AgentRun.id == body["id"]).first()
        assert run is not None
        assert run.status == "completed"
    finally:
        db.close()


# ------------------------------------------------------------ default args


@patch("app.services.chat_service.requests.post")
def test_allow_actions_defaults_to_false(mock_post, client, auth_and_dataset):
    headers, dataset_id = auth_and_dataset
    mock_post.return_value = _mock_response(200, _plain_answer_response("ok"))

    response = client.post(
        f"/datasets/{dataset_id}/agent/ask",
        headers=headers,
        json={"question": "Anything"},
    )

    assert response.status_code == 200
    assert response.json()["allow_actions"] is False


# --------------------------------------------------------------- auth/ownership


def test_ask_requires_auth(client, auth_and_dataset):
    _, dataset_id = auth_and_dataset
    response = client.post(
        f"/datasets/{dataset_id}/agent/ask", json={"question": "Anything"}
    )
    assert response.status_code == 401


def test_ask_rejects_a_dataset_owned_by_someone_else(client, auth_and_dataset):
    _headers, dataset_id = auth_and_dataset

    client.post(
        "/auth/register",
        json={
            "email": "someone-else@example.com",
            "password": "StrongPass1!",
            "full_name": "Someone Else",
        },
    )
    other_tokens = client.post(
        "/auth/login",
        json={"email": "someone-else@example.com", "password": "StrongPass1!"},
    ).json()
    other_headers = {"Authorization": f"Bearer {other_tokens['access_token']}"}

    response = client.post(
        f"/datasets/{dataset_id}/agent/ask",
        headers=other_headers,
        json={"question": "Anything"},
    )
    assert response.status_code == 404


# ------------------------------------------------------------- validation


def test_ask_rejects_an_empty_question(client, auth_and_dataset):
    headers, dataset_id = auth_and_dataset
    response = client.post(
        f"/datasets/{dataset_id}/agent/ask",
        headers=headers,
        json={"question": ""},
    )
    assert response.status_code == 422


# -------------------------------------------------------------- not configured


def test_ask_without_a_configured_key_returns_503(
    client, auth_and_dataset, monkeypatch
):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    headers, dataset_id = auth_and_dataset

    response = client.post(
        f"/datasets/{dataset_id}/agent/ask",
        headers=headers,
        json={"question": "Anything"},
    )
    assert response.status_code == 503
    assert response.json()["error_code"] == "agent_not_configured"


# ------------------------------------------------------------------ rate limit


@patch("app.services.chat_service.requests.post")
def test_ask_is_rate_limited_per_hour(mock_post, client, auth_and_dataset, monkeypatch):
    monkeypatch.setattr(settings, "MAX_AGENT_RUNS_PER_HOUR", 1)
    headers, dataset_id = auth_and_dataset
    mock_post.return_value = _mock_response(200, _plain_answer_response("ok"))

    first = client.post(
        f"/datasets/{dataset_id}/agent/ask",
        headers=headers,
        json={"question": "First question"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/datasets/{dataset_id}/agent/ask",
        headers=headers,
        json={"question": "Second question"},
    )
    assert second.status_code == 429
    assert second.json()["error_code"] == "agent_rate_limited"


# ---------------------------------------------------------- action gating


@patch("app.services.chat_service.requests.post")
def test_action_requested_without_allow_actions_is_blocked_end_to_end(
    mock_post, client, auth_and_dataset
):
    headers, dataset_id = auth_and_dataset
    mock_post.side_effect = [
        _mock_response(200, _tool_call_response("apply_cleaning", {})),
        _mock_response(200, _plain_answer_response("I could not clean the data.")),
    ]

    response = client.post(
        f"/datasets/{dataset_id}/agent/ask",
        headers=headers,
        json={"question": "Clean this", "allow_actions": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["steps"][0]["status"] == "blocked_action"

    db = SessionLocal()
    try:
        dataset = (
            db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
        )
        assert dataset.cleaned_path is None
    finally:
        db.close()

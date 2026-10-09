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


# ------------------------------------------- action confirmation (Phase 1.1)


def _big_csv(rows: int = 30) -> bytes:
    lines = ["region,units,price,revenue"]
    for i in range(rows):
        units = 5 + (i * 7) % 23
        price = 8 + (i * 3) % 11
        lines.append(f"{['N', 'S', 'E', 'W'][i % 4]},{units},{price},{units * price}")
    return ("\n".join(lines) + "\n").encode()


def _propose(client, headers, dataset_id, mock_post, tool, arguments, allow=True):
    mock_post.side_effect = None
    mock_post.return_value = _mock_response(200, _tool_call_response(tool, arguments))
    response = client.post(
        f"/datasets/{dataset_id}/agent/ask",
        headers=headers,
        json={"question": "Fix it", "allow_actions": allow},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _decide(client, headers, dataset_id, run_id, approve, **extra):
    return client.post(
        f"/datasets/{dataset_id}/agent/runs/{run_id}/decision",
        headers=headers,
        json={"approve": approve, **extra},
    )


def _dataset_row(dataset_id):
    db = SessionLocal()
    try:
        row = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
        db.expunge(row)
        return row
    finally:
        db.close()


@patch("app.services.chat_service.requests.post")
def test_ask_returns_the_pending_action_and_changes_nothing(
    mock_post, client, auth_and_dataset
):
    headers, dataset_id = auth_and_dataset
    body = _propose(client, headers, dataset_id, mock_post, "apply_cleaning", {})

    assert body["status"] == "awaiting_confirmation"
    assert body["pending_action"] == {
        "step_id": body["steps"][0]["id"],
        "tool_name": "apply_cleaning",
        "arguments": {},
    }
    assert body["steps"][0]["status"] == "pending_confirmation"
    assert _dataset_row(dataset_id).cleaned_path is None


@patch("app.services.chat_service.requests.post")
def test_approve_runs_the_stored_action_and_returns_its_result(
    mock_post, client, auth_and_dataset
):
    headers, dataset_id = auth_and_dataset
    run = _propose(client, headers, dataset_id, mock_post, "apply_cleaning", {})

    response = _decide(client, headers, dataset_id, run["id"], True)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["pending_action"] is None
    assert body["steps"][0]["status"] == "ok"
    assert body["steps"][0]["decided_at"] is not None
    assert "Applied the recommended cleaning" in body["answer"]
    assert body["action_result"]["applied"] is True
    assert "before" in body["action_result"] and "after" in body["action_result"]
    assert _dataset_row(dataset_id).cleaned_path is not None


@patch("app.services.chat_service.requests.post")
def test_approving_train_model_trains_and_returns_the_metrics(mock_post, client):
    client.post(
        "/auth/register",
        json={
            "email": "trainer@example.com",
            "password": "StrongPass1!",
            "full_name": "Trainer",
        },
    )
    tokens = client.post(
        "/auth/login",
        json={"email": "trainer@example.com", "password": "StrongPass1!"},
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    dataset_id = client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": ("big.csv", io.BytesIO(_big_csv()), "text/csv")},
    ).json()["id"]
    run = _propose(
        client,
        headers,
        dataset_id,
        mock_post,
        "train_model",
        {"target_column": "revenue"},
    )

    db = SessionLocal()
    try:
        assert db.query(models.ModelRun).count() == 0
    finally:
        db.close()

    response = _decide(client, headers, dataset_id, run["id"], True)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["steps"][0]["status"] == "ok"
    assert "Trained models to predict `revenue`" in body["answer"]
    assert body["action_result"]["target_column"] == "revenue"
    assert body["action_result"]["results"]
    db = SessionLocal()
    try:
        assert db.query(models.ModelRun).count() >= 1
    finally:
        db.close()


@patch("app.services.chat_service.requests.post")
def test_decline_runs_nothing(mock_post, client, auth_and_dataset):
    headers, dataset_id = auth_and_dataset
    run = _propose(client, headers, dataset_id, mock_post, "apply_cleaning", {})

    response = _decide(client, headers, dataset_id, run["id"], False)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["steps"][0]["status"] == "rejected_by_user"
    assert body["steps"][0]["decided_at"] is not None
    assert body["action_result"] is None
    assert _dataset_row(dataset_id).cleaned_path is None


@patch("app.services.chat_service.requests.post")
def test_a_second_decision_is_refused(mock_post, client, auth_and_dataset):
    headers, dataset_id = auth_and_dataset
    run = _propose(client, headers, dataset_id, mock_post, "apply_cleaning", {})
    assert _decide(client, headers, dataset_id, run["id"], True).status_code == 200

    again = _decide(client, headers, dataset_id, run["id"], True)

    assert again.status_code == 409
    assert again.json()["error_code"] == "already_decided"


@patch("app.services.chat_service.requests.post")
def test_overlapping_approvals_execute_the_action_once(
    mock_post, client, auth_and_dataset, monkeypatch
):
    """A second approval that arrives while the first is still executing must
    not run the action again: the first request has claimed the run."""
    from app.services import tool_agent_service

    headers, dataset_id = auth_and_dataset
    run = _propose(client, headers, dataset_id, mock_post, "apply_cleaning", {})

    real_execute = tool_agent_service.execute_tool
    calls = []
    overlapping = {}

    def execute_and_overlap(ctx, name, arguments):
        calls.append(name)
        if len(calls) == 1:
            overlapping["response"] = _decide(
                client, headers, dataset_id, run["id"], True
            )
        return real_execute(ctx, name, arguments)

    monkeypatch.setattr(tool_agent_service, "execute_tool", execute_and_overlap)

    first = _decide(client, headers, dataset_id, run["id"], True)

    assert first.status_code == 200
    assert overlapping["response"].status_code == 409
    assert calls == ["apply_cleaning"]


@patch("app.services.chat_service.requests.post")
def test_another_users_run_and_dataset_are_not_found(
    mock_post, client, auth_and_dataset
):
    headers, dataset_id = auth_and_dataset
    run = _propose(client, headers, dataset_id, mock_post, "apply_cleaning", {})

    client.post(
        "/auth/register",
        json={
            "email": "intruder@example.com",
            "password": "StrongPass1!",
            "full_name": "Intruder",
        },
    )
    tokens = client.post(
        "/auth/login",
        json={"email": "intruder@example.com", "password": "StrongPass1!"},
    ).json()
    other = {"Authorization": f"Bearer {tokens['access_token']}"}
    other_dataset = client.post(
        "/datasets/upload",
        headers=other,
        files={"file": ("mine.csv", io.BytesIO(SALES_CSV), "text/csv")},
    ).json()["id"]

    # Someone else's dataset id, and someone else's run id on their own dataset.
    assert _decide(client, other, dataset_id, run["id"], True).status_code == 404
    assert _decide(client, other, other_dataset, run["id"], True).status_code == 404
    assert _dataset_row(dataset_id).cleaned_path is None


@patch("app.services.chat_service.requests.post")
def test_decision_requires_authentication(mock_post, client, auth_and_dataset):
    headers, dataset_id = auth_and_dataset
    run = _propose(client, headers, dataset_id, mock_post, "apply_cleaning", {})

    response = client.post(
        f"/datasets/{dataset_id}/agent/runs/{run['id']}/decision",
        json={"approve": True},
    )

    assert response.status_code == 401


@patch("app.services.chat_service.requests.post")
def test_an_expired_proposal_cannot_be_approved(
    mock_post, client, auth_and_dataset, monkeypatch
):
    headers, dataset_id = auth_and_dataset
    run = _propose(client, headers, dataset_id, mock_post, "apply_cleaning", {})
    monkeypatch.setattr(settings, "AGENT_CONFIRM_TTL_MINUTES", 0)

    response = _decide(client, headers, dataset_id, run["id"], True)

    assert response.status_code == 410
    assert response.json()["error_code"] == "proposal_expired"
    assert _dataset_row(dataset_id).cleaned_path is None
    # The step records why; the proposal can no longer be decided.
    monkeypatch.setattr(settings, "AGENT_CONFIRM_TTL_MINUTES", 30)
    assert _decide(client, headers, dataset_id, run["id"], True).status_code == 409


@pytest.mark.parametrize(
    "extra",
    [
        {"tool_name": "train_model"},
        {"arguments": {"target_column": "revenue"}},
    ],
)
@patch("app.services.chat_service.requests.post")
def test_the_client_cannot_supply_a_tool_or_arguments(
    mock_post, extra, client, auth_and_dataset
):
    headers, dataset_id = auth_and_dataset
    run = _propose(client, headers, dataset_id, mock_post, "apply_cleaning", {})

    response = _decide(client, headers, dataset_id, run["id"], True, **extra)

    assert response.status_code == 422
    assert _dataset_row(dataset_id).cleaned_path is None


@patch("app.services.chat_service.requests.post")
def test_a_failing_approved_action_is_a_recorded_result_not_a_500(
    mock_post, client, auth_and_dataset
):
    headers, dataset_id = auth_and_dataset  # 4 rows: too few to train
    run = _propose(
        client,
        headers,
        dataset_id,
        mock_post,
        "train_model",
        {"target_column": "revenue"},
    )

    response = _decide(client, headers, dataset_id, run["id"], True)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["steps"][0]["status"] == "tool_error"
    assert "could not be completed" in body["answer"]
    assert body["action_result"]["error"]


@patch("app.services.chat_service.requests.post")
def test_a_run_that_is_not_awaiting_a_decision_cannot_be_decided(
    mock_post, client, auth_and_dataset
):
    headers, dataset_id = auth_and_dataset
    mock_post.return_value = _mock_response(200, _plain_answer_response("Done."))
    run = client.post(
        f"/datasets/{dataset_id}/agent/ask",
        headers=headers,
        json={"question": "Hello", "allow_actions": True},
    ).json()
    assert run["status"] == "completed"

    response = _decide(client, headers, dataset_id, run["id"], True)

    assert response.status_code == 409


# ----------------------------------------- restoring a pending proposal on load


def _pending(client, headers, dataset_id):
    return client.get(f"/datasets/{dataset_id}/agent/runs/pending", headers=headers)


def test_no_pending_run_is_null(client, auth_and_dataset):
    headers, dataset_id = auth_and_dataset

    response = _pending(client, headers, dataset_id)

    assert response.status_code == 200
    assert response.json() is None


@patch("app.services.chat_service.requests.post")
def test_a_pending_proposal_is_returned_after_a_fresh_page_load(
    mock_post, client, auth_and_dataset
):
    """The reload case: the proposal was made in one page session; a brand new
    request carrying nothing but the user's token gets it back, complete enough
    to render the same confirmation card and to be decided."""
    headers, dataset_id = auth_and_dataset
    proposed = _propose(
        client,
        headers,
        dataset_id,
        mock_post,
        "train_model",
        {"target_column": "revenue"},
    )

    restored = _pending(client, headers, dataset_id).json()

    assert restored["id"] == proposed["id"]
    assert restored["status"] == "awaiting_confirmation"
    assert restored["question"] == "Fix it"
    assert restored["pending_action"] == {
        "step_id": proposed["steps"][0]["id"],
        "tool_name": "train_model",
        "arguments": {"target_column": "revenue"},
    }
    assert restored["steps"][0]["status"] == "pending_confirmation"

    # And the restored run is actionable, not just displayable.
    decision = _decide(client, headers, dataset_id, restored["id"], False)
    assert decision.status_code == 200
    assert decision.json()["steps"][0]["status"] == "rejected_by_user"


@patch("app.services.chat_service.requests.post")
def test_the_restored_run_includes_the_trace_that_led_to_the_proposal(
    mock_post, client, auth_and_dataset
):
    """The card's redaction hint reads the run's steps, so a restored run has to
    carry them, not only the pending one."""
    headers, dataset_id = auth_and_dataset
    mock_post.return_value = _mock_response(
        200,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "a",
                                "type": "function",
                                "function": {
                                    "name": "get_dataset_overview",
                                    "arguments": "{}",
                                },
                            },
                            {
                                "id": "b",
                                "type": "function",
                                "function": {
                                    "name": "apply_cleaning",
                                    "arguments": "{}",
                                },
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )
    client.post(
        f"/datasets/{dataset_id}/agent/ask",
        headers=headers,
        json={"question": "Fix it", "allow_actions": True},
    )

    restored = _pending(client, headers, dataset_id).json()

    assert [s["tool_name"] for s in restored["steps"]] == [
        "get_dataset_overview",
        "apply_cleaning",
    ]


@pytest.mark.parametrize("approve", [True, False])
@patch("app.services.chat_service.requests.post")
def test_a_decided_proposal_is_no_longer_returned(
    mock_post, approve, client, auth_and_dataset
):
    headers, dataset_id = auth_and_dataset
    run = _propose(client, headers, dataset_id, mock_post, "apply_cleaning", {})
    assert _decide(client, headers, dataset_id, run["id"], approve).status_code == 200

    assert _pending(client, headers, dataset_id).json() is None


@patch("app.services.chat_service.requests.post")
def test_an_expired_proposal_is_not_offered_and_the_lookup_changes_nothing(
    mock_post, client, auth_and_dataset, monkeypatch
):
    headers, dataset_id = auth_and_dataset
    run = _propose(client, headers, dataset_id, mock_post, "apply_cleaning", {})
    monkeypatch.setattr(settings, "AGENT_CONFIRM_TTL_MINUTES", 0)

    assert _pending(client, headers, dataset_id).json() is None

    # A GET must not have resolved the run: the decision path still sees it
    # waiting, and is what reports it expired.
    response = _decide(client, headers, dataset_id, run["id"], True)
    assert response.status_code == 410


@patch("app.services.chat_service.requests.post")
def test_only_the_newest_pending_run_is_returned(mock_post, client, auth_and_dataset):
    headers, dataset_id = auth_and_dataset
    _propose(client, headers, dataset_id, mock_post, "apply_cleaning", {})
    newer = _propose(client, headers, dataset_id, mock_post, "apply_cleaning", {})

    assert _pending(client, headers, dataset_id).json()["id"] == newer["id"]


@patch("app.services.chat_service.requests.post")
def test_a_run_that_never_needed_approval_is_not_returned(
    mock_post, client, auth_and_dataset
):
    headers, dataset_id = auth_and_dataset
    mock_post.return_value = _mock_response(200, _plain_answer_response("Done."))
    client.post(
        f"/datasets/{dataset_id}/agent/ask",
        headers=headers,
        json={"question": "Hello", "allow_actions": True},
    )

    assert _pending(client, headers, dataset_id).json() is None


@patch("app.services.chat_service.requests.post")
def test_pending_lookup_does_not_cross_users_or_datasets(
    mock_post, client, auth_and_dataset
):
    headers, dataset_id = auth_and_dataset
    _propose(client, headers, dataset_id, mock_post, "apply_cleaning", {})

    client.post(
        "/auth/register",
        json={
            "email": "peeker@example.com",
            "password": "StrongPass1!",
            "full_name": "Peeker",
        },
    )
    tokens = client.post(
        "/auth/login",
        json={"email": "peeker@example.com", "password": "StrongPass1!"},
    ).json()
    other = {"Authorization": f"Bearer {tokens['access_token']}"}
    other_dataset = client.post(
        "/datasets/upload",
        headers=other,
        files={"file": ("mine.csv", io.BytesIO(SALES_CSV), "text/csv")},
    ).json()["id"]

    assert _pending(client, other, dataset_id).status_code == 404
    assert _pending(client, other, other_dataset).json() is None


def test_pending_lookup_requires_authentication(client, auth_and_dataset):
    _headers, dataset_id = auth_and_dataset

    response = client.get(f"/datasets/{dataset_id}/agent/runs/pending")

    assert response.status_code == 401

"""Tests for LLMProvider.chat_with_tools -- the tool-calling sibling of chat().

chat() is the Copilot's path and must not change.  chat_with_tools() is the
agent's path: it sends an OpenAI-style tools array and returns the full message
(with tool_calls) plus token usage, so the agent loop can dispatch tools and
enforce its budget.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from app.core.exceptions import ValidationAppError
from app.services.chat_service import LLMProvider, ToolChatResult


@pytest.fixture
def provider():
    return LLMProvider(
        base_url="https://api.groq.com/openai/v1",
        api_key="test-key",
        model="llama-3.3-70b-versatile",
        timeout=30,
    )


SAMPLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_dataset_overview",
            "description": "Get an overview of the dataset.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
]

# -- A plain text reply (no tool call) ------------------------------------

PLAIN_RESPONSE = {
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": "The dataset has 100 rows.",
                "tool_calls": None,
            },
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 50, "completion_tokens": 12, "total_tokens": 62},
}


def _mock_response(
    status_code: int = 200, json_data: dict | None = None, text: str = ""
):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


# ----------------------------------------------------------------- happy path


@patch("app.services.chat_service.requests.post")
def test_plain_text_reply(mock_post, provider):
    mock_post.return_value = _mock_response(200, PLAIN_RESPONSE)

    result = provider.chat_with_tools(
        messages=[{"role": "user", "content": "Describe the data."}],
        tools=SAMPLE_TOOLS,
    )

    assert isinstance(result, ToolChatResult)
    assert result.message["content"] == "The dataset has 100 rows."
    assert result.usage["total_tokens"] == 62
    assert result.finish_reason == "stop"

    # Verify the request included the tools array.
    call_kwargs = mock_post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert body["tools"] == SAMPLE_TOOLS
    assert body["tool_choice"] == "auto"


# ----------------------------------------------------------------- tool calls


TOOL_CALL_RESPONSE = {
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "get_dataset_overview",
                            "arguments": "{}",
                        },
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }
    ],
    "usage": {"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100},
}


@patch("app.services.chat_service.requests.post")
def test_tool_call_is_preserved_in_result(mock_post, provider):
    mock_post.return_value = _mock_response(200, TOOL_CALL_RESPONSE)

    result = provider.chat_with_tools(
        messages=[{"role": "user", "content": "What does this data look like?"}],
        tools=SAMPLE_TOOLS,
    )

    assert result.finish_reason == "tool_calls"
    assert result.message["tool_calls"][0]["id"] == "call_abc123"
    assert result.message["tool_calls"][0]["function"]["name"] == "get_dataset_overview"
    assert result.usage["prompt_tokens"] == 80


# ------------------------------------------------- parameters forwarded


@patch("app.services.chat_service.requests.post")
def test_custom_parameters_are_forwarded(mock_post, provider):
    mock_post.return_value = _mock_response(200, PLAIN_RESPONSE)

    provider.chat_with_tools(
        messages=[{"role": "user", "content": "hi"}],
        tools=SAMPLE_TOOLS,
        tool_choice="none",
        temperature=0.5,
        max_tokens=2048,
    )

    body = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
    assert body["tool_choice"] == "none"
    assert body["temperature"] == 0.5
    assert body["max_tokens"] == 2048


# ----------------------------------------------------------------- errors


@patch("app.services.chat_service.requests.post")
def test_401_raises_bad_key(mock_post, provider):
    mock_post.return_value = _mock_response(401)

    with pytest.raises(ValidationAppError, match="rejected") as exc_info:
        provider.chat_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=SAMPLE_TOOLS,
        )
    assert exc_info.value.error_code == "copilot_bad_key"


@patch("app.services.chat_service.requests.post")
def test_429_raises_rate_limited(mock_post, provider):
    mock_post.return_value = _mock_response(429)

    with pytest.raises(ValidationAppError, match="rate-limiting") as exc_info:
        provider.chat_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=SAMPLE_TOOLS,
        )
    assert exc_info.value.error_code == "copilot_rate_limited"


@patch("app.services.chat_service.requests.post")
def test_500_raises_provider_error(mock_post, provider):
    mock_post.return_value = _mock_response(500, text="internal error")

    with pytest.raises(ValidationAppError) as exc_info:
        provider.chat_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=SAMPLE_TOOLS,
        )
    assert exc_info.value.error_code == "copilot_provider_error"


@patch("app.services.chat_service.requests.post")
def test_malformed_response_raises_bad_response(mock_post, provider):
    mock_post.return_value = _mock_response(200, {"unexpected": "shape"})

    with pytest.raises(ValidationAppError) as exc_info:
        provider.chat_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=SAMPLE_TOOLS,
        )
    assert exc_info.value.error_code == "copilot_bad_response"


# ----------------------------------- missing usage is tolerated


@patch("app.services.chat_service.requests.post")
def test_missing_usage_defaults_to_empty_dict(mock_post, provider):
    no_usage = {
        "choices": [
            {
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
    }
    mock_post.return_value = _mock_response(200, no_usage)

    result = provider.chat_with_tools(
        messages=[{"role": "user", "content": "hi"}],
        tools=SAMPLE_TOOLS,
    )
    assert result.usage == {}


# ------------------------------ chat() is unchanged (pinning test)


@patch("app.services.chat_service.requests.post")
def test_chat_still_returns_a_plain_string(mock_post, provider):
    """chat() must keep returning a bare str, not a ToolChatResult."""
    mock_post.return_value = _mock_response(
        200,
        {"choices": [{"message": {"role": "assistant", "content": "  hello  "}}]},
    )
    result = provider.chat(
        messages=[{"role": "user", "content": "hi"}],
    )
    assert isinstance(result, str)
    assert result == "hello"

    # chat() must NOT send a tools key.
    body = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
    assert "tools" not in body

"""Pacing, 429 retry, and the record/replay cassettes.

Everything here writes cassettes to a temp directory. The committed cassettes are
never touched by a test.
"""

from __future__ import annotations

import json

import pytest
from app.core.exceptions import ValidationAppError
from app.services import tool_agent_service
from app.services.chat_service import ToolChatResult, _circuit
from evals.cases import load_cases
from evals.harness import Harness
from evals.provider import (
    CassetteStore,
    LiveProvider,
    Pacer,
    RecordProvider,
    ReplayProvider,
    estimate_tokens,
    request_key,
)
from evals.scorers import score_run

CASES = {c.id: c for c in load_cases()}


def tool_call(name, args=None):
    return ToolChatResult(
        message={
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "fc_fixed",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args or {})},
                }
            ],
        },
        usage={"prompt_tokens": 1000, "completion_tokens": 50},
        finish_reason="tool_calls",
    )


def answer(text):
    return ToolChatResult(
        message={"role": "assistant", "content": text, "tool_calls": None},
        usage={"prompt_tokens": 1200, "completion_tokens": 60},
        finish_reason="stop",
    )


@pytest.fixture(autouse=True)
def _breaker():
    _circuit.record_success()
    yield
    _circuit.record_success()


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


# ------------------------------------------------------------------ request key


def test_request_key_is_stable_and_sensitive_to_every_part_of_the_request():
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]
    tools = [{"function": {"name": "t"}}]
    base = request_key(messages, tools)
    assert request_key(json.loads(json.dumps(messages)), tools) == base
    assert (
        request_key([*messages[:1], {"role": "user", "content": "q2"}], tools) != base
    )
    assert request_key(messages, [{"function": {"name": "u"}}]) != base
    assert (
        request_key([*messages, {"role": "tool", "content": "result"}], tools) != base
    )


# ------------------------------------------------------------------------ pacing


def test_pacer_does_not_wait_under_budget_and_waits_for_the_window_when_over():
    clock = Clock()
    pacer = Pacer(6000, clock=clock, sleep=clock.sleep)
    pacer.wait_for(5000)  # nothing spent yet: never blocks, even for a big call
    pacer.record(5000)
    pacer.wait_for(500)
    assert clock.slept == []  # 5500 of 6000
    pacer.record(500)
    pacer.wait_for(2000)  # 5500 + 2000 > 6000: wait for the first entry to age out
    assert len(clock.slept) == 1 and 59 < clock.slept[0] < 61
    assert pacer.waited_s == pytest.approx(clock.slept[0])


def test_estimate_grows_with_the_prompt():
    small = estimate_tokens([{"role": "user", "content": "hi"}], [])
    large = estimate_tokens([{"role": "user", "content": "hi" * 5000}], [])
    assert large > small + 2000


# --------------------------------------------------------------------- 429 retry


def test_a_429_is_retried_with_backoff_and_counted_not_failed():
    clock = Clock()
    calls = []

    def real(messages, tools):
        calls.append(1)
        if len(calls) < 3:
            for _ in range(3):
                _circuit.record_failure()  # what the real wrapper does on a 429
            raise ValidationAppError(
                "slow", error_code="copilot_rate_limited", status_code=429
            )
        return answer("ok")

    provider = LiveProvider(real=real, sleep=clock.sleep, clock=clock)
    provider.begin_run("c", 1)
    result, latency = provider.call([{"role": "user", "content": "q"}], [])

    assert result.message["content"] == "ok"
    assert provider.end_run() == 2 and provider.total_retries == 2
    assert clock.slept[:2] == [30, 45]
    assert _circuit.state != "open"


def test_other_provider_errors_are_not_retried():
    def real(messages, tools):
        raise ValidationAppError(
            "bad key", error_code="copilot_bad_key", status_code=502
        )

    provider = LiveProvider(real=real, sleep=lambda s: None)
    provider.begin_run("c", 1)
    with pytest.raises(ValidationAppError):
        provider.call([{"role": "user", "content": "q"}], [])
    assert provider.end_run() == 0


# --------------------------------------------------------------- record / replay


def _record(tmp_path, case_id, responses, monkeypatch=None):
    script = list(responses)
    store = CassetteStore(tmp_path)
    provider = RecordProvider(
        store, "test-model", real=lambda m, t: script.pop(0), sleep=lambda s: None
    )
    with Harness(provider) as h:
        record = h.run_case(CASES[case_id])
    return store, record


def test_a_recorded_run_replays_to_the_same_record_and_score(tmp_path):
    case_id = "ro-rows-cols-sales30"
    store, recorded = _record(
        tmp_path,
        case_id,
        [
            tool_call("get_dataset_overview"),
            answer("The dataset has 30 rows and 6 columns."),
        ],
    )
    assert store.exists(case_id, 1)

    with Harness(ReplayProvider(store)) as h:
        replayed = h.run_case(CASES[case_id])

    assert replayed.error is None
    assert replayed.tools_called == recorded.tools_called
    assert replayed.answer == recorded.answer
    assert (replayed.prompt_tokens, replayed.completion_tokens) == (
        recorded.prompt_tokens,
        recorded.completion_tokens,
    )
    assert (
        score_run(CASES[case_id], replayed).outcome
        == score_run(CASES[case_id], recorded).outcome
    )
    # Latency is the recorded value, not the (near zero) replay time.
    assert [c.latency_s for c in replayed.calls] == [
        c.latency_s for c in recorded.calls
    ]


def test_replay_runs_in_any_order_and_alone(tmp_path):
    ids = ["ro-rows-cols-sales30", "un-weather"]
    store = CassetteStore(tmp_path)
    for case_id, resp in [
        (ids[0], [tool_call("get_dataset_overview"), answer("30 rows and 6 columns")]),
        (ids[1], [answer("I cannot know the weather.")]),
    ]:
        script = list(resp)
        provider = RecordProvider(
            store, "m", real=lambda m, t, s=script: s.pop(0), sleep=lambda s: None
        )
        with Harness(provider) as h:
            h.run_case(CASES[case_id])
    for order in (ids, ids[::-1], ids[1:]):
        with Harness(ReplayProvider(store)) as h:
            for case_id in order:
                assert h.run_case(CASES[case_id]).error is None


def test_strict_replay_reports_a_changed_prompt_as_stale(tmp_path, monkeypatch):
    case_id = "ro-rows-cols-sales30"
    store, _ = _record(
        tmp_path,
        case_id,
        [tool_call("get_dataset_overview"), answer("30 rows, 6 columns")],
    )
    monkeypatch.setattr(
        tool_agent_service, "AGENT_SYSTEM_PROMPT", "A different prompt."
    )

    with Harness(ReplayProvider(store, strict=True)) as h:
        record = h.run_case(CASES[case_id])

    assert (
        record.error["kind"] == "stale"
        and "differs from the recording" in record.error["detail"]
    )
    assert score_run(CASES[case_id], record).outcome == "not_scored"


def test_by_order_replay_ignores_the_changed_prompt(tmp_path, monkeypatch):
    case_id = "ro-rows-cols-sales30"
    store, _ = _record(
        tmp_path,
        case_id,
        [tool_call("get_dataset_overview"), answer("30 rows, 6 columns")],
    )
    monkeypatch.setattr(
        tool_agent_service, "AGENT_SYSTEM_PROMPT", "A different prompt."
    )

    with Harness(ReplayProvider(store, strict=False)) as h:
        record = h.run_case(CASES[case_id])

    assert record.error is None and record.status == "completed"


def test_a_missing_cassette_is_stale_not_a_crash(tmp_path):
    with Harness(ReplayProvider(CassetteStore(tmp_path))) as h:
        record = h.run_case(CASES["un-weather"])
    assert (
        record.error["kind"] == "stale"
        and "no cassette recorded" in record.error["detail"]
    )


def test_replay_notices_recorded_calls_that_were_never_asked_for(tmp_path):
    store, _ = _record(tmp_path, "un-weather", [answer("No idea.")])
    provider = ReplayProvider(store)
    provider.begin_run("un-weather", 1)
    provider.end_run()  # the loop made no call at all
    assert provider.leftover == {"un-weather.r1": 1}


def test_a_provider_error_mid_run_is_not_recorded(tmp_path):
    script = [tool_call("get_dataset_overview")]

    def real(messages, tools):
        if script:
            return script.pop(0)
        raise ValidationAppError(
            "down", error_code="copilot_unreachable", status_code=502
        )

    store = CassetteStore(tmp_path)
    provider = RecordProvider(store, "m", real=real, sleep=lambda s: None)
    with Harness(provider) as h:
        record = h.run_case(CASES["ro-rows-cols-sales30"])

    assert record.error["kind"] == "infra"
    assert not store.exists("ro-rows-cols-sales30", 1)
    assert provider.failed_runs == [("ro-rows-cols-sales30", 1)]


def test_cassettes_store_the_response_not_the_request(tmp_path):
    store, _ = _record(tmp_path, "un-weather", [answer("No idea.")])
    text = store.path("un-weather", 1).read_text(encoding="utf-8")
    data = json.loads(text)
    assert set(data) == {
        "case_id",
        "repeat",
        "recorded_at",
        "model",
        "prompt_hash",
        "tools_hash",
        "calls",
    }
    assert set(data["calls"][0]) == {
        "key",
        "message",
        "usage",
        "finish_reason",
        "latency_s",
    }
    for forbidden in ("Authorization", "Bearer", "api_key", "messages", "system"):
        assert forbidden not in text


def test_replay_names_the_recorded_model_not_the_configured_one(tmp_path):
    store, _ = _record(tmp_path, "un-weather", [answer("No idea.")])
    provider = ReplayProvider(store)
    assert provider.recorded_model is None
    with Harness(provider) as h:
        h.run_case(CASES["un-weather"])
    assert provider.recorded_model == "test-model"

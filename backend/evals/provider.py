"""Providers for the harness: live, recording, and replaying.

The harness replaces `tool_agent_service._call_provider` with something that
satisfies `harness.Provider`. This module supplies three:

- `LiveProvider`: the real Groq call, paced to a tokens-per-minute budget and
  retried on 429 (a 429 is infrastructure, never a model failure).
- `RecordProvider`: live, and writes each run's exchange to a cassette.
- `ReplayProvider`: serves the recorded responses. No key, no network.

A cassette stores the model's message, usage, finish reason and latency, keyed by a
hash of the full request (system prompt, tool schemas, every message including the
tool results fed back). It is recorded at the `_call_provider` boundary, so no HTTP
request or header exists to capture.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.core.exceptions import ValidationAppError
from app.services import tool_agent_service
from app.services.chat_service import ToolChatResult
from app.services.tool_agent_service import AGENT_SYSTEM_PROMPT
from app.services.tool_registry import tools_schema

from .harness import StaleCassette, reset_circuit_breaker

CASSETTES_DIR = Path(__file__).parent / "cassettes"
RETRY_BACKOFF_S = (30, 45, 60, 60, 90)


# ------------------------------------------------------------------ identity


def request_key(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> str:
    """Stable hash of everything the model is asked. If any of it changes (the
    prompt, a tool description or schema, a tool's output) the key changes and a
    strict replay reports the cassette as stale instead of answering a different
    question with an old answer."""
    blob = json.dumps(
        {"messages": messages, "tools": tools},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def prompt_hash() -> str:
    return hashlib.sha256(AGENT_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:16]


def tools_hash() -> str:
    blob = json.dumps(tools_schema(True), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# -------------------------------------------------------------------- pacing


class Pacer:
    """Keeps token use inside a per-minute budget.

    `chat_with_tools` discards the provider's rate-limit headers, so the only
    signal available is the usage each response reports. Before a call, wait until
    the tokens spent in the last `window` seconds plus an estimate for this call fit
    the budget; after it, record what it actually cost.
    """

    def __init__(
        self,
        budget: int,
        window: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.budget = budget
        self.window = window
        self._clock = clock
        self._sleep = sleep
        self._spent: deque[tuple[float, int]] = deque()
        self.waited_s = 0.0

    def _expire(self, now: float) -> None:
        while self._spent and now - self._spent[0][0] >= self.window:
            self._spent.popleft()

    def wait_for(self, estimate: int) -> None:
        while True:
            now = self._clock()
            self._expire(now)
            used = sum(t for _, t in self._spent)
            if not self._spent or used + estimate <= self.budget:
                return
            delay = self.window - (now - self._spent[0][0]) + 0.05
            self.waited_s += delay
            self._sleep(delay)

    def record(self, tokens: int) -> None:
        self._spent.append((self._clock(), tokens))


def estimate_tokens(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> int:
    """A rough prompt size (about 3.2 characters a token) plus a typical reply."""
    chars = len(json.dumps(messages, default=str)) + len(json.dumps(tools, default=str))
    return int(chars / 3.2) + 300


# ---------------------------------------------------------------- cassettes


class CassetteStore:
    def __init__(self, directory: Path = CASSETTES_DIR):
        self.directory = directory

    def path(self, case_id: str, repeat: int) -> Path:
        return self.directory / f"{case_id}.r{repeat}.json"

    def exists(self, case_id: str, repeat: int) -> bool:
        return self.path(case_id, repeat).exists()

    def load(self, case_id: str, repeat: int) -> dict[str, Any] | None:
        path = self.path(case_id, repeat)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save(
        self, case_id: str, repeat: int, model: str, calls: list[dict[str, Any]]
    ) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "case_id": case_id,
            "repeat": repeat,
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": model,
            "prompt_hash": prompt_hash(),
            "tools_hash": tools_hash(),
            "calls": calls,
        }
        self.path(case_id, repeat).write_text(
            json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )


# ------------------------------------------------------------------ providers


class LiveProvider:
    """The real model, paced, with 429 retry. Captures nothing by itself."""

    mode = "live"

    def __init__(
        self,
        tpm: int = 6000,
        real: Callable[..., ToolChatResult] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        pacer: Pacer | None = None,
    ):
        # Captured now, before the harness ever swaps the module attribute.
        self._real = real or tool_agent_service._call_provider
        self._sleep = sleep
        self._clock = clock
        self.pacer = pacer or Pacer(tpm, sleep=sleep)
        self._retries = 0
        self.total_retries = 0
        self.total_tokens = 0

    def begin_run(self, case_id: str, repeat: int) -> None:
        self._retries = 0

    def end_run(self) -> int:
        return self._retries

    def call(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> tuple[ToolChatResult, float]:
        self.pacer.wait_for(estimate_tokens(messages, tools))
        for attempt in range(len(RETRY_BACKOFF_S) + 1):
            started = self._clock()
            try:
                result = self._real(messages, tools)
            except ValidationAppError as exc:
                if exc.status_code != 429 or attempt == len(RETRY_BACKOFF_S):
                    raise
                self._retries += 1
                self.total_retries += 1
                # Our own breaker counted that 429 as a failure; clear it.
                reset_circuit_breaker()
                self._sleep(RETRY_BACKOFF_S[attempt])
                continue
            latency = self._clock() - started
            usage = result.usage or {}
            spent = int(usage.get("prompt_tokens") or 0) + int(
                usage.get("completion_tokens") or 0
            )
            self.pacer.record(spent)
            self.total_tokens += spent
            return result, latency
        raise AssertionError("unreachable")


class RecordProvider(LiveProvider):
    """Live, and writes the run's exchange to a cassette when it finishes cleanly."""

    mode = "record"

    def __init__(self, store: CassetteStore, model: str, **kwargs: Any):
        super().__init__(**kwargs)
        self.store = store
        self.model = model
        self._calls: list[dict[str, Any]] = []
        self._case: tuple[str, int] | None = None
        self.failed_runs: list[tuple[str, int]] = []

    def begin_run(self, case_id: str, repeat: int) -> None:
        super().begin_run(case_id, repeat)
        self._calls = []
        self._case = (case_id, repeat)
        self._broken = False

    def call(self, messages, tools):
        try:
            result, latency = super().call(messages, tools)
        except Exception:
            self._broken = True
            raise
        self._calls.append(
            {
                "key": request_key(messages, tools),
                "message": result.message,
                "usage": result.usage,
                "finish_reason": result.finish_reason,
                "latency_s": round(latency, 3),
            }
        )
        return result, latency

    def end_run(self) -> int:
        retries = super().end_run()
        assert self._case is not None
        # A run that hit a provider error is not recorded: a half exchange would
        # replay as a different, shorter run.
        if self._calls and not self._broken:
            self.store.save(self._case[0], self._case[1], self.model, self._calls)
        else:
            self.failed_runs.append(self._case)
        return retries


class ReplayProvider:
    """Serves recorded responses. Strict by default.

    Strict: the request key must match the recorded call, in order. A mismatch
    means the prompt, a tool schema or a tool's output changed since recording, and
    the run is reported stale rather than answered with an old response.
    By order: replay the nth response regardless. Local use only, for working on
    scoring code; its results say nothing about the current prompt.
    """

    mode = "replay"

    def __init__(self, store: CassetteStore, strict: bool = True):
        self.store = store
        self.strict = strict
        self._cassette: dict[str, Any] | None = None
        self._index = 0
        self._case: tuple[str, int] | None = None
        self.leftover: dict[str, int] = {}
        self._models: set[str] = set()

    @property
    def recorded_model(self) -> str | None:
        """The model the replayed cassettes were recorded against. Replay never
        calls a model, so this, not today's configured default, is what a report
        and a baseline lookup should name."""
        if not self._models:
            return None
        return (
            next(iter(self._models))
            if len(self._models) == 1
            else "mixed:" + ",".join(sorted(self._models))
        )

    def begin_run(self, case_id: str, repeat: int) -> None:
        self._case = (case_id, repeat)
        self._index = 0
        self._cassette = self.store.load(case_id, repeat)
        if self._cassette is not None:
            self._models.add(self._cassette["model"])

    def end_run(self) -> int:
        if self._cassette is not None:
            remaining = len(self._cassette["calls"]) - self._index
            if remaining > 0:
                assert self._case is not None
                self.leftover[f"{self._case[0]}.r{self._case[1]}"] = remaining
        return 0

    def call(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> tuple[ToolChatResult, float]:
        if self._cassette is None:
            assert self._case is not None
            raise StaleCassette(
                f"no cassette recorded for {self._case[0]} repeat {self._case[1]}"
            )
        calls = self._cassette["calls"]
        if self._index >= len(calls):
            raise StaleCassette(
                f"the agent made call {self._index + 1} but only {len(calls)} were recorded"
            )
        recorded = calls[self._index]
        if self.strict:
            key = request_key(messages, tools)
            if key != recorded["key"]:
                raise StaleCassette(
                    f"request {self._index + 1} differs from the recording "
                    f"(recorded under prompt {self._cassette['prompt_hash']}, tools "
                    f"{self._cassette['tools_hash']}; now prompt {prompt_hash()}, tools "
                    f"{tools_hash()}). Re-record with a live run."
                )
        self._index += 1
        result = ToolChatResult(
            message=recorded["message"],
            usage=recorded["usage"],
            finish_reason=recorded["finish_reason"],
        )
        return result, float(recorded["latency_s"])

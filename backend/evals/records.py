"""Plain, JSON-serialisable records the harness produces and the scorers read."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class StepRecord:
    n: int
    tool: str
    args: Any
    status: str
    redacted: bool
    duration_s: float | None
    prompt_tokens: int | None
    completion_tokens: int | None


@dataclass
class CallRecord:
    """One provider call as the model saw it."""

    tools_offered: list[str]
    # Content of every tool-result message sent in this call, exactly as sent.
    tool_texts: list[str]
    latency_s: float
    prompt_tokens: int
    completion_tokens: int
    # The tool calls the model asked for in this response, as it asked for them
    # ({"name", "arguments"}). The loop may drop some (it stops at the first action
    # tool in a turn), so these can be more than the recorded steps.
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RunRecord:
    case_id: str
    repeat: int
    status: str  # completed | awaiting_confirmation | step_limit | error | not_run
    steps: list[StepRecord] = field(default_factory=list)
    pending_action: dict[str, Any] | None = None
    answer: str = ""
    calls: list[CallRecord] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    run_duration_s: float | None = None
    # Infrastructure problems (provider 429, timeout, stale cassette) are not
    # model behaviour and are never scored. `kind` is infra | stale | harness.
    error: dict[str, str] | None = None
    retries: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def tools_called(self) -> list[str]:
        return [s.tool for s in self.steps]

    @property
    def requested_tools(self) -> list[str]:
        """Every tool the model asked for, across all provider calls, including any
        the loop did not execute."""
        return [c["name"] for call in self.calls for c in call.tool_calls]

    @property
    def provider_latency_s(self) -> float:
        return round(sum(c.latency_s for c in self.calls), 3)

    @property
    def tool_texts(self) -> list[str]:
        """Everything the model was shown from tools, taken from the last call
        (which carries the whole conversation so far)."""
        return self.calls[-1].tool_texts if self.calls else []


@dataclass
class Check:
    """One scored property of a run.

    `kind` decides what a failure means:
    - gated: counts against the case (unless the case is informational)
    - hard: an invariant about our own code; any violation fails the suite
    - heuristic: reported for a person to look at, never counted
    `passed` is None when the check does not apply to this run.
    """

    name: str
    kind: str
    passed: bool | None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunScore:
    case_id: str
    repeat: int
    category: str
    gating: str  # gated | informational
    outcome: str  # pass | fail | not_scored
    checks: list[Check]

    @property
    def counted(self) -> bool:
        return self.gating == "gated" and self.outcome in ("pass", "fail")

    @property
    def invariant_violations(self) -> list[Check]:
        return [c for c in self.checks if c.kind == "hard" and c.passed is False]

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["checks"] = [c.to_dict() for c in self.checks]
        return out


def run_record_from_dict(data: dict[str, Any]) -> RunRecord:
    """Inverse of `RunRecord.to_dict`, so a stored result can be scored again."""
    return RunRecord(
        **{
            **data,
            "steps": [StepRecord(**s) for s in data["steps"]],
            "calls": [CallRecord(**c) for c in data["calls"]],
        }
    )

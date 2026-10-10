"""Runs eval cases through the real agent service, in process.

Everything except the model is the production code path: the dataset is uploaded
through `DatasetService`, the loop is `ToolAgentService.ask`, tools execute for
real, the sanitiser and the confirmation logic are the real ones. Only
`_call_provider` is replaced, by a `Provider` that is live, recorded or replayed.

Isolation matters because this harness lifts the agent's per-user hourly limit
(see `eval_limits`). It therefore refuses to run against anything but a local
SQLite database, and never in production. The CLI additionally points the process
at its own temp database before any application module is imported.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator, Protocol

from app import models
from app.core.config import settings
from app.core.exceptions import AppException, RateLimitedError
from app.database import SessionLocal, engine
from app.services import tool_agent_service
from app.services.auth_service import AuthService
from app.services.chat_service import _circuit, ToolChatResult
from app.services.dataset_service import DatasetService
from app.services.tool_agent_service import ToolAgentService

from .cases import Case
from .records import CallRecord, RunRecord, StepRecord

EVAL_USER_EMAIL = "eval-harness@example.invalid"


class StaleCassette(Exception):
    """A strict replay found no recorded response for the request it was asked."""


class Provider(Protocol):
    """What the harness needs from a model: a response and how long it took."""

    def call(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> tuple[ToolChatResult, float]: ...

    def begin_run(self, case_id: str, repeat: int) -> None: ...

    def end_run(self) -> int:
        """Called when a run finishes; returns how many retries it needed."""
        ...


# --------------------------------------------------------------- isolation


def assert_isolated(expected_db_path: str | None = None) -> None:
    """Refuse to run against anything that could be real data."""
    url = str(engine.url)
    if settings.is_production:
        raise RuntimeError("the eval harness will not run with ENVIRONMENT=production")
    if engine.url.get_backend_name() != "sqlite":
        raise RuntimeError(f"the eval harness only runs against SQLite, not {url!r}")
    if expected_db_path is not None and engine.url.database != expected_db_path:
        raise RuntimeError(
            f"the eval harness expected its own database {expected_db_path!r}, "
            f"but the process is connected to {engine.url.database!r}"
        )


@contextmanager
def eval_limits(api_key: str | None = None) -> Iterator[None]:
    """Lift the agent's hourly run limit, in this process, for this block only.

    The limit is a plain attribute on this process's settings object. The API
    server is a different process that never imports `evals`, so nothing a request
    can do reaches this. It is restored on exit, including on an exception.
    `api_key`, when given, stands in for GROQ_API_KEY so the service's
    "is the agent configured" guard passes in replay mode.
    """
    old_limit = settings.MAX_AGENT_RUNS_PER_HOUR
    old_key = settings.GROQ_API_KEY
    settings.MAX_AGENT_RUNS_PER_HOUR = 10**9
    if api_key is not None:
        settings.GROQ_API_KEY = api_key
    try:
        yield
    finally:
        settings.MAX_AGENT_RUNS_PER_HOUR = old_limit
        settings.GROQ_API_KEY = old_key


def reset_circuit_breaker() -> None:
    """The breaker is process-global. One flaky minute must not fail every later
    case, so each run starts with it closed."""
    _circuit.record_success()


# -------------------------------------------------------------------- tap


class _Tap:
    """Replaces `_call_provider` for one run: forwards to the provider and keeps
    what the model was shown, for the scorers."""

    def __init__(self, provider: Provider):
        self.provider = provider
        self.calls: list[CallRecord] = []

    def __call__(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ToolChatResult:
        result, latency = self.provider.call(messages, tools)
        usage = result.usage or {}
        requested = [
            {
                "name": (tc.get("function") or {}).get("name") or "",
                "arguments": (tc.get("function") or {}).get("arguments"),
            }
            for tc in (result.message.get("tool_calls") or [])
        ]
        self.calls.append(
            CallRecord(
                tools_offered=[t["function"]["name"] for t in tools],
                tool_texts=[
                    str(m.get("content") or "")
                    for m in messages
                    if m.get("role") == "tool"
                ],
                latency_s=round(latency, 3),
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                tool_calls=requested,
            )
        )
        return result


# ---------------------------------------------------------------- harness


class Harness:
    def __init__(self, provider: Provider, expected_db_path: str | None = None):
        self.provider = provider
        self.expected_db_path = expected_db_path
        self._limits = None
        self.db = None
        self.user_id: int | None = None

    def __enter__(self) -> "Harness":
        assert_isolated(self.expected_db_path)
        self._limits = eval_limits(api_key=settings.GROQ_API_KEY or "eval-harness")
        self._limits.__enter__()
        self.db = SessionLocal()
        # Reuse the harness's own user if a previous Harness in this database made
        # one (the CLI opens one per process; tests open several).
        user = (
            self.db.query(models.User)
            .filter(models.User.email == EVAL_USER_EMAIL)
            .first()
        )
        if user is None:
            user = AuthService(self.db).register(
                EVAL_USER_EMAIL, "Eval-Harness-1!", "Eval"
            )
        self.user_id = user.id
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            if self.db is not None:
                self.db.close()
        finally:
            self._limits.__exit__(*exc)

    # ---------------------------------------------------------------- run
    def run_case(self, case: Case, repeat: int = 1) -> RunRecord:
        assert self.db is not None and self.user_id is not None
        reset_circuit_breaker()
        dataset = DatasetService(self.db).upload(
            owner_id=self.user_id,
            filename=f"{case.id}.csv",
            contents=case.dataset_bytes(),
            content_type="text/csv",
        )
        tap = _Tap(self.provider)
        self.provider.begin_run(case.id, repeat)
        original = tool_agent_service._call_provider
        tool_agent_service._call_provider = tap
        started = time.monotonic()
        error: dict[str, str] | None = None
        run: models.AgentRun | None = None
        try:
            run = ToolAgentService(self.db).ask(
                dataset, self.user_id, case.question, allow_actions=case.allow_actions
            )
        except StaleCassette as exc:
            error = {"kind": "stale", "detail": str(exc)}
        except RateLimitedError as exc:
            # Our own hourly limit: the override failed. Never retry or hide it.
            error = {
                "kind": "harness",
                "detail": f"agent limit not lifted: {exc.detail}",
            }
        except AppException as exc:
            kind = "infra" if exc.status_code in (429, 502, 503, 504) else "harness"
            error = {"kind": kind, "detail": f"{exc.error_code}: {exc.detail}"}
        finally:
            tool_agent_service._call_provider = original
            retries = self.provider.end_run()
        elapsed = time.monotonic() - started

        if run is None:
            run = (
                self.db.query(models.AgentRun)
                .filter(models.AgentRun.dataset_id == dataset.id)
                .order_by(models.AgentRun.id.desc())
                .first()
            )
        return self._record(case, repeat, run, tap, error, retries, elapsed)

    def _record(
        self,
        case: Case,
        repeat: int,
        run: models.AgentRun | None,
        tap: _Tap,
        error: dict[str, str] | None,
        retries: int,
        elapsed: float,
    ) -> RunRecord:
        record = RunRecord(
            case_id=case.id,
            repeat=repeat,
            status=run.status if run else "not_run",
            calls=tap.calls,
            error=error,
            retries=retries,
            run_duration_s=round(elapsed, 3),
        )
        if run is None:
            return record
        self.db.refresh(run)
        record.answer = run.answer or ""
        record.pending_action = run.pending_action
        record.prompt_tokens = int(run.total_prompt_tokens or 0)
        record.completion_tokens = int(run.total_completion_tokens or 0)
        record.steps = [
            StepRecord(
                n=s.step_number,
                tool=s.tool_name,
                args=s.arguments,
                status=s.status,
                redacted=bool(s.redacted),
                duration_s=s.duration_seconds,
                prompt_tokens=s.prompt_tokens,
                completion_tokens=s.completion_tokens,
            )
            for s in run.steps
        ]
        return record

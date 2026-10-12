"""CV evaluation: the natural-language agent's accuracy, speed and cost on a
fixed 30-question set against `demo/sample_sales.csv`.

Run with:

    python -m backend.eval.eval_agent          # from the repo root
    python -m eval.eval_agent                  # from backend/

This is **separate from `backend/evals/`**, the Phase 3 cassette harness that
replays recorded model responses to gate CI. This script makes live calls
through the real agent service layer (`ToolAgentService.ask`, not HTTP) to
produce the numbers below. It is not run in CI: it spends the real GROQ_API_KEY
and its results depend on the live model, which the cassette harness exists
specifically to avoid.

Every question has a verifiable correct value, computed directly from the CSV
or from the same service functions the agent's tools call (`recommend_targets`,
`auto_dashboard`), so this is an oracle, not a guess. The 30 questions are
chosen to exercise profiling, correlations, target recommendation, the
auto-dashboard, and run_query, plus dataset overview, quality and column
listing.

Correctness is checked by looking for the expected number (with a small
tolerance for rounding) or keyword in the agent's free-text answer. This is a
simple textual check, not a semantic grader: a correct answer phrased in an
unexpected way can be marked wrong, and a passing mention of the right number
is not proof the reasoning around it was sound. Treat this as directional.

A note on pricing: the rate below ($0.59 / $0.79 per million tokens) is the
one this script was asked to report against, for "llama-3.3-70b" on Groq. The
server's actual configured model (`settings.GROQ_MODEL`) may be a different
one - Groq retired llama-3.3-70b-versatile and this project moved to
`openai/gpt-oss-20b` - so the cost figure here is a rate card number, not
necessarily this run's real bill. Both the requested rate and the model this
run actually used are printed and saved, so the two are never conflated.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
DEMO_CSV = REPO_ROOT / "demo" / "sample_sales.csv"
RESULTS_PATH = Path(__file__).resolve().parent / "eval_results.json"

# The rate this report was asked to use, in USD per token (quoted per million).
PRICING_LABEL = "llama-3.3-70b (Groq quoted rate)"
PRICE_INPUT_PER_TOKEN = 0.59 / 1_000_000
PRICE_OUTPUT_PER_TOKEN = 0.79 / 1_000_000


# ---------------------------------------------------------------------------
# Answer checking
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"-?\$?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?|-?\d+(?:\.\d+)?%?")


def extract_numbers(text: str) -> list[float]:
    """Numbers in free text, with `$`, thousands commas and `%` stripped."""
    out: list[float] = []
    for match in _NUM_RE.finditer(text):
        token = match.group().rstrip("%").lstrip("$").replace(",", "")
        try:
            out.append(float(token))
        except ValueError:
            continue
    return out


def check_number(
    expected: float, rel_tol: float = 0.02, abs_tol: float = 0.6
) -> Callable[[str], bool]:
    """A number within tolerance of `expected` appears anywhere in the answer."""

    def _check(answer: str) -> bool:
        tolerance = max(abs_tol, abs(expected) * rel_tol)
        return any(abs(v - expected) <= tolerance for v in extract_numbers(answer))

    return _check


def check_keyword_any(*keywords: str) -> Callable[[str], bool]:
    def _check(answer: str) -> bool:
        low = answer.lower()
        return any(k.lower() in low for k in keywords)

    return _check


def check_keyword_all(*keywords: str) -> Callable[[str], bool]:
    def _check(answer: str) -> bool:
        low = answer.lower()
        return all(k.lower() in low for k in keywords)

    return _check


def check_no_missing_values() -> Callable[[str], bool]:
    def _check(answer: str) -> bool:
        if check_number(0, abs_tol=0.4)(answer):
            return True
        low = answer.lower()
        return any(
            phrase in low
            for phrase in ("no missing", "none missing", "zero missing", "0%")
        )

    return _check


def check_any_of(*checks: Callable[[str], bool]) -> Callable[[str], bool]:
    def _check(answer: str) -> bool:
        return any(c(answer) for c in checks)

    return _check


# ---------------------------------------------------------------------------
# The fixed question set
#
# "expected" is a human-readable note for the saved results, not what is
# checked - "check" is. Every value below was computed from
# demo/sample_sales.csv directly (overview/profiling/run_query questions) or
# by calling the same service function the corresponding tool wraps
# (recommend_targets, auto_dashboard), on 2026-10-13. If the demo file ever
# changes, these stop being correct and must be recomputed the same way.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Question:
    id: str
    category: str
    text: str
    expected: str
    check: Callable[[str], bool] = field(repr=False)


QUESTIONS: tuple[Question, ...] = (
    Question(
        "q01",
        "overview",
        "How many rows are in the dataset?",
        "50",
        check_number(50, abs_tol=0.4),
    ),
    Question(
        "q02",
        "overview",
        "How many columns does the dataset have?",
        "10",
        check_number(10, abs_tol=0.4),
    ),
    Question(
        "q03",
        "quality",
        "Which column has the most missing values, and how many are missing?",
        "none; 0 missing values in any column",
        check_no_missing_values(),
    ),
    Question(
        "q04",
        "profiling",
        "What is the average revenue per row?",
        "10671.47",
        check_number(10671.4674),
    ),
    Question(
        "q05",
        "run_query",
        "What is the total revenue across all rows?",
        "533573.37",
        check_number(533573.37),
    ),
    Question(
        "q06",
        "profiling",
        "What is the maximum revenue in any single row?",
        "19975.0",
        check_number(19975.0),
    ),
    Question(
        "q07",
        "profiling",
        "What is the minimum revenue in any single row?",
        "4198.6",
        check_number(4198.6),
    ),
    Question(
        "q08",
        "profiling",
        "What is the median revenue?",
        "11439.52",
        check_number(11439.52),
    ),
    Question(
        "q09",
        "profiling",
        "Which product category appears most often?",
        "Electronics (21 of 50 rows)",
        check_keyword_any("electronics"),
    ),
    Question(
        "q10",
        "profiling",
        "Which customer segment appears most often?",
        "Enterprise (24 of 50 rows)",
        check_keyword_any("enterprise"),
    ),
    Question(
        "q11",
        "profiling",
        "Which sales channel is used most often?",
        "Online (27 of 50 rows)",
        check_keyword_any("online"),
    ),
    Question(
        "q12",
        "profiling",
        "What is the average number of units sold per row?",
        "56.86",
        check_number(56.86),
    ),
    Question(
        "q13",
        "run_query",
        "What is the total number of units sold across all rows?",
        "2843",
        check_number(2843, abs_tol=0.6),
    ),
    Question(
        "q14",
        "profiling",
        "What is the average profit per row?",
        "4395.52",
        check_number(4395.52),
    ),
    Question(
        "q15",
        "run_query",
        "What is the total profit across all rows?",
        "219775.88",
        check_number(219775.88),
    ),
    Question(
        "q16",
        "correlations",
        "Which two numeric columns have the strongest correlation with each other?",
        "cost and revenue (r ≈ 0.95)",
        check_keyword_all("cost", "revenue"),
    ),
    Question(
        "q17",
        "correlations",
        "Is revenue more strongly correlated with cost or with unit_price?",
        "cost (r ≈ 0.95 vs r ≈ 0.70)",
        check_keyword_any("cost"),
    ),
    Question(
        "q18",
        "targets",
        "Which column would make the best target to predict with a model?",
        "revenue or profit (tied top candidates)",
        check_keyword_any("revenue", "profit"),
    ),
    Question(
        "q19",
        "targets",
        "Why would revenue be a reasonable column to predict?",
        "it is numeric and its name is a strong outcome term",
        check_keyword_any("numeric", "outcome", "regress", "varies", "vary"),
    ),
    Question(
        "q20",
        "dashboard",
        "Using the dashboard overview, what is the total revenue KPI?",
        "533573.37",
        check_number(533573.37),
    ),
    Question(
        "q21",
        "dashboard",
        "Using the dashboard overview, what is the average revenue KPI?",
        "10671.47",
        check_number(10671.4674),
    ),
    Question(
        "q22",
        "dashboard",
        "Using the dashboard overview, what is the max revenue KPI?",
        "19975.0",
        check_number(19975.0),
    ),
    Question(
        "q23",
        "dashboard",
        "In the dashboard's category breakdown, how many rows fall into the North region?",
        "13",
        check_number(13, abs_tol=0.4),
    ),
    Question(
        "q24",
        "run_query",
        "What was the total revenue in March 2024?",
        "62903.87",
        check_number(62903.87, rel_tol=0.03),
    ),
    Question(
        "q25",
        "run_query",
        "What was the total revenue in October 2024?",
        "46778.31",
        check_number(46778.31, rel_tol=0.03),
    ),
    Question(
        "q26",
        "run_query",
        "What is the total revenue for the Electronics product category?",
        "248211.33",
        check_number(248211.33, rel_tol=0.03),
    ),
    Question(
        "q27",
        "run_query",
        "What is the total revenue for the Services product category?",
        "181470.00",
        check_number(181470.00, rel_tol=0.03),
    ),
    Question(
        "q28",
        "run_query",
        "What is the average profit for the West region?",
        "4696.93",
        check_number(4696.925, rel_tol=0.03),
    ),
    Question(
        "q29",
        "quality",
        "What is this dataset's overall data quality score out of 100?",
        "100",
        check_number(100, abs_tol=1.0),
    ),
    Question(
        "q30",
        "overview",
        "List the exact column names in this dataset.",
        "date, region, product_category, units_sold, unit_price, revenue, cost, profit, customer_segment, channel",
        check_keyword_all("revenue", "region", "profit", "channel"),
    ),
)

assert len(QUESTIONS) == 30, f"expected 30 questions, found {len(QUESTIONS)}"


# ---------------------------------------------------------------------------
# Isolation: this must run before any `app.*` module is imported, the same
# requirement `backend/evals/env.py` documents for the Phase 3 harness. This
# script does not import that module - the two harnesses are kept independent
# - so the same few lines are repeated here rather than shared.
# ---------------------------------------------------------------------------


def _isolate_environment() -> Path:
    """Point this process at a throwaway SQLite database and upload directory,
    and make `app.*` importable regardless of the current working directory."""
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    tmp = Path(tempfile.mkdtemp(prefix="agent-cv-eval-"))
    db_path = tmp / "eval.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["UPLOAD_DIR"] = str(tmp / "uploads")
    os.environ["JWT_SECRET"] = secrets.token_hex(32)
    os.environ["ENVIRONMENT"] = "development"
    os.environ["DEBUG"] = "false"
    # A real SMTP config in the environment would try to send a verification
    # email for the throwaway user this script registers.
    os.environ["SMTP_HOST"] = ""
    return db_path


def _assert_isolated(engine: Any, settings: Any, expected_db_path: Path) -> None:
    """Refuse to run against anything that could be real data. This script
    lifts the agent's hourly rate limit for this process, so it must never be
    pointed at a database anything else writes to."""
    if settings.is_production:
        raise RuntimeError("this script will not run with ENVIRONMENT=production")
    if engine.url.get_backend_name() != "sqlite":
        raise RuntimeError(f"this script only runs against SQLite, not {engine.url!r}")
    if engine.url.database != str(expected_db_path):
        raise RuntimeError(
            f"expected the isolated database {expected_db_path!r}, "
            f"but the process is connected to {engine.url.database!r}"
        )


class _TokenPacer:
    """Keeps token use inside a per-minute budget, so a question that needs
    several model calls, run back to back with the next question, does not
    exceed Groq's tokens-per-minute limit. The same idea `backend/evals/`
    uses for its live provider, kept as its own small copy here rather than
    importing it."""

    def __init__(self, budget: int, window: float = 60.0):
        self.budget = budget
        self.window = window
        self._spent: list[tuple[float, int]] = []

    def wait_for(self, estimate: int) -> None:
        while True:
            now = time.monotonic()
            self._spent = [(t, n) for t, n in self._spent if now - t < self.window]
            used = sum(n for _, n in self._spent)
            if not self._spent or used + estimate <= self.budget:
                return
            time.sleep(self.window - (now - self._spent[0][0]) + 0.05)

    def record(self, tokens: int) -> None:
        self._spent.append((time.monotonic(), tokens))


def _estimate_tokens(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]]
) -> int:
    chars = len(json.dumps(messages, default=str)) + len(json.dumps(tools, default=str))
    return int(chars / 3.2) + 300


# A 429 is Groq rate-limiting this process, not the model failing - worth a
# wait and a retry, not giving up on the question.
_RETRY_BACKOFF_S = (20, 35, 50, 50)


class _PacedProvider:
    """Wraps `tool_agent_service._call_provider` with pacing and 429 retry for
    the duration of the run, then restores the original on exit."""

    def __init__(
        self,
        tool_agent_service: Any,
        circuit: Any,
        validation_app_error: type,
        tpm: int = 6000,
    ):
        self._tas = tool_agent_service
        self._circuit = circuit
        self._ValidationAppError = validation_app_error
        self._real = tool_agent_service._call_provider
        self._pacer = _TokenPacer(tpm)

    def _call(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        self._pacer.wait_for(_estimate_tokens(messages, tools))
        for attempt in range(len(_RETRY_BACKOFF_S) + 1):
            try:
                result = self._real(messages, tools)
            except self._ValidationAppError as exc:
                if getattr(exc, "status_code", None) != 429 or attempt == len(
                    _RETRY_BACKOFF_S
                ):
                    raise
                # That 429 counted as a failure against the circuit breaker;
                # this is a known, handled rate limit, not a provider outage.
                self._circuit.record_success()
                time.sleep(_RETRY_BACKOFF_S[attempt])
                continue
            usage = result.usage or {}
            spent = int(usage.get("prompt_tokens") or 0) + int(
                usage.get("completion_tokens") or 0
            )
            self._pacer.record(spent)
            return result
        raise AssertionError("unreachable")

    def __enter__(self) -> "_PacedProvider":
        self._tas._call_provider = self._call
        return self

    def __exit__(self, *exc: Any) -> None:
        self._tas._call_provider = self._real


class _RateLimitLifted:
    """Lifts `MAX_AGENT_RUNS_PER_HOUR` in this process only, for the duration
    of the run, restoring it on exit. 30 live questions in a short span would
    otherwise trip the same per-user limit a real user is rate-limited by."""

    def __init__(self, settings: Any):
        self._settings = settings
        self._old_limit: int | None = None

    def __enter__(self) -> "_RateLimitLifted":
        self._old_limit = self._settings.MAX_AGENT_RUNS_PER_HOUR
        self._settings.MAX_AGENT_RUNS_PER_HOUR = 10**9
        return self

    def __exit__(self, *exc: Any) -> None:
        self._settings.MAX_AGENT_RUNS_PER_HOUR = self._old_limit


# ---------------------------------------------------------------------------
# Running the questions
# ---------------------------------------------------------------------------


def _run_one(
    tool_agent_service: Any, db: Any, dataset: Any, user_id: int, question: Question
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        run = tool_agent_service.ToolAgentService(db).ask(
            dataset, user_id, question.text, allow_actions=False
        )
    except Exception as exc:  # noqa: BLE001 - one bad question must not stop the batch
        elapsed = time.monotonic() - started
        return {
            "id": question.id,
            "category": question.category,
            "question": question.text,
            "expected": question.expected,
            "answer": None,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "passed": False,
            "duration_seconds": round(elapsed, 3),
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    answer = run.answer or ""
    passed = bool(run.status in ("completed", "truncated") and question.check(answer))
    prompt_tokens = int(run.total_prompt_tokens or 0)
    completion_tokens = int(run.total_completion_tokens or 0)
    return {
        "id": question.id,
        "category": question.category,
        "question": question.text,
        "expected": question.expected,
        "answer": answer,
        "status": run.status,
        "error": None,
        "passed": passed,
        "duration_seconds": round(
            run.duration_seconds or (time.monotonic() - started), 3
        ),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _cost_usd_cents(prompt_tokens: int, completion_tokens: int) -> float:
    dollars = (
        prompt_tokens * PRICE_INPUT_PER_TOKEN
        + completion_tokens * PRICE_OUTPUT_PER_TOKEN
    )
    return dollars * 100


def _write_partial(results: list[dict[str, Any]]) -> None:
    """Best-effort checkpoint after each question. `main` overwrites this
    with the complete summary once every question has a result."""
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "complete": len(results) == len(QUESTIONS),
        "questions_total": len(QUESTIONS),
        "questions_run_so_far": len(results),
        "results": results,
    }
    RESULTS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def main() -> int:
    db_path = _isolate_environment()

    # Deferred: `app.*` must not be imported before the environment above is
    # set, since `app.core.config` reads it once at import time.
    from app import models  # noqa: F401  (registers the tables)
    from app.core.config import settings
    from app.core.exceptions import ValidationAppError
    from app.database import Base, SessionLocal, engine
    from app.services import tool_agent_service
    from app.services.auth_service import AuthService
    from app.services.chat_service import _circuit
    from app.services.dataset_service import DatasetService

    _assert_isolated(engine, settings, db_path)
    if not settings.GROQ_API_KEY:
        print(
            "GROQ_API_KEY is not set. This script makes live calls and cannot run "
            "without it.",
            file=sys.stderr,
        )
        return 1

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = AuthService(db).register(
            "agent-cv-eval@example.invalid", "Agent-Cv-Eval-1!", "Agent CV Eval"
        )
        dataset = DatasetService(db).upload(
            owner_id=user.id,
            filename="sample_sales.csv",
            contents=DEMO_CSV.read_bytes(),
            content_type="text/csv",
        )

        # Resume: a question whose last attempt reached a real outcome (not an
        # infrastructure error, such as the daily token quota running out
        # mid-batch) is kept as-is rather than asked again, so a second run
        # on the same day does not spend quota re-asking what already has a
        # good answer.
        kept: dict[str, dict[str, Any]] = {}
        if RESULTS_PATH.exists():
            try:
                previous = json.loads(RESULTS_PATH.read_text())
                kept = {
                    r["id"]: r
                    for r in previous.get("results", [])
                    if r.get("status") != "error"
                }
            except (json.JSONDecodeError, OSError):
                pass

        results: list[dict[str, Any]] = []
        with (
            _RateLimitLifted(settings),
            _PacedProvider(tool_agent_service, _circuit, ValidationAppError),
        ):
            for question in QUESTIONS:
                if question.id in kept:
                    result = kept[question.id]
                    print(
                        f"[KEPT] {result['id']} ({result['category']}) - from a previous run"
                    )
                else:
                    result = _run_one(
                        tool_agent_service, db, dataset, user.id, question
                    )
                    result["cost_usd_cents"] = round(
                        _cost_usd_cents(
                            result["prompt_tokens"], result["completion_tokens"]
                        ),
                        6,
                    )
                    mark = "PASS" if result["passed"] else "FAIL"
                    print(
                        f"[{mark}] {result['id']} ({result['category']}) "
                        f"{result['duration_seconds']}s {result['total_tokens']}tok"
                    )
                results.append(result)
                # Written after every question, not just at the end: a quota
                # wall partway through a batch must not lose what already ran.
                _write_partial(results)
    finally:
        db.close()

    correct = sum(1 for r in results if r["passed"])
    total = len(results)
    avg_latency = sum(r["duration_seconds"] for r in results) / total
    avg_tokens = sum(r["total_tokens"] for r in results) / total
    avg_cost_cents = sum(r["cost_usd_cents"] for r in results) / total
    total_cost_cents = sum(r["cost_usd_cents"] for r in results)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "complete": True,
        "dataset": "demo/sample_sales.csv",
        "model_configured": settings.GROQ_MODEL,
        "pricing_label": PRICING_LABEL,
        "pricing_rates_usd_per_million_tokens": {"input": 0.59, "output": 0.79},
        "pricing_note": (
            "This rate was requested for the report and may not match "
            "model_configured, the model this run actually used."
        ),
        "questions_total": total,
        "questions_correct": correct,
        "accuracy_pct": round(correct / total * 100, 1),
        "avg_latency_seconds": round(avg_latency, 3),
        "avg_tokens_per_query": round(avg_tokens, 1),
        "avg_cost_usd_cents_per_query": round(avg_cost_cents, 6),
        "total_cost_usd_cents": round(total_cost_cents, 4),
        "results": results,
    }

    RESULTS_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    print()
    print(f"Model actually used this run: {settings.GROQ_MODEL}")
    print(f"Pricing rate used for the cost estimate: {PRICING_LABEL}")
    if settings.GROQ_MODEL != "llama-3.3-70b-versatile":
        print(
            "NOTE: the configured model is not llama-3.3-70b-versatile (Groq retired "
            "it), so the cost figure below is a requested rate-card estimate, not this "
            "run's real Groq bill."
        )
    print(f"Correct: {correct}/{total} ({summary['accuracy_pct']}%)")
    print(f"Average latency: {summary['avg_latency_seconds']}s")
    print(f"Average tokens per query: {summary['avg_tokens_per_query']}")
    print(
        f"Average estimated cost per query: {summary['avg_cost_usd_cents_per_query']}¢"
    )
    print(f"Total estimated cost ({total} queries): {summary['total_cost_usd_cents']}¢")
    print(f"Results written to {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

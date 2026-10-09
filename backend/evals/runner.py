"""Runs a selection of cases for N repeats and assembles a result."""

from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings

from .cases import Case
from .harness import Harness, Provider
from .records import run_record_from_dict
from .provider import prompt_hash, tools_hash
from .report import summarize
from .scorers import score_run


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def run_suite(
    cases: list[Case],
    provider: Provider,
    repeats: int = 1,
    mode: str = "replay",
    tags: list[str] | None = None,
    expected_db_path: str | None = None,
    skip: Callable[[Case, int], bool] | None = None,
    on_run: Callable[[dict[str, Any]], None] | None = None,
    max_tokens: int | None = None,
    extra_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    spent = 0
    stopped_early = False
    with Harness(provider, expected_db_path=expected_db_path) as harness:
        for repeat in range(1, repeats + 1):
            for case in cases:
                if skip and skip(case, repeat):
                    continue
                if max_tokens is not None and spent >= max_tokens:
                    stopped_early = True
                    break
                record = harness.run_case(case, repeat)
                score = score_run(case, record)
                spent += record.prompt_tokens + record.completion_tokens
                entry = {"record": record.to_dict(), "score": score.to_dict()}
                runs.append(entry)
                if on_run:
                    on_run(entry)
            if stopped_early:
                break
    identity = {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:6],
        "mode": mode,
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "model": getattr(provider, "recorded_model", None) or settings.GROQ_MODEL,
        "prompt_hash": prompt_hash(),
        "tools_hash": tools_hash(),
        "repeats": repeats,
        "single_repeat": repeats == 1,
        "tags": tags or ["all"],
        "n_cases": len({r["score"]["case_id"] for r in runs}),
        "stopped_early_at_token_budget": stopped_early,
        **(extra_identity or {}),
    }
    return {"identity": identity, "runs": runs, "summary": summarize(runs)}


def write_result(result: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    from .report import render_markdown

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / result["identity"]["run_id"]
    json_path = stem.with_suffix(".json")
    md_path = stem.with_suffix(".md")
    json_path.write_text(
        json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    md_path.write_text(render_markdown(result), encoding="utf-8")
    return json_path, md_path


def rescore_result(result: dict[str, Any], cases: list[Case]) -> dict[str, Any]:
    """Apply the current cases and scorers to the records stored in a result.

    Scoring is a pure function of (case, record), so fixing a scorer or a case
    expectation does not need another live run. Identity is kept (mode, model,
    prompt hash: the run is still the run that was recorded) and marked rescored.
    """
    by_id = {c.id: c for c in cases}
    runs = []
    for run in result["runs"]:
        case = by_id[run["score"]["case_id"]]
        record = run_record_from_dict(run["record"])
        runs.append(
            {"record": run["record"], "score": score_run(case, record).to_dict()}
        )
    identity = {
        **result["identity"],
        "rescored_from": result["identity"]["run_id"],
        "rescored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scored_at_git_sha": git_sha(),
        "run_id": result["identity"]["run_id"] + "-rescored",
    }
    return {"identity": identity, "runs": runs, "summary": summarize(runs)}

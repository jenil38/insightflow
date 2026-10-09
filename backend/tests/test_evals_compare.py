"""Baselines, the noise rule, and the CI baseline check."""

from __future__ import annotations

import json

import pytest
from evals import compare as cmp
from evals.report import summarize


def run(case, category, outcome, repeat=1, error=None):
    return {
        "record": {
            "case_id": case,
            "repeat": repeat,
            "status": "completed",
            "answer": "",
            "steps": [],
            "calls": [{"latency_s": 1.0}],
            "prompt_tokens": 1000,
            "completion_tokens": 100,
            "error": error,
            "retries": 0,
        },
        "score": {
            "case_id": case,
            "repeat": repeat,
            "category": category,
            "gating": "gated",
            "outcome": outcome,
            "checks": [],
        },
    }


def result(outcomes, *, mode="live", prompt="p1", tools="t1", model="m/x", extra=()):
    runs = [run(c, cat, o) for c, cat, o in outcomes] + list(extra)
    return {
        "identity": {
            "run_id": "r",
            "mode": mode,
            "model": model,
            "prompt_hash": prompt,
            "tools_hash": tools,
            "repeats": 1,
            "single_repeat": True,
            "tags": ["all"],
            "n_cases": len(outcomes),
        },
        "runs": runs,
        "summary": summarize(runs),
    }


BASE = [
    ("a", "read_only", "pass"),
    ("b", "read_only", "pass"),
    ("c", "actions", "fail"),
]


# ------------------------------------------------------------------- compare


def test_small_samples_are_never_called_a_regression():
    before = summarize([run(f"a{i}", "read_only", "pass") for i in range(3)])
    after = summarize(
        [run(f"a{i}", "read_only", "pass" if i == 0 else "fail") for i in range(3)]
    )
    diff = cmp.compare(before, after)
    assert diff["categories"]["read_only"]["verdict"] == "lower, within noise"
    assert diff["regressed"] is False


def test_a_large_drop_over_many_runs_is_a_regression():
    before = summarize([run(f"a{i}", "read_only", "pass") for i in range(100)])
    outcomes = ["pass"] * 55 + ["fail"] * 45
    after = summarize([run(f"a{i}", "read_only", o) for i, o in enumerate(outcomes)])
    diff = cmp.compare(before, after)
    assert diff["categories"]["read_only"]["verdict"] == "REGRESSION"
    assert diff["regressed"] is True


def test_flips_added_and_removed_cases_are_listed():
    a = result(BASE)["summary"]
    b = result(
        [("a", "read_only", "fail"), ("c", "actions", "fail"), ("d", "actions", "pass")]
    )["summary"]
    changes = {f["case"]: f["change"] for f in cmp.compare(a, b)["flips"]}
    assert changes == {"a": "pass -> fail", "b": "removed", "d": "added"}


def test_a_new_invariant_violation_is_a_regression_regardless_of_rates():
    a = result(BASE)["summary"]
    bad = run("a", "read_only", "pass")
    bad["score"]["checks"] = [
        {
            "name": "invariant:tool_results_fenced",
            "kind": "hard",
            "passed": False,
            "detail": "x",
        }
    ]
    b = result(BASE[1:], extra=[bad])["summary"]
    assert cmp.compare(a, b)["regressed"] is True


def test_token_growth_warns_and_never_fails():
    a = summarize([run("a", "read_only", "pass")])
    b = summarize([run("a", "read_only", "pass")])
    b["tokens"]["p50"] = a["tokens"]["p50"] * 1.5
    diff = cmp.compare(a, b)
    assert diff["token_warning"] is True and diff["regressed"] is False
    assert "WARNING" in cmp.render_compare(diff)


# ------------------------------------------------------------- baseline check


@pytest.fixture
def baseline_dir(tmp_path):
    cmp.accept(result(BASE), tmp_path)
    return tmp_path


def check(res, directory):
    lines: list[str] = []
    code = cmp.check_against_baseline(res, directory, out=lines.append)
    return code, "\n".join(lines)


def test_replay_that_reproduces_the_baseline_passes_even_with_a_known_model_failure(
    baseline_dir,
):
    code, text = check(result(BASE, mode="replay"), baseline_dir)
    assert code == 0 and "1 known gated/informational failure" in text


def test_a_changed_outcome_fails_because_replay_is_deterministic(baseline_dir):
    changed = [("a", "read_only", "fail"), *BASE[1:]]
    code, text = check(result(changed, mode="replay"), baseline_dir)
    assert code == 1 and "case `a` outcome changed" in text and "deterministic" in text


def test_a_changed_prompt_or_tool_schema_asks_for_a_re_record(baseline_dir):
    code, text = check(result(BASE, mode="replay", prompt="p2"), baseline_dir)
    assert code == 1 and "prompt_hash" in text and "Re-record" in text
    code, text = check(result(BASE, mode="replay", tools="t2"), baseline_dir)
    assert code == 1 and "tools_hash" in text


def test_missing_and_new_cases_fail(baseline_dir):
    code, text = check(result(BASE[:2], mode="replay"), baseline_dir)
    assert code == 1 and "in the baseline but was not run" in text
    code, text = check(
        result([*BASE, ("z", "actions", "pass")], mode="replay"), baseline_dir
    )
    assert code == 1 and "is new" in text


def test_unscored_runs_stale_cassettes_and_violations_fail(baseline_dir):
    stale = run("a", "read_only", "not_scored", error={"kind": "stale", "detail": "x"})
    res = result(BASE[1:], mode="replay", extra=[stale])
    code, text = check(res, baseline_dir)
    assert code == 1 and "not scored" in text


def test_no_baseline_is_a_failure_with_the_fix_in_the_message(tmp_path):
    code, text = check(result(BASE, mode="replay"), tmp_path)
    assert code == 1 and "baseline --accept" in text


def test_accept_writes_a_per_model_file_that_keeps_identity_and_summary(tmp_path):
    path = cmp.accept(result(BASE, model="openai/gpt-oss-20b"), tmp_path)
    assert path.name == "openai__gpt-oss-20b.json"
    data = json.loads(path.read_text())
    assert data["identity"]["prompt_hash"] == "p1" and "per_case" in data["summary"]
    assert "runs" not in data  # transcripts are not committed in the baseline

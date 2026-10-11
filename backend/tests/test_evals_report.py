"""Summaries and the report text."""

from __future__ import annotations

from evals.report import NOT_MEASURED, percentile, render_markdown, summarize, wilson


def run(
    case_id,
    category,
    outcome,
    gating="gated",
    repeat=1,
    tokens=(100, 20),
    error=None,
    checks=(),
    steps=(),
    answer="a",
    retries=0,
):
    return {
        "record": {
            "case_id": case_id,
            "repeat": repeat,
            "status": "completed",
            "answer": answer,
            "steps": [{"tool": t, "status": "ok"} for t in steps],
            "calls": [{"latency_s": 1.0}],
            "prompt_tokens": tokens[0],
            "completion_tokens": tokens[1],
            "error": error,
            "retries": retries,
        },
        "score": {
            "case_id": case_id,
            "repeat": repeat,
            "category": category,
            "gating": gating,
            "outcome": outcome,
            "checks": list(checks),
        },
    }


def check(name, kind, passed, detail=""):
    return {"name": name, "kind": kind, "passed": passed, "detail": detail}


def test_summary_counts_gated_and_informational_separately_and_skips_infra_errors():
    runs = [
        run("a", "read_only", "pass"),
        run("b", "read_only", "fail"),
        run("c", "actions", "pass", gating="informational"),
        run(
            "d",
            "actions",
            "not_scored",
            error={"kind": "infra", "detail": "429"},
            retries=2,
        ),
    ]
    s = summarize(runs)
    assert s["gated"]["overall"] == {"pass": 1, "fail": 1, "n": 2}
    assert s["gated"]["by_category"]["read_only"]["n"] == 2
    assert "actions" not in s["gated"]["by_category"]
    assert s["informational"]["actions"] == {"pass": 1, "fail": 0, "n": 1}
    assert s["errors"] == {"infra": 1} and s["retries"] == 2
    assert s["per_case"]["d"]["not_scored"] == 1


def test_flaky_cases_have_mixed_outcomes_across_repeats():
    runs = [
        run("a", "read_only", "pass", repeat=1),
        run("a", "read_only", "fail", repeat=2),
        run("b", "read_only", "pass", repeat=1),
        run("b", "read_only", "pass", repeat=2),
    ]
    assert summarize(runs)["flaky_cases"] == ["a"]


def test_action_behaviour_and_invariants_are_tallied():
    runs = [
        run("a", "actions", "pass", checks=[check("action", "gated", True)]),
        run(
            "b",
            "actions",
            "fail",
            checks=[check("action", "gated", False, "missed: nothing proposed")],
        ),
        run(
            "c",
            "actions",
            "fail",
            checks=[
                check("action", "gated", False, "over-eager: proposed apply_cleaning")
            ],
        ),
        run(
            "d",
            "actions",
            "pass",
            checks=[
                check("invariant:tool_results_fenced", "hard", False, "1 unfenced")
            ],
        ),
    ]
    s = summarize(runs)
    assert s["action_behaviour"] == {"missed": 1, "over_eager": 1, "correct": 1, "n": 3}
    assert s["invariant_violations"][0]["check"] == "invariant:tool_results_fenced"


def test_percentiles_and_wilson_interval():
    assert percentile([], 0.5) is None
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    low, high = wilson(0, 3)
    assert low == 0.0 and high > 0.5  # three runs say almost nothing
    narrow = wilson(90, 100)
    assert narrow[1] - narrow[0] < 0.15 and narrow[0] < 0.9 < narrow[1]


def result(mode="live", repeats=1, runs=None):
    runs = runs or [
        run(
            "a",
            "read_only",
            "fail",
            checks=[
                check("fact:mean:revenue", "gated", False, "expected about 5"),
                check(
                    "numbers_traceable",
                    "heuristic",
                    False,
                    "candidates to review: ['7']",
                ),
            ],
            steps=["profile_column"],
            answer="It is 7.",
        )
    ]
    return {
        "identity": {
            "run_id": "r1",
            "mode": mode,
            "repeats": repeats,
            "single_repeat": repeats == 1,
            "model": "m",
            "git_sha": "abc",
            "prompt_hash": "p",
            "tools_hash": "t",
            "tags": ["all"],
            "n_cases": 1,
            "started": "now",
        },
        "runs": runs,
        "summary": summarize(runs),
    }


def test_the_report_leads_with_what_is_not_measured_and_shows_n_everywhere():
    text = render_markdown(result())
    assert text.index(NOT_MEASURED) < text.index("## Gated results")
    assert "no judge" in NOT_MEASURED
    assert "0/1 = 0%" in text and "95% interval" in text
    assert "FAILED `fact:mean:revenue`: expected about 5" in text
    assert "candidates to review: ['7']" in text
    assert "One repeat per case" in text


def test_the_replay_report_says_the_model_is_not_being_measured():
    text = render_markdown(result(mode="replay"))
    assert "the model is not being measured" in text and "(recorded)" in text


def test_rescoring_applies_the_current_scorers_to_stored_records_without_a_model():
    from evals.cases import load_cases
    from evals.runner import rescore_result

    stored = result()
    # A stored run for a real case, scored (wrongly) as a failure by an older scorer.
    stored["runs"] = [
        run(
            "ro-unique-region",
            "read_only",
            "fail",
            answer="There are four distinct regions.",
        )
    ]
    stored["runs"][0]["record"]["steps"] = [
        {
            "n": 1,
            "tool": "profile_column",
            "args": {"column": "region"},
            "status": "ok",
            "redacted": False,
            "duration_s": 0.0,
            "prompt_tokens": 1,
            "completion_tokens": 1,
        }
    ]
    stored["runs"][0]["record"]["calls"] = [
        {
            "tools_offered": ["profile_column"],
            "tool_texts": [],
            "latency_s": 1.0,
            "prompt_tokens": 1,
            "completion_tokens": 1,
        }
    ]
    stored["identity"]["run_id"] = "orig"
    out = rescore_result(stored, load_cases())

    assert out["runs"][0]["score"]["outcome"] == "pass"
    assert (
        out["identity"]["rescored_from"] == "orig"
        and out["identity"]["run_id"] == "orig-rescored"
    )
    assert out["identity"]["mode"] == stored["identity"]["mode"]
    assert (
        out["runs"][0]["record"] == stored["runs"][0]["record"]
    )  # the records are untouched

"""Baselines, the noise rule, and the CI baseline check."""

from __future__ import annotations

import json

import pytest
from evals import compare as cmp
from evals.compare import AcceptRefused, MergeRefused
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


def result(
    outcomes,
    *,
    mode="record",
    prompt="p1",
    tools="t1",
    model="m/x",
    extra=(),
    repeats=1,
    **ident,
):
    runs = [run(c, cat, o) for c, cat, o in outcomes] + list(extra)
    return {
        "identity": {
            "run_id": "r",
            "mode": mode,
            "model": model,
            "prompt_hash": prompt,
            "tools_hash": tools,
            "repeats": repeats,
            "single_repeat": repeats == 1,
            "tags": ["all"],
            "n_cases": len(outcomes),
            **ident,
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


# ----------------------------------------------- review fixes: what may become the baseline

ALL_IDS = [c for c, _, _ in BASE]


def refused(res, directory, **kw):
    with pytest.raises(AcceptRefused) as exc:
        cmp.accept(res, directory, all_case_ids=ALL_IDS, **kw)
    return "\n".join(exc.value.reasons)


def test_only_a_complete_error_free_record_run_can_become_the_baseline(tmp_path):
    assert cmp.accept(result(BASE), tmp_path, all_case_ids=ALL_IDS).exists()


def test_a_live_or_replay_result_is_refused(tmp_path):
    for mode in ("live", "replay"):
        text = refused(result(BASE, mode=mode), tmp_path)
        assert f"mode is {mode!r}" in text and "cassettes" in text


def test_a_partial_result_is_refused(tmp_path):
    assert "partial: 1 case(s) were not run" in refused(result(BASE[:2]), tmp_path)
    # Fewer runs for a case than repeats is partial too.
    assert "fewer than 2 run(s)" in refused(result(BASE, repeats=2), tmp_path)


def test_an_errored_or_budget_stopped_result_is_refused(tmp_path):
    stale = run(
        "a", "read_only", "not_scored", error={"kind": "infra", "detail": "429"}
    )
    assert "errored" in refused(result(BASE[1:], extra=[stale]), tmp_path)
    assert "budget-stopped" in refused(
        result(BASE, stopped_early_at_token_budget=True), tmp_path
    )


def test_accepting_a_regression_needs_an_explicit_flag_and_names_the_cases(tmp_path):
    cmp.accept(result(BASE), tmp_path, all_case_ids=ALL_IDS)
    worse = [
        ("a", "read_only", "fail"),
        ("b", "read_only", "fail"),
        ("c", "actions", "fail"),
    ]

    text = refused(result(worse), tmp_path)
    assert "regression" in text and "a, b" in text and "--allow-regression" in text
    written = json.loads(cmp.baseline_path("m/x", tmp_path).read_text())
    assert (
        written["summary"]["per_case"]["a"]["pass"] == 1
    )  # the old baseline is untouched

    cmp.accept(result(worse), tmp_path, all_case_ids=ALL_IDS, allow_regression=True)
    assert (
        json.loads(cmp.baseline_path("m/x", tmp_path).read_text())["summary"][
            "per_case"
        ]["a"]["fail"]
        == 1
    )


def test_an_improvement_or_first_baseline_needs_no_flag(tmp_path):
    better = [
        ("a", "read_only", "pass"),
        ("b", "read_only", "pass"),
        ("c", "actions", "pass"),
    ]
    cmp.accept(result(BASE), tmp_path, all_case_ids=ALL_IDS)
    cmp.accept(result(better), tmp_path, all_case_ids=ALL_IDS)


# ----------------------------------------------- review fixes: the CI baseline check


def test_a_repeats_mismatch_is_reported_as_such_and_not_blamed_on_the_code(
    baseline_dir,
):
    code, text = check(result(BASE, mode="replay", repeats=3), baseline_dir)
    assert code == 1 and "repeats mismatch" in text
    assert (
        "recorded with repeats=1" in text
        and "--repeats 1" in text
        and "not a code change" in text
    )
    assert "deterministic" not in text and "outcome changed" not in text


def test_a_failing_hard_check_fails_even_when_every_outcome_matches(baseline_dir):
    """Hard checks do not change a case's outcome, so outcomes can match the baseline
    exactly while an invariant about our code is broken."""
    broken = run("a", "read_only", "pass")
    broken["score"]["checks"] = [
        {
            "name": "invariant:no_action_executed_in_ask",
            "kind": "hard",
            "passed": False,
            "detail": "executed",
        }
    ]
    res = result(BASE[1:], mode="replay", extra=[broken])
    assert (
        res["summary"]["per_case"] == result(BASE, mode="replay")["summary"]["per_case"]
    )

    code, text = check(res, baseline_dir)
    assert code == 1 and "hard invariants violated" in text
    assert "outcome changed" not in text
    # ...and it is listed before everything else.
    assert (
        text.index("hard invariants violated") < len(text) // 2
        or text.count("  - ") == 1
    )


# ----------------------------------------------------------------------- merge


def test_merge_replaces_only_the_re_recorded_cases_and_says_so():
    base = result(BASE)
    base["identity"]["run_id"] = "full"
    fresh = result([("a", "read_only", "fail")])
    fresh["identity"]["run_id"] = "one"
    merged = cmp.merge_results(base, fresh)

    outcomes = {r["score"]["case_id"]: r["score"]["outcome"] for r in merged["runs"]}
    assert outcomes == {"a": "fail", "b": "pass", "c": "fail"}
    assert merged["identity"]["merged_from"] == ["full", "one"]
    assert merged["identity"]["replaced_cases"] == ["a"]
    assert merged["identity"]["mode"] == "record"
    assert merged["summary"]["per_case"]["a"] == {"pass": 0, "fail": 1, "not_scored": 0}
    # A merged result is a complete record run, so it can become the baseline.
    assert not cmp.refusals_to_accept(merged, ALL_IDS)


def test_merge_refuses_anything_that_would_not_match_the_cassettes():
    base = result(BASE)
    for bad, why in [
        (result([("a", "read_only", "pass")], mode="live"), "not a record run"),
        (result([("a", "read_only", "pass")], prompt="p2"), "prompt_hash differs"),
        (result([("a", "read_only", "pass")], model="other"), "model differs"),
        (result([("zz", "read_only", "pass")]), "cases the base does not"),
        (
            result(
                [],
                extra=[
                    run(
                        "a",
                        "read_only",
                        "not_scored",
                        error={"kind": "infra", "detail": "x"},
                    )
                ],
            ),
            "unscored runs",
        ),
    ]:
        with pytest.raises(MergeRefused, match=why):
            cmp.merge_results(base, bad)

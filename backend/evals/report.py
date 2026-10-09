"""Summaries and the human-readable report.

Every rate is shown with its n. The report opens with what the suite does not
measure, because a table of passing checks invites the reading that the answers
are good.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

NOT_MEASURED = (
    "**Not measured:** whether free-text answers are faithful to the tool results, "
    "answer the question well, or are honest about tool errors. There is no judge "
    "model in this version. An answer can pass every check below and still be a poor "
    "answer. Number-traceability is a heuristic whose flags need a person to look."
)


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 3)


def wilson(passed: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a pass rate. Wide for small n, which is the point."""
    if n == 0:
        return (0.0, 1.0)
    p = passed / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3))


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """`runs` are {"record": RunRecord.to_dict(), "score": RunScore.to_dict()}."""
    per_case: dict[str, dict[str, int]] = defaultdict(
        lambda: {"pass": 0, "fail": 0, "not_scored": 0}
    )
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0})
    info: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0})
    kinds: dict[str, dict[str, int]] = defaultdict(lambda: {"passed": 0, "failed": 0})
    violations: list[dict[str, str]] = []
    errors: dict[str, int] = defaultdict(int)
    action = {"missed": 0, "over_eager": 0, "correct": 0, "n": 0}
    tokens: list[float] = []
    latency: list[float] = []
    steps: list[float] = []
    retries = 0

    for run in runs:
        rec, score = run["record"], run["score"]
        case_id = score["case_id"]
        per_case[case_id][score["outcome"]] += 1
        retries += rec.get("retries", 0)
        if rec.get("error"):
            errors[rec["error"]["kind"]] += 1
            continue
        tokens.append(rec["prompt_tokens"] + rec["completion_tokens"])
        latency.append(sum(c["latency_s"] for c in rec["calls"]))
        steps.append(len(rec["steps"]))
        counted = score["gating"] == "gated"
        bucket = by_category[score["category"]] if counted else info[score["category"]]
        bucket[score["outcome"]] += 1
        for check in score["checks"]:
            if check["passed"] is None:
                continue
            kinds[check["kind"]]["passed" if check["passed"] else "failed"] += 1
            if check["kind"] == "hard" and check["passed"] is False:
                violations.append(
                    {"case": case_id, "check": check["name"], "detail": check["detail"]}
                )
            if check["name"] == "action":
                action["n"] += 1
                if check["passed"]:
                    action["correct"] += 1
                elif "missed" in check["detail"]:
                    action["missed"] += 1
                elif "over-eager" in check["detail"]:
                    action["over_eager"] += 1

    flaky = sorted(c for c, v in per_case.items() if v["pass"] and v["fail"])
    totals = {"pass": 0, "fail": 0}
    for v in by_category.values():
        totals["pass"] += v["pass"]
        totals["fail"] += v["fail"]
    return {
        "gated": {
            "overall": {**totals, "n": totals["pass"] + totals["fail"]},
            "by_category": {
                k: {**v, "n": v["pass"] + v["fail"]}
                for k, v in sorted(by_category.items())
            },
        },
        "informational": {
            k: {**v, "n": v["pass"] + v["fail"]} for k, v in sorted(info.items())
        },
        "per_case": {k: dict(v) for k, v in sorted(per_case.items())},
        "check_kinds": {k: dict(v) for k, v in sorted(kinds.items())},
        "invariant_violations": violations,
        "action_behaviour": action,
        "errors": dict(errors),
        "retries": retries,
        "flaky_cases": flaky,
        "tokens": {
            "total": int(sum(tokens)),
            "p50": percentile(tokens, 0.5),
            "p95": percentile(tokens, 0.95),
        },
        "provider_latency_s": {
            "p50": percentile(latency, 0.5),
            "p95": percentile(latency, 0.95),
        },
        "steps_per_run": {"mean": round(sum(steps) / len(steps), 2) if steps else None},
    }


def _rate(passed: int, n: int) -> str:
    if n == 0:
        return "n/a (n=0)"
    lo, hi = wilson(passed, n)
    return f"{passed}/{n} = {100 * passed / n:.0f}% (95% interval {100 * lo:.0f}-{100 * hi:.0f}%)"


def render_markdown(result: dict[str, Any]) -> str:
    ident, summ = result["identity"], result["summary"]
    lines = [f"# Agent eval report: {ident['run_id']}", "", NOT_MEASURED, ""]
    lines += ["## Run identity", ""]
    for key in (
        "mode",
        "model",
        "git_sha",
        "prompt_hash",
        "tools_hash",
        "repeats",
        "tags",
        "n_cases",
        "replay_strict",
        "started",
    ):
        if key in ident:
            lines.append(f"- **{key}:** {ident[key]}")
    if ident["mode"] == "replay":
        lines.append(
            "- **Replay:** the model is not being measured. Cost and latency below are the "
            "recorded values from the live run that produced the cassettes."
        )
    if ident.get("single_repeat"):
        lines.append(
            "- **One repeat per case:** rates below are from single runs of a "
            "non-deterministic model. Treat them as a first reading, not a baseline of record."
        )
    lines += ["", "## Gated results", ""]
    g = summ["gated"]
    lines.append(f"**Overall:** {_rate(g['overall']['pass'], g['overall']['n'])}")
    lines += ["", "| Category | Result |", "|---|---|"]
    for cat, v in g["by_category"].items():
        lines.append(f"| {cat} | {_rate(v['pass'], v['n'])} |")
    if summ["informational"]:
        lines += ["", "Informational cases (scored, never counted):", ""]
        for cat, v in summ["informational"].items():
            lines.append(f"- {cat}: {v['pass']} pass, {v['fail']} fail (n={v['n']})")

    a = summ["action_behaviour"]
    lines += [
        "",
        "## Action behaviour",
        "",
        f"Of {a['n']} runs with an action expectation: {a['correct']} correct, "
        f"{a['missed']} missed a proposal, {a['over_eager']} proposed when it should not have.",
    ]

    lines += ["", "## Invariants (about our code, not the model)", ""]
    if summ["invariant_violations"]:
        lines.append("**VIOLATED:**")
        for v in summ["invariant_violations"]:
            lines.append(f"- `{v['check']}` in `{v['case']}`: {v['detail']}")
    else:
        lines.append("None violated.")

    failures = [r for r in result["runs"] if r["score"]["outcome"] == "fail"]
    lines += ["", f"## Failures ({len(failures)})", ""]
    for r in failures[:40]:
        score, rec = r["score"], r["record"]
        bad = [
            c for c in score["checks"] if c["kind"] == "gated" and c["passed"] is False
        ]
        tools = (
            " -> ".join(f"{s['tool']}[{s['status']}]" for s in rec["steps"])
            or "(no tools)"
        )
        lines.append(
            f"### {score['case_id']} (repeat {score['repeat']}, {score['gating']})"
        )
        lines.append(f"- tools: {tools}")
        for c in bad:
            lines.append(f"- FAILED `{c['name']}`: {c['detail']}")
        lines.append(f"- answer: {rec['answer'][:300].replace(chr(10), ' ')}")
        lines.append("")
    if len(failures) > 40:
        lines.append(f"... and {len(failures) - 40} more in the JSON.")

    review = [
        (r["score"]["case_id"], c["detail"])
        for r in result["runs"]
        for c in r["score"]["checks"]
        if c["kind"] == "heuristic" and c["passed"] is False
    ]
    lines += ["", f"## Heuristic flags for a person to review ({len(review)})", ""]
    lines += [f"- `{case}`: {detail}" for case, detail in review[:40]] or ["None."]

    t, lat = summ["tokens"], summ["provider_latency_s"]
    lines += [
        "",
        "## Cost and latency" + (" (recorded)" if ident["mode"] == "replay" else ""),
        "",
        f"- tokens per run: p50 {t['p50']}, p95 {t['p95']}, total {t['total']}",
        f"- provider latency per run (s): p50 {lat['p50']}, p95 {lat['p95']}",
        f"- tool calls per run (mean): {summ['steps_per_run']['mean']}",
        "- latency depends on the provider and the time of day; it is reported, never gated.",
    ]
    lines += ["", "## Infrastructure", ""]
    lines.append(
        f"- not scored (infrastructure/stale/harness): {summ['errors'] or 'none'}"
    )
    lines.append(f"- provider 429 retries: {summ['retries']}")
    if summ["flaky_cases"]:
        lines += ["", "## Flaky (mixed outcomes across repeats)", ""]
        lines += [f"- {c}" for c in summ["flaky_cases"]]
    return "\n".join(lines) + "\n"

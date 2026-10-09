"""Baselines and regression checks. Pure JSON in, text and an exit code out.

Two different questions are answered here and kept apart:

- `compare`: how does a run differ from another run, with a noise rule so that
  a small change in a rate of a non-deterministic model is not called a regression.
- `check_against_baseline`: the CI check on a *replay*. Replay is deterministic, so
  any per-case difference from the baseline means our code changed behaviour (a
  tool's output, the sanitiser, the scorers). A case the recorded model got wrong is
  a known result in the baseline, not a failure.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .report import wilson

BASELINES_DIR = Path(__file__).parent / "baselines"
DROP_THRESHOLD = 0.10  # a gated rate must fall by at least this much to matter
TOKEN_WARN = 0.20  # token p50 change worth a warning


def slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "__", model)


def baseline_path(model: str, directory: Path = BASELINES_DIR) -> Path:
    return directory / f"{slug(model)}.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def baseline_from_result(result: dict[str, Any]) -> dict[str, Any]:
    ident = result["identity"]
    keep = (
        "run_id",
        "mode",
        "started",
        "git_sha",
        "model",
        "prompt_hash",
        "tools_hash",
        "repeats",
        "single_repeat",
        "tags",
        "n_cases",
    )
    return {
        "schema": 1,
        "accepted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "identity": {k: ident[k] for k in keep if k in ident},
        "summary": result["summary"],
    }


def accept(result: dict[str, Any], directory: Path = BASELINES_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = baseline_path(result["identity"]["model"], directory)
    path.write_text(
        json.dumps(
            baseline_from_result(result), indent=1, ensure_ascii=False, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------- compare


def _rate(v: dict[str, int]) -> float | None:
    n = v["pass"] + v["fail"]
    return v["pass"] / n if n else None


def _majority(counts: dict[str, int]) -> str:
    scored = counts.get("pass", 0) + counts.get("fail", 0)
    if not scored:
        return "not_scored"
    return "pass" if counts.get("pass", 0) * 2 >= scored else "fail"


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """`a` is the earlier summary (baseline), `b` the new one."""
    flips = []
    for case in sorted(set(a["per_case"]) | set(b["per_case"])):
        ca, cb = a["per_case"].get(case), b["per_case"].get(case)
        if ca is None or cb is None:
            flips.append({"case": case, "change": "added" if ca is None else "removed"})
            continue
        before, after = _majority(ca), _majority(cb)
        if before != after:
            flips.append(
                {
                    "case": case,
                    "change": f"{before} -> {after}",
                    "before": ca,
                    "after": cb,
                }
            )

    categories = {}
    for cat in sorted(set(a["gated"]["by_category"]) | set(b["gated"]["by_category"])):
        va = a["gated"]["by_category"].get(cat, {"pass": 0, "fail": 0})
        vb = b["gated"]["by_category"].get(cat, {"pass": 0, "fail": 0})
        ra, rb = _rate(va), _rate(vb)
        if ra is None or rb is None:
            verdict = "not comparable"
        else:
            la, ha = wilson(va["pass"], va["pass"] + va["fail"])
            lb, hb = wilson(vb["pass"], vb["pass"] + vb["fail"])
            if rb <= ra - DROP_THRESHOLD:
                verdict = "REGRESSION" if hb < la else "lower, within noise"
            elif rb >= ra + DROP_THRESHOLD:
                verdict = "improved" if lb > ha else "higher, within noise"
            else:
                verdict = "no meaningful change"
        categories[cat] = {"before": va, "after": vb, "verdict": verdict}

    tok_a, tok_b = a["tokens"]["p50"], b["tokens"]["p50"]
    token_change = None
    if tok_a and tok_b:
        token_change = round((tok_b - tok_a) / tok_a, 3)
    new_violations = [
        v for v in b["invariant_violations"] if v not in a["invariant_violations"]
    ]
    return {
        "flips": flips,
        "categories": categories,
        "token_p50_change": token_change,
        "token_warning": token_change is not None and token_change > TOKEN_WARN,
        "new_invariant_violations": new_violations,
        "regressed": any(c["verdict"] == "REGRESSION" for c in categories.values())
        or bool(new_violations),
    }


def render_compare(
    diff: dict[str, Any], label_a: str = "baseline", label_b: str = "new"
) -> str:
    lines = [f"# {label_a} -> {label_b}", ""]
    lines.append("| Category | " + label_a + " | " + label_b + " | Verdict |")
    lines.append("|---|---|---|---|")
    for cat, c in diff["categories"].items():
        fmt = lambda v: f"{v['pass']}/{v['pass'] + v['fail']}"  # noqa: E731
        lines.append(
            f"| {cat} | {fmt(c['before'])} | {fmt(c['after'])} | {c['verdict']} |"
        )
    lines += ["", f"## Cases that changed outcome ({len(diff['flips'])})", ""]
    lines += [f"- `{f['case']}`: {f['change']}" for f in diff["flips"]] or ["None."]
    if diff["token_p50_change"] is not None:
        flag = " (WARNING: more than 20% higher)" if diff["token_warning"] else ""
        lines += [
            "",
            f"Token p50 per run changed by {100 * diff['token_p50_change']:+.0f}%{flag}.",
        ]
    if diff["new_invariant_violations"]:
        lines += ["", "## NEW invariant violations", ""]
        lines += [
            f"- `{v['check']}` in `{v['case']}`"
            for v in diff["new_invariant_violations"]
        ]
    lines += [
        "",
        "Rates come from few runs of a non-deterministic model; 'within noise' means the "
        "95% intervals overlap, not that nothing changed.",
    ]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------- CI baseline check


def check_against_baseline(
    result: dict[str, Any], directory: Path = BASELINES_DIR, out=print
) -> int:
    """Exit code for the CI replay: 0 only if replay reproduced the baseline."""
    ident, summ = result["identity"], result["summary"]
    path = baseline_path(ident["model"], directory)
    if not path.exists():
        out(
            f"BASELINE CHECK FAILED: no baseline at {path}. Run `baseline --accept <result.json>`."
        )
        return 1
    base = load(path)
    problems: list[str] = []

    for key in ("prompt_hash", "tools_hash"):
        if base["identity"].get(key) != ident.get(key):
            problems.append(
                f"{key} is {ident.get(key)} but the baseline was accepted at "
                f"{base['identity'].get(key)}: the prompt or tool schemas changed. Re-record "
                "cassettes with a live run and accept a new baseline in the same change."
            )

    base_cases, new_cases = base["summary"]["per_case"], summ["per_case"]
    for case in sorted(set(base_cases) - set(new_cases)):
        problems.append(f"case `{case}` is in the baseline but was not run")
    for case in sorted(set(new_cases) - set(base_cases)):
        problems.append(f"case `{case}` is new: record it and accept a new baseline")
    for case in sorted(set(base_cases) & set(new_cases)):
        if base_cases[case] != new_cases[case]:
            problems.append(
                f"case `{case}` outcome changed: baseline {base_cases[case]}, replay {new_cases[case]}. "
                "Replay is deterministic, so a tool, the sanitiser, a scorer or the harness changed behaviour."
            )
    if summ["errors"]:
        problems.append(f"runs were not scored: {summ['errors']}")
    if summ["invariant_violations"]:
        problems.append(f"hard invariants violated: {summ['invariant_violations']}")

    if problems:
        out("BASELINE CHECK FAILED:")
        for p in problems:
            out(f"  - {p}")
        return 1
    known = [c for c, v in new_cases.items() if v.get("fail")]
    out(
        f"Baseline check passed: {len(new_cases)} cases reproduced "
        f"(baseline {base['identity'].get('run_id')}, {base['identity'].get('mode')}). "
        f"{len(known)} known gated/informational failure(s) from the recorded model are in the baseline."
    )
    return 0

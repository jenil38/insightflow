"""`python -m evals ...` from `backend/`.

Live and record spend the real provider key and are rate limited, so they are run
by hand, never in CI. CI runs `run --mode replay` only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import env
from .cases import load_cases, select

DEFAULT_OUT = Path(__file__).parent / "results"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the suite and write a report")
    run.add_argument("--mode", choices=["live", "record", "replay"], default="replay")
    run.add_argument("--tags", default="all", help="comma separated; 'smoke' or 'all'")
    run.add_argument("--cases", default="", help="comma separated case ids")
    run.add_argument("--repeats", type=int, default=1)
    run.add_argument(
        "--tpm",
        type=int,
        default=int(os.environ.get("EVAL_TPM", "6000")),
        help="tokens per minute budget for live/record (default 6000)",
    )
    run.add_argument(
        "--max-tokens", type=int, default=None, help="stop after this many tokens"
    )
    run.add_argument(
        "--resume",
        action="store_true",
        help="record mode: skip runs that already have a cassette",
    )
    run.add_argument(
        "--by-order",
        action="store_true",
        help="replay by position, ignoring request keys (local only; says nothing about the current prompt)",
    )
    run.add_argument("--out", default=str(DEFAULT_OUT))
    run.add_argument("--check-baseline", action="store_true")
    mrg = sub.add_parser(
        "merge",
        help="replace some cases in a full record result with a fresh record of just those",
    )
    mrg.add_argument("base")
    mrg.add_argument("replacement")
    mrg.add_argument("--out", default=str(DEFAULT_OUT))
    cmp_ = sub.add_parser(
        "compare", help="diff two result files (or a result against a baseline)"
    )
    cmp_.add_argument("before")
    cmp_.add_argument("after")
    base = sub.add_parser("baseline", help="promote a result to the committed baseline")
    base.add_argument("--accept", required=True, metavar="RESULT_JSON")
    base.add_argument(
        "--allow-regression",
        action="store_true",
        help="accept even if cases the current baseline passes now fail",
    )
    resc = sub.add_parser(
        "rescore",
        help="re-apply the current cases and scorers to a stored result, without calling a model",
    )
    resc.add_argument("result")
    resc.add_argument("--out", default=str(DEFAULT_OUT))
    sub.add_parser("list", help="list the cases")
    return parser


def _regression_command(args: argparse.Namespace) -> int:
    """These work on JSON files only and never import the application."""
    from . import compare as cmp

    if args.command == "merge":
        from .report import render_markdown

        try:
            merged = cmp.merge_results(
                cmp.load(Path(args.base)), cmp.load(Path(args.replacement))
            )
        except cmp.MergeRefused as exc:
            print(f"refusing to merge: {exc}", file=sys.stderr)
            return 2
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = out_dir / merged["identity"]["run_id"].replace("+", "_")
        stem.with_suffix(".json").write_text(
            json.dumps(merged, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        stem.with_suffix(".md").write_text(render_markdown(merged), encoding="utf-8")
        print(f"merged result: {stem.with_suffix('.json')}")
        return 0
    if args.command == "baseline":
        result = cmp.load(Path(args.accept))
        try:
            written = cmp.accept(
                result,
                all_case_ids=[c.id for c in load_cases()],
                allow_regression=args.allow_regression,
            )
        except cmp.AcceptRefused as exc:
            print("refusing to accept this result as the baseline:", file=sys.stderr)
            for reason in exc.reasons:
                print(f"  - {reason}", file=sys.stderr)
            return 2
        print(f"baseline written: {written}")
        return 0
    before, after = cmp.load(Path(args.before)), cmp.load(Path(args.after))
    a = before["summary"]
    b = after["summary"]
    diff = cmp.compare(a, b)
    print(cmp.render_compare(diff, Path(args.before).stem, Path(args.after).stem))
    return 1 if diff["regressed"] else 0


def exit_code_for(mode: str, result: dict) -> int:
    """1 for anything that must fail a run, whatever flags were given.

    A hard-invariant violation is reported first: it is about our code and must not
    be overshadowed by a stale cassette or an infrastructure error. In replay mode
    any run that could not be scored (stale, infrastructure, harness) fails the run
    too, with or without --check-baseline; replay is deterministic, so an error entry
    means something is wrong, not something transient.
    """
    summ, ident = result["summary"], result["identity"]
    code = 0
    if summ["invariant_violations"]:
        print(
            f"INVARIANT VIOLATIONS: {len(summ['invariant_violations'])}",
            file=sys.stderr,
        )
        for v in summ["invariant_violations"][:5]:
            print(f"  - {v['check']} in {v['case']}: {v['detail']}", file=sys.stderr)
        code = 1
    if mode == "replay":
        if summ["errors"].get("stale") or ident.get("replay_leftover_calls"):
            print("STALE CASSETTES: re-record with a live run", file=sys.stderr)
            code = 1
        other = {k: v for k, v in summ["errors"].items() if k != "stale"}
        if other:
            print(f"UNSCORED RUNS IN REPLAY: {other}", file=sys.stderr)
            code = 1
    return code


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command in ("compare", "baseline", "merge"):
        return _regression_command(args)
    cases = load_cases()
    if args.command == "list":
        for c in cases:
            print(f"{c.id:45s} {c.category:13s} {c.gating:13s} {','.join(c.tags)}")
        print(f"\n{len(cases)} cases")
        return 0

    if args.command == "rescore":
        env.isolate()  # scorers import the application; keep it off any real database
        from .runner import rescore_result, write_result

        result = json.loads(Path(args.result).read_text(encoding="utf-8"))
        rescored = rescore_result(result, cases)
        json_path, md_path = write_result(rescored, Path(args.out))
        print(f"report: {md_path}\nresult: {json_path}")
        return 1 if rescored["summary"]["invariant_violations"] else 0

    try:
        chosen = select(
            cases,
            [t for t in args.tags.split(",") if t],
            [i for i in args.cases.split(",") if i] or None,
        )
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not chosen:
        print("no cases selected", file=sys.stderr)
        return 2

    db_path = env.isolate()
    # Application modules are imported only now, after the environment is aimed at
    # the throwaway database.
    from .harness import assert_isolated
    from .provider import CassetteStore, LiveProvider, RecordProvider, ReplayProvider
    from .runner import run_suite, write_result

    assert_isolated(str(db_path))  # before anything is created in the database
    env.create_schema()
    from app.core.config import settings

    store = CassetteStore()
    if args.mode == "replay":
        provider = ReplayProvider(store, strict=not args.by_order)
    else:
        if not settings.GROQ_API_KEY:
            print(
                "GROQ_API_KEY is not set; live and record modes need it.",
                file=sys.stderr,
            )
            return 2
        if args.mode == "record":
            provider = RecordProvider(store, settings.GROQ_MODEL, tpm=args.tpm)
        else:
            provider = LiveProvider(tpm=args.tpm)

    skip = (
        (lambda c, r: store.exists(c.id, r))
        if args.mode == "record" and args.resume
        else None
    )

    def progress(entry):
        rec, score = entry["record"], entry["score"]
        tools = ",".join(s["tool"] for s in rec["steps"]) or "-"
        note = f" ERROR[{rec['error']['kind']}]" if rec["error"] else ""
        print(
            f"[{score['outcome']:10s}] {score['case_id']:45s} r{score['repeat']} tools={tools}{note}",
            flush=True,
        )

    result = run_suite(
        chosen,
        provider,
        repeats=args.repeats,
        mode=args.mode,
        tags=[t for t in args.tags.split(",") if t],
        expected_db_path=str(db_path),
        skip=skip,
        on_run=progress,
        max_tokens=args.max_tokens,
        extra_identity={
            "replay_strict": (not args.by_order) if args.mode == "replay" else None
        },
    )
    if args.mode == "replay" and getattr(provider, "leftover", None):
        result["identity"]["replay_leftover_calls"] = provider.leftover
    json_path, md_path = write_result(result, Path(args.out))
    print(f"\nreport: {md_path}\nresult: {json_path}")

    exit_code = exit_code_for(args.mode, result)
    if args.mode == "record" and getattr(provider, "failed_runs", None):
        print(
            f"{len(provider.failed_runs)} run(s) not recorded (provider errors); re-run with --resume",
            file=sys.stderr,
        )
    if args.check_baseline:
        from .compare import check_against_baseline

        exit_code = max(exit_code, check_against_baseline(result))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

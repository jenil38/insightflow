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
    resc = sub.add_parser(
        "rescore",
        help="re-apply the current cases and scorers to a stored result, without calling a model",
    )
    resc.add_argument("result")
    resc.add_argument("--out", default=str(DEFAULT_OUT))
    sub.add_parser("list", help="list the cases")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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

    env.create_schema()
    assert_isolated(str(db_path))
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

    summ = result["summary"]
    exit_code = 0
    if summ["invariant_violations"]:
        print(
            f"INVARIANT VIOLATIONS: {len(summ['invariant_violations'])}",
            file=sys.stderr,
        )
        exit_code = 1
    if args.mode == "replay" and (
        summ["errors"].get("stale") or result["identity"].get("replay_leftover_calls")
    ):
        print("STALE CASSETTES: re-record with a live run", file=sys.stderr)
        exit_code = 1
    if args.mode == "record" and getattr(provider, "failed_runs", None):
        print(
            f"{len(provider.failed_runs)} run(s) not recorded (provider errors); re-run with --resume",
            file=sys.stderr,
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

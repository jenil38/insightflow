"""The CLI, run as a subprocess the way CI and a developer run it.

A subprocess matters here: `python -m evals run` points its own process at a
throwaway database before the application is imported, which must never leak into
the test process.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def cli(*args, env_extra=None, drop=("GROQ_API_KEY",)):
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "evals", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_list_prints_every_case():
    out = cli("list")
    assert out.returncode == 0 and "54 cases" in out.stdout
    assert "inj-ro-literal_english" in out.stdout


def test_replay_of_committed_cassettes_exits_zero_and_writes_a_report(tmp_path):
    out = cli(
        "run",
        "--mode",
        "replay",
        "--cases",
        "ro-rows-cols-sales30,act-on-clean",
        "--out",
        str(tmp_path),
    )
    assert out.returncode == 0, out.stdout + out.stderr
    results = list(tmp_path.glob("*.json"))
    assert len(results) == 1 and list(tmp_path.glob("*.md"))
    data = json.loads(results[0].read_text())
    assert data["identity"]["mode"] == "replay"
    assert data["identity"]["replay_strict"] is True
    assert data["summary"]["errors"] == {}
    assert {r["score"]["outcome"] for r in data["runs"]} == {"pass"}


def test_an_unknown_case_is_a_clean_error_not_a_traceback():
    out = cli("run", "--mode", "replay", "--cases", "no-such-case")
    assert (
        out.returncode == 2
        and "unknown case ids" in out.stderr
        and "Traceback" not in out.stderr
    )


def test_live_mode_without_a_key_is_refused_before_any_call():
    out = cli("run", "--mode", "live", "--cases", "un-weather")
    assert out.returncode == 2 and "GROQ_API_KEY" in out.stderr


def test_a_replay_result_cannot_be_accepted_as_a_baseline(tmp_path):
    fake = tmp_path / "replay.json"
    fake.write_text(
        json.dumps({"identity": {"mode": "replay", "model": "m"}, "summary": {}})
    )
    out = cli("baseline", "--accept", str(fake))
    assert out.returncode == 2 and "does not measure the model" in out.stderr

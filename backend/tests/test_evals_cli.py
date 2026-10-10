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


def cli(*args, env_extra=None):
    # GROQ_API_KEY is set to an empty string rather than removed: pydantic-settings
    # reads backend/.env too, and an empty environment variable takes precedence over
    # it, so a developer's real key can never turn these tests into live calls.
    env = {**os.environ, "GROQ_API_KEY": ""}
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
    assert out.returncode == 0 and "55 cases" in out.stdout
    assert "inj-ro-literal_english" in out.stdout


def test_replay_of_committed_cassettes_exits_zero_and_writes_a_report(tmp_path):
    out = cli(
        "run",
        "--mode",
        "replay",
        "--cases",
        "act-off-clean,act-on-clean",
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
    assert out.returncode == 2 and "only a record run can be accepted" in out.stderr
    assert "Traceback" not in out.stderr


def test_a_developer_key_in_the_environment_cannot_cause_a_live_call():
    out = cli(
        "run", "--mode", "live", "--cases", "un-weather", env_extra={"GROQ_API_KEY": ""}
    )
    assert out.returncode == 2 and "GROQ_API_KEY" in out.stderr


def test_the_baseline_command_refuses_a_result_that_is_not_a_record_run(tmp_path):
    fake = tmp_path / "live.json"
    fake.write_text(
        json.dumps(
            {
                "identity": {"mode": "live", "model": "m"},
                "runs": [],
                "summary": {"errors": {}},
            }
        )
    )
    out = cli("baseline", "--accept", str(fake))
    assert (
        out.returncode == 2
        and "only a record run can be accepted" in out.stderr
        and "partial" in out.stderr
    )


# --------------------------------------------------- exit codes, as a function


def _result(errors=None, violations=(), leftover=None):
    return {
        "identity": {"replay_leftover_calls": leftover} if leftover else {},
        "summary": {"errors": errors or {}, "invariant_violations": list(violations)},
    }


def test_any_error_entry_fails_a_replay_even_without_check_baseline(capsys):
    from evals.__main__ import exit_code_for

    for kind in ("stale", "infra", "harness"):
        assert exit_code_for("replay", _result({kind: 1})) == 1
    assert exit_code_for("replay", _result()) == 0
    assert exit_code_for("replay", _result(leftover={"c.r1": 1})) == 1
    # Outside replay an infrastructure error is transient and is not an exit failure here.
    assert exit_code_for("record", _result({"infra": 1})) == 0
    assert "UNSCORED RUNS IN REPLAY" in capsys.readouterr().err


def test_an_invariant_violation_is_reported_ahead_of_stale(capsys):
    from evals.__main__ import exit_code_for

    violation = {
        "case": "c",
        "check": "invariant:no_action_executed_in_ask",
        "detail": "executed",
    }
    assert exit_code_for("replay", _result({"stale": 1}, [violation])) == 1
    err = capsys.readouterr().err
    assert err.index("INVARIANT VIOLATIONS") < err.index("STALE CASSETTES")
    assert exit_code_for("live", _result(violations=[violation])) == 1


def test_the_schema_is_only_created_after_the_database_is_asserted_to_be_the_harness_own():
    source = (BACKEND / "evals" / "__main__.py").read_text()
    assert source.index("assert_isolated(str(db_path))") < source.index(
        "env.create_schema()"
    )


def test_the_isolated_environment_blanks_smtp_so_registration_cannot_send_mail(
    monkeypatch,
):
    from evals import env

    for name in (
        "DATABASE_URL",
        "UPLOAD_DIR",
        "JWT_SECRET",
        "ENVIRONMENT",
        "DEBUG",
        "SMTP_HOST",
    ):
        monkeypatch.setenv(name, "before")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    env.isolate()
    assert os.environ["SMTP_HOST"] == ""

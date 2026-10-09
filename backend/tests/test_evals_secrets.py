"""The scan that guards committed cassettes against credentials."""

from __future__ import annotations

from pathlib import Path

from evals.provider import CASSETTES_DIR
from evals.secrets import scan_directory, scan_text


def test_scan_flags_each_kind_of_credential():
    planted = {
        "groq-style key": "key is gsk_abcdefghij1234567890",
        "authorization header": '"Authorization": "x"',
        "bearer token": "Bearer abcdefgh12345678",
        "api key mention": "set your API_KEY first",
        "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig",
        "generic secret assignment": 'password: "hunter2hunter2"',
    }
    for name, text in planted.items():
        assert name in scan_text(text), name


def test_scan_flags_the_configured_key_value_and_passes_ordinary_model_output():
    assert scan_text("the value is s3cr3t-value-123", ["s3cr3t-value-123"]) == [
        "the configured key value"
    ]
    assert scan_text("The dataset has 30 rows and 6 columns. prompt_tokens: 120") == []


def test_scan_directory_names_the_offending_files(tmp_path: Path):
    (tmp_path / "clean.json").write_text('{"message": "hello"}')
    (tmp_path / "dirty.json").write_text('{"message": "Bearer abcdefgh12345678"}')
    assert scan_directory(tmp_path) == {"dirty.json": ["bearer token"]}


def test_the_committed_cassettes_contain_no_credentials():
    assert CASSETTES_DIR.exists()
    assert list(CASSETTES_DIR.glob("*.json")), "no cassettes are committed"
    assert scan_directory(CASSETTES_DIR) == {}

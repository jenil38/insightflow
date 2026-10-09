"""Ground truth computed from the dataset bytes, never typed by hand.

A hand-written expected number goes stale the day a dataset changes and is wrong
if its author mis-added. The oracle recomputes it with pandas from the same
bytes the agent was given. It deliberately does not call the application's own
analysis code: an oracle that shared the code under test would agree with its
bugs.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

FACT_KINDS = {
    "row_count",
    "column_count",
    "missing_count",
    "missing_pct",
    "mean",
    "min",
    "max",
    "unique_count",
    "top_category",
    "correlation",
    "group_top",
    "absent_column",
}


@dataclass
class Resolved:
    kind: str
    label: str
    numbers: list[float] = field(default_factory=list)
    strings: list[str] = field(default_factory=list)


def load_frame(data: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(data))


def resolve_fact(df: pd.DataFrame, fact: dict[str, Any]) -> Resolved:
    kind = fact["kind"]
    if kind not in FACT_KINDS:
        raise ValueError(f"unknown fact kind {kind!r}")
    col = fact.get("column")

    if kind == "row_count":
        return Resolved(kind, "number of rows", [float(len(df))])
    if kind == "column_count":
        return Resolved(kind, "number of columns", [float(df.shape[1])])
    if kind == "absent_column":
        if col in df.columns:
            raise ValueError(f"absent_column {col!r} exists in the dataset")
        return Resolved(kind, f"column {col!r} does not exist", strings=[col])

    if kind == "correlation":
        x, y = fact["x"], fact["y"]
        value = round(float(df[x].corr(df[y])), 4)
        return Resolved(kind, f"correlation of {x} and {y}", [value])

    if kind == "group_top":
        measure, dim = fact["measure"], fact["dimension"]
        agg = fact.get("aggregation", "sum")
        grouped = df.groupby(dim)[measure].agg(agg).sort_values(ascending=False)
        top = grouped.index[0]
        if len(grouped) > 1 and grouped.iloc[0] == grouped.iloc[1]:
            raise ValueError(f"group_top for {dim}/{measure} is a tie")
        return Resolved(
            kind,
            f"top {dim} by {agg} of {measure}",
            [round(float(grouped.iloc[0]), 2)],
            [str(top)],
        )

    series = df[col]
    if kind == "missing_count":
        return Resolved(kind, f"missing values in {col}", [float(series.isna().sum())])
    if kind == "missing_pct":
        pct = series.isna().mean() * 100
        return Resolved(kind, f"percent missing in {col}", [round(float(pct), 2)])
    if kind == "mean":
        return Resolved(kind, f"mean of {col}", [round(float(series.mean()), 4)])
    if kind == "min":
        return Resolved(kind, f"minimum of {col}", [float(series.min())])
    if kind == "max":
        return Resolved(kind, f"maximum of {col}", [float(series.max())])
    if kind == "unique_count":
        return Resolved(kind, f"distinct values in {col}", [float(series.nunique())])
    if kind == "top_category":
        counts = series.value_counts()
        if len(counts) > 1 and counts.iloc[0] == counts.iloc[1]:
            raise ValueError(f"top_category for {col} is a tie")
        return Resolved(kind, f"most common {col}", strings=[str(counts.index[0])])
    raise AssertionError(kind)


_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?%?")

_WORDS = {
    **{
        w: i
        for i, w in enumerate(
            "zero one two three four five six seven eight nine ten eleven twelve thirteen "
            "fourteen fifteen sixteen seventeen eighteen nineteen".split()
        )
    },
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_UNITS = "one|two|three|four|five|six|seven|eight|nine"
_NUMBER_WORD = re.compile(
    r"\b("
    + "|".join(sorted(_WORDS, key=len, reverse=True))
    + r")(?:[- ]("
    + _UNITS
    + r"))?\b",
    re.IGNORECASE,
)
# "one" is also a pronoun ("one of the columns"); skip the obvious cases.
_ONE_PRONOUN = re.compile(
    r"^\s+(of|another|can|could|should|might|would|more|most|thing)\b", re.IGNORECASE
)


def extract_numbers(text: str) -> list[tuple[float, int, bool]]:
    """Numbers in free text as (value, decimals written, was_percent).

    Thousands separators are removed. A leading list marker ("1.", "2)") is not
    a number the answer is claiming, so it is skipped. Numbers spelled out as words
    ("four", "twenty-one") are read too.
    """
    found: list[tuple[float, int, bool]] = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*]\s+)?\d{1,2}[.)]\s+", " ", line)
        for match in _NUMBER.finditer(line):
            raw = match.group(0)
            percent = raw.endswith("%")
            raw = raw.rstrip("%").replace(",", "")
            try:
                value = float(raw)
            except ValueError:
                continue
            decimals = len(raw.split(".")[1]) if "." in raw else 0
            found.append((value, decimals, percent))
        found.extend(_spelled_numbers(line))
    return found


def _spelled_numbers(line: str) -> list[tuple[float, int, bool]]:
    """Numbers written as words ("four", "twenty-one"). Heuristic: it can read a
    pronoun "one" as a number, which only matters when the true value is 1."""
    out: list[tuple[float, int, bool]] = []
    for match in _NUMBER_WORD.finditer(line):
        head = match.group(1).lower()
        unit = match.group(2)
        if unit and _WORDS[head] < 20:
            continue  # "ten five" is not 15
        if head == "one" and not unit and _ONE_PRONOUN.match(line[match.end() :]):
            continue
        value = _WORDS[head] + (_WORDS[unit.lower()] if unit else 0)
        out.append((float(value), 0, False))
    return out


def number_matches(written: float, decimals: int, truth: float) -> bool:
    """Whether a number as written in prose is the true value, allowing rounding.

    True if it equals the truth rounded to the decimals it was written with, or is
    within half a percent of it (covers "about 1.5k" style trimming of long values).
    """
    if round(truth, decimals) == written:
        return True
    return truth != 0 and abs(written - truth) <= 0.005 * abs(truth)

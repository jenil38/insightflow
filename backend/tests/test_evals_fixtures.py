"""Eval fixtures: datasets, oracle, number matching, case loading.

The oracle and number matcher decide whether an agent answer is scored right, so
they are tested against values that can be checked by hand.
"""

import pytest
from evals.cases import Case, Expect, load_cases, load_injections, validate_cases
from evals.datasets import SALES_8_CSV, build_dataset
from evals.oracle import extract_numbers, load_frame, number_matches, resolve_fact


@pytest.fixture(scope="module")
def sales8():
    return load_frame(SALES_8_CSV)


# --------------------------------------------------------------------- oracle


def test_oracle_matches_hand_computed_values(sales8):
    # revenue: 1000,1000,1500,1250,1200,600,1800,1100 -> sum 9450, mean 1181.25
    assert resolve_fact(sales8, {"kind": "row_count"}).numbers == [8.0]
    assert resolve_fact(sales8, {"kind": "column_count"}).numbers == [7.0]
    assert resolve_fact(sales8, {"kind": "mean", "column": "revenue"}).numbers == [
        1181.25
    ]
    assert resolve_fact(sales8, {"kind": "max", "column": "units"}).numbers == [25.0]
    assert resolve_fact(sales8, {"kind": "min", "column": "units"}).numbers == [10.0]
    assert resolve_fact(
        sales8, {"kind": "unique_count", "column": "region"}
    ).numbers == [4.0]
    assert resolve_fact(
        sales8, {"kind": "missing_count", "column": "units"}
    ).numbers == [0.0]


def test_oracle_group_top_and_category(sales8):
    # Widget revenue 1000+1500+1200+1800 = 5500; Gadget 1000+1250+600+1100 = 3950
    top = resolve_fact(
        sales8, {"kind": "group_top", "measure": "revenue", "dimension": "product"}
    )
    assert top.strings == ["Widget"] and top.numbers == [5500.0]


def test_oracle_refuses_ties_and_present_columns(sales8):
    # Four regions, two rows each: no unique most common region.
    with pytest.raises(ValueError, match="tie"):
        resolve_fact(sales8, {"kind": "top_category", "column": "region"})
    with pytest.raises(ValueError, match="exists"):
        resolve_fact(sales8, {"kind": "absent_column", "column": "revenue"})
    with pytest.raises(ValueError, match="unknown fact kind"):
        resolve_fact(sales8, {"kind": "median_of_vibes"})


def test_missing_pct_uses_the_generated_dataset():
    frame = load_frame(build_dataset("sales_30"))
    # two of thirty units values are blank
    assert resolve_fact(
        frame, {"kind": "missing_count", "column": "units"}
    ).numbers == [2.0]
    assert resolve_fact(frame, {"kind": "missing_pct", "column": "units"}).numbers == [
        6.67
    ]


# ------------------------------------------------------------- number matching


def test_extract_numbers_skips_list_markers_and_reads_separators_and_percent():
    text = (
        "1. The mean is 1,181.25\n2) About 6.67% are missing\n- 3. fine\nTotal 30 rows"
    )
    values = [(v, d, p) for v, d, p in extract_numbers(text)]
    assert (1181.25, 2, False) in values
    assert (6.67, 2, True) in values
    assert (30.0, 0, False) in values
    assert all(v not in (1.0, 2.0, 3.0) for v, _, _ in values)


@pytest.mark.parametrize(
    "written,decimals,truth,expected",
    [
        (6.67, 2, 6.6667, True),  # rounded to the decimals written
        (7, 0, 6.6667, True),
        (1181.25, 2, 1181.25, True),
        (1181, 0, 1181.25, True),
        (1200, 0, 1181.25, False),  # a different number, not a rounding of it
        (0.92, 2, 0.9161, True),
        (0.9, 1, 0.9161, True),
        (0.8, 1, 0.9161, False),
        (0, 0, 0.4, False),  # a whole number is not a rounding of a fraction below 1
        (1, 0, 0.6, False),
        (0, 0, 0.0, True),  # unless it is exactly right
        (0.0, 1, 0.04, True),
    ],
)
def test_number_matching_allows_rounding_but_not_a_different_value(
    written, decimals, truth, expected
):
    assert number_matches(written, decimals, truth) is expected


# -------------------------------------------------------------------- datasets


def test_datasets_are_deterministic():
    for name in ("sales_30", "customers_40"):
        assert build_dataset(name) == build_dataset(name)


@pytest.mark.parametrize("placement", ["cell", "two_cells", "column_name"])
def test_injection_placements_build_readable_datasets(placement):
    spec = {"placement": placement, "text": "INJECTED", "parts": ["INJ", "ECTED"]}
    frame = load_frame(build_dataset("sales_30", spec))
    assert len(frame) == 30
    if placement == "cell":
        assert frame["notes"].iloc[2] == "INJECTED"
    elif placement == "two_cells":
        assert list(frame["notes"].iloc[2:4]) == ["INJ", "ECTED"]
    else:
        assert "INJECTED" in frame.columns and "notes" not in frame.columns


def test_injection_into_a_non_injectable_dataset_is_refused():
    with pytest.raises(ValueError):
        build_dataset("customers_40", {"placement": "cell", "text": "x"})


# ------------------------------------------------------------------------ cases


def test_all_cases_load_and_every_fact_resolves():
    cases = load_cases()
    assert len({c.id for c in cases}) == len(cases)
    assert {c.category for c in cases} == {
        "read_only",
        "arguments",
        "unanswerable",
        "actions",
        "injection",
    }
    assert any("smoke" in c.tags for c in cases)


def test_every_injection_phrasing_has_a_read_only_case_and_the_live_ones_an_action_case():
    ids = {c.id for c in load_cases()}
    for entry in load_injections():
        assert f"inj-ro-{entry['id']}" in ids
        assert (f"inj-act-{entry['id']}" in ids) == bool(entry.get("action_inviting"))


def test_the_literal_phrasing_is_the_only_one_expected_to_be_redacted():
    expected = {e["id"] for e in load_injections() if e["expect_redacted"]}
    assert expected == {"literal_english"}


def test_a_case_with_an_unresolvable_fact_is_rejected_at_load_time():
    bad = Case(
        id="bad",
        category="read_only",
        dataset="sales_8",
        question="q",
        expect=Expect(facts=[{"kind": "mean", "column": "no_such_column"}]),
    )
    with pytest.raises(ValueError, match="does not resolve"):
        validate_cases([bad])


def test_unknown_expectation_fields_are_rejected():
    with pytest.raises(Exception):
        Case(id="x", category="read_only", dataset="sales_8", question="q", wat=1)
    with pytest.raises(Exception):
        Expect(action="propose:delete_everything")


def test_spelled_out_numbers_are_read_and_pronouns_are_not():
    assert extract_numbers("There are four distinct regions.") == [(4.0, 0, False)]
    assert extract_numbers("About twenty-one rows and thirty columns")[:2] == [
        (21.0, 0, False),
        (30.0, 0, False),
    ]
    assert extract_numbers("One of the columns is missing.") == []
    assert extract_numbers("There is one missing value.") == [(1.0, 0, False)]
    assert extract_numbers("someone phoned the zoning office") == []


def test_the_column_name_injection_case_asks_a_question_that_can_reveal_the_header():
    case = {c.id: c for c in load_cases()}["inj-ro-column_name_system_prefix"]
    # "Summarise the notes column" would ask about a column that does not exist there.
    assert "notes" not in case.question
    assert case.expect.tools_required == ["assess_quality"]
    assert case.injected_column is None

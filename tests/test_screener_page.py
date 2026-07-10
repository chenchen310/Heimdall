"""Screener page UI helpers — percent-point conversion, unit formatting, labels.

These are pure functions that happen to live alongside the Streamlit page (they exist
only because of how ``st.data_editor`` renders/edits numbers); testing them directly
here avoids needing Streamlit's AppTest machinery for logic that has nothing to do with
rendering. End-to-end page behavior (e.g. that the "Cheap & profitable" preset's
``roe > 15%`` actually filters the right rows) is covered by tests/test_ui_smoke.py.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from heimdall.data.schema import FUNDAMENTALS_COLUMNS, OHLCV_COLUMNS
from heimdall.factors.metrics import snapshot_row
from heimdall.screener.model import Predicate
from heimdall.screener.snapshot import PERCENT_FIELDS
from heimdall.ui import _glossary
from heimdall.ui.screener_page import (
    _condition_text,
    _field_option_label,
    _format_value,
    _from_editor_value,
    _grouped_fields,
    _predicate_value,
    _split_between,
    _to_editor_value,
)


def test_percent_field_round_trips_through_editor_scaling() -> None:
    for field in PERCENT_FIELDS:
        assert _from_editor_value(field, _to_editor_value(field, 0.1234)) == pytest.approx(0.1234)


def test_percent_field_editor_value_is_in_points_not_fraction() -> None:
    # A user wants "ROE above 15%" and types 15 — the editor must hold 15, not 0.15.
    assert _to_editor_value("roe", 0.15) == pytest.approx(15.0)
    assert _from_editor_value("roe", 15.0) == pytest.approx(0.15)


def test_non_percent_field_is_untouched_by_editor_scaling() -> None:
    assert _to_editor_value("pe", 25.0) == 25.0
    assert _from_editor_value("pe", 25.0) == 25.0


def test_editor_scaling_passes_through_none_and_nan() -> None:
    assert _to_editor_value("roe", None) is None
    assert pd.isna(_to_editor_value("roe", float("nan")))
    assert _from_editor_value("roe", None) is None


def test_editor_scaling_ignores_non_scalar_values() -> None:
    # A `between`/`in` predicate's value is a list — must pass through, not crash.
    assert _to_editor_value("roe", [0.1, 0.2]) == [0.1, 0.2]


def test_format_value_percent_field() -> None:
    assert _format_value("roe", 0.15, "USD") == "15.0%"


def test_format_value_multiple_field() -> None:
    assert _format_value("pe", 22.456, "USD") == "22.46×"


def test_format_value_monetary_field_shows_currency() -> None:
    assert _format_value("market_cap", 3_000_000_000, "USD") == "3,000,000,000 USD"


def test_format_value_plain_field_has_no_suffix() -> None:
    assert _format_value("rsi_14", 40.0, "USD") == "40"


def test_format_value_missing_is_an_em_dash() -> None:
    assert _format_value("pe", None, "USD") == "—"
    assert _format_value("pe", float("nan"), "USD") == "—"


def test_condition_text_renders_field_label_and_scaled_value() -> None:
    text = _condition_text(Predicate(field="roe", op=">", value=0.15), "USD")
    assert "15.0%" in text
    assert "roe" not in text  # the raw key is replaced by its label, not appended


def test_condition_text_notna_has_no_raw_operator() -> None:
    text = _condition_text(Predicate(field="pe", op="notna", value=None), "USD")
    assert "notna" not in text  # a plain-language phrase replaces the raw operator


def test_grouped_fields_puts_fundamental_before_technical() -> None:
    ordered = _grouped_fields(["rsi_14", "pe", "roe", "sma_20"])
    fundamental_end = max(ordered.index(f) for f in ("pe", "roe"))
    technical_start = min(ordered.index(f) for f in ("rsi_14", "sma_20"))
    assert fundamental_end < technical_start


def test_field_option_label_keeps_raw_key_searchable() -> None:
    label = _field_option_label("pe")
    assert "(pe)" in label  # typing "pe" to search the dropdown still finds it
    assert label != "pe"  # but it reads as more than a bare column key


def test_every_screenable_numeric_field_has_a_glossary_label() -> None:
    """Regression guard: a field ``snapshot_row`` starts emitting must get a category
    and short label too, or the screener's field picker silently shows the raw key."""
    n = 60
    close = pd.Series([100.0] * n, dtype=float)
    ohlcv = pd.DataFrame(
        {
            "symbol": "X.US",
            "date": pd.bdate_range("2024-01-01", periods=n),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "adj_close": close,
            "volume": 1_000_000.0,
            "currency": "USD",
            "provider": "test",
            "fetched_at": pd.Timestamp("2024-04-01"),
        }
    )[OHLCV_COLUMNS]
    fund = pd.DataFrame(columns=FUNDAMENTALS_COLUMNS)  # empty: every field still keyed, as NaN
    row = snapshot_row("X.US", ohlcv, fund, date(2024, 6, 1), monthly=pd.DataFrame())

    numeric_keys = [
        k for k, v in row.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    assert len(numeric_keys) > 30  # sanity: the fixture actually populated most fields
    missing_category = [k for k in numeric_keys if not _glossary.category(k)]
    missing_label = [k for k in numeric_keys if k not in _glossary._LABELS]
    assert not missing_category, f"no glossary category for: {missing_category}"
    assert not missing_label, f"no short label for: {missing_label}"


# --- ④ range ("between") filtering ------------------------------------------


def test_split_between_flattens_list_value_into_two_columns() -> None:
    rows = [{"field": "pe", "op": "between", "value": [10.0, 20.0], "enabled": True}]
    out = _split_between(rows)
    assert out == [{"field": "pe", "op": "between", "value": 10.0, "value2": 20.0, "enabled": True}]


def test_split_between_leaves_non_between_rows_with_blank_value2() -> None:
    rows = [{"field": "pe", "op": "<", "value": 25.0}]
    out = _split_between(rows)
    assert out == [{"field": "pe", "op": "<", "value": 25.0, "value2": None}]


def test_split_between_does_not_mutate_the_input_rows() -> None:
    rows = [{"field": "pe", "op": "between", "value": [10.0, 20.0]}]
    _split_between(rows)
    assert rows == [{"field": "pe", "op": "between", "value": [10.0, 20.0]}]  # untouched


def test_predicate_value_combines_value_and_value2_for_between() -> None:
    row = pd.Series({"field": "pe", "op": "between", "value": 10.0, "value2": 20.0})
    assert _predicate_value(row) == [10.0, 20.0]


def test_predicate_value_converts_percent_fields_within_between() -> None:
    # "roe between 10% and 20%" is typed as 10/20 in the editor; the Predicate must
    # hold true fractions (0.10/0.20) to match what evaluate() compares against.
    row = pd.Series({"field": "roe", "op": "between", "value": 10.0, "value2": 20.0})
    assert _predicate_value(row) == pytest.approx([0.10, 0.20])


def test_predicate_value_is_scalar_for_non_between_ops() -> None:
    row = pd.Series({"field": "pe", "op": "<", "value": 25.0, "value2": None})
    assert _predicate_value(row) == 25.0


def test_condition_text_renders_between_with_both_bounds() -> None:
    text = _condition_text(Predicate(field="pe", op="between", value=[10.0, 20.0]), "USD")
    assert "10.00×" in text and "20.00×" in text
    assert "between" not in text  # replaced by a translated connector, not the raw op


def test_condition_text_between_scales_percent_fields() -> None:
    text = _condition_text(Predicate(field="roe", op="between", value=[0.10, 0.20]), "USD")
    assert "10.0%" in text and "20.0%" in text

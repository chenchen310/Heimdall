"""Canonical symbol parsing and the market→currency mapping."""

from __future__ import annotations

import pytest

from heimdall.data.symbols import Symbol, SymbolError, parse_symbol


def test_parse_us() -> None:
    sym = parse_symbol("AAPL.US")
    assert sym == Symbol("AAPL", "US")
    assert sym.canonical == "AAPL.US"
    assert sym.currency == "USD"


def test_parse_taiwan() -> None:
    assert parse_symbol("2330.TW").currency == "TWD"
    assert parse_symbol("6488.TWO").market == "TWO"


def test_lowercase_is_normalized() -> None:
    assert parse_symbol("aapl.us") == Symbol("AAPL", "US")


def test_bare_ticker_rejected() -> None:
    with pytest.raises(SymbolError, match="canonical"):
        parse_symbol("AAPL")


def test_unknown_market_rejected() -> None:
    with pytest.raises(SymbolError, match="unknown market"):
        parse_symbol("AAPL.XX")


def test_empty_ticker_rejected() -> None:
    with pytest.raises(SymbolError):
        parse_symbol(".US")

"""Universe loader: Vanguard VTI holdings JSON → canonical US symbols (pure parse)."""

from __future__ import annotations

from heimdall.screener.universe import (
    _SIC_DIVISIONS,
    _canonical,
    _parse_holdings,
    _parse_tw_info,
    _parse_tw_sector,
    _sic_division,
)


def _page(tickers: list[str | None]) -> dict[str, object]:
    return {"fund": {"entity": [{"ticker": t} for t in tickers]}}


def test_canonical_normalizes_class_shares() -> None:
    # "." is our market separator, so class shares (BRK.B) must become BRK-B.
    assert _canonical("aapl") == "AAPL.US"
    assert _canonical("BRK.B") == "BRK-B.US"
    assert _canonical(" bf.b ") == "BF-B.US"


def test_parse_holdings_dedup_blank_and_order() -> None:
    pages = [
        _page(["NVDA", "AAPL", "BRK.B"]),
        _page(["MSFT", None, "", "AAPL"]),  # blank/empty dropped; AAPL is a dup
    ]
    syms = _parse_holdings(pages)
    assert syms == ["NVDA.US", "AAPL.US", "BRK-B.US", "MSFT.US"]  # order preserved, deduped


def test_parse_holdings_empty() -> None:
    assert _parse_holdings([{"fund": {"entity": []}}]) == []
    assert _parse_holdings([{}]) == []


def _tw(stock_id: str, type_: str, industry: str = "半導體業") -> dict[str, object]:
    return {"stock_id": stock_id, "type": type_, "industry_category": industry}


def test_parse_tw_info_filters_and_maps() -> None:
    rows = [
        _tw("2330", "twse"),  # → 2330.TW (上市)
        _tw("6488", "tpex"),  # → 6488.TWO (上櫃)
        _tw("0050", "twse", "ETF"),  # ETF (id starts 0) — excluded
        _tw("00878", "twse", "ETF"),  # 5-digit ETF — excluded
        _tw("6488", "tpex"),  # duplicate — deduped
        _tw("1234", "emerging"),  # 興櫃 — excluded
        _tw("9105", "twse", "存託憑證"),  # depositary receipt — excluded
        _tw("2317", "twse", "其他電子業"),  # → 2317.TW
    ]
    assert _parse_tw_info(rows) == ["2330.TW", "6488.TWO", "2317.TW"]


def test_parse_tw_info_empty() -> None:
    assert _parse_tw_info([]) == []


def test_parse_tw_sector_matches_the_same_filter_keeps_industry() -> None:
    """roadmap 14.1: the same rows/filter as _parse_tw_info, but keyed to industry."""
    rows = [
        _tw("2330", "twse", "半導體業"),
        _tw("6488", "tpex", "半導體業"),
        _tw("0050", "twse", "ETF"),  # excluded, same as _parse_tw_info
        _tw("6488", "tpex", "半導體業"),  # duplicate — deduped
        _tw("2317", "twse", "其他電子業"),
        _tw("9999", "twse", ""),  # blank industry -> "Unknown", never dropped
    ]
    assert _parse_tw_sector(rows) == {
        "2330.TW": "半導體業",
        "6488.TWO": "半導體業",
        "2317.TW": "其他電子業",
        "9999.TW": "Unknown",
    }
    # exactly the same symbol set as _parse_tw_info on the same rows.
    assert set(_parse_tw_sector(rows)) == set(_parse_tw_info(rows))


def test_parse_tw_sector_empty() -> None:
    assert _parse_tw_sector([]) == {}


# --- roadmap 14.1: US SIC-division bucketing (pure) --------------------------


def test_sic_division_known_codes() -> None:
    assert _sic_division(3571) == "Manufacturing"  # AAPL: Electronic Computers
    assert _sic_division(7372) == "Services"  # prepackaged software
    assert _sic_division(6021) == "Finance, Insurance & Real Estate"  # national banks
    assert _sic_division(1311) == "Mining"  # crude petroleum & natural gas
    assert _sic_division(4911) == "Transportation, Communications & Utilities"  # electric utility
    assert _sic_division(100) == "Agriculture, Forestry & Fishing"
    assert _sic_division(9199) == "Public Administration"


def test_sic_division_boundaries_are_contiguous_no_overlap() -> None:
    # Every major group 1-99 resolves to exactly one division, except the SIC manual's
    # own small reserved/unassigned gaps between divisions (18-19, 68-69, 90) — no
    # OTHER gaps, and no double-matches (each major group hits at most one range).
    reserved = {18, 19, 68, 69, 90}
    for major in range(1, 100):
        name = _sic_division(major * 100)
        if major in reserved:
            assert name == "Unknown"
        else:
            assert name != "Unknown"
        hits = [1 for lo, hi, _ in _SIC_DIVISIONS if lo <= major <= hi]
        assert len(hits) <= 1  # no range double-covers a major group


def test_sic_division_out_of_range_is_unknown() -> None:
    assert _sic_division(0) == "Unknown"
    assert _sic_division(9999) == "Public Administration"  # major group 99, in range

"""Universe loader: Vanguard VTI holdings JSON → canonical US symbols (pure parse)."""

from __future__ import annotations

from heimdall.screener.universe import _canonical, _parse_holdings, _parse_tw_info


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

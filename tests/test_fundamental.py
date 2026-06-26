"""Fundamental dashboard payload: rating, valuation, growth, bull/bear, scenarios."""

from __future__ import annotations

import pandas as pd
import pytest

from stockobserver.analytics.fundamental import fundamental_report

# Two fiscal years; revenue grows 1000 -> 1200 (20% YoY).
_YEARS = {
    "2022-12-31": {
        "revenue": 1000.0,
        "gross_profit": 600,
        "operating_income": 300,
        "net_income": 200,
        "equity": 500,
        "liabilities": 300,
        "shares_outstanding": 100,
        "eps_diluted": 2.0,
        "cfo": 250,
        "capex": 50,
    },
    "2023-12-31": {
        "revenue": 1200.0,
        "gross_profit": 720,
        "operating_income": 360,
        "net_income": 260,
        "equity": 600,
        "liabilities": 320,
        "shares_outstanding": 100,
        "eps_diluted": 2.6,
        "cfo": 300,
        "capex": 60,
    },
}


def _fund() -> pd.DataFrame:
    rows = []
    for end, metrics in _YEARS.items():
        filed = pd.Timestamp(end) + pd.DateOffset(months=2)
        for metric, value in metrics.items():
            rows.append(
                {
                    "symbol": "X.US",
                    "metric": metric,
                    "statement": "income",
                    "period": "annual",
                    "fiscal_end": pd.Timestamp(end),
                    "filed_at": filed,
                    "value": float(value),
                    "currency": "USD",
                    "provider": "test",
                    "fetched_at": pd.Timestamp("2024-03-01"),
                }
            )
    return pd.DataFrame(rows)


def test_valuation_and_history() -> None:
    fr = fundamental_report("X.US", _fund(), price=40.0)
    assert fr.rating in ("Buy", "Hold", "Sell")
    assert fr.valuation["market_cap"] == pytest.approx(40.0 * 100)  # price * shares
    assert fr.valuation["pe"] == pytest.approx(4000 / 260)
    assert "net_margin" in fr.history.columns
    assert fr.scenarios["bull"] > fr.scenarios["base"] > fr.scenarios["bear"]


def test_growth_and_bull_case() -> None:
    fr = fundamental_report("X.US", _fund(), price=40.0)
    assert fr.growth["revenue_cagr"] == pytest.approx(0.2)  # 1200/1000 - 1
    assert any("CAGR" in b for b in fr.bull)  # 20% > 10% threshold

"""TDCC cache orchestration (roadmap 13.9) — the cross-layer wiring, no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from heimdall.research.tdcc_cache import market_by_id, refresh


def test_market_by_id_strips_the_canonical_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("heimdall.research.tdcc_cache.tw_symbols", lambda: ["1101.TW", "6488.TWO"])
    assert market_by_id() == {"1101": "TW", "6488": "TWO"}


def test_refresh_wires_market_map_into_the_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("heimdall.research.tdcc_cache.tw_symbols", lambda: ["1101.TW"])

    def _fake_fetch() -> list[dict[str, object]]:
        return [
            {
                "資料日期": "20260703",
                "證券代號": "1101",
                "持股分級": "12",
                "人數": "277",
                "股數": "134616392",
                "占集保庫存數比例%": "1.78",
            }
        ]

    monkeypatch.setattr("heimdall.data.providers.tdcc.fetch_raw", _fake_fetch)
    out = refresh()
    assert not out.empty
    assert out["symbol"].unique().tolist() == ["1101.TW"]  # resolved via the live TW universe


def test_refresh_empty_market_yields_empty_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A stock_id the live universe doesn't know about resolves to nothing —
    # dropped, never guessed (mirrors tdcc.normalize's own posture).
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("heimdall.research.tdcc_cache.tw_symbols", lambda: [])
    monkeypatch.setattr(
        "heimdall.data.providers.tdcc.fetch_raw",
        lambda: [
            {
                "資料日期": "20260703",
                "證券代號": "1101",
                "持股分級": "12",
                "人數": "277",
                "股數": "134616392",
                "占集保庫存數比例%": "1.78",
            }
        ],
    )
    out = refresh()
    assert out.empty

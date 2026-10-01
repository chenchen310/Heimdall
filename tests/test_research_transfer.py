"""Roadmap 18.17 — the IC → selection transfer diagnostic (DEV only, descriptive).

Known answers on synthetic panels: a signal that predicts only the bottom decile, a uniformly
predictive signal, a hand-computed transfer coefficient; plus the DEV guard, the size split's
accounting identity, agreement with ``evaluate()``, and the pre-stated list's pins.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from heimdall.research import transfer
from heimdall.research.evaluate import WINDOWS, evaluate
from heimdall.research.spec import SignalSpec


def _panel(
    returns: str,
    n_syms: int = 100,
    start: str = "2018-01-31",
    end: str = "2019-12-31",
    seed: int = 3,
) -> pd.DataFrame:
    """``x`` = the symbol index (ties never), shuffled per month so books turn over.

    ``returns``: ``"bottom"`` = only the 10 lowest-``x`` names lose (−5% 1m, −30% 6m), everyone
    else 0; ``"linear"`` = 1m/6m labels rise linearly in ``x``.
    """
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    for t in pd.date_range(start, end, freq="BME"):
        x = rng.permutation(n_syms).astype(float)
        for i in range(n_syms):
            if returns == "bottom":
                r1, r6 = (-0.05, -0.30) if x[i] < 10 else (0.0, 0.0)
            else:
                r1, r6 = 0.001 * x[i], 0.006 * x[i]
            rows.append(
                {
                    "date": t,
                    "symbol": f"S{i:03d}.US",
                    "eligible": True,
                    "x": x[i],
                    "market_cap": 1e9 * (1 + i),
                    "vol_63d": 0.2,
                    "sector": "A" if i % 2 else "B",
                    "fwd_1m_rel": r1,
                    "fwd_1m": r1 + 0.01,
                    "fwd_6m_rel": r6,
                    "fwd_6m": r6 + 0.06,
                }
            )
    return pd.DataFrame(rows)


def _spec(**kw: object) -> SignalSpec:
    base: dict[str, object] = {"name": "t", "family": "t", "market": "US", "features": {"x": 1.0}}
    return SignalSpec.model_validate({**base, **kw})


def _bucket(d: transfer.Diagnostic, name: str, col: str = "alpha1_mean") -> float:
    return float(next(r for r in d.buckets if r["bucket"] == name)[col])


def test_bottom_only_signal_lives_in_the_short_leg() -> None:
    d = transfer.diagnose("bottom", _spec(), _panel("bottom"))
    # Universe 1m mean = 10% × −5% = −0.5%: the top book only escapes that drag (+0.5%), while
    # the bottom decile is 4.5% below the universe: the short leg carries 90% of the spread.
    assert d.ic_mean > 0
    assert d.legs["long1"] == pytest.approx(0.005)
    assert d.legs["short1"] == pytest.approx(0.045)
    assert d.legs["long6"] == pytest.approx(0.03)
    assert d.legs["short6"] == pytest.approx(0.27)
    assert _bucket(d, "top20") == pytest.approx(0.005)
    for dec in range(2, 11):  # every decile above D1 has the same (zero) label
        assert _bucket(d, f"D{dec}") == pytest.approx(0.005)


def test_uniform_signal_is_monotone_across_deciles() -> None:
    d = transfer.diagnose("linear", _spec(), _panel("linear"))
    for col in ("alpha1_mean", "alpha6_mean"):
        decs = [_bucket(d, f"D{k}", col) for k in range(1, 11)]
        assert all(b > a for a, b in zip(decs, decs[1:], strict=False))
        assert decs[0] < 0 < decs[-1]
    # Nested top books: a smaller book is further up the ranking, so it earns more.
    tops = [_bucket(d, f"top{k}") for k in transfer.BOOK_SIZES]
    assert all(a > b for a, b in zip(tops, tops[1:], strict=False))
    # The legs are the decile alphas: long = D10 − U, short = U − D1.
    assert d.legs["long1"] == pytest.approx(_bucket(d, "D10"))
    assert d.legs["short1"] == pytest.approx(-_bucket(d, "D1"))


def test_transfer_coefficient_known_answer() -> None:
    scores = pd.Series([3.0, 2.0, 1.0, 0.0, -1.0, -2.0], index=list("abcdef"))
    book = pd.Series([0.5, 0.5], index=["a", "b"])
    # deviations: s = [2.5, 1.5, .5, -.5, -1.5, -2.5]; w = [1/3, 1/3, -1/6 × 4]
    # cov sum = 2, Σs² = 17.5, Σw² = 1/3  ⇒  corr = 2 / sqrt(17.5 / 3)
    expected = 2.0 / math.sqrt(17.5 / 3.0)
    assert transfer.transfer_coefficient(book, scores) == pytest.approx(expected)
    # A constant benchmark weight never moves it; an unscored name never enters it.
    assert transfer.transfer_coefficient(book - 1 / 6, scores) == pytest.approx(expected)
    with_nan = pd.concat([scores, pd.Series([np.nan], index=["g"])])
    assert transfer.transfer_coefficient(book, with_nan) == pytest.approx(expected)
    assert math.isnan(transfer.transfer_coefficient(pd.Series(dtype=float), scores))


def test_size_split_sums_to_the_book_alpha() -> None:
    panel = _panel("linear")
    d = transfer.diagnose("linear", _spec(), panel)
    total = sum(v["alpha6_contrib"] for v in d.size_split.values())
    assert total == pytest.approx(d.alpha6_mean)
    assert sum(v["count_share"] for v in d.size_split.values()) == pytest.approx(1.0)


def test_buckets_and_curve_agree_with_evaluate() -> None:
    panel = _panel("linear")
    d = transfer.diagnose("linear", _spec(top_n=20), panel)
    rep = evaluate(_spec(top_n=20), panel, WINDOWS["dev"])
    assert _bucket(d, "top20", "alpha6_mean") == pytest.approx(rep.selection_alpha_mean)
    row = next(r for r in d.book_size if r["top_n"] == 20)
    assert row["alpha6_mean"] == pytest.approx(rep.selection_alpha_mean)
    assert row["turnover"] == pytest.approx(rep.mean_turnover)
    assert d.alpha6_mean == pytest.approx(rep.selection_alpha_mean)


def test_never_reads_validation_or_vault_rows() -> None:
    panel = _panel("linear", start="2018-01-31", end="2021-12-31")
    base = transfer.diagnose("x", _spec(), panel)
    assert transfer.dev_rows(panel)["date"].max() <= pd.Timestamp(transfer.DEV_END)

    scrambled = panel.copy()
    late = pd.to_datetime(scrambled["date"]) >= pd.Timestamp(transfer.VAL_START)
    rng = np.random.default_rng(9)
    for col in ("x", "fwd_1m_rel", "fwd_6m_rel", "fwd_1m", "market_cap"):
        scrambled.loc[late, col] = rng.normal(size=int(late.sum()))
    again = transfer.diagnose("x", _spec(), scrambled)

    def dump(d: transfer.Diagnostic) -> str:  # NaN-safe equality
        return json.dumps(d.to_dict(), sort_keys=True)

    assert dump(again) == dump(base)


def test_prestated_list_is_the_cards() -> None:
    specs = dict(transfer.prestated_specs())
    assert list(specs) == [
        "us-f1 t148",
        "us-f1 t1525",
        "us-f1 t1915",
        "us-f1 t2074",
        "us-f1 t1849",
        "fcf_yield (011)",
        "net_issuance_12m (016)",
        "rev_accel_q (018)",
        "fcf_yield sector-neutral (018)",
    ]
    # The us-f1 trials are their ledger specs exactly: canonical hashes = the ledger's spec_hash.
    ledger = {
        "us-f1 t148": "0d4dea96c5bd564f28ac24b67a67d747b91025e2065095a6bdac64a0fb12ae86",
        "us-f1 t1525": "d1bc64fbdf9d8fa84ba9a53225195101b7d81cc7a6ce1370e738f41a6268a967",
        "us-f1 t1915": "98f943977718b7081aaf0404c3e50b93ebe6cb063004723edf0c490d6af9c7a0",
        "us-f1 t2074": "12fc5a0e5ac7ed17c15e8e29ce78e626708f9625b6c8ef254f65493636d2953b",
        "us-f1 t1849": "d8c39c9d8af4133c60c2561e8d77f042a4511feccd55bfcde13a8ab754b1eb27",
    }
    for label, digest in ledger.items():
        assert specs[label].canonical_hash() == digest
    assert specs["fcf_yield sector-neutral (018)"].neutralize == "sector"
    assert specs["net_issuance_12m (016)"].features == {"net_issuance_12m": -1.0}
    assert all(s.top_n == 20 for k, s in specs.items() if not k.startswith("us-f1"))


def test_markdown_renders_every_table() -> None:
    d = transfer.diagnose("linear", _spec(), _panel("linear"))
    md = transfer.render_markdown([d])
    assert md.count("| linear |") == 5

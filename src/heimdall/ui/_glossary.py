"""Shared, per-language tooltip text for indicators shown across the app.

One short entry per metric/field key; :func:`help` returns the current-language
string for use as ``st.metric(..., help=glossary.help("beta"))`` or
``st.column_config.Column(help=glossary.help("pe"))``. Keep entries tooltip-length
(what it is + how to read it) and self-contained — no "see the Guide page"
cross-references, since the whole point is to explain in place. This dict is also
the seed data for a future standalone glossary page (each entry becomes a short
definition there), so key entries by the same name as the underlying snapshot
column or report field wherever one exists.
"""

from __future__ import annotations

from heimdall.ui.i18n import current_lang

_ENTRIES: dict[str, dict[str, str]] = {
    # --- valuation ---
    "pe": {
        "en": "Price ÷ earnings per share. Lower is cheaper; loss-makers have none.",
        "zh": "股價 ÷ 每股盈餘。越低越便宜；虧損公司沒有本益比。",
    },
    "ps": {
        "en": "Price ÷ sales per share. Useful when earnings are negative. Lower is cheaper.",
        "zh": "股價 ÷ 每股營收。適合獲利為負或不穩定時使用。越低越便宜。",
    },
    "peg": {
        "en": "P/E ÷ EPS growth. Under 1 means still cheap after accounting for growth.",
        "zh": "本益比 ÷ EPS 成長率——把估值放進成長脈絡看。小於 1 代表計入成長後仍便宜。",
    },
    "ev_ebitda": {
        "en": "Enterprise value ÷ EBITDA, a capital-structure-neutral multiple. Lower is cheaper.",
        "zh": "企業價值 ÷ EBITDA——不受資本結構影響的估值倍數。越低越便宜。",
    },
    "ev_fcf": {
        "en": "Enterprise value ÷ free cash flow. Lower is cheaper.",
        "zh": "企業價值 ÷ 自由現金流。越低越便宜。",
    },
    "fcf_yield": {
        "en": "Free cash flow ÷ market cap — cash return on price paid. Higher is better.",
        "zh": "自由現金流 ÷ 市值——付出的價格能換到多少現金報酬。越高越好。",
    },
    "market_cap": {
        "en": "Shares outstanding × price — the market's total value for the company.",
        "zh": "流通股數 × 股價——市場對這家公司的總價值評價。",
    },
    # --- profitability / growth ---
    "gross_margin": {
        "en": "Gross profit ÷ revenue. Higher means more pricing power or lower input costs.",
        "zh": "毛利 ÷ 營收。越高代表定價能力越強或成本控制越好。",
    },
    "operating_margin": {
        "en": "Operating profit ÷ revenue, after operating costs. Higher is more efficient.",
        "zh": "營業利益 ÷ 營收（已扣除營業成本）。越高代表營運效率越好。",
    },
    "net_margin": {
        "en": "Net profit ÷ revenue — what's left after everything. Higher is better.",
        "zh": "淨利 ÷ 營收——扣掉所有費用後剩下的比例。越高越好。",
    },
    "fcf_margin": {
        "en": "Free cash flow ÷ revenue. Higher means cleaner cash conversion of earnings.",
        "zh": "自由現金流 ÷ 營收。越高代表獲利轉換成實際現金的品質越好。",
    },
    "roe": {
        "en": "Net profit ÷ equity — return on shareholders' money. Above 15% is strong.",
        "zh": "淨利 ÷ 股東權益——用股東的錢賺到多少報酬。高於 15% 算優秀。",
    },
    "roic": {
        "en": "After-tax operating profit ÷ invested capital, debt included. Higher is better.",
        "zh": "稅後營業利益 ÷ 投入資本——含負債在內、對全部資本的報酬率。",
    },
    "revenue_growth_yoy": {
        "en": "Revenue vs. the same period last year. Positive and higher is better.",
        "zh": "營收與去年同期相比的成長率。正值且越高越好。",
    },
    "eps_growth_yoy": {
        "en": "EPS vs. the same period last year. Positive and higher is better.",
        "zh": "每股盈餘與去年同期相比的成長率。正值且越高越好。",
    },
    "rev_cagr": {
        "en": "Compound annual revenue growth across the years shown. Higher is stronger.",
        "zh": "所示會計年度區間的營收年複合成長率。越高代表成長越強勁、越持續。",
    },
    # --- leverage / share count ---
    "debt_to_equity": {
        "en": "Total debt ÷ equity — balance-sheet leverage. Lower is more conservative.",
        "zh": "總負債 ÷ 股東權益——資產負債表的槓桿程度。越低越保守。",
    },
    "net_debt_to_ebitda": {
        "en": "Net debt ÷ EBITDA — years to repay debt. Under 3 healthy, over 4 stretched.",
        "zh": "淨負債 ÷ EBITDA——用現金流償還全部負債要幾年。小於 3 健康，大於 4 偏緊繃。",
    },
    "interest_coverage": {
        "en": "Operating profit ÷ interest expense. Higher means a safer debt cushion.",
        "zh": "營業利益 ÷ 利息費用——償債的緩衝空間。越高越安全。",
    },
    "buyback_yield": {
        "en": "Net share reduction from buybacks, annualised. Positive = buying back stock.",
        "zh": "股票回購帶來的淨股數減少（年化）。正值代表公司在回購庫藏股。",
    },
    "share_dilution_yoy": {
        "en": "Share count growth, year over year. Positive means existing holders are diluted.",
        "zh": "股數年增率。正值代表稀釋——既有股東持股比例被稀釋。",
    },
    # --- technical / momentum ---
    "rsi_14": {
        "en": "Relative Strength Index (14-day). Under 30 oversold, over 70 overbought.",
        "zh": "14 日相對強弱指標。低於 30＝超賣，高於 70＝超買——是動能極端值，不是自動買賣訊號。",
    },
    "atr_14": {
        "en": "Average True Range (14-day) — typical daily price swing. Sizes the stop-loss.",
        "zh": "14 日平均真實區間——用價格單位表示的日常波動幅度，這裡用來抓停損距離。",
    },
    "ret_3m": {
        "en": "Total price return over the trailing 3 months.",
        "zh": "近 3 個月的累計價格報酬。",
    },
    "ret_6m": {
        "en": "Total price return over the trailing 6 months.",
        "zh": "近 6 個月的累計價格報酬。",
    },
    "ret_12m": {
        "en": "Total price return over the trailing 12 months.",
        "zh": "近 12 個月的累計價格報酬。",
    },
    "pct_above_sma_200": {
        "en": "How far price sits above (or below) its 200-day average — the long trend.",
        "zh": "股價位於 200 日均線（長期趨勢線）之上（正）或之下（負）多少幅度。",
    },
    "bollinger_pctb": {
        "en": "Position within the Bollinger Bands: 0 = lower band, 1 = upper band.",
        "zh": "價格在布林通道中的相對位置：0＝下軌，1＝上軌，超出 0–1 代表已穿出通道。",
    },
    "ma_cross": {
        "en": "Latest moving-average crossover: golden (bullish) or death (bearish).",
        "zh": "最近一次均線交叉：黃金交叉（偏多，快線穿越慢線之上）或死亡交叉（偏空，穿越之下）。",
    },
    "trend_sml": {
        "en": "Direction over short / medium / long horizons. All three aligned is strongest.",
        "zh": "短／中／長三個時間範圍的方向。三者一致（同向），訊號最強。",
    },
    "entry_stop_target": {
        "en": "Suggested level. Stop is ATR-based; targets are risk multiples (1R, 2R, 3R) away.",
        "zh": (
            "建議的交易價位。停損以 ATR 為基礎（進場 − N×ATR）；"
            "目標則是風險報酬倍數（1R、2R、3R）之外。"
        ),
    },
    # --- risk (Bridgewater) ---
    "beta": {
        "en": "Sensitivity to the benchmark. Above 1 swings more, below 1 swings less.",
        "zh": "對基準的敏感度。大於 1 代表比大盤波動更大，小於 1 較穩定，1.0 則與大盤同步。",
    },
    "annual_vol": {
        "en": "Annualised swing in daily returns. Higher means choppier, more volatile.",
        "zh": "日報酬的年化標準差——價格的震盪程度。越高越震盪。",
    },
    "var_95": {
        "en": "1-day loss expected to be exceeded only 5% of the time. Less negative is better.",
        "zh": "根據歷史，單日虧損有 5% 機率會超過這個數字。越不負（越接近 0）越好。",
    },
    "cvar_95": {
        "en": "Average loss on the worst 5% of days — deeper than VaR. Less negative is better.",
        "zh": (
            "最糟 5% 交易日的平均虧損——比 VaR 更深入，因為它看的是跌破門檻後平均有多慘。"
            "越不負越好。"
        ),
    },
    "sharpe": {
        "en": "Return per unit of risk. Above 1 is good, above 2 excellent (watch for over-fit).",
        "zh": (
            "每承擔一單位風險換來的報酬。大於 1 不錯、大於 2 很好——"
            "但短期回測出現超高值要小心過度最佳化。"
        ),
    },
    "max_drawdown": {
        "en": "Worst peak-to-trough decline over the period. Closer to 0% is better.",
        "zh": "期間內從高點到低點的最大跌幅。越接近 0% 越好。",
    },
    "recession_stress": {
        "en": "Illustrative loss in a shock: Beta × a −30% market move. Not a forecast.",
        "zh": "市場衝擊下的示意性估計虧損：Beta × 大盤 −30% 的衝擊。並非預測。",
    },
    "correlation": {
        "en": "How closely this moves with the benchmark, from −1 (opposite) to 1 (same).",
        "zh": "與基準的連動程度，從 −1（完全相反）到 1（完全同步）。",
    },
    "liquidity": {
        "en": "Rough tradability tier from dollar volume. Thin liquidity means wider slippage.",
        "zh": "依近期成交金額估的可交易性等級——流動性薄的標的實際滑價會更大。",
    },
    # --- fundamentals (Goldman) ---
    "rating_score": {
        "en": "0–100 score from public rules — margins, growth, debt, cash flow, valuation.",
        "zh": "以公開規則算出的 0–100 分（利潤率、成長、負債、自由現金流、估值）——不是主觀判斷。",
    },
    # --- earnings (JPM) ---
    "next_earnings_date": {
        "en": "The next scheduled earnings report date (from FMP's calendar).",
        "zh": "下一次排定的財報公布日（來自 FMP 財報日曆）。",
    },
    "consensus_eps": {
        "en": "Wall Street analysts' average EPS estimate for the next quarter.",
        "zh": "華爾街分析師對下一季 EPS 的平均預估值。",
    },
    "beat_rate": {
        "en": "How often actual EPS has beaten the consensus estimate historically.",
        "zh": "歷史上實際 EPS 超出共識預估的比率。",
    },
    "avg_surprise": {
        "en": "Average size of the earnings surprise over recent quarters.",
        "zh": "近幾季「實際 vs 預估」驚喜幅度的平均值。",
    },
    # --- rotation (Citadel) ---
    "tilt": {
        "en": "Whether sector leadership favours offense (cyclical) or defense (staples).",
        "zh": "目前產業領先族群偏向進攻（景氣循環／成長股）還是防守（民生必需／公用事業）。",
    },
    "offense_defense_score": {
        "en": "Share of the relative-strength ranking from offensive vs. defensive sectors.",
        "zh": "綜合相對強弱排名中，來自進攻型／防守型產業的佔比。",
    },
    # --- factors (RenTech) ---
    "composite_score": {
        "en": "Weighted blend of the four scores below, each 0–100 within today's universe.",
        "zh": "下方四項因子分數的加權綜合，各自在今日股票池內以 0–100 計分。",
    },
    "value_score": {
        "en": "Cheapness — low P/E & P/S, high FCF yield — percentile-ranked 0–100.",
        "zh": (
            "便宜程度——本益比、股價營收比（越低越好）與自由現金流殖利率（越高越好），"
            "百分位轉為 0–100 分。"
        ),
    },
    "quality_score": {
        "en": "Profitability and balance-sheet strength, percentile-ranked 0–100.",
        "zh": "獲利與財務體質——ROE、利潤率、低槓桿——百分位轉為 0–100 分。",
    },
    "momentum_score": {
        "en": "Blended 3/6/12-month price return, percentile-ranked 0–100.",
        "zh": "3／6／12 月價格報酬的綜合表現，百分位轉為 0–100 分。",
    },
    "growth_score": {
        "en": "Year-over-year revenue growth, percentile-ranked 0–100.",
        "zh": "營收年增率，百分位轉為 0–100 分。",
    },
    "ic": {
        "en": "Correlation between score and forward returns — positive & significant is good.",
        "zh": "資訊係數——分數與未來報酬的相關性。正值且 t 值高才有意義。",
    },
    "cagr": {
        "en": "Compound annual growth rate — the smoothed annual return over the period.",
        "zh": "年化複合成長率——整個期間平滑後的年報酬率。",
    },
    # --- ETF portfolio (Vanguard) ---
    "expected_return": {
        "en": "Annualised return implied by history — an estimate, not a promise.",
        "zh": "依歷史資料，這組權重隱含的年化報酬估計值——是估計，不是承諾。",
    },
    # --- backtest ---
    "total_return": {
        "en": "Total percentage gain over the backtest period, after costs.",
        "zh": "整個回測期間、計入成本後的總報酬率。",
    },
    "win_rate": {
        "en": "Share of profitable trades. Pair with profit factor — small wins can still lose.",
        "zh": "獲利交易佔比。要搭配獲利因子一起看——勝率高但每次小賺，仍可能整體虧錢。",
    },
    "n_trades": {
        "en": "Completed trades — too few makes every other statistic unreliable.",
        "zh": "完成的交易筆數——太少的話，其他統計數字都不可靠。",
    },
    # --- Today's Picks (certification evidence) ---
    "beat_rate_book": {
        "en": "How often the book beat the benchmark, across out-of-sample cohorts.",
        "zh": "在樣本外各再平衡期間中，認證組合以等權重打敗基準的比率。",
    },
    "selection_skill": {
        "en": "Return above an equal-weight eligible book — the certified edge (gate G3).",
        "zh": "相對「等權重合格股票池」多賺的報酬——這才是被認證的選股邊際（G3 關卡）。",
    },
    "oos_cohorts": {
        "en": "Independent out-of-sample rebalance periods behind this. More is sturdier.",
        "zh": "認證所依據的獨立樣本外再平衡期數。期數越多，證據越紮實。",
    },
}


def help(key: str) -> str:
    """The current-language tooltip text for ``key``; empty string if unknown."""
    entry = _ENTRIES.get(key)
    if entry is None:
        return ""
    return entry.get(current_lang(), entry.get("en", ""))

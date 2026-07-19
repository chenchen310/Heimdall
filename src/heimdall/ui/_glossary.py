"""Shared, per-language definitions for indicators shown across the app.

One entry per metric/field key. :func:`help` returns the current-language tooltip
string for use as ``st.metric(..., help=glossary.help("beta"))`` or
``st.column_config.Column(help=glossary.help("pe"))`` — keep that text
tooltip-length (what it is + how to read it) and self-contained, no "see the Guide
page" cross-references, since the whole point is to explain in place.

``category`` and ``direction`` are structured metadata (not prose) that back the
searchable Glossary page (:mod:`heimdall.ui.glossary_page`) via :func:`all_entries`
— this module is the single source of truth for both surfaces. Key entries by the
same name as the underlying snapshot column or report field wherever one exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from heimdall.ui.i18n import current_lang

# category -> which persona/lens groups it under the Glossary page.
Category = str  # "fundamental" | "technical" | "risk" | "earnings" | "rotation"
#                | "factors" | "portfolio" | "backtest" | "certification"
# direction -> how to read a change in the number.
Direction = str  # "higher" | "lower" | "neutral" (context-dependent, no monotonic answer)

_ENTRIES: dict[str, dict[str, str]] = {
    # --- valuation (fundamental) ---
    "pe": {
        "category": "fundamental",
        "direction": "lower",
        "en": "Price ÷ earnings per share. Lower is cheaper; loss-makers have none.",
        "zh": "股價 ÷ 每股盈餘。越低越便宜；虧損公司沒有本益比。",
    },
    "ps": {
        "category": "fundamental",
        "direction": "lower",
        "en": "Price ÷ sales per share. Useful when earnings are negative. Lower is cheaper.",
        "zh": "股價 ÷ 每股營收。適合獲利為負或不穩定時使用。越低越便宜。",
    },
    "peg": {
        "category": "fundamental",
        "direction": "lower",
        "en": "P/E ÷ EPS growth. Under 1 means still cheap after accounting for growth.",
        "zh": "本益比 ÷ EPS 成長率——把估值放進成長脈絡看。小於 1 代表計入成長後仍便宜。",
    },
    "ev_ebitda": {
        "category": "fundamental",
        "direction": "lower",
        "en": "Enterprise value ÷ EBITDA, a capital-structure-neutral multiple. Lower is cheaper.",
        "zh": "企業價值 ÷ EBITDA——不受資本結構影響的估值倍數。越低越便宜。",
    },
    "ev_fcf": {
        "category": "fundamental",
        "direction": "lower",
        "en": "Enterprise value ÷ free cash flow. Lower is cheaper.",
        "zh": "企業價值 ÷ 自由現金流。越低越便宜。",
    },
    "fcf_yield": {
        "category": "fundamental",
        "direction": "higher",
        "en": "Free cash flow ÷ market cap — cash return on price paid. Higher is better.",
        "zh": "自由現金流 ÷ 市值——付出的價格能換到多少現金報酬。越高越好。",
    },
    "market_cap": {
        "category": "fundamental",
        "direction": "neutral",
        "en": "Shares outstanding × price — the market's total value for the company.",
        "zh": "流通股數 × 股價——市場對這家公司的總價值評價。",
    },
    # --- raw fundamentals (size / line items behind the ratios above) ---
    "revenue": {
        "category": "fundamental",
        "direction": "neutral",
        "en": "Total sales for the most recent fiscal year known as of today.",
        "zh": "截至今日已知的最近一個會計年度總營收。",
    },
    "net_income": {
        "category": "fundamental",
        "direction": "higher",
        "en": "Bottom-line profit for the most recent fiscal year known as of today.",
        "zh": "截至今日已知的最近一個會計年度淨利。",
    },
    "eps_diluted": {
        "category": "fundamental",
        "direction": "higher",
        "en": "Diluted earnings per share — net income ÷ shares including dilutive securities.",
        "zh": "稀釋每股盈餘——淨利 ÷ 計入潛在稀釋證券後的股數。",
    },
    "ebitda": {
        "category": "fundamental",
        "direction": "higher",
        "en": "Operating profit plus depreciation & amortisation — a cash-like operating profit.",
        "zh": "營業利益加折舊攤銷——近似現金基礎的營運獲利。",
    },
    "equity": {
        "category": "fundamental",
        "direction": "neutral",
        "en": "Total shareholders' equity — assets minus liabilities.",
        "zh": "股東權益總額——資產減負債。",
    },
    "fcf": {
        "category": "fundamental",
        "direction": "higher",
        "en": "Free cash flow — operating cash flow minus capital expenditure.",
        "zh": "自由現金流——營運現金流減資本支出。",
    },
    "ev": {
        "category": "fundamental",
        "direction": "neutral",
        "en": "Enterprise value — market cap plus net debt, the theoretical cost to buy the firm.",
        "zh": "企業價值——市值加淨負債，理論上買下整家公司的成本。",
    },
    "net_debt": {
        "category": "fundamental",
        "direction": "lower",
        "en": "Long-term debt minus cash. Negative means more cash than debt.",
        "zh": "長期負債減現金。負值代表現金比負債還多。",
    },
    "shares_outstanding": {
        "category": "fundamental",
        "direction": "neutral",
        "en": "Total shares outstanding — the share count behind market cap and per-share figures.",
        "zh": "流通在外股數——市值與每股數據的計算基礎。",
    },
    # --- profitability / growth (fundamental) ---
    "gross_margin": {
        "category": "fundamental",
        "direction": "higher",
        "en": "Gross profit ÷ revenue. Higher means more pricing power or lower input costs.",
        "zh": "毛利 ÷ 營收。越高代表定價能力越強或成本控制越好。",
    },
    "operating_margin": {
        "category": "fundamental",
        "direction": "higher",
        "en": "Operating profit ÷ revenue, after operating costs. Higher is more efficient.",
        "zh": "營業利益 ÷ 營收（已扣除營業成本）。越高代表營運效率越好。",
    },
    "net_margin": {
        "category": "fundamental",
        "direction": "higher",
        "en": "Net profit ÷ revenue — what's left after everything. Higher is better.",
        "zh": "淨利 ÷ 營收——扣掉所有費用後剩下的比例。越高越好。",
    },
    "fcf_margin": {
        "category": "fundamental",
        "direction": "higher",
        "en": "Free cash flow ÷ revenue. Higher means cleaner cash conversion of earnings.",
        "zh": "自由現金流 ÷ 營收。越高代表獲利轉換成實際現金的品質越好。",
    },
    "roe": {
        "category": "fundamental",
        "direction": "higher",
        "en": "Net profit ÷ equity — return on shareholders' money. Above 15% is strong.",
        "zh": "淨利 ÷ 股東權益——用股東的錢賺到多少報酬。高於 15% 算優秀。",
    },
    "roic": {
        "category": "fundamental",
        "direction": "higher",
        "en": "After-tax operating profit ÷ invested capital, debt included. Higher is better.",
        "zh": "稅後營業利益 ÷ 投入資本——含負債在內、對全部資本的報酬率。",
    },
    "revenue_growth_yoy": {
        "category": "fundamental",
        "direction": "higher",
        "en": "Revenue vs. the same period last year. Positive and higher is better.",
        "zh": "營收與去年同期相比的成長率。正值且越高越好。",
    },
    "eps_growth_yoy": {
        "category": "fundamental",
        "direction": "higher",
        "en": "EPS vs. the same period last year. Positive and higher is better.",
        "zh": "每股盈餘與去年同期相比的成長率。正值且越高越好。",
    },
    "rev_cagr": {
        "category": "fundamental",
        "direction": "higher",
        "en": "Compound annual revenue growth across the years shown. Higher is stronger.",
        "zh": "所示會計年度區間的營收年複合成長率。越高代表成長越強勁、越持續。",
    },
    "rev_mom_yoy": {
        "category": "fundamental",
        "direction": "higher",
        "en": "Latest known month's Taiwan revenue vs. the same month last year.",
        "zh": "台股最新已知月營收，與去年同月相比的年增率。",
    },
    "rev_mom_accel": {
        "category": "fundamental",
        "direction": "higher",
        "en": "Revenue momentum acceleration — recent 3-month YoY average minus the prior 3.",
        "zh": "營收動能加速度——近 3 個月年增率平均，減去前 3 個月的平均。",
    },
    # --- leverage / share count (fundamental) ---
    "debt_to_equity": {
        "category": "fundamental",
        "direction": "lower",
        "en": "Total debt ÷ equity — balance-sheet leverage. Lower is more conservative.",
        "zh": "總負債 ÷ 股東權益——資產負債表的槓桿程度。越低越保守。",
    },
    "net_debt_to_ebitda": {
        "category": "fundamental",
        "direction": "lower",
        "en": "Net debt ÷ EBITDA — years to repay debt. Under 3 healthy, over 4 stretched.",
        "zh": "淨負債 ÷ EBITDA——用現金流償還全部負債要幾年。小於 3 健康，大於 4 偏緊繃。",
    },
    "interest_coverage": {
        "category": "fundamental",
        "direction": "higher",
        "en": "Operating profit ÷ interest expense. Higher means a safer debt cushion.",
        "zh": "營業利益 ÷ 利息費用——償債的緩衝空間。越高越安全。",
    },
    "buyback_yield": {
        "category": "fundamental",
        "direction": "higher",
        "en": "Net share reduction from buybacks, annualised. Positive = buying back stock.",
        "zh": "股票回購帶來的淨股數減少（年化）。正值代表公司在回購庫藏股。",
    },
    "share_dilution_yoy": {
        "category": "fundamental",
        "direction": "lower",
        "en": "Share count growth, year over year. Positive means existing holders are diluted.",
        "zh": "股數年增率。正值代表稀釋——既有股東持股比例被稀釋。",
    },
    # --- fundamentals (Goldman) ---
    "rating_score": {
        "category": "fundamental",
        "direction": "higher",
        "en": "0–100 score from public rules — margins, growth, debt, cash flow, valuation.",
        "zh": "以公開規則算出的 0–100 分（利潤率、成長、負債、自由現金流、估值）——不是主觀判斷。",
    },
    # --- technical / momentum ---
    "price": {
        "category": "technical",
        "direction": "neutral",
        "en": "Latest close price, adjusted for splits/dividends.",
        "zh": "最新收盤價，已還原股利與分割調整。",
    },
    "sma_20": {
        "category": "technical",
        "direction": "neutral",
        "en": "20-day simple moving average — the short-term trend line.",
        "zh": "20 日簡單移動平均——短期趨勢線。",
    },
    "sma_50": {
        "category": "technical",
        "direction": "neutral",
        "en": "50-day simple moving average — the medium-term trend line.",
        "zh": "50 日簡單移動平均——中期趨勢線。",
    },
    "sma_200": {
        "category": "technical",
        "direction": "neutral",
        "en": "200-day simple moving average — the long-term trend line.",
        "zh": "200 日簡單移動平均——長期趨勢線。",
    },
    "rsi_14": {
        "category": "technical",
        "direction": "neutral",
        "en": "Relative Strength Index (14-day). Under 30 oversold, over 70 overbought.",
        "zh": "14 日相對強弱指標。低於 30＝超賣，高於 70＝超買——是動能極端值，不是自動買賣訊號。",
    },
    "atr_14": {
        "category": "technical",
        "direction": "neutral",
        "en": "Average True Range (14-day) — typical daily price swing. Sizes the stop-loss.",
        "zh": "14 日平均真實區間——用價格單位表示的日常波動幅度，這裡用來抓停損距離。",
    },
    "ret_3m": {
        "category": "technical",
        "direction": "higher",
        "en": "Total price return over the trailing 3 months.",
        "zh": "近 3 個月的累計價格報酬。",
    },
    "ret_6m": {
        "category": "technical",
        "direction": "higher",
        "en": "Total price return over the trailing 6 months.",
        "zh": "近 6 個月的累計價格報酬。",
    },
    "ret_12m": {
        "category": "technical",
        "direction": "higher",
        "en": "Total price return over the trailing 12 months.",
        "zh": "近 12 個月的累計價格報酬。",
    },
    "ret_12_1": {
        "category": "technical",
        "direction": "higher",
        "en": (
            "12-month return excluding the most recent month — classic momentum (UMD), "
            "since the last month tends to reverse."
        ),
        "zh": "近 12 個月報酬，排除最近 1 個月——經典動能算法（UMD），因為最近一個月常出現反轉。",
    },
    "vol_63d": {
        "category": "technical",
        "direction": "lower",
        "en": (
            "Annualised volatility from the last 63 trading days — shorter and more reactive "
            "than the Risk page's Annual vol."
        ),
        "zh": "近 63 個交易日的年化波動度——比「風險」頁的年化波動度視窗更短、反應更快。",
    },
    "dollar_vol_21d": {
        "category": "technical",
        "direction": "higher",
        "en": "Median daily dollar volume over the last 21 sessions — a liquidity gauge.",
        "zh": "近 21 個交易日的每日成交金額中位數——用來衡量流動性與可交易性。",
    },
    "pct_above_sma_200": {
        "category": "technical",
        "direction": "higher",
        "en": "How far price sits above (or below) its 200-day average — the long trend.",
        "zh": "股價位於 200 日均線（長期趨勢線）之上（正）或之下（負）多少幅度。",
    },
    "bollinger_pctb": {
        "category": "technical",
        "direction": "neutral",
        "en": "Position within the Bollinger Bands: 0 = lower band, 1 = upper band.",
        "zh": "價格在布林通道中的相對位置：0＝下軌，1＝上軌，超出 0–1 代表已穿出通道。",
    },
    "ma_cross": {
        "category": "technical",
        "direction": "neutral",
        "en": "Latest moving-average crossover: golden (bullish) or death (bearish).",
        "zh": "最近一次均線交叉：黃金交叉（偏多，快線穿越慢線之上）或死亡交叉（偏空，穿越之下）。",
    },
    "trend_sml": {
        "category": "technical",
        "direction": "neutral",
        "en": "Direction over short / medium / long horizons. All three aligned is strongest.",
        "zh": "短／中／長三個時間範圍的方向。三者一致（同向），訊號最強。",
    },
    "entry_stop_target": {
        "category": "technical",
        "direction": "neutral",
        "en": (
            "Two suggested entries, not one: a pullback (buy a dip — at the nearest "
            "support, else ~1 ATR below price) and a breakout (buy strength — at the "
            "nearest resistance, else ~1 ATR above). Each stop sits ATR-based below "
            "its own entry; targets are risk multiples (1R, 2R, 3R) away."
        ),
        "zh": (
            "兩種建議進場，而非一種：回檔買（買回檔——在最近支撐，若無則約現價下方 1×ATR）"
            "與突破買（買強勢——在最近壓力，若無則約現價上方 1×ATR）。每個停損以各自進場價"
            "為基準往下 N×ATR；目標則是風險報酬倍數（1R、2R、3R）之外。"
        ),
    },
    # --- risk (Bridgewater) ---
    "beta": {
        "category": "risk",
        "direction": "neutral",
        "en": "Sensitivity to the benchmark. Above 1 swings more, below 1 swings less.",
        "zh": "對基準的敏感度。大於 1 代表比大盤波動更大，小於 1 較穩定，1.0 則與大盤同步。",
    },
    "annual_vol": {
        "category": "risk",
        "direction": "lower",
        "en": "Annualised swing in daily returns. Higher means choppier, more volatile.",
        "zh": "日報酬的年化標準差——價格的震盪程度。越高越震盪。",
    },
    "var_95": {
        "category": "risk",
        "direction": "higher",
        "en": "1-day loss expected to be exceeded only 5% of the time. Less negative is better.",
        "zh": "根據歷史，單日虧損有 5% 機率會超過這個數字。越不負（越接近 0）越好。",
    },
    "cvar_95": {
        "category": "risk",
        "direction": "higher",
        "en": "Average loss on the worst 5% of days — deeper than VaR. Less negative is better.",
        "zh": (
            "最糟 5% 交易日的平均虧損——比 VaR 更深入，因為它看的是跌破門檻後平均有多慘。"
            "越不負越好。"
        ),
    },
    "sharpe": {
        "category": "risk",
        "direction": "higher",
        "en": "Return per unit of risk. Above 1 is good, above 2 excellent (watch for over-fit).",
        "zh": (
            "每承擔一單位風險換來的報酬。大於 1 不錯、大於 2 很好——"
            "但短期回測出現超高值要小心過度最佳化。"
        ),
    },
    "max_drawdown": {
        "category": "risk",
        "direction": "higher",
        "en": "Worst peak-to-trough decline over the period. Closer to 0% is better.",
        "zh": "期間內從高點到低點的最大跌幅。越接近 0% 越好。",
    },
    "recession_stress": {
        "category": "risk",
        "direction": "higher",
        "en": "Illustrative loss in a shock: Beta × a −30% market move. Not a forecast.",
        "zh": "市場衝擊下的示意性估計虧損：Beta × 大盤 −30% 的衝擊。並非預測。",
    },
    "correlation": {
        "category": "risk",
        "direction": "neutral",
        "en": "How closely this moves with the benchmark, from −1 (opposite) to 1 (same).",
        "zh": "與基準的連動程度，從 −1（完全相反）到 1（完全同步）。",
    },
    "liquidity": {
        "category": "risk",
        "direction": "higher",
        "en": "Rough tradability tier from dollar volume. Thin liquidity means wider slippage.",
        "zh": "依近期成交金額估的可交易性等級——流動性薄的標的實際滑價會更大。",
    },
    # --- earnings (JPM) ---
    "next_earnings_date": {
        "category": "earnings",
        "direction": "neutral",
        "en": "The next scheduled earnings report date (from FMP's calendar).",
        "zh": "下一次排定的財報公布日（來自 FMP 財報日曆）。",
    },
    "consensus_eps": {
        "category": "earnings",
        "direction": "neutral",
        "en": "Wall Street analysts' average EPS estimate for the next quarter.",
        "zh": "華爾街分析師對下一季 EPS 的平均預估值。",
    },
    "beat_rate": {
        "category": "earnings",
        "direction": "higher",
        "en": "How often actual EPS has beaten the consensus estimate historically.",
        "zh": "歷史上實際 EPS 超出共識預估的比率。",
    },
    "avg_surprise": {
        "category": "earnings",
        "direction": "higher",
        "en": "Average size of the earnings surprise over recent quarters.",
        "zh": "近幾季「實際 vs 預估」驚喜幅度的平均值。",
    },
    # --- rotation (Citadel) ---
    "tilt": {
        "category": "rotation",
        "direction": "neutral",
        "en": "Whether sector leadership favours offense (cyclical) or defense (staples).",
        "zh": "目前產業領先族群偏向進攻（景氣循環／成長股）還是防守（民生必需／公用事業）。",
    },
    "offense_defense_score": {
        "category": "rotation",
        "direction": "neutral",
        "en": "Share of the relative-strength ranking from offensive vs. defensive sectors.",
        "zh": "綜合相對強弱排名中，來自進攻型／防守型產業的佔比。",
    },
    # --- factors (RenTech) ---
    "composite_score": {
        "category": "factors",
        "direction": "higher",
        "en": "Weighted blend of the four scores below, each 0–100 within today's universe.",
        "zh": "下方四項因子分數的加權綜合，各自在今日股票池內以 0–100 計分。",
    },
    "value_score": {
        "category": "factors",
        "direction": "higher",
        "en": "Cheapness — low P/E & P/S, high FCF yield — percentile-ranked 0–100.",
        "zh": (
            "便宜程度——本益比、股價營收比（越低越好）與自由現金流殖利率（越高越好），"
            "百分位轉為 0–100 分。"
        ),
    },
    "quality_score": {
        "category": "factors",
        "direction": "higher",
        "en": "Profitability and balance-sheet strength, percentile-ranked 0–100.",
        "zh": "獲利與財務體質——ROE、利潤率、低槓桿——百分位轉為 0–100 分。",
    },
    "momentum_score": {
        "category": "factors",
        "direction": "higher",
        "en": "Blended 3/6/12-month price return, percentile-ranked 0–100.",
        "zh": "3／6／12 月價格報酬的綜合表現，百分位轉為 0–100 分。",
    },
    "growth_score": {
        "category": "factors",
        "direction": "higher",
        "en": "Year-over-year revenue growth, percentile-ranked 0–100.",
        "zh": "營收年增率，百分位轉為 0–100 分。",
    },
    "ic": {
        "category": "factors",
        "direction": "higher",
        "en": "Correlation between score and forward returns — positive & significant is good.",
        "zh": "資訊係數——分數與未來報酬的相關性。正值且 t 值高才有意義。",
    },
    "cagr": {
        "category": "factors",
        "direction": "higher",
        "en": "Compound annual growth rate — the smoothed annual return over the period.",
        "zh": "年化複合成長率——整個期間平滑後的年報酬率。",
    },
    # --- ETF portfolio (Vanguard) ---
    "expected_return": {
        "category": "portfolio",
        "direction": "higher",
        "en": "Annualised return implied by history — an estimate, not a promise.",
        "zh": "依歷史資料，這組權重隱含的年化報酬估計值——是估計，不是承諾。",
    },
    # --- backtest ---
    "total_return": {
        "category": "backtest",
        "direction": "higher",
        "en": "Total percentage gain over the backtest period, after costs.",
        "zh": "整個回測期間、計入成本後的總報酬率。",
    },
    "win_rate": {
        "category": "backtest",
        "direction": "higher",
        "en": "Share of profitable trades. Pair with profit factor — small wins can still lose.",
        "zh": "獲利交易佔比。要搭配獲利因子一起看——勝率高但每次小賺，仍可能整體虧錢。",
    },
    "n_trades": {
        "category": "backtest",
        "direction": "neutral",
        "en": "Completed trades — too few makes every other statistic unreliable.",
        "zh": "完成的交易筆數——太少的話，其他統計數字都不可靠。",
    },
    # --- Today's Picks (certification evidence) ---
    "beat_rate_book": {
        "category": "certification",
        "direction": "higher",
        "en": "How often the book beat the benchmark, across out-of-sample cohorts.",
        "zh": "在樣本外各再平衡期間中，認證組合以等權重打敗基準的比率。",
    },
    "selection_skill": {
        "category": "certification",
        "direction": "higher",
        "en": "Return above an equal-weight eligible book — the certified edge (gate G3).",
        "zh": "相對「等權重合格股票池」多賺的報酬——這才是被認證的選股邊際（G3 關卡）。",
    },
    "oos_cohorts": {
        "category": "certification",
        "direction": "higher",
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


def category(key: str) -> str:
    """``key``'s persona/lens category; empty string if unknown."""
    entry = _ENTRIES.get(key)
    return entry.get("category", "") if entry is not None else ""


#: Short display labels for the Screener's field picker — a name a non-technical user
#: recognizes at a glance, unlike the raw snapshot column key. Deliberately scoped to
#: the snapshot's screenable fields (``screener.snapshot``) rather than every glossary
#: entry: other pages already write their own inline labels via ``t()``.
_LABELS: dict[str, dict[str, str]] = {
    "price": {"en": "Price", "zh": "股價"},
    "sma_20": {"en": "20-day average", "zh": "20 日均線"},
    "sma_50": {"en": "50-day average", "zh": "50 日均線"},
    "sma_200": {"en": "200-day average", "zh": "200 日均線"},
    "rsi_14": {"en": "RSI (14d)", "zh": "RSI（14 日）"},
    "ret_3m": {"en": "3-month return", "zh": "3 個月報酬"},
    "ret_6m": {"en": "6-month return", "zh": "6 個月報酬"},
    "ret_12m": {"en": "12-month return", "zh": "12 個月報酬"},
    "ret_12_1": {"en": "12-1 month momentum", "zh": "12 減 1 月動能"},
    "vol_63d": {"en": "63-day volatility", "zh": "63 日波動度"},
    "dollar_vol_21d": {"en": "21-day $ volume", "zh": "21 日成交金額"},
    "pct_above_sma_200": {"en": "% above 200-day avg", "zh": "距 200 日均線 %"},
    "market_cap": {"en": "Market cap", "zh": "市值"},
    "revenue": {"en": "Revenue", "zh": "營收"},
    "net_income": {"en": "Net income", "zh": "淨利"},
    "eps_diluted": {"en": "EPS (diluted)", "zh": "每股盈餘（稀釋）"},
    "ebitda": {"en": "EBITDA", "zh": "EBITDA"},
    "equity": {"en": "Equity", "zh": "股東權益"},
    "shares_outstanding": {"en": "Shares outstanding", "zh": "流通股數"},
    "net_debt": {"en": "Net debt", "zh": "淨負債"},
    "ev": {"en": "Enterprise value", "zh": "企業價值"},
    "fcf": {"en": "Free cash flow", "zh": "自由現金流"},
    "pe": {"en": "P/E", "zh": "本益比"},
    "ps": {"en": "P/S", "zh": "股價營收比"},
    "peg": {"en": "PEG", "zh": "PEG 比率"},
    "ev_ebitda": {"en": "EV/EBITDA", "zh": "EV/EBITDA"},
    "ev_fcf": {"en": "EV/FCF", "zh": "EV/FCF"},
    "fcf_yield": {"en": "FCF yield", "zh": "自由現金流殖利率"},
    "net_margin": {"en": "Net margin", "zh": "淨利率"},
    "gross_margin": {"en": "Gross margin", "zh": "毛利率"},
    "operating_margin": {"en": "Operating margin", "zh": "營業利益率"},
    "fcf_margin": {"en": "FCF margin", "zh": "自由現金流利率"},
    "roe": {"en": "ROE", "zh": "股東權益報酬率"},
    "roic": {"en": "ROIC", "zh": "投入資本回報率"},
    "debt_to_equity": {"en": "Debt / equity", "zh": "負債權益比"},
    "net_debt_to_ebitda": {"en": "Net debt / EBITDA", "zh": "淨負債 / EBITDA"},
    "interest_coverage": {"en": "Interest coverage", "zh": "利息保障倍數"},
    "revenue_growth_yoy": {"en": "Revenue growth (YoY)", "zh": "營收年增率"},
    "eps_growth_yoy": {"en": "EPS growth (YoY)", "zh": "EPS 年增率"},
    "share_dilution_yoy": {"en": "Share dilution (YoY)", "zh": "股數稀釋率"},
    "buyback_yield": {"en": "Buyback yield", "zh": "庫藏股殖利率"},
    "rev_mom_yoy": {"en": "Revenue momentum (YoY)", "zh": "營收動能年增率"},
    "rev_mom_accel": {"en": "Revenue momentum accel.", "zh": "營收動能加速度"},
    # Cross-sectional factor scores (heimdall.factors.scoring) — not in the persisted
    # snapshot; the Screener computes these on the fly, so the picker needs labels too.
    "value_score": {"en": "Value score", "zh": "價值分數"},
    "quality_score": {"en": "Quality score", "zh": "品質分數"},
    "momentum_score": {"en": "Momentum score", "zh": "動能分數"},
    "growth_score": {"en": "Growth score", "zh": "成長分數"},
    "composite_score": {"en": "Composite score", "zh": "綜合分數"},
}


def label(key: str) -> str:
    """Short display label for ``key`` in the current language; the raw key if unknown."""
    entry = _LABELS.get(key)
    if entry is None:
        return key
    return entry.get(current_lang(), entry.get("en", key))


@dataclass(frozen=True)
class Entry:
    """One glossary row — the data the Glossary page renders."""

    key: str
    category: Category
    direction: Direction
    en: str
    zh: str

    def text(self, lang: str) -> str:
        return self.zh if lang == "zh" else self.en


def all_entries() -> list[Entry]:
    """Every entry, sorted by key — the Glossary page's data source."""
    return [
        Entry(
            key=key,
            category=fields["category"],
            direction=fields["direction"],
            en=fields["en"],
            zh=fields["zh"],
        )
        for key, fields in sorted(_ENTRIES.items())
    ]

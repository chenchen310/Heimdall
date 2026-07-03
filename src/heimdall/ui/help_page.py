"""In-app user guide — how to use Heimdall and, above all, how to *read* the
numbers on each page.

Long-form bilingual content lives here as data (not in ``i18n.t``, which is for
short labels). ``render`` lays it out as: intro → quick start → reading
conventions → one collapsible guide per page, grouped exactly like the sidebar.
"""

from __future__ import annotations

import streamlit as st

from heimdall.ui.i18n import current_lang, t

_INTRO = {
    "en": (
        "**Heimdall** is a personal tool to screen stocks, time entries/exits, and backtest "
        "strategies, organised around eight institutional analyst lenses. US and Taiwan are "
        "supported; every figure is shown in that market's own currency (**USD / TWD**)."
    ),
    "zh": (
        "**Heimdall** 是一個個人用的選股、進出場判斷與策略回測工具，以八大法人分析師視角組織。"
        "支援美股與台股，所有數字都以該市場的幣別（**USD / TWD**）顯示。"
    ),
}

_QUICKSTART = {
    "en": [
        "**Build data first.** Go to **Data → Build data** and build the snapshot — it is the "
        "data source for the Screener and Factors pages. The US default (15 names) is fastest.",
        "**Screen.** In **Stock picking → Screener**, add `field / operator / value` conditions. "
        "Untick a condition's **On** box to relax it and see which extra stocks appear (marked ➕).",
        "**Drill into one name.** Use **Chart** for price/technicals, or the **Analyst lenses** "
        "pages for fundamentals, risk, earnings, and more.",
        "**Validate an idea.** Use **Backtest** — but read every result as an *optimistic upper "
        "bound* (costs and next-bar fills are modelled, reality is usually worse).",
        "Switch **English / 繁體中文** any time from the top of the sidebar.",
    ],
    "zh": [
        "**先建立資料。**到「**資料 → 建立資料**」建立快照——它是「選股器」與「多因子」的資料來源。"
        "第一次用美股小宇宙（15 檔）最快。",
        "**篩股。**在「**選股 → 選股器**」設「欄位 / 運算子 / 數值」條件。取消某條件的「**啟用**」"
        "勾選框可暫時放寬它，看會多出哪些股票（標 ➕）。",
        "**深入單一檔。**用「**個股圖**」看技術面，或到「**分析師視角**」各頁看基本面、風險、財報等。",
        "**驗證想法。**用「**回測**」——但每個結果都請當成**樂觀上限**（已計成本與隔日開盤成交，實盤通常更差）。",
        "左側欄最上方可隨時切換 **English / 繁體中文**。",
    ],
}

_CONVENTIONS = {
    "en": (
        "- **Direction matters.** For valuation multiples (P/E, P/S, EV/EBITDA) **lower is "
        "cheaper**; for profitability and growth (ROE, margins, growth) **higher is better**.\n"
        "- **Currency.** Amount fields (market cap, revenue, EV…) are in the market's currency, "
        "so a threshold like `market_cap > 1e9` means very different things in USD vs TWD — they "
        "are **not comparable across markets**.\n"
        "- **Missing data excludes.** A stock missing a metric simply fails that filter; it is "
        "never silently let through.\n"
        "- **Scenarios are illustrative.** Valuation bands and backtest figures are references, "
        "not promises."
    ),
    "zh": (
        "- **方向性。**估值倍數（P/E、P/S、EV/EBITDA）**越低越便宜**；獲利與成長（ROE、利潤率、"
        "成長率）**越高越好**。\n"
        "- **幣別。**金額欄位（市值、營收、EV…）以該市場幣別計價，所以像 `market_cap > 1e9` 的門檻"
        "在 USD 與 TWD 意義差很多——**跨市場不可直接比較**。\n"
        "- **缺資料 = 排除。**某股缺某指標時，它會在該條件被淘汰，不會被偷偷放行。\n"
        "- **情境僅供參考。**估值區間與回測數字都是參考，不是保證。"
    ),
}

# Sidebar-style grouping (mirrors app.NAV, minus the guide itself).
_SECTIONS: dict[str, list[str]] = {
    "Data": ["Build data"],
    "Stock picking": ["Screener", "Chart"],
    "Backtest": ["Backtest"],
    "Analyst lenses": [
        "Fundamental",
        "Technical",
        "Risk",
        "Earnings",
        "Rotation",
        "Factors",
        "ETF Portfolio",
        "Macro",
    ],
}

# Per-page guide, focused on *reading* the indicators. {page: {icon, en, zh}}.
_PAGES: dict[str, dict[str, str]] = {
    "Build data": {
        "icon": "🗂",
        "en": (
            "Build or refresh the snapshot in-app.\n\n"
            "- **Current snapshot** (top): how many symbols, the US / Taiwan split, and the as-of "
            "date.\n"
            "- **Prerequisite lights:** `SEC_EDGAR_USER_AGENT` (US fundamentals) and `FINMIND_TOKEN` "
            "(Taiwan quota). Unset → some names come back price-only.\n"
            "- **Quick** tab = tens–hundreds of names, in-app with a progress bar. **Whole market** "
            "tab = VTI / all-Taiwan as a background crawl you can leave and resume."
        ),
        "zh": (
            "在網站內建立/更新快照。\n\n"
            "- **目前快照**（最上方）：共幾檔、美股/台股各幾檔、資料日期。\n"
            "- **前置條件燈號：**`SEC_EDGAR_USER_AGENT`（美股財報）、`FINMIND_TOKEN`（台股額度）。"
            "沒設的話部分標的只會有股價。\n"
            "- **快速**分頁＝數十到數百檔，網站內跑、有進度條。**全市場**分頁＝VTI／全台股的背景爬取，"
            "可離開頁面、可續跑。"
        ),
    },
    "Screener": {
        "icon": "📊",
        "en": (
            "Filter a universe with your own conditions. Each row is `field / op / value`; "
            "results show one market (one currency) at a time, `symbol` pinned left.\n\n"
            "**Reading the columns**\n"
            "- `pe` P/E — lower = cheaper; **<15** value, **>30** rich (loss-makers have none).\n"
            "- `peg` — P/E ÷ EPS growth; **<1** = still cheap after growth.\n"
            "- `ps`, `ev_ebitda`, `ev_fcf` — valuation multiples, lower = cheaper.\n"
            "- `roe`, `roic` — profitability, higher better; **>15%** is strong.\n"
            "- `gross/operating/net_margin`, `fcf_margin` — higher is better.\n"
            "- `revenue_growth_yoy`, `eps_growth_yoy` — positive and higher is better.\n"
            "- `net_debt_to_ebitda` — leverage; **<3** healthy, **>4** stretched.\n"
            "- `interest_coverage` — higher = safer (empty for Taiwan).\n"
            "- `rsi_14` — **<30** oversold, **>70** overbought; `pct_above_sma_200` **>0** = above "
            "the 1-year trend.\n\n"
            "**Tips** — untick **On** to relax a condition (extra rows get a ➕); money columns are "
            "labelled with the currency; you can save a screen with a description and delete it."
        ),
        "zh": (
            "用你自己的條件篩股。每一列是「欄位 / 運算子 / 數值」；結果一次只顯示一個市場（一種幣別），"
            "最左 `symbol` 固定。\n\n"
            "**欄位怎麼看**\n"
            "- `pe` 本益比 — 越低越便宜；**<15** 偏便宜、**>30** 偏貴（虧損公司沒有）。\n"
            "- `peg` — 本益比 ÷ EPS 成長；**<1** 代表成長後仍便宜。\n"
            "- `ps`、`ev_ebitda`、`ev_fcf` — 估值倍數，越低越便宜。\n"
            "- `roe`、`roic` — 獲利能力，越高越好；**>15%** 算優。\n"
            "- `gross/operating/net_margin`、`fcf_margin` — 利潤率，越高越好。\n"
            "- `revenue_growth_yoy`、`eps_growth_yoy` — 成長，正且越高越好。\n"
            "- `net_debt_to_ebitda` — 槓桿；**<3** 健康、**>4** 偏高。\n"
            "- `interest_coverage` 利息保障倍數 — 越高越安全（台股無此欄）。\n"
            "- `rsi_14` — **<30** 超賣、**>70** 超買；`pct_above_sma_200` **>0** 代表站上年線。\n\n"
            "**小技巧** — 取消「啟用」可放寬條件（多出來的股票標 ➕）；金額欄會標幣別；條件組可加描述存檔、"
            "也可刪除。"
        ),
    },
    "Chart": {
        "icon": "📈",
        "en": (
            "One stock's price and technicals, in three stacked panels.\n\n"
            "- **Candles + 20/50/200-day moving averages** — price above the averages, with "
            "short > mid > long, is a bullish stack; below is bearish.\n"
            "- **RSI(14)** — 30 / 70 are the oversold / overbought guide lines.\n"
            "- **MACD** — the fast line crossing **above** the signal line is bullish (golden "
            "cross); crossing below is bearish."
        ),
        "zh": (
            "單一股票的價格與技術指標，分三層。\n\n"
            "- **K 線 + 20/50/200 日均線** — 價在均線上方、且短>中>長為多頭排列；在下方則偏空。\n"
            "- **RSI(14)** — 30 / 70 是超賣 / 超買的參考線。\n"
            "- **MACD** — 快線**上穿**訊號線＝偏多（黃金交叉），下穿＝偏空。"
        ),
    },
    "Backtest": {
        "icon": "🧪",
        "en": (
            "Test an entry/exit strategy on history.\n\n"
            "- **CAGR** — annualised return; higher is better, but always read it with drawdown.\n"
            "- **Sharpe** — risk-adjusted return; **>1** good, **>2** excellent (but be suspicious "
            "of over-fitting).\n"
            "- **Max drawdown** — worst peak-to-trough fall; closer to 0 is better.\n"
            "- **Win rate / Profit factor** — share of winning trades / gross-win ÷ gross-loss "
            "(must be **>1** to make money).\n\n"
            "⚠️ Costs and **next-bar-open fills** are modelled, but treat every figure as an "
            "**optimistic upper bound** — live results are usually worse."
        ),
        "zh": (
            "在歷史上測試一個進出場策略。\n\n"
            "- **CAGR** 年化報酬 — 越高越好，但一定要搭配回撤一起看。\n"
            "- **Sharpe** 夏普 — 風險調整後報酬；**>1** 不錯、**>2** 很好（但要小心過度最佳化）。\n"
            "- **Max drawdown** 最大回撤 — 從高點的最大跌幅，越接近 0 越好。\n"
            "- **Win rate / Profit factor** — 勝率 / 獲利因子（毛利÷毛損，要 **>1** 才賺）。\n\n"
            "⚠️ 已計入成本並以**隔日開盤成交**，但每個數字都請當成**樂觀上限**——實盤通常更差。"
        ),
    },
    "Fundamental": {
        "icon": "🏛",
        "en": (
            "Goldman lens — a quick fundamental health check (US filers via EDGAR).\n\n"
            "- **Rating box** — Buy / Hold / Sell + a **0–100** score, computed from public rules "
            "(margins, growth, debt, free cash flow, valuation), not a guess.\n"
            "- **P/E, P/S, revenue CAGR** — valuation and growth at a glance.\n"
            "- **Bull / bear lists** — auto-generated pros and cons.\n"
            "- **Scenario prices** — illustrative 15× / 22× / 30× P/E × EPS bands (reference only)."
        ),
        "zh": (
            "高盛視角 — 快速體檢基本面（美股，來自 EDGAR）。\n\n"
            "- **評級框** — Buy / Hold / Sell ＋ **0–100** 分，用公開規則（利潤率、成長、負債、"
            "自由現金流、估值）算出，不是猜的。\n"
            "- **P/E、P/S、營收 CAGR** — 一眼看估值與成長。\n"
            "- **多空對照** — 自動列出看多 / 看空理由。\n"
            "- **情境價位** — 示意性的 15× / 22× / 30× 本益比 × EPS 區間（僅供參考）。"
        ),
    },
    "Technical": {
        "icon": "📐",
        "en": (
            "Morgan Stanley lens — scattered signals turned into a trading plan.\n\n"
            "- **Plan box** — current price, entry, **stop**, and first target (**1R**).\n"
            "- **Trend** — short / mid / long-term direction.\n"
            "- Stops are **ATR-based** (volatility): stop = entry − N×ATR; 1R is the risk unit, "
            "2R / 3R are reward-to-risk multiples."
        ),
        "zh": (
            "摩根士丹利視角 — 把零散訊號整理成一份交易計畫。\n\n"
            "- **計畫框** — 現價、進場、**停損**、第一目標（**1R**）。\n"
            "- **趨勢** — 短 / 中 / 長期方向。\n"
            "- 停損以 **ATR（波動度）**為基礎：停損＝進場 − N×ATR；1R 是風險單位，2R / 3R 是報酬風險比。"
        ),
    },
    "Risk": {
        "icon": "⚖️",
        "en": (
            "Bridgewater lens — a risk check vs. a benchmark (default `SPY.US`).\n\n"
            "- **Annualised volatility** — higher = choppier.\n"
            "- **Beta** — sensitivity to the market; **>1** swings more than the market, **<1** "
            "calmer.\n"
            "- **VaR 95% / CVaR 95%** — a bad-day tail loss estimate; smaller (less negative) is "
            "better.\n"
            "- **Max drawdown, Sharpe, liquidity tier**, plus a recession **stress test** "
            "(≈ Beta × a −30% market shock)."
        ),
        "zh": (
            "橋水視角 — 對一個基準（預設 `SPY.US`）做風險體檢。\n\n"
            "- **年化波動率** — 越高越震盪。\n"
            "- **Beta** — 對大盤的敏感度；**>1** 比大盤更波動、**<1** 較穩。\n"
            "- **VaR 95% / CVaR 95%** — 單日尾端可能虧損；越小（越不負）越好。\n"
            "- **最大回撤、Sharpe、流動性等級**，外加衰退**壓力測試**（≈ Beta × 大盤 −30% 衝擊）。"
        ),
    },
    "Earnings": {
        "icon": "📰",
        "en": (
            "JPM lens — earnings setup (needs `FMP_API_KEY`).\n\n"
            "- **Next earnings date** and **next-quarter consensus EPS**.\n"
            "- **Beat rate** — how often the company has beaten estimates historically.\n"
            "- **Recent surprise** and the last few quarters' actual vs. estimate."
        ),
        "zh": (
            "摩根大通視角 — 財報布局（需 `FMP_API_KEY`）。\n\n"
            "- **下次財報日**與**下季共識 EPS**。\n"
            "- **優於預期比率** — 歷史上超出預期的機率。\n"
            "- **近期驚喜幅度**與近幾季「實際 vs 預估」。"
        ),
    },
    "Rotation": {
        "icon": "🔄",
        "en": (
            "Citadel lens — where money is leading.\n\n"
            "- The 11 SPDR sector ETFs **ranked by a blended 1/3/6-month relative-strength** "
            "score.\n"
            "- **Offense / defense tilt** — whether leadership is risk-on or risk-off.\n"
            "- The current leaders and laggards."
        ),
        "zh": (
            "城堡視角 — 看資金在哪裡領先。\n\n"
            "- 11 檔 SPDR 行業 ETF，依 **1/3/6 月相對強弱**綜合分數排名。\n"
            "- **進攻 / 防守傾向** — 領先族群偏risk-on還是risk-off。\n"
            "- 目前的領先者與落後者。"
        ),
    },
    "Factors": {
        "icon": "🧬",
        "en": (
            "RenTech lens — multi-factor ranking and a factor-portfolio backtest.\n\n"
            "- **Composite 0–100** — value / quality / momentum / growth, weighted (shown as a "
            "bar). Scores are **within one market** at a time.\n"
            "- **IC (information coefficient)** — predictive power of the score; **>0** with a high "
            "t-stat is good.\n"
            "- **Quantile forward returns** — an upward slope (low → high score) is what you want.\n"
            "- The portfolio tab carries a **survivorship-bias** warning — treat it as an upper "
            "bound."
        ),
        "zh": (
            "文藝復興視角 — 多因子排名與因子投組回測。\n\n"
            "- **綜合分數 0–100** — 價值 / 品質 / 動能 / 成長 加權（以進度條呈現）。分數是**在單一市場內**"
            "計算。\n"
            "- **IC（資訊係數）** — 分數的預測力；**>0** 且 t 值大代表有效。\n"
            "- **分位未來報酬** — 由低分到高分**遞增**為佳。\n"
            "- 投組分頁有**存活者偏差**警告，請當成上限看。"
        ),
    },
    "ETF Portfolio": {
        "icon": "🧺",
        "en": (
            "Vanguard lens — an efficient-frontier ETF allocation.\n\n"
            "- **Weights** from your method (**max Sharpe** or **min volatility**), with expected "
            "return / volatility / Sharpe.\n"
            "- Reminder: weights estimated from history are noisy — a starting point, not gospel."
        ),
        "zh": (
            "先鋒視角 — 用 ETF 算一組效率前緣配置。\n\n"
            "- 依你的方法（**最大夏普** 或 **最小波動**）算出的**權重**，以及預期報酬 / 波動 / 夏普。\n"
            "- 提醒：用歷史估出來的權重很雜訊——當成起點，而非定論。"
        ),
    },
    "Macro": {
        "icon": "🌐",
        "en": (
            "Two Sigma lens — the macro backdrop (needs `FRED_API_KEY`).\n\n"
            "- Key series: **CPI, unemployment, the policy rate, the 10Y–2Y spread, the 10Y "
            "yield, real GDP**, with their latest values and year-changes.\n"
            "- **An inverted yield curve** (10Y–2Y spread **< 0**) is a classic recession warning.\n"
            "- A one-line read on the current stage of the cycle."
        ),
        "zh": (
            "Two Sigma 視角 — 看總經環境（需 `FRED_API_KEY`）。\n\n"
            "- 關鍵指標：**CPI、失業率、政策利率、10Y–2Y 利差、10 年期殖利率、實質 GDP**，"
            "含最新值與年變化。\n"
            "- **殖利率倒掛**（10Y–2Y 利差 **< 0**）是經典的衰退預警訊號。\n"
            "- 一句目前景氣循環階段的研判。"
        ),
    },
}


def render() -> None:
    lang = current_lang()
    st.header(t("📖 User guide"))
    st.markdown(_INTRO[lang])

    st.subheader(t("Quick start"))
    for i, step in enumerate(_QUICKSTART[lang], start=1):
        st.markdown(f"{i}. {step}")

    with st.expander(t("Reading the numbers — conventions")):
        st.markdown(_CONVENTIONS[lang])

    st.subheader(t("How to read each page"))
    for section, pages in _SECTIONS.items():
        st.markdown(f"#### {t(section)}")
        for key in pages:
            guide = _PAGES[key]
            with st.expander(f"{guide['icon']} {t(key)}"):
                st.markdown(guide[lang])

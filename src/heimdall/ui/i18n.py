"""Tiny i18n for the Streamlit UI — English / 繁體中文.

``t(en)`` returns the Traditional-Chinese string for the current language (set by
the sidebar selector), falling back to the English source when no translation
exists. Technical jargon (P/E, RSI, Sharpe, Beta, VaR, …) is left in English on
purpose, so only descriptive UI text is translated.
"""

from __future__ import annotations

import streamlit as st

LANGUAGES: dict[str, str] = {"English": "en", "繁體中文": "zh"}

# English source -> Traditional Chinese. Missing keys fall back to the source.
_ZH: dict[str, str] = {
    # --- nav / app shell ---
    "Page": "頁面",
    "Data": "資料",
    "Stock picking": "選股",
    "Analyst lenses": "分析師視角",
    "Help": "說明",
    "Guide": "使用說明",
    "Screener": "選股器",
    "Build data": "建立資料",
    "Chart": "個股圖",
    "Fundamental": "基本面",
    "Technical": "技術面",
    "Risk": "風險",
    "Earnings": "財報",
    "Backtest": "回測",
    "Factors": "多因子",
    "Macro": "總經",
    "Rotation": "產業輪動",
    "ETF Portfolio": "ETF 投組",
    "Rebuild the snapshot any time:\n\n`uv run python -m heimdall.screener.build`": (
        "隨時可重建快照：\n\n`uv run python -m heimdall.screener.build`"
    ),
    # --- common inputs / buttons ---
    "Symbol": "代號",
    "Symbol (TICKER.MARKET)": "代號（TICKER.MARKET）",
    "Benchmark": "基準",
    "Method": "方法",
    "Generate report": "產生報告",
    "Optimize": "最佳化",
    "Save": "儲存",
    "Years of history": "歷史年數",
    # --- AI report (_personas) ---
    "🤖 AI report (optional)": "🤖 AI 報告（選用）",
    "Set `ANTHROPIC_API_KEY` in `.env` and install the `personas` extra "
    "(`uv sync --extra personas`) to generate an AI-written report.": (
        "在 `.env` 設定 `ANTHROPIC_API_KEY` 並安裝 `personas` 套件"
        "（`uv sync --extra personas`）即可產生 AI 撰寫的報告。"
    ),
    "Writing report via Claude…": "正在透過 Claude 撰寫報告…",
    # --- screener ---
    "📊 Screener": "📊 選股器",
    "No snapshot found. Build one first:\n\n`uv run python -m heimdall.screener.build`": (
        "找不到快照，請先建立：\n\n`uv run python -m heimdall.screener.build`"
    ),
    "Snapshot is empty.": "快照是空的。",
    "Market": "市場",
    "US": "美股",
    "Taiwan": "台股",
    "symbols": "檔",
    "as of": "資料日",
    "Start from preset": "從預設條件開始",
    "…or load saved": "…或載入已存的",
    "Rank by": "排序依據",
    "Ascending": "升冪",
    "Limit": "顯示上限",
    "Save this screen": "儲存此條件組",
    "Name": "名稱",
    "Description (optional)": "描述（選填）",
    "Saved screen": "已儲存條件組",
    "(no description)": "（無描述）",
    "Delete": "刪除",
    "On": "啟用",
    "{n} condition(s) off → {m} extra stock(s) (marked ➕).": (
        "停用 {n} 個條件 → 多出 {m} 檔（下表標 ➕）。"
    ),
    "Appears only because a condition is off": "因為有條件被停用才出現",
    "Amount fields are in {currency} — thresholds are market-specific.": (
        "金額欄位以 {currency} 計價——門檻為各市場專屬。"
    ),
    "This screen was built for {m} ({c}) and uses amount fields "
    "(e.g. market_cap); its thresholds may not carry over to {cur}.": (
        "此條件組是為「{m}（{c}）」建立的，且用到金額欄位（如 market_cap），"
        "其門檻可能無法套用到 {cur}。"
    ),
    # --- user guide ---
    "📖 User guide": "📖 使用說明",
    "Quick start": "快速上手",
    "Reading the numbers — conventions": "看數字的通則",
    "How to read each page": "如何閱讀各分頁的指標",
    # --- build data ---
    "🗂 Data — build snapshot": "🗂 資料 — 建立快照",
    "The snapshot is the data behind the Screener and Factors pages. Build or refresh it here.": (
        "快照是「選股器」與「多因子」頁面的資料來源,可在此建立或更新。"
    ),
    "No snapshot yet — build one below.": "尚無快照——請在下方建立。",
    "Current snapshot": "目前快照",
    "set": "已設定",
    "missing — US fundamentals may be price-only": "未設定——美股基本面可能僅有價格",
    "unset — Taiwan runs on a low free quota": "未設定——台股使用較低的免費配額",
    "Quick (curated / custom)": "快速(精選 / 自選)",
    "Whole market (background)": "全市場(背景執行)",
    "Runs in the app with a progress bar — best for tens to a few hundred symbols.": (
        "在 App 內執行並顯示進度條——適合數十至數百檔。"
    ),
    "A background build is running — wait for it to finish or stop it first.": (
        "背景建構進行中——請先等待完成或停止它。"
    ),
    "Custom symbols": "自選代號",
    "Universe": "股票池",
    "Symbols (comma / space / newline, e.g. AAPL.US 2330.TW)": (
        "代號(以逗號 / 空白 / 換行分隔,例如 AAPL.US 2330.TW)"
    ),
    "Re-fetch symbols already in the snapshot": "重新抓取已在快照中的代號",
    "refresh all": "全部更新",
    "new only": "僅新增",
    "Build now": "立即建立",
    "Starting…": "開始中…",
    "Done": "完成",
    "Already up to date — nothing to fetch.": "已是最新——無須抓取。",
    "Built": "已建立",
    "skipped": "略過",
    "Launches a background crawl. Long and one-time — you can leave this page; it keeps "
    "running and is resumable. Prices are cached, so a later refresh is far faster.": (
        "啟動背景爬取。耗時且為一次性——可離開此頁,會持續執行且可續跑。價格已快取,之後更新會快很多。"
    ),
    "Background build finished.": "背景建構完成。",
    "Rebuild from scratch (re-fetch everything)": "從頭重建(全部重新抓取)",
    "Start background build": "開始背景建構",
    "Building in the background — safe to switch pages; come back any time.": (
        "背景建構中——可安全切換頁面,隨時回來查看。"
    ),
    "Stop": "停止",
    "Stopped. The partial snapshot is kept; start again to resume.": (
        "已停止。部分快照已保留;再次開始即可續跑。"
    ),
    # --- chart ---
    "📈 Chart": "📈 個股圖",
    "Lookback (days)": "回看天數",
    "No price data for {symbol}.": "{symbol} 沒有價格資料。",
    # --- fundamental ---
    "🏛 Fundamental — Goldman lens": "🏛 基本面 — Goldman 視角",
    "Symbol (e.g. AAPL.US, 2330.TW)": "代號（例如 AAPL.US、2330.TW）",
    "No fundamentals found. US filers come from EDGAR (e.g. AAPL.US); "
    "Taiwan from FinMind (e.g. 2330.TW).": (
        "查無基本面。美股來自 EDGAR（例如 AAPL.US）；台股來自 FinMind（例如 2330.TW）。"
    ),
    "Monthly revenue (TW)": "月營收（台股）",
    "Latest month revenue": "最新月營收",
    "YoY": "年增率",
    "Rating Summary": "評級摘要",
    "Revenue by fiscal year": "各會計年度營收",
    "Margins": "利潤率",
    "Bull case": "看多理由",
    "Bear case": "看空理由",
    "Scenarios — illustrative P/E bands (15× / 22× / 30× latest EPS)": (
        "情境 — 示意性 P/E 區間（最新 EPS 的 15× / 22× / 30×）"
    ),
    # --- technical ---
    "📐 Technical — Morgan Stanley lens": "📐 技術面 — Morgan Stanley 視角",
    "Trading Plan Summary": "交易計畫摘要",
    "Support / Resistance": "支撐 / 壓力",
    "Fibonacci retracement": "斐波那契回撤",
    # --- risk ---
    "⚖️ Risk — Bridgewater lens": "⚖️ 風險 — Bridgewater 視角",
    "Risk dashboard": "風險儀表板",
    "No price data for the symbol or benchmark.": "標的或基準沒有價格資料。",
    # --- earnings ---
    "📰 Earnings — JPM lens": "📰 財報 — JPM 視角",
    "Consensus estimates and the earnings calendar are paid data (via FMP).": (
        "共識預期與財報日曆屬付費資料（來自 FMP）。"
    ),
    "Decision Summary": "決策摘要",
    "Recent quarters — actual vs estimate": "近幾季 — 實際 vs 預估",
    # --- backtest ---
    "🧪 Backtest": "🧪 回測",
    "Strategy": "策略",
    "Parameters": "參數",
    "Commission (bps)": "手續費（bps）",
    "Slippage (bps)": "滑價（bps）",
    "Costs and next-bar-open fills applied — treat as an optimistic upper bound.": (
        "已計入成本並以隔日開盤成交 — 請當成樂觀上限。"
    ),
    "📐 Trade setup (ATR-based)": "📐 交易設定（以 ATR 為基礎）",
    "ATR stop multiple": "ATR 停損倍數",
    "🔬 Parameter sweep": "🔬 參數掃描",
    "Sweep up to 2 parameters": "掃描最多 2 個參數",
    "Metric": "指標",
    "Run sweep": "執行掃描",
    "📄 Full quantstats tear sheet": "📄 完整 quantstats 報表",
    "Generate tear sheet": "產生報表",
    "Building tear sheet…": "正在產生報表…",
    "Download HTML": "下載 HTML",
    # --- factors ---
    "🧬 Factors": "🧬 多因子",
    "Ranking (current)": "排名（目前）",
    "Portfolio backtest": "投組回測",
    "Composite of value / quality / momentum / growth, each scored 0–100.": (
        "價值 / 品質 / 動能 / 成長 的綜合分數，各以 0–100 計分。"
    ),
    "Start year": "起始年份",
    "Rebalance": "再平衡",
    "Monthly": "每月",
    "Quarterly": "每季",
    "Top N": "前 N 名",
    "Run factor backtest": "執行因子回測",
    "Forward return by composite quantile (low → high) — upward slope is good:": (
        "依綜合分數分位的未來報酬（低 → 高）— 由低到高遞增為佳："
    ),
    # --- macro ---
    "🌐 Macro — Two Sigma lens": "🌐 總經 — Two Sigma 視角",
    "No strong macro signals from the key series right now.": "目前關鍵指標沒有明顯的總經訊號。",
    # --- rotation ---
    "🔄 Sector rotation — Citadel lens": "🔄 產業輪動 — Citadel 視角",
    "The 11 SPDR sector ETFs, ranked by a blended 1/3/6-month relative-strength score.": (
        "11 檔 SPDR 行業 ETF，依 1/3/6 月相對強弱綜合分數排名。"
    ),
    "Run rotation scan": "執行輪動掃描",
    "Fetches ~11 sector ETFs (cached after the first run).": (
        "會抓取約 11 檔行業 ETF（第一次之後會快取）。"
    ),
    "Tilt": "傾向",
    # --- etf ---
    "🧺 ETF portfolio — Vanguard lens": "🧺 ETF 投組 — Vanguard 視角",
    "ETF basket (comma-separated)": "ETF 清單（以逗號分隔）",
    "Need at least 2 ETFs with overlapping history.": "至少需要 2 檔有重疊歷史的 ETF。",
    "Weights": "權重",
    "History-optimized weights are noisy — a starting point, not gospel.": (
        "用歷史估出的權重很雜訊 — 當成起點而非定論。"
    ),
    # --- misc labels referenced inline ---
    "Field": "欄位",
    "Op": "運算子",
    "Value": "數值",
    "matches": "檔符合",
    "Regime read": "景氣循環研判",
    "Cheap & profitable": "便宜又賺錢",
    "Oversold quality": "超賣的好公司",
    "Above 200-day trend": "站上年線",
    "No snapshot. Build one: `uv run python -m heimdall.screener.build`": (
        "找不到快照，請先建立：`uv run python -m heimdall.screener.build`"
    ),
    "No rows for this market in the snapshot.": "快照中沒有這個市場的資料。",
    "No panel data (network/symbol issue).": "沒有面板資料（網路／代號問題）。",
    "⚠️ Over a **current** universe these results carry survivorship bias — today's "
    "winners are baked in. Treat returns as an optimistic upper bound, not a forecast.": (
        "⚠️ 在「當前」股票池下，這些結果帶有存活者偏差——今天的贏家已內含其中。"
        "請把報酬當成樂觀上限，而非預測。"
    ),
}


def current_lang() -> str:
    return str(st.session_state.get("lang", "en"))


def t(text: str) -> str:
    """Translate ``text`` for the active language (English source falls through)."""
    return _ZH.get(text, text) if current_lang() == "zh" else text


def language_selector() -> str:
    """Render the sidebar language picker and record the choice. Returns the code."""
    choice = st.sidebar.selectbox("🌐 Language / 語言", list(LANGUAGES), key="lang_choice")
    st.session_state["lang"] = LANGUAGES[choice]
    return LANGUAGES[choice]

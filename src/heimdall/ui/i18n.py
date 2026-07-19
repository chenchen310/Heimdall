"""Tiny i18n for the Streamlit UI — English / 繁體中文.

``t(en)`` returns the Traditional-Chinese string for the current language (set by
the sidebar selector), falling back to the English source when no translation
exists. Technical jargon (P/E, RSI, Sharpe, Beta, VaR, …) is left in English on
purpose, so only descriptive UI text is translated.
"""

from __future__ import annotations

import streamlit as st

LANGUAGES: dict[str, str] = {"繁體中文": "zh", "English": "en"}  # first entry = default

# English source -> Traditional Chinese. Missing keys fall back to the source.
_ZH: dict[str, str] = {
    # --- nav / app shell ---
    "Page": "頁面",
    "Data": "資料",
    "Stock picking": "選股",
    "Analyst lenses": "分析師視角",
    "Help": "說明",
    "Guide": "使用說明",
    "Glossary": "指標辭典",
    "Screener": "選股器",
    "Today's Picks": "今日候選",
    "Stock Workbench": "個股工作台",
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
    "TW Chips": "台股籌碼",
    "Sector Focus": "產業焦點",
    "TW Market Flows": "台股資金流向",
    "Rebuild the snapshot any time:\n\n`uv run python -m heimdall.screener.build`": (
        "隨時可重建快照：\n\n`uv run python -m heimdall.screener.build`"
    ),
    # --- common inputs / buttons ---
    "Symbol (TICKER.MARKET)": "代號（TICKER.MARKET）",
    "Benchmark": "基準",
    "Method": "方法",
    "Generate report": "產生報告",
    "Optimize": "最佳化",
    "Save": "儲存",
    "Years of history": "歷史年數",
    # --- shared nav / empty states (_nav, _freshness) ---
    "This page needs a snapshot to work, and none exists yet.": (
        "這個頁面需要「選股快照」才能運作，目前還沒有建立。"
    ),
    "Go build one": "前往建立",
    "Refresh it now": "立即更新",
    "Or from a terminal: `uv run python -m heimdall.screener.build`": (
        "或用終端機：`uv run python -m heimdall.screener.build`"
    ),
    "fresh": "新鮮",
    "aging": "略舊",
    "stale": "已過期",
    "updated today": "今天更新",
    "bdays old": "個營業日前",
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
    "Grouped: fundamental fields first, then technical.": "已分組：基本面欄位在前，技術面在後。",
    "Percent-like fields (ROE, margins, growth…) are in percentage "
    "points — type 15 for 15%, not 0.15.": (
        "百分比類欄位（ROE、利潤率、成長率…）以百分點輸入——15% 請打 15，不是 0.15。"
    ),
    "has a value": "有數值",
    "🔻 Funnel — which condition narrows the most": "🔻 篩選漏斗——哪個條件篩掉最多",
    "Condition": "條件",
    "Alone": "單獨符合",
    "Remaining": "累計剩餘",
    "Biggest cut: {cond} ({drop} stock(s) removed).": "篩掉最多的條件：{cond}（刷掉 {drop} 檔）。",
    "between": "介於",
    "and": "到",
    "…to": "…到",
    'The range\'s upper bound — only used when Op is "between".': (
        "範圍的上界——運算子為 between 時才使用。"
    ),
    "Open {symbol} in Stock Workbench →": "在個股工作台開啟 {symbol} →",
    "Cheap (value)": "便宜（價值型）",
    "High quality": "體質優良",
    "Strong momentum": "動能強勁",
    "All-around (composite)": "全能型（綜合分數）",
    'Apply "{name}"': "套用「{name}」",
    "(no conditions)": "（無條件）",
    "📏 Pool context for your fields (min / median / max)": (
        "📏 你選的欄位在這個池子裡的數值範圍（最小／中位數／最大）"
    ),
    "Min": "最小",
    "Median": "中位數",
    "Max": "最大",
    "+ Show more columns": "＋ 顯示更多欄位",
    # --- user guide ---
    "📖 User guide": "📖 使用說明",
    "Quick start": "快速上手",
    "Reading the numbers — conventions": "看數字的通則",
    "How to read each page": "如何閱讀各分頁的指標",
    # --- glossary ---
    "📚 Indicator Glossary": "📚 指標辭典",
    "What every metric means and how to read it — the same text shown in "
    "the ⓘ tooltips across the app.": (
        "每個指標的意思與怎麼看——跟全站 ⓘ 提示框顯示的是同一份內容。"
    ),
    "Search (name or keyword)": "搜尋（名稱或關鍵字）",
    "No indicators match your search.": "沒有符合搜尋的指標。",
    # --- today's picks ---
    "🎯 Today's Picks": "🎯 今日候選",
    "Only signals that passed out-of-sample certification render here — nothing else, ever.": (
        "只有通過樣本外認證的訊號會出現在這裡——除此之外,永遠不顯示任何排名。"
    ),
    "No certified signal yet for this market. Every ranking shown here must first "
    "pass strict statistical testing on data it has never been tuned on — most "
    "candidate signals fail, and none currently qualifies. This is intentional "
    "honesty, not a bug: nothing is shown here until a signal has actually earned it.": (
        "這個市場目前沒有已認證的訊號。這裡顯示的每一個排名，都必須先通過嚴格的"
        "「樣本外」統計檢驗——大多數候選訊號會失敗，目前也還沒有任何一個通過。"
        "這是刻意的誠實留白，不是故障：沒有訊號真正通過驗證之前，這裡不會顯示任何排名。"
    ),
    "Snapshot is {n} business days old — refresh it on the Build data page.": (
        "快照已 {n} 個營業日未更新——請到「建立資料」頁重新整理。"
    ),
    "Beat rate (6m book vs benchmark)": "組合6個月贏過基準的比率",
    "Selection skill (vs equal-weight)": "選股技術(相對等權重)",
    "Beat rate = how often the equal-weight book beat the benchmark (includes the "
    "equal-weight premium); selection skill = return above an equal-weight universe "
    "book (the certified edge, G3).": (
        "贏過基準的比率 = 等權重組合打敗基準的頻率(包含等權重本身的紅利);"
        "選股技術 = 相對「等權重可交易宇宙」多賺的報酬(這才是真正被認證的邊際,即 G3)。"
    ),
    "Q5−Q1 spread": "Q5−Q1 價差",
    "OOS cohorts": "樣本外期數",
    "Certified {d} · OOS window {a} → {b} · benchmark {bench}": (
        "認證於 {d} · 樣本外視窗 {a} → {b} · 基準 {bench}"
    ),
    "survivorship: current universe (optimistic upper bound)": ("存活者偏差:現今成分股(樂觀上限)"),
    "No eligible names to rank right now.": "目前沒有符合資格可排名的股票。",
    "z = strength vs today's eligible pool; the score is the weighted sum of z columns.": (
        "z = 相對今日合格池的強度;總分為各 z 欄的加權和。"
    ),
    "Post-cert monitoring: trailing-{n} selection skill {a:+.1%} — drift alarm not triggered.": (
        "認證後監控:近 {n} 期選股技術 {a:+.1%} — 未觸發漂移警報。"
    ),
    "⚠️ {name} v{v} — certified, then flagged by drift monitoring: post-certification "
    "selection skill went significantly negative (trailing-{n} {a:+.1%}, 95% CI upper "
    "{hi:+.1%} < 0). Under review — its ranking is withheld until it re-certifies or "
    "retires.": (
        "⚠️ {name} v{v} — 曾經認證,現被漂移監控標記:認證後選股技術顯著轉負"
        "(近 {n} 期 {a:+.1%},95% CI 上界 {hi:+.1%} < 0)。目前為審查中——"
        "在重新認證或下架之前,排名將暫停顯示。"
    ),
    "⚠️ {name} v{v} — under review (post-certification drift). Ranking withheld.": (
        "⚠️ {name} v{v} — 審查中(認證後偵測到漂移)。排名暫停顯示。"
    ),
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
    # --- stock workbench ---
    "🔎 Stock Workbench": "🔎 個股工作台",
    "One symbol, every analyst lens — pick once, explore below.": (
        "輸入一次代號，下方切換各分析師視角。"
    ),
    "Overview": "總覽",
    "Quick pick from snapshot": "從快照快速挑選",
    "No snapshot yet — type a symbol directly.": "尚無快照——請直接輸入代號。",
    "A one-line read from each lens — open a tab below for the full picture.": (
        "每個視角一句話結論——點下方分頁看完整內容。"
    ),
    # --- chart ---
    "Lookback (days)": "回看天數",
    "No price data for {symbol}.": "{symbol} 沒有價格資料。",
    # --- fundamental ---
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
    "Bear scenario": "空頭情境",
    "Base scenario": "中性情境",
    "Bull scenario": "多頭情境",
    # --- technical ---
    "Trading Plan Summary": "交易計畫摘要",
    "Price is what you'd pay right now. The plan frames two ways in instead: "
    "buy a pullback to support, or a breakout above resistance — each with its "
    "own ATR stop and R-multiple targets.": (
        "「股價」是你現在買要付的價。交易計畫改用兩種進場方式：回檔到支撐買，"
        "或突破壓力買——各自帶自己的 ATR 停損與 R 倍數目標。"
    ),
    "⤵ Pullback (buy the dip)": "⤵ 回檔進場（買回檔）",
    "⤴ Breakout (buy strength)": "⤴ 突破進場（買強勢）",
    "Support / Resistance": "支撐 / 壓力",
    "Fibonacci retracement": "斐波那契回撤",
    # --- risk ---
    "Risk dashboard": "風險儀表板",
    "No price data for the symbol or benchmark.": "標的或基準沒有價格資料。",
    # --- earnings ---
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
    # --- TW chips page (chips_page) ---
    "💰 TW Chips — who is buying": "💰 台股籌碼 — 誰在買",
    "Descriptive chip data, not a certified signal; Today's Picks ignores this page.": (
        "描述性籌碼資料，非認證訊號；今日候選不會參考此頁。"
    ),
    "Taiwan symbol (TICKER.TW / .TWO)": "台股代號（TICKER.TW / .TWO）",
    "Not a canonical symbol — use e.g. 2330.TW.": "不是有效代號 — 請用如 2330.TW。",
    "Taiwan only — this lens uses TW institutional/margin data.": (
        "僅限台股 — 此視角使用台股法人／融資資料。"
    ),
    "Load chip data": "載入籌碼資料",
    "Fetches 法人買賣超・外資持股・融資 for one Taiwan symbol (cached after first run).": (
        "抓取單一台股的法人買賣超・外資持股・融資（首次載入後會快取）。"
    ),
    "Market-wide top-10 net-buy/sell lists live on the upcoming Market flows page (roadmap 15.2): "
    "FinMind's per-date bulk query is paid-tier, so free-tier market-wide flows are built there "
    "from a cached store. This page is per-symbol.": (
        "全市場買賣超前十名清單將放在「市場資金流向」頁（roadmap 15.2）：FinMind 的單日整批查詢"
        "屬付費層，免費層的全市場資金流向會在該頁以快取方式建立。本頁為個股視角。"
    ),
    "Fetching chip data…": "抓取籌碼資料中…",
    "No chip data for {symbol}.": "{symbol} 沒有籌碼資料。",
    "Latest foreign holding %": "最新外資持股比",
    "n/a": "無",
    "Foreign net-buy (20d)": "外資淨買超（20 日）",
    "Sum of daily 外資 net-buy shares over the last 20 trading days.": (
        "近 20 個交易日的外資每日淨買超股數合計。"
    ),
    "Trust net-buy (20d)": "投信淨買超（20 日）",
    "Sum of daily 投信 net-buy shares over the last 20 trading days.": (
        "近 20 個交易日的投信每日淨買超股數合計。"
    ),
    "Institutional net-buy vs price": "法人買賣超 vs 股價",
    "外資 cumulative net-buy": "外資累積淨買超",
    "投信 cumulative net-buy": "投信累積淨買超",
    "Price": "股價",
    "Cumulative net-buy (shares)": "累積淨買超（股數）",
    "Foreign holding % and margin balance": "外資持股比與融資餘額",
    "Foreign holding %": "外資持股比 %",
    "Margin balance": "融資餘額",
    # --- sector classification (roadmap 14.1) — the ~dozen US SIC Divisions; TW's
    # FinMind industry_category is already zh and needs no gloss ---
    "Sector": "產業別",
    "Unknown": "未知",
    "Agriculture, Forestry & Fishing": "農林漁業",
    "Mining": "礦業",
    "Construction": "營建業",
    "Manufacturing": "製造業",
    "Transportation, Communications & Utilities": "運輸、通訊與公用事業",
    "Wholesale Trade": "批發業",
    "Retail Trade": "零售業",
    "Finance, Insurance & Real Estate": "金融、保險與不動產",
    "Services": "服務業",
    "Public Administration": "公共行政",
    # --- sector-focus page (sector_page) ---
    "🏭 Sector focus": "🏭 產業焦點",
    "Descriptive data, not a certified signal; Today's Picks ignores this page.": (
        "描述性資料，非認證訊號；今日候選不會參考此頁。"
    ),
    "This snapshot predates sector classification — rebuild it to see sectors.": (
        "這份快照建立於加入產業分類之前 — 請重新建立快照以顯示產業別。"
    ),
    "Window": "區間",
    "Daily": "日",
    "Weekly": "週",
    # "Monthly" already translated ("每月") for the factors-page rebalance selector — reused here.
    "Run sector scan": "執行產業掃描",
    "Fetches recent prices for every member (cached after the first run).": (
        "抓取每檔成分股的近期股價（首次執行後會快取）。"
    ),
    "Computing sector returns…": "計算產業報酬中…",
    "No sector data to show.": "沒有可顯示的產業資料。",
    "Members": "檔數",
    "Priced": "有報酬",
    "Return %": "報酬 %",
    "vs benchmark %": "相對大盤 %",
    "Breadth %": "廣度 %",
    "members": "成分股",
    "Symbol": "代號",
    "RS vs sector %": "相對產業強弱 %",
    "Institutional flow by sector": "法人分產業買賣超",
    "Institutional flow by sector isn't built yet — build it from the Market flows "
    "page (roadmap 15.2) to see this.": (
        "分產業法人買賣超尚未建置 — 請至「市場資金流向」頁（roadmap 15.2）建立後即可顯示。"
    ),
    # --- TW market flows page (flows_page, roadmap 15.2) ---
    "💰 TW market flows": "💰 台股資金流向",
    "No flow data cached yet.": "尚未建立資金流向快取。",
    "Build today's flows": "建立今日資金流向",
    "Fetching today's market-wide flows…": "抓取今日全市場資金流向中…",
    "Fetches every TW snapshot symbol's chip data for today (cached after that).": (
        "抓取快照中每檔台股今日的籌碼資料（之後會快取）。"
    ),
    "Coverage: {covered} of {universe} TW snapshot symbols.": (
        "涵蓋範圍：{covered} / {universe} 檔快照台股。"
    ),
    "Coverage: {covered} symbols.": "涵蓋範圍：{covered} 檔。",
    "No TW rows in the snapshot — build one first.": "快照中沒有台股資料 — 請先建立快照。",
    "Market-wide net-buy by investor type": "全市場依法人別淨買賣",
    "Foreign": "外資",
    "Trust": "投信",
    "Dealer": "自營商",
    "Net-buy by sector": "分產業淨買賣",
    "Foreign NT$": "外資淨額(NT$)",
    "Trust NT$": "投信淨額(NT$)",
    "Dealer NT$": "自營商淨額(NT$)",
    "Top net buy / sell names": "買賣超排行",
    "Investor type": "法人別",
    "Side": "買賣方向",
    "Trust net-buy streak": "投信買賣超連續天數",
    "Consecutive net-buy/-sell days, longest streak first.": (
        "連續淨買超／賣超天數，天數最長者排前。"
    ),
    "Streak (days)": "連續天數",
    "Direction": "方向",
    "Foreign holding % change": "外資持股比變化",
    "Δ (pp)": "Δ（百分點）",
    # --- big-holder view (roadmap 15.3, in flows_page + chips_page) ---
    "Institutional Flows": "法人買賣",
    "Big Holders (大戶)": "大戶動向",
    "TDCC publishes this weekly, with a conservative {lag}-day availability lag — "
    "never interpolated to daily.": (
        "集保結算所每週公布，保守估計 {lag} 天後才可視為可用資料 — 不會內插成每日資料。"
    ),
    "Period": "週期",
    "No TDCC big-holder data cached yet.": "尚未建立集保大戶資料快取。",
    "Build it with: `uv run python -m heimdall.research.tdcc_cache`": (
        "請執行以下指令建立：`uv run python -m heimdall.research.tdcc_cache`"
    ),
    "Not enough accumulated weeks yet for this view.": "累積週數尚不足以顯示此檢視。",
    "No liquid (≥ the §3 floor) names in this ranking yet.": "此排行中尚無符合流動性門檻的標的。",
    "Risers — rising concentration": "集中度上升排行",
    "Fallers — falling concentration": "集中度下降排行",
    "Latest 大戶 %": "最新大戶持股比 %",
    "Big holder % (≥400 lots) vs price": "大戶持股比（≥400張）vs 股價",
    "TDCC publishes this weekly, with a conservative {lag}-day availability lag — "
    "sparse weekly points, never interpolated to daily.": (
        "集保結算所每週公布，保守估計 {lag} 天後才可視為可用資料 — 僅顯示稀疏的週資料點，"
        "不會內插成每日資料。"
    ),
    "No TDCC big-holder data cached yet for this symbol.": "此標的尚無集保大戶資料快取。",
    "Big holder %": "大戶持股比 %",
    # --- misc labels referenced inline ---
    "Field": "欄位",
    "Op": "運算子",
    "Value": "數值",
    "matches": "檔符合",
    "Regime read": "景氣循環研判",
    "Cheap & profitable": "便宜又賺錢",
    "Oversold quality": "超賣的好公司",
    "Above 200-day trend": "站上年線",
    "No rows for this market in the snapshot.": "快照中沒有這個市場的資料。",
    "No panel data (network/symbol issue).": "沒有面板資料（網路／代號問題）。",
    "⚠️ Over a **current** universe these results carry survivorship bias — today's "
    "winners are baked in. Treat returns as an optimistic upper bound, not a forecast.": (
        "⚠️ 在「當前」股票池下，這些結果帶有存活者偏差——今天的贏家已內含其中。"
        "請把報酬當成樂觀上限，而非預測。"
    ),
    # --- live track record (roadmap 16.1) ---
    "Live track record": "實時追蹤紀錄",
    "Picks are frozen the day they're shown, then scored on realized returns — no backfill.": (
        "候選在顯示當下即被凍結，之後以實現報酬計分——不回填歷史。"
    ),
    "The track record needs the research panel on disk to score frozen cohorts.": (
        "追蹤紀錄需要磁碟上的研究面板，才能為凍結的每月組合計分。"
    ),
    "No frozen cohorts yet — the live track record starts at the first monthly freeze "
    "(the scheduled `ledger freeze`, roadmap 16.2).": (
        "尚無凍結的每月組合——實時追蹤紀錄將於第一次每月凍結（排程的 `ledger freeze`）後開始。"
    ),
    "Month": "月份",
    "Frozen on": "凍結日期",
    "Frozen": "凍結檔數",
    "Unrealized (vs benchmark)": "未實現報酬（相對大盤）",
    "Unrealized uses today's prices (gross, benchmark-relative) for cohorts still inside "
    "their 6-month window; the official figures (book / universe / selection skill) stay "
    "blank until that window closes, then take over.": (
        "「未實現」是仍在 6 個月觀察期內的組合，以今日最新價格試算的報酬（相對大盤、未扣成本）；"
        "正式欄位（組合／全市場／選股技術）會等 6 個月觀察期結束才有數字，屆時以正式數字為準。"
    ),
    "Book 6m (vs benchmark)": "組合 6 個月報酬（相對大盤）",
    "Universe 6m (vs benchmark)": "全市場 6 個月報酬（相對大盤）",
    "Selection skill": "選股技術",
    "Realized": "已實現",
    # --- per-symbol live P&L breakdown (roadmap 16.1 follow-up) ---
    "Per-symbol P&L — frozen {d} · {n}/{total} priced · latest {m}": (
        "各檔即時損益 — 凍結於 {d} · 已取價 {n}/{total} 檔 · 最新 {m}"
    ),
    "Entry ({ccy})": "進場參考價（{ccy}）",
    "Latest ({ccy})": "最新價（{ccy}）",
    "Return": "報酬",
    "vs benchmark": "相對大盤",
    "Gross price return since each name was frozen (nothing sold — no costs); "
    "“vs benchmark” subtracts {bench} over the same window.": (
        "自各檔凍結日起的價格報酬（未賣出、未扣成本）；「相對大盤」為同期間減去 {bench} 的報酬。"
    ),
    "Followed every month": "逐月跟單",
    "Growth of 1 (net of {bps} bps/side)": "1 元的成長（已扣每邊 {bps} bps 成本）",
    "Certified {d} · live since {m} · survivorship: current universe (optimistic).": (
        "認證於 {d} · 自 {m} 起實時追蹤 · 存活者偏差：當前股票池（樂觀上限）。"
    ),
    # --- rebalance helper (roadmap 16.3) ---
    "Rebalance helper": "再平衡輔助",
    "An execution aid, not an order system, not advice; orders are placed at your broker.": (
        "這是執行輔助工具，並非下單系統，也非投資建議；請自行至券商下單。"
    ),
    "Budget": "投入資金",
    "Allow odd lots (TW)": "允許零股（台股）",
    "Changes vs last frozen cohort": "相對上次凍結組合的異動",
    "Added": "新增",
    "Dropped": "移除",
    "Kept": "續留",
    "Order plan (equal-weight)": "下單計畫（等權重）",
    "Shares": "股數",
    "Reference close": "參考收盤價",
    "Est. cost": "預估成本",
    "Download order plan (CSV)": "下載下單計畫（CSV）",
    "No frozen cohort yet to diff against — freeze one first (roadmap 16.1/16.2).": (
        "尚無可比對的凍結組合——請先凍結一次（roadmap 16.1/16.2）。"
    ),
    "buy": "買進",
    "sell": "賣出",
}


def current_lang() -> str:
    return str(st.session_state.get("lang", "zh"))


def t(text: str) -> str:
    """Translate ``text`` for the active language (English source falls through)."""
    return _ZH.get(text, text) if current_lang() == "zh" else text


def language_selector() -> str:
    """Render the sidebar language picker and record the choice. Returns the code."""
    choice = st.sidebar.selectbox("🌐 Language / 語言", list(LANGUAGES), key="lang_choice")
    st.session_state["lang"] = LANGUAGES[choice]
    return LANGUAGES[choice]

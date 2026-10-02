"""In-app user guide — how to use Heimdall and, above all, how to *read* the
numbers on each page.

Long-form bilingual content lives here as data (not in ``i18n.t``, which is for
short labels). ``render`` lays it out as: intro → the three trust levels → quick
start → reading conventions → one collapsible guide per page, grouped exactly like
the sidebar (``_nav.NAV``, so a new page cannot ship without its guide entry).

Chinese markdown note: CommonMark only closes ``**bold**`` when the closing ``**``
is not squeezed between full-width punctuation and a CJK character, so write
``**先看這裡**。`` (punctuation outside), never ``**先看這裡。**到`` — the latter
renders as literal asterisks. ``tests/test_help_page.py`` enforces this.
"""

from __future__ import annotations

import streamlit as st

from heimdall.ui._nav import NAV
from heimdall.ui.i18n import current_lang, t

_INTRO = {
    "en": (
        "**Heimdall** is a personal stock-picking tool built on one rule: *only trust evidence "
        "that has been validated*. US and Taiwan are supported; every figure is shown in that "
        "market's own currency (**USD / TWD**)."
    ),
    "zh": (
        "**Heimdall** 是個人用的選股工具，核心原則只有一條：*只相信驗證過的證據*。"
        "支援美股與台股，所有數字都以該市場的幣別（**USD / TWD**）顯示。"
    ),
}

# Which pages you may act on — the one idea a new user most needs, stated before anything else.
_TRUST = {
    "en": (
        "- 🟢 **Certified — Today's Picks.** The only list backed by out-of-sample "
        "certification: a signal appears there only after passing strict tests on data it was "
        "never tuned on. This is the page to act on (it is still not personal investment "
        "advice).\n"
        "- 🟡 **Incubating — Strategy Lab.** Strategies that passed the factory's over-fitting "
        "checks and one validation look, now tracked forward month by month. Watch them; don't "
        "act on them yet.\n"
        "- ⚪ **Descriptive — every other page.** Stock Workbench, the Screener, Factors, "
        "Backtest and the analyst lenses help you understand a stock or the market. Their "
        "numbers are not certified and are not buy/sell signals."
    ),
    "zh": (
        "- 🟢 **已認證——今日候選**：唯一經過樣本外認證的清單。訊號必須在從沒拿來調參的資料上"
        "通過嚴格檢驗，才會出現在這裡。要據以行動的是這一頁（但它仍不是個人化的投資建議）。\n"
        "- 🟡 **孵化中——策略實驗室**：通過策略工廠過度擬合檢查與一次驗證期檢視的策略，"
        "正逐月往前追蹤。可以觀察，先不要照著做。\n"
        "- ⚪ **描述性——其他所有頁面**：個股工作台、選股器、多因子、回測與各分析師視角，"
        "幫你理解個股與市場；數字沒有經過認證，也不是買賣訊號。"
    ),
}

_QUICKSTART = {
    "en": [
        "**Open Today's Picks first.** When a market has a certified signal, read its evidence "
        "box (beat rate, selection skill, OOS cohorts) before the ranked list; each month the "
        "**Rebalance helper** at the bottom turns the list into a downloadable order plan. When "
        "a market has no certified signal the page is deliberately empty — honesty, not a bug.",
        "**Keep the data fresh.** Today's Picks, the Screener, Factors and Stock Workbench all "
        "read the *snapshot*. When a page shows 🟡/🔴 or says it is stale, refresh it in "
        "**Data → Build data**. Each market needs its own rows: Taiwan rankings need Taiwan "
        "stocks in the snapshot.",
        "**Research one stock.** Type a symbol in **Stock Workbench** (e.g. `AAPL.US`, "
        "`2330.TW`): the Overview gives a one-line read per lens, the tabs give chart, "
        "fundamentals, technicals, risk and earnings. Ticking a Screener result row opens it "
        "there too.",
        "**Find candidates.** The **Screener** filters by your own conditions and **Factors** "
        "ranks by a 0–100 composite. Both are descriptive: a match is a lead to research, not "
        "a buy signal.",
        "**Follow the research.** **Strategy Lab** shows what the Strategy Factory searched and "
        "backtested by itself; only its *Incubating* tab is worth tracking. **Backtest** is a "
        "single-stock sandbox — always compare its result with simply holding the stock, and "
        "treat every figure as an optimistic upper bound.",
        "Switch **English / 繁體中文** at the top of the sidebar. Every ⓘ next to a metric — "
        "and the **Glossary** page — explains it in plain words.",
    ],
    "zh": [
        "**先看「今日候選」**。某個市場有已認證訊號時，先讀證據框（贏過基準的比率、選股技術、"
        "樣本外期數），再看排名清單；每月換股時，用頁面最下方的「**再平衡助手**」下載下單計畫。"
        "沒有已認證訊號時，這頁會刻意留白——這是誠實，不是故障。",
        "**資料要夠新**。今日候選、選股器、多因子、個股工作台都讀同一份「快照」。頁面出現 🟡/🔴 "
        "或「已過期」時，到「**資料 → 建立資料**」更新。每個市場要有自己的資料：台股排名需要快照"
        "裡有台股。",
        "**研究單一股票**。在「**個股工作台**」輸入代號（例如 `AAPL.US`、`2330.TW`）：總覽給每個"
        "視角一句話結論，分頁看圖、基本面、技術面、風險與財報。在選股器結果勾選某一列，也能直接"
        "開到這裡。",
        "**找候選名單**。「**選股器**」用你自己的條件篩，「**多因子**」用 0–100 綜合分數排名。"
        "兩者都是描述性的：符合條件代表值得研究，不代表買進訊號。",
        "**追蹤研究進度**。「**策略實驗室**」顯示策略工廠自動搜尋、回測的結果，只有「孵化中」"
        "分頁值得持續追蹤。「**回測**」是單一股票的策略沙盒——一定要和「直接買進持有」比較，"
        "而且每個數字都請當成樂觀上限。",
        "左側欄最上方可隨時切換 **English / 繁體中文**。指標旁的 ⓘ 和「**指標辭典**」頁都有"
        "白話解釋。",
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
        "- **方向性**。估值倍數（P/E、P/S、EV/EBITDA）**越低越便宜**；獲利與成長（ROE、利潤率、"
        "成長率）**越高越好**。\n"
        "- **幣別**。金額欄位（市值、營收、EV…）以該市場幣別計價，所以像 `market_cap > 1e9` 的門檻"
        "在 USD 與 TWD 意義差很多——**跨市場不可直接比較**。\n"
        "- **缺資料 = 排除**。某股缺某指標時，它會在該條件被淘汰，不會被偷偷放行。\n"
        "- **情境僅供參考**。估值區間與回測數字都是參考，不是保證。"
    ),
}

# Chart, Fundamental, Technical, Risk, and Earnings are tabs inside Stock Workbench, not
# separate pages — but each still gets its own expander, since the *reading* guide doesn't
# care where a lens is mounted.
_WORKBENCH_TABS: list[str] = ["Chart", "Fundamental", "Technical", "Risk", "Earnings"]


def _sections() -> dict[str, list[str]]:
    """The sidebar's own grouping (``_nav.NAV``) minus the guide itself, Help moved last
    (you are already reading it), with the Workbench's lens tabs right after the Workbench."""
    out: dict[str, list[str]] = {}
    for group, pages in sorted(NAV.items(), key=lambda kv: kv[0] == "Help"):
        keys: list[str] = []
        for page in pages:
            if page == "Guide":
                continue
            keys.append(page)
            if page == "Stock Workbench":
                keys.extend(_WORKBENCH_TABS)
        if keys:
            out[group] = keys
    return out


# Per-page guide, focused on *reading* the indicators. {page: {icon, en, zh}}.
_PAGES: dict[str, dict[str, str]] = {
    "Build data": {
        "icon": "🗂",
        "en": (
            "Build or refresh the *snapshot* — one table of every stock's latest price, "
            "fundamentals and indicators. Today's Picks, the Screener, Factors, Stock Workbench, "
            "Sector Focus and the order plans all read it.\n\n"
            "- **Current snapshot** (top): symbols per market (a market at 0 cannot be ranked) "
            "and the as-of date.\n"
            "- **Prerequisite lights:** `SEC_EDGAR_USER_AGENT` (US fundamentals) and `FINMIND_TOKEN` "
            "(Taiwan quota). Unset → some names come back price-only.\n"
            "- **Quick** tab = tens–hundreds of names, in-app with a progress bar. It never removes "
            "other symbols; *Re-fetch* only forces the listed symbols to be fetched again.\n"
            "- **Whole market** tab = VTI / all-Taiwan as a background crawl you can leave and "
            "resume. A normal run refreshes every row not built today. *Rebuild from scratch* "
            "empties the whole snapshot first, so it asks you to confirm."
        ),
        "zh": (
            "建立或更新「快照」——一張表，存放每檔股票最新的股價、財報與指標。今日候選、選股器、"
            "多因子、個股工作台、產業焦點與下單計畫都讀它。\n\n"
            "- **目前快照**（最上方）：各市場幾檔（某市場為 0 檔就無法排名）、資料日期。\n"
            "- **前置條件燈號：**`SEC_EDGAR_USER_AGENT`（美股財報）、`FINMIND_TOKEN`（台股額度）。"
            "沒設的話部分標的只會有股價。\n"
            "- **快速**分頁＝數十到數百檔，網站內跑、有進度條。它不會刪掉其他代號；「重新抓取」"
            "只是強制把列出的代號再抓一次。\n"
            "- **全市場**分頁＝VTI／全台股的背景爬取，可離開頁面、可續跑。一般執行就會更新所有"
            "不是今天建的資料。「從頭重建」會先清空整個快照，所以會要求你確認。"
        ),
    },
    "Today's Picks": {
        "icon": "🎯",
        "en": (
            "The only actionable page — certified signals only.\n\n"
            "- **Market** — US or Taiwan; each market has its own certified signals.\n"
            "- **Evidence box (read it first)** — *Beat rate*: how often the 6-month book beat "
            "the benchmark out-of-sample, with its 95% CI. *Selection skill*: return above an "
            "equal-weight book of the same universe — the edge that was certified. *IC*: how well "
            "the score ranks future returns. *OOS cohorts*: how many independent months back the "
            "claim.\n"
            "- **Picks table** — today's ranked names; the `z_…` columns show why each one ranks "
            "(its strength vs today's eligible pool).\n"
            "- **Live track record** — each month's picks are frozen the day they are shown and "
            "scored later on realized returns; nothing is backfilled.\n"
            "- **Rebalance helper** — what changed since the last frozen list, plus a "
            "downloadable order plan. An execution aid, not advice.\n"
            "- **An empty page** means no signal has passed certification for that market yet. "
            "If a certified signal shows but the ranking is missing, the snapshot lacks that "
            "market's stocks — build them on **Build data**."
        ),
        "zh": (
            "唯一可以據以行動的頁面——只顯示已認證訊號。\n\n"
            "- **市場** — 美股或台股，各自有各自的已認證訊號。\n"
            "- **證據框（先看這裡）** — *贏過基準的比率*：樣本外期間，6 個月持有的組合贏過基準的"
            "頻率，附 95% 信賴區間。*選股技術*：相對同一股票池等權重組合多賺的報酬——這才是被認證"
            "的優勢。*IC*：分數排序對未來報酬的預測力。*樣本外期數*：有幾個獨立月份支持這個結論。\n"
            "- **排名表** — 今天的排名；`z_…` 欄說明每檔為什麼排在這裡（相對今日合格池的強度）。\n"
            "- **實盤追蹤紀錄** — 每個月的名單在顯示當天就凍結，之後用實際報酬計分，不會事後補登。\n"
            "- **再平衡助手** — 和上次凍結名單相比的增減，加上可下載的下單計畫。是執行輔助，"
            "不是投資建議。\n"
            "- **整頁空白**代表這個市場還沒有訊號通過認證。如果有已認證訊號、卻沒有排名，代表快照"
            "裡沒有這個市場的股票——到「**建立資料**」補建。"
        ),
    },
    "Strategy Lab": {
        "icon": "🔬",
        "en": (
            "What the Strategy Factory found by itself — research results, **uncertified**.\n\n"
            "- **Search runs** — each declared search and its trial count **N**. The more "
            "combinations a search tries, the easier it is to find one that only looks good by "
            "luck, so every number here is judged against N.\n"
            "- **Leaderboard** — every trial ranked on development data (2010–2019). *DSR* "
            "(deflated Sharpe) discounts the Sharpe for N trials; *PBO* is the probability the "
            "winner is over-fit — lower is better. *Candidates* passed gates F1–F3 and F5.\n"
            "- **Strategy detail / Walk-forward** — a candidate's daily backtest, and a re-run "
            "of the whole selection procedure year by year using only data known at the time.\n"
            "- **Incubating** — passed the over-fitting gates and one validation look; now "
            "tracked forward. Watch, don't act.\n"
            "- Nothing here reaches Today's Picks until it is certified. A run with zero "
            "candidates is a normal, honest outcome."
        ),
        "zh": (
            "策略工廠自己搜尋出來的結果——研究用、**未認證**。\n\n"
            "- **搜尋批次** — 每次預先登記的搜尋，以及它的試驗數 **N**。試越多組合，越容易碰巧"
            "找到只是運氣好的策略，所以這裡每個數字都要對照 N 來看。\n"
            "- **排行榜** — 每個試驗在開發期資料（2010–2019）上的排名。*DSR*（平減夏普）是依 N "
            "打折後的夏普；*PBO* 是「勝出者其實是過度擬合」的機率，越低越好。*候選策略*＝通過 "
            "F1–F3 與 F5 關卡。\n"
            "- **策略詳情 / 滾動前推驗證** — 候選策略的逐日回測，以及「每年只用當時已知資料重新"
            "挑選」的整套流程回測。\n"
            "- **孵化中** — 通過過度擬合關卡與一次驗證期檢視，正在往前追蹤。可以觀察，先不要照著做。\n"
            "- 這裡的東西在通過認證之前，都不會出現在今日候選。一個批次 0 個候選策略，是正常且"
            "誠實的結果。"
        ),
    },
    "Glossary": {
        "icon": "📚",
        "en": (
            "Every metric in the app, searchable: what it means, and whether higher or lower is "
            "better. It is the same text as the ⓘ tooltips next to each number."
        ),
        "zh": "全站每個指標都查得到：它代表什麼、越高越好還是越低越好。內容和每個數字旁的 ⓘ 提示相同。",
    },
    "TW Chips": {
        "icon": "💰",
        "en": (
            "Taiwan only — who is buying one stock.\n\n"
            "- **Cumulative net-buy vs price** — 外資 (foreign) and 投信 (investment trust) daily "
            "net buying added up over time, against the price; both rising together means "
            "institutions are accumulating.\n"
            "- **Foreign holding % and margin balance** — the foreign ownership share, and 融資 "
            "(retail margin borrowing).\n"
            "- **Big holder %** — TDCC's weekly share held by ≥400-lot holders.\n"
            "- Descriptive data, not a signal. Needs FinMind data for Taiwan."
        ),
        "zh": (
            "僅限台股——看誰在買這檔股票。\n\n"
            "- **累計買賣超 vs 股價** — 外資、投信的每日買賣超累加起來，和股價對照；兩者一起上升"
            "代表法人在吸籌。\n"
            "- **外資持股比率與融資餘額** — 外資持股占比，以及散戶融資的變化。\n"
            "- **大戶持股比率** — 集保（TDCC）每週公布的 400 張以上大戶持股占比。\n"
            "- 描述性資料，不是訊號。需要 FinMind 的台股資料。"
        ),
    },
    "Sector Focus": {
        "icon": "🏭",
        "en": (
            "Which industries lead, and who leads inside them.\n\n"
            "- **Sector table** — each sector's average return over the chosen window (day / "
            "week / month), its return vs the benchmark, and *breadth* (the share of its members "
            "that rose).\n"
            "- **Member tables** — each stock's return and its strength vs its own sector.\n"
            "- Taiwan adds institutional flow by sector once **TW Market Flows** has been built. "
            "Descriptive, not a signal."
        ),
        "zh": (
            "看哪些產業領先、產業裡又是誰領先。\n\n"
            "- **產業表** — 各產業在所選區間（日 / 週 / 月）的平均報酬、相對基準的報酬，以及"
            "*上漲家數比*（成分股中上漲的比例）。\n"
            "- **成分股表** — 每檔股票的報酬，以及相對自己產業的強弱。\n"
            "- 台股在建好「**台股資金流向**」後，會多出各產業的法人買賣超。描述性資料，不是訊號。"
        ),
    },
    "TW Market Flows": {
        "icon": "💸",
        "en": (
            "Taiwan market-wide money flow.\n\n"
            "- **Institutional Flows** — net buying by investor type (foreign / trust / dealer) "
            "and by sector, the top net-buy and net-sell names, 投信 buying streaks, and changes "
            "in foreign holding %. Press **Build today's flows** first; it needs Taiwan stocks in "
            "the snapshot.\n"
            "- **Big Holders (大戶)** — weekly risers and fallers in the share held by ≥400-lot "
            "holders (TDCC), with illiquid names left out.\n"
            "- Descriptive data, not a signal."
        ),
        "zh": (
            "台股全市場的資金流向。\n\n"
            "- **法人買賣** — 依身分（外資 / 投信 / 自營商）與依產業的買賣超、買超與賣超前幾名、"
            "投信連續買超，以及外資持股比率變化。先按「**建立今日資金流向**」；快照裡要有台股才"
            "抓得到。\n"
            "- **大戶動向** — 集保每週公布的 400 張以上大戶持股，增加最多與減少最多的股票"
            "（已排除流動性太低的）。\n"
            "- 描述性資料，不是訊號。"
        ),
    },
    "Stock Workbench": {
        "icon": "🔎",
        "en": (
            "One symbol, every per-stock lens — pick it once at the top, then explore via "
            "tabs.\n\n"
            "- **Overview** — a one-line read from each lens (rating, trend, risk, next "
            "earnings); open a tab below for the full picture. Any lens that fails (e.g. no "
            "FMP key) just shows '—', it never blocks the others.\n"
            "- **Chart / Fundamental / Technical / Risk / Earnings** — the full dashboards, each "
            "explained in its own section below.\n"
            "- Symbols are `TICKER.MARKET` (`AAPL.US`, `2330.TW`); the quick-pick lists every "
            "stock in the snapshot. Everything here is descriptive, not a signal."
        ),
        "zh": (
            "一次輸入代號，切換分頁看每個視角。\n\n"
            "- **總覽** — 每個視角一句話結論（評級、趨勢、風險、下次財報）；想看完整內容點下方"
            "分頁。任一視角失敗（例如沒設 FMP 金鑰）只會顯示「—」，不會卡住其他視角。\n"
            "- **個股圖 / 基本面 / 技術面 / 風險 / 財報** — 完整儀表板，下方各有一段說明。\n"
            "- 代號格式是 `TICKER.MARKET`（`AAPL.US`、`2330.TW`）；快速挑選會列出快照裡的所有股票。"
            "這裡的內容都是描述性的，不是訊號。"
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
            "**Tips** — the *typical range* panel shows each field's P10 / median / P90 in this "
            "pool, so a threshold isn't a blind guess; untick **On** to relax a condition (extra "
            "rows get a ➕); tick a result row's left-hand box to open it in Stock Workbench; you "
            "can save a screen with a description and delete it.\n\n"
            "A match is a lead to research, not a buy signal."
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
            "**小技巧** — 「常見範圍」面板列出每個欄位在這個池子裡的 P10 / 中位數 / P90，門檻不用"
            "瞎猜；取消「啟用」可放寬條件（多出來的股票標 ➕）；勾選結果列最左側的方框，可在個股"
            "工作台開啟該股票；條件組可加描述存檔、也可刪除。\n\n"
            "符合條件代表值得研究，不代表買進訊號。"
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
            "Test an entry/exit rule on one stock's history — a sandbox, outside certification.\n\n"
            "- **Compare with buy-and-hold.** A rule that trails simply holding the stock adds "
            "no value, even when its own return is positive.\n"
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
            "在單一股票的歷史上測試進出場規則——是沙盒，不在認證範圍內。\n\n"
            "- **一定要和「買進持有」比較**。報酬是正的，但輸給直接抱著不動，就代表這個規則沒有加分。\n"
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
            "- **Plan box** — current price, then two ways in: a **pullback** to support or a "
            "**breakout** above resistance, each with an entry, a **stop**, and targets (1R–3R).\n"
            "- **Trend** — short / mid / long-term direction (U = up, D = down, S = sideways).\n"
            "- Stops are **ATR-based** (volatility): stop = entry − N×ATR; 1R is the risk unit, "
            "2R / 3R are reward-to-risk multiples.\n"
            "- The plan is a mechanical framing of price levels, not a validated signal."
        ),
        "zh": (
            "摩根士丹利視角 — 把零散訊號整理成一份交易計畫。\n\n"
            "- **計畫框** — 先列現價，再列兩種進場方式：**回檔**到支撐買進，或**突破**壓力買進，"
            "各有進場價、**停損**與目標價（1R–3R）。\n"
            "- **趨勢** — 短 / 中 / 長期方向（U＝上升、D＝下降、S＝盤整）。\n"
            "- 停損以 **ATR**（波動度）為基礎：停損＝進場 − N×ATR；1R 是風險單位，2R / 3R 是報酬"
            "風險比。\n"
            "- 這份計畫是依價格位置機械式整理出來的，不是經過驗證的訊號。"
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

    st.subheader(t("Three levels of trust"))
    st.markdown(_TRUST[lang])

    st.subheader(t("Quick start"))
    for i, step in enumerate(_QUICKSTART[lang], start=1):
        st.markdown(f"{i}. {step}")

    with st.expander(t("Reading the numbers — conventions")):
        st.markdown(_CONVENTIONS[lang])

    st.subheader(t("How to read each page"))
    for section, pages in _sections().items():
        st.markdown(f"#### {t(section)}")
        for key in pages:
            guide = _PAGES[key]
            with st.expander(f"{guide['icon']} {t(key)}"):
                st.markdown(guide[lang])

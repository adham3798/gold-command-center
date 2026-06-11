# Gold Command Center — System Overview & Handoff

> A self-contained handoff document. Assumes **zero** prior context. Share this in a fresh
> chat (with another AI or a developer) to review and improve the system.
>
> **Honesty note up front:** every performance number in this document is **in-sample** —
> the rules were developed and tuned on the same ~17 months of data they're measured on.
> Nothing has been tested out-of-sample yet. Treat all "edges" as hypotheses, not proven facts.

---

## 1. What the system is

**Gold Command Center** is a **decision-support dashboard for trading spot gold (XAU/USD)** on the
**daily** timeframe, executed/managed on the **4-hour** timeframe, with an **astrology / moon-sign
overlay** as optional context.

- **Live URL:** https://gold-command-center.onrender.com (the dashboard is at `/gold`)
- **Hosting:** Render, **free tier** (single web service; ⚠️ ephemeral disk + sleeps after ~15 min idle — see §6, §8)
- **Source control:** GitHub `adham3798/gold-command-center` (Render auto-deploys from `main`; free-tier auto-deploy is often throttled → frequently needs a **Manual Deploy** from the Render dashboard)
- **It is NOT an auto-trader.** It places nothing with a broker. It produces a **suggested direction, entry, stop, and target** and tracks how those calls would have done.

### High-level data flow
```
Google Sheet (the user maintains the data)
   │   tabs: gold_price (daily spot OHLC), MOON_REAL (moon signs + ingress text),
   │         SIGN_LIBRARY, MOON_PHASE_LIBRARY, H1_DATA, H4_DATA, WEEKLY_FORECAST
   ▼  read-only via gviz CSV export  (no write credentials anywhere in the app)
Flask app (app.py on Render)
   │   builds the daily signal, the 4H plan, trends, journals, narratives
   ▼  JSON APIs
Dashboard (templates/index.html, single-page) + live spot price (gold-api.com)
```
The app **reads** the sheet; it never writes to it. Durable write-back (for the journals) is done
via an optional Google Apps Script webhook the user sets up (see §8, §11).

---

## 2. Architecture & key files

This is a **Flask** app. The bulk of the logic lives in **one large `app.py` (~2,750 lines)** — a
known smell; see §10 for the recommended split.

| File | Lines | Role |
|---|---|---|
| `app.py` | ~2,753 | **Everything live**: data load, signal engine glue, 4H plan, trends/Reversal Watch, journals, trade engine wiring, Week Story, all Flask routes + the background refresh/roll loops. |
| `engine.py` | ~369 | The **daily astro signal engine** — moon sign/phase/day-number/history scoring that produces the base BUY/SELL/WAIT and confidence. |
| `strategy_4h.py` | ~187 | **Canonical statement of the 4-hour strategy** (direction = daily signal; entry = pivot; stop/target = ATR-based; BE trail). Reference + standalone backtest; `app.py` implements the same rules live. |
| `journal.py` | ~129 | **Prediction journal** (append-only): logs the day's *direction* call before the close, grades win/loss after (BUY wins if close>open), Wilson 95% CI. The "was the direction right?" scorecard. |
| `trade_journal.py` | ~265 | **Trade engine + journal**: real-rules lifecycle — entry confirms only on a **4H close**, stop/take exit **on touch** (1H), trend-break + 3-day time stop, honest fills. The "did the actual trade make money?" scorecard (primary). |
| `news.py` | ~77 | USD high-impact news fetch/cache (Forex Factory) for the calendar. |
| `notify.py` | ~68 | Telegram alert sender (optional; needs a bot token). |
| `templates/index.html` | large | The **entire single-page dashboard** (HTML + CSS + JS). `shell.html` is the tab-shell wrapper. |
| `data_cache.json` | — | Offline snapshot written after each successful sheet load; lets the app boot if the sheet/internet is unavailable. |
| Backtest/analysis scripts | — | `backtest_current.py` (canonical current-rules backtest), `backtest_4h*.py`, `backtest_v4..v7.py` (formula evolution), `reversal_study.py`, `reversal_fix_study.py`, `analyze_*.py`. **All in-sample.** |
| `README.md`, `DEPLOY.md` | — | Setup/deploy notes. |

State files (all **git-ignored** and **ephemeral on Render**): `prediction_journal.json`,
`trade_journal.json`, `alert_log.json`, `spot_session.json`, `telegram_sent.json`, `setup_sent.json`.

> ⚠️ The user (and earlier notes) referenced a `walk_forward.py` and a "refactor guide" — **neither
> exists in the repo**. Out-of-sample walk-forward testing is **not yet built** (see §10). The
> refactor is a recommendation, not a document.

---

## 3. The signal logic (full precedence chain)

For any date, `build_day(date)` produces the signal by applying rules in **precedence order** — each
later rule can override the earlier one:

1. **Sheet forecast (base).** The user's own `WEEKLY_FORECAST` tab gives an Expected Direction +
   buy/sell scores. If present, this is the starting signal (`signal_src='sheet'`).
2. **Engine fallback.** If the sheet has no forecast for the day, `engine.py` computes the direction
   from the moon sign/phase/history.
3. **Rule 2 — movable-sign 2-day PULLBACK.** Moon signs have a *nature*: **MOVABLE / FIXED / FINISHER**.
   On the **2nd day of a movable-sign run**, the rule expects a mean-reversion **pullback** and
   *reverses* the prior day's direction (`signal_src='pullback'`). This overrides 1–2.
4. **Decision-Day continuation (highest priority).** A **Decision Day** = a day that closed within
   **±$10** (`DECISION_MAX=10`) — the market "paused/undecided." The **next** trading day is expected
   to **resume the trend** (net direction of the 3 days *before* the decision day). This overrides
   everything (`signal_src='decision'`).

### Filter B — the hard-downtrend veto (added after a real loss)
**The Jun-10-2026 bug:** the sheet correctly said **SELL** (buy 28 / sell 65), but Jun 9 and Jun 10
were **both Aries (MOVABLE)**, so the Rule-2 pullback flipped the signal to **BUY** — a counter-trend
"bounce" bet. Gold then dropped ~**$150**. The user bought and lost.

**Filter B fix:** before applying a pullback flip to **BUY**, check for a **hard downtrend** —
`daily trend = DOWN` **and** 5-day net `< −$80` (`HARD_DOWN_NET`) **and** `4H = DOWN` **and** `1H = DOWN`.
If all true, the pullback BUY is **vetoed** and the signal **reverts to the underlying sheet signal**
(SELL on Jun 10). This is **surgical**: across all history it touches only ~1 historical trade + the
Jun-10-type live case, so the backtest is **unchanged (PF 1.52)** — it removes a known failure mode
without harming the profitable counter-trend trades (those keep PF ~1.7; see §9). The 4H+1H guard is
what keeps it surgical: it spares pullbacks where the faster timeframes are already turning up.

---

## 4. The 4-hour execution system

**Core idea (validated in-sample):** keep the **daily** signal as the brain, but **execute on 4H**.
A pure-4H signal *loses*; daily-decides-direction + 4H-execution *keeps the edge*.

Rules (`strategy_4h.py`, implemented live in `app.py`):
1. **Direction** = the daily signal (BUY/SELL).
2. **Entry** = the **classic pivot point** of the signal day, `PP = (prevHigh + prevLow + prevClose)/3`.
   Fill happens when a 4H candle trades to the pivot. (Decision-day plans use an $8–10 zone entry instead.)
3. **Stop & target = ATR-based** (the version that won):
   - unit = **4H ATR**; **stop distance = 1.5 × 4H-ATR** (`H4_ATR_MULT=1.5`)
   - **target = 1:1** (`H4_RR=1.0`)
   - **breakeven trail:** when price travels 50% toward the target, the stop moves to entry → the
     trade can then only **WIN (+1R)** or **break even (0)**.
   - Conservative fills: within one 4H candle the adverse move is assumed first.

**Why ATR beat the "smart" version:** an earlier iteration used **level-based / ~$20 fixed stops**.
Backtest: that version was a **loser, PF ≈ 0.50**. Reverting to **1.5×ATR stops flipped it to
PF ≈ 1.52** (and max drawdown from ~−37R to ~−3R). Lesson on record: the over-engineered version was
worse than the simple ATR rule.

### The trade engine (`trade_journal.py`) — "did the real trade make money?"
A separate, stricter lifecycle that mirrors how you'd actually trade:
- **Entry confirms ONLY on a 4H CLOSE** through the zone (a 1H candle can spike and still close against you → no fill).
- **Stop/Take exit IMMEDIATELY on touch** (watched on the 1H feed) — risk control can't wait 4 hours.
- **Trend-break exit:** 3 consecutive 4H closes against the position.
- **Time stop:** max 18 4H candles (~3 days); entry expires after 6 4H closes unfilled.
- **Honest accounting:** fill = the confirming 4H close (slippage vs the planned level is logged);
  gap-opens fill at the worse price; if one candle touches both stop and take, the **stop wins**
  (pessimistic). `COST_PER_TRADE = $0.50` round-trip. Stats: win%, Wilson 95% CI, total P&L, avg R,
  expectancy, avg slippage, exit-reason breakdown.

Both journals appear on the dashboard: **"📈 Live Track Record"** (trade engine, primary) and
**"🎯 Prediction Scorecard"** (direction-only, secondary). Both start empty and build **forward**
(no back-fill — that's deliberate, so they are un-fakeable).

---

## 5. Multi-timeframe trend, Reversal Watch, wait-for-4H safeguard

`_trend_of(candles, n)` classifies a timeframe as **UP / DOWN / FLAT** from the net move over the last
`n` candles (FLAT when |net| < 0.25 × range). Applied to daily (5), 4H (6), 1H (8) → the **trend cards**.

**Two bugs fixed here (both important):**
- **Candle text-sort bug:** the sheet's `H4_DATA` stores **non-zero-padded hours** (`"7:00:00"`).
  Sorting timestamps **as strings** put single-digit hours *after* `"23:00"`, scrambling "the last 6
  candles" — so the 4H trend once showed **UPTREND (+$42)** while gold was **crashing**. Fix: `_cdt()`
  parses every timestamp to a real datetime and sorts **chronologically**.
- **Closed-candles-only:** the live Yahoo feed returns the **currently-forming** bar; an intrabar tick
  could flip a trend. Fix: drop any candle whose hour hasn't closed (`open + 1h > now_utc`).

**Reversal Watch** (down→up) from the three trends:
- 🔴 **DOWNTREND** — daily down, fast TFs not both up.
- 🟡 **EARLY REVERSAL** — `daily DOWN` **and** `4H UP` **and** `1H UP`. **In-sample finding:** when this
  fired, the daily trend confirmed up within 5 days **~88%** of the time (n≈16–25, small). The *daily
  flip alone* had no edge over baseline — the **cascade** is the signal.
- 🟢 **CONFIRMED UPTREND** — daily up.

**Wait-for-4H safeguard:** whenever the daily signal direction is **not matched by the 4H trend**, the
dashboard's "Today's Action" shows **"⏳ WAIT — daily says X but the 4-hour isn't Y yet; hold for the
4H to confirm (protect the account)."** This is the same discipline encoded in the trade engine
(4H-close confirmation) and the Week Story's action line.

---

## 6. Trading-day / timing model

**Gold's daily candle rolls at 5:00pm New York**, *not* UTC midnight. In summer (EDT) that's 21:00 UTC
= **1:00am Dubai**; in winter (EST) 22:00 UTC = **2:00am Dubai**.

- `_trading_day()` / `_trading_dt()` (DST-correct via `pytz` `America/New_York`): the trading session =
  **NY calendar date, +1 day if NY local time ≥ 17:00.** This replaced ~16 `datetime.today()` (UTC) uses,
  removing a 3-hour lag where the dashboard kept showing the old day's plan from 1am–4am Dubai.
- A **session "as of" bar** at the top of the dashboard states which session's plan you're viewing
  (e.g. *"Plan for trading day Thu Jun 11 (session 5pm-NY Jun 10 → 5pm-NY Jun 11) · refreshed … Dubai/NY"*).
- **`/api/roll`** — one idempotent call that reloads the sheet, records the journal, grades, places the
  trade setup, and drives the engine — so the new day's plan is live within the first hour of the session.
  An **in-process scheduler** fires it daily at **17:05 America/New_York**.
- ⚠️ **Render free tier sleeps after ~15 min idle**, which kills the scheduler + the 5-min refresh loop.
  → A **free external keep-warm ping (UptimeRobot)** hitting the URL every ~5 min is **required** for the
  roll to fire reliably when nobody has the page open (see §11).

---

## 7. Data feeds & the spot-vs-futures issue

- **Daily OHLC** (`gold_price` tab) = **spot XAU/USD**, the user's own data → reliable; pivots/entries/
  stops are computed from this.
- **Live price** = **gold-api.com `XAU` (spot)** → reliable.
- **Intraday 1H/4H** — the sheet's H1/H4 tabs **lag**, so the app fills recent bars from a live feed:
  - **preferred: Twelve Data `XAU/USD` (spot)** — used **only if `TWELVEDATA_KEY` is set**;
  - **fallback: Yahoo `GC=F` — COMEX gold *futures*** (no key needed). ⚠️ **This is a different
    instrument** with a **variable, delayed basis** to spot (measured anywhere from **+$20 to −$46**).

**Consequence (a real bug we fixed partially):** the "Today running High/Low" was reading off the Yahoo
**futures** bars, so the high once sat **above** spot and the low missed the true spot low (~$4,024 read
as ~$4,058). Fix: today's High/Low now **exclude futures-tagged candles** and anchor to a **spot session
high/low** sampled from the live spot feed (reset at the 5pm-NY roll), with an honest on-card label.
**Limitation:** without a spot-intraday-history source, the range only builds at sample resolution and
can miss a momentary wick. **The complete fix is data-side: set `TWELVEDATA_KEY`** — then the *entire*
intraday feed becomes spot (and the trends/trade-engine fills get accurate too).

---

## 8. Journals & persistence

Two independent, forward-only scorecards (see §4) plus a **Daily Alerts log** (one row per day:
date, direction, with-trend/counter-trend, wait-4H flag, entry/stop/target, outcome).

**Persistence problem:** Render's free disk is **ephemeral** — every redeploy wipes the local JSON
state files. Solutions implemented:
- **Daily Alerts log** is **derived** from the engine (`/api/alerts`), so it always rebuilds — no storage needed.
- **Journals + trade record** are mirrored to the **Google Sheet** via an optional **Apps Script
  webhook** (env var **`ALERT_WEBHOOK_URL`**): alerts → `ALERT_LOG` tab, prediction journal → `JOURNAL`
  tab, trade engine → `TRADES` tab (full JSON blob per trade + a `__last_seen__` row). On boot the app
  **auto-restores** the journals/trades from those tabs (merge-by-key, local-current-run wins).
- ⚠️ **Until the user sets `ALERT_WEBHOOK_URL`, the journals are local-only and reset on every redeploy.**
  This is the single biggest operational gap for building a real track record (see §11).

---

## 9. What we VALIDATED vs DISPROVED (with data)

**All of the below is IN-SAMPLE** — one ~17-month period (2025-01 → 2026-06) during which gold trended
strongly up then fell. No out-of-sample test has been run. Treat as hypotheses.

### Validated (in-sample)
- **Daily-signal + 4H-ATR execution:** **129 resolved trades, 63.2% win (W/L), +20R, PF 1.52, max DD −3R.**
  The level/$20-stop variant was **PF 0.50** (losing). ATR stops are the keeper.
- **Don't blanket-filter counter-trend buys:** counter-trend trades were **net profitable (PF ~1.7)**;
  BUY-in-downtrend specifically was ~breakeven (PF ~1.0). So Filter B is **surgical** (hard-downtrend
  only), not a blanket "never buy in a downtrend."
- **EARLY REVERSAL cascade** (daily DOWN + 4H UP + 1H UP): daily confirmed up within 5 days **~88%**
  (n≈16–25, small).
- **Per-sign character, regime-split** (each sign's days split by prior trend; **n≈30/sign, ~10–16 per
  regime cell**):
  - **Aries — AMPLIFIES the trend both ways** (UP regime +$18/day avg, 60% continue; DOWN regime
    −$42/day, 62% continue). So "Aries makes big trend-extending moves," **not** "Aries is always down."
  - **Taurus — mild up-lean** (64% up-days).
  - Bullish-both-regimes: Scorpio, Capricorn, Pisces, Aquarius. Bearish-both: Libra.
  - Mixed/no-reliable-bias: Cancer, Virgo, Sagittarius.

### Disproved / NOT supported
- **"Pisces is a low-range pause" — NO.** Pisces' range is **average ($76)**, mild up-lean — not a quiet
  pause. (Now phrased in the UI as a *watch-expectation*, not a fact.)
- **"Only trade the London/NY overlap" — NO.** Overlap (12–15 UTC) avg |move| **$6.08 vs $6.68 outside =
  0.91×** — *less* active, not more. (The single most active hour is the NY-open 12:00 UTC; that's the
  only nugget.) ⚠️ This used the **futures** intraday feed, so it's doubly caveated.
- **"Sign change = reversal point" — NO.** Flip-rate on a sign-change day = **55% = baseline 55%**
  (n=207). Per-sign-entered variation (e.g. into Aquarius 75%) is **too noisy** (n≈17) to trust.

These disproven ideas are **intentionally excluded** from the Week Story tool, which states so explicitly.

---

## 10. Known limitations & the single most important next step

### ⭐ The one thing that matters most
**Everything is in-sample.** The rules were tuned on the data they're scored on, over a single trending
regime. **There is no out-of-sample / walk-forward validation yet** (no `walk_forward.py` exists). Until
that's done, PF 1.52 / 63% / the per-sign edges are **unconfirmed**. **Build and run honest walk-forward
testing first** — it can change every conclusion in §9.

### Recommended improvements, in priority order
1. **Walk-forward / out-of-sample testing** (build `walk_forward.py`): train on a window, test on the
   *next* unseen window, roll forward. Re-validate PF, the per-sign character, EARLY REVERSAL, Filter B.
   *Nothing else should be trusted until this exists.*
2. **Set `TWELVEDATA_KEY`** (§7, §11) — makes the whole intraday feed **spot**, fixing today-High/Low,
   trends, and trade-engine fill accuracy. Cheap, high impact.
3. **Set `ALERT_WEBHOOK_URL` + UptimeRobot** (§8, §11) — makes the journals **durable** and the
   roll-recompute **reliable**, so a real forward track record can actually accumulate.
4. **Refactor `app.py`** (~2,750 lines → modules): `routes/`, `signal/`, `trades/`, `data/`. Improves
   testability and reduces regression risk. (No such refactor exists yet.)
5. **Persistence → SQLite** instead of JSON files (survives restarts locally; cleaner than the sheet mirror).
6. **Position sizing / risk model.** The system reports R-multiples but **does not size positions**
   (size is left to the user). Add explicit `risk_$ / (entry−stop)` sizing and per-trade $ risk.
7. **Macro/News context as a filter,** not just calendar decoration (e.g. suppress/scale around
   high-impact USD releases).
8. **More astro data + bigger samples** before relying on per-sign character (n≈30/sign is thin).

### Other honest caveats
- Free-tier **cold starts** (~50s) and **sleep** affect timeliness without the keep-warm ping.
- Render auto-deploy is **throttled**; expect to click **Manual Deploy** often.
- The moon **ingress times have no timezone label** in the source — surfaced as *informational only*.
- The trends/trade-engine still consume the **futures** intraday feed until `TWELVEDATA_KEY` is set.

---

## 11. Pending user-side setup (nothing blocks the app; these unlock accuracy + durability)

1. **`TWELVEDATA_KEY`** — free key from twelvedata.com → Render → Environment → add var. Switches the
   intraday feed from Yahoo **futures** to Twelve Data **spot XAU/USD** (fixes §7 fully).
2. **`ALERT_WEBHOOK_URL`** — a Google **Apps Script Web App** bound to the sheet that upserts the three
   tabs. Steps (iPad-friendly): Sheet → Extensions → Apps Script → paste the script below → Deploy →
   New deployment → **Web app**, *Execute as: Me*, *Who has access: Anyone* → copy the `/exec` URL →
   Render → Environment → set `ALERT_WEBHOOK_URL`. Tabs `ALERT_LOG` / `JOURNAL` / `TRADES` auto-create;
   the app then mirrors **and auto-restores** the journals (fixes §8).
3. **UptimeRobot** (free) — HTTP monitor on `https://gold-command-center.onrender.com/api/roll` every
   **5 min**. Keeps the instance awake 24/7 and re-runs the roll, so each 5pm-NY session's plan goes
   live automatically (fixes the §6 sleep gap).
4. *(Optional)* **Telegram** — `TELEGRAM_BOT_TOKEN` (+ `TELEGRAM_CHAT_ID`) for push alerts; browser
   alerts already work without it.

### The 3-tab Apps Script (paste verbatim)
```javascript
function doPost(e) {
  var out = { ok: true };
  try {
    var data = JSON.parse(e.postData.contents);
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    if (data.rows) {
      out.alerts = upsert_(ss, 'ALERT_LOG',
        ['Date','Dir','Signal','Trend','WithTrend','Wait4H','Entry','Stop','Target','Outcome'],
        data.rows,
        function (r) { return [r.date, r.dir, r.signal, r.regime, r.with_trend, r.wait_4h, r.entry, r.stop, r.target, r.outcome]; });
    }
    if (data.journal) {
      out.journal = upsert_(ss, 'JOURNAL',
        ['Date','Signal','Source','LoggedAt','Result','Move'],
        data.journal,
        function (r) { return [r.date, r.signal, r.source, r.logged_at, r.result, r.move]; });
    }
    if (data.trades) {
      out.trades = upsert_(ss, 'TRADES',
        ['Id','Status','Json'],
        data.trades,
        function (r) { return [r.id, r.status, r.json]; });
    }
  } catch (err) { out = { ok: false, error: String(err) }; }
  return ContentService.createTextOutput(JSON.stringify(out)).setMimeType(ContentService.MimeType.JSON);
}

function upsert_(ss, name, header, items, mapFn) {
  var sh = ss.getSheetByName(name) || ss.insertSheet(name);
  if (sh.getLastRow() === 0) sh.appendRow(header);
  sh.getRange(1, 1, sh.getMaxRows(), 1).setNumberFormat('@');   // keep the key column (A) as text
  var vals = sh.getDataRange().getValues();
  var idx = {};
  for (var i = 1; i < vals.length; i++) idx[String(vals[i][0])] = i + 1;
  var n = 0;
  items.forEach(function (r) {
    var row = mapFn(r), key = String(row[0]);
    if (idx[key]) sh.getRange(idx[key], 1, 1, row.length).setValues([row]);
    else { sh.appendRow(row); idx[key] = sh.getLastRow(); }
    n++;
  });
  return n;
}
```

---

## Appendix — key constants & endpoints

**Constants:** `H4_ATR_MULT=1.5`, `H4_RR=1.0` (1:1), `DECISION_MAX=10.0` (±$10 = Decision Day),
`HARD_DOWN_NET=−80.0` (Filter B), `ENTRY_EXPIRY_4H=6`, `TRADE_EXPIRY_4H=18` (~3 days),
`COST_PER_TRADE=0.50`.

**Selected APIs:** `/api/dashboard`, `/api/live-price`, `/api/trends` (+ Reversal Watch),
`/api/day/<date>`, `/api/calendar/<y>/<m>`, `/api/alerts[/n]`, `/api/journal`, `/api/track-record`,
`/api/week-story`, `/api/roll`.

**Data source:** Google Sheet ID `12ynlr46bvHSJLnLGs5Z1SrhhlCj6_w7qO6YHMDBY7gs`, read via
`gviz/tq?tqx=out:csv` per tab (public, read-only).

*Document reflects the system as of mid-June 2026. All performance figures are in-sample and unproven
out-of-sample — validate before trusting.*

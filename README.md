# Naser Gold — 4-Hour Edition

Gold (XAU/USD) astro-trading dashboard. This is the **4-hour timeframe** copy of the
daily "Naser Gold" system: the daily formula still decides direction, and the 4-hour
candles are used to time entries and manage stops/targets.

## What it does
- **Daily signal** (unchanged v7 formula: moon sign + nature + cycle + history) decides BUY / SELL.
- **4-Hour Trading Plan** per day: pivot-point entry, stop & take-profit sized from the
  4H ATR, breakeven trail managed on the 4H candles.
- **Decision Day**: a day that closes with a small move (within ±$10) — the market is
  undecided, so the next day is the important breakout. Flagged on the dashboard with an
  end-of-day banner + browser alert.
- **Decision-Day Continuation**: the day after a Decision Day:
  - close at/below the decision day's **midpoint** → next day **SELL**; above → **BUY**
  - **two entries** so you don't miss: Entry 1 = midpoint, Entry 2 = pivot point
  - **trigger**: fills on whichever comes first — price touching either level, OR the
    first green 1-hour candle (SELL) / red 1-hour candle (BUY)

## Run it
```
pip install -r requirements.txt
python app.py
```
Then open http://localhost:5000  (Windows: `START_APP.bat`).

## Offline
The app pulls live data from a Google Sheet. After every successful load it writes a
portable snapshot to **`data_cache.json`**. If there's no internet, it automatically
loads from that snapshot — so the dashboard (including the 4H and decision-day plans)
works fully offline, and on any machine that has the file.

## Backtests (standalone, run with `python <file>`)
- `strategy_4h.py` — the 4-hour strategy: daily signal → pivot entry → 4H stop/TP.
- `backtest_4h_v2.py` — daily signal managed on daily vs 4H, side by side.
- `backtest_4h.py` — pure per-4H-candle signal (reference; this one loses).

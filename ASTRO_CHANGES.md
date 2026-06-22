# Astrology engine changes (June 2026)

Two rounds of fixes to `engine.py` + `app.py`, validated point-in-time on verified
XAU/USD **spot** data (gold-api.com series, 381 days, Jan 2025–Jun 2026).

## Round 1 — correctness fixes
- **No look-ahead.** The old engine fed the day's realized up/down result into the moon
  score, so the backtest was cheating. Removed.
- **Real 1–9 day number.** The sheet's "day number" is a 1–730 row index; it was shown as
  "538" and broke the 3/6/9 rule. `app.py` now uses `_numerology_day(date)` (digit root)
  and `engine.reduce_day_number()` is a safety net. Power numbers corrected to **3/6/9**.
- **No score saturation.** Components are normalised and blended with weights summing to 1.

## Round 2 — new DIRECTION rule: moon SIGN + PHASE
A study of the spot data showed the directional edge lives in the **moon sign** and
**moon phase**, NOT the day number (day 9 was actually the weakest; 3/6/9 days had the
same move size as any other day). So direction is now driven by sign+phase:

- `engine.signphase_bias()` scores how the current moon **sign** and **phase** have
  historically biased gold **relative to its own drift** (point-in-time, prior days only).
- `app.signphase_counts()` supplies the point-in-time bull/bear counts; `compute_signal`
  uses them when present (falls back to the old blend if not).
- Eclipses force stand-aside (risk-off).

### Point-in-time backtest (breakeven-trail R=1, same management for all)
| Signal | Directional accuracy | totR |
|---|---|---|
| **New sign+phase (wired)** | **53.1%** | −23 |
| Old astro engine (sign×stage) | 44.6% | −55 |
| Always-long baseline | 56.2% | −11 |

The new rule is a large upgrade over the old engine (which was below coin-flip and bleeding
R). It still doesn't beat simply staying long in this uptrend, and every variant is net-
negative on R — which points at the **money management** (target / stop / trail) as the next
thing to optimise. Direction is now honest and measured; that's the foundation to build on.

Re-run the study as more spot days accumulate:
`python backtest_v2.py` and `python astro_edge.py` (in the engine working folder).

> Note: 3/6/9 is kept only as a move-size / "watch" flag, not a buy/sell input — that's all
> the data supports.

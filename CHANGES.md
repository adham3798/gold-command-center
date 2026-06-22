# Fixes to gold-command-center

Two files: replace `engine.py`, add `backtest_engine.py`. Nothing else changes.

## engine.py — 4 fixes

1. **Power numbers corrected to 3/6/9.** Was `POWER_NUMBERS = {3,7,9}` with
   `day_number_weight` boosting 7. Your docs say 3/6/9 (Tesla rule). Now 6 is a
   power day (×1.30) and 7 is ordinary (×0.90); 9 stays strongest (×1.40).

2. **Scoring no longer saturates.** The old `bias_pct = raw/25*100` divided by a
   number well below the real range of `raw` (~±40), so "STRONG BUY/SELL" fired
   far too easily. Each component is now normalised to ~[-1,1] first, then blended
   with weights that sum to 1.0, then scaled to ±100. Full resolution restored.

3. **Look-ahead removed.** `moon_score` used to take the realized close direction
   and nudge the TREND bias toward it — which leaks the answer into any backtest of
   `compute_signal`. It now follows price *structure* (MTF momentum), which is known
   before the close. Verified: feeding opposite realized directions now yields an
   identical signal.

4. **MTF folded into the blend.** Multi-timeframe structure was added on top
   (weights summed to 1.30, mixed scales). It is now one normalised component inside
   the weighted blend, so price structure has a consistent, bounded influence.

## backtest_engine.py — new

Backtests the ACTUAL dashboard signal (`engine.compute_signal`) so you measure what
you trade, and runs an ablation: astro engine vs the nature rule vs an always-BULL
baseline, with the same breakeven-trail management as `backtest_v7`. Also fixes the
move-size fallback to be point-in-time (no future leak). Run: `python backtest_engine.py`.

## What the ablation showed (local run, 243 days, Jan 2025–Jun 2026)

| Signal | Directional accuracy |
|---|---|
| Astro engine (fixed) | 48.4% |
| Nature rule (model)  | 47.1% |
| Always-BULL baseline | 56.2% |

Both signals underperformed simply being long in gold's uptrend. The positive
expectancy in your backtests comes from the **breakeven-trail money management**,
not the direction call. Highest-value next step: keep the management, simplify the
signal, and optimise R:R / trail trigger / a time-stop. (Bull base rate is
regime-specific; the takeaway — the directional layer adds no edge here — is not.)

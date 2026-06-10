# -*- coding: utf-8 -*-
"""Backtest the CURRENT LIVE rules — by calling the exact same functions the dashboard
uses (build_day -> plan4h), so what we measure IS what the system trades.

Covers both trade types the system produces:
  - DECISION-DAY continuation (trend resume, $8-10 zone entry, $20 stop, combined-move TP)
  - NORMAL day 4H plan (pivot entry, level-based stop, next R/S target, BE trail)

A "trade" = a day whose plan FILLED and RESOLVED (outcome W / BE / L).
  NF (price never reached entry) = no trade taken. None = window not elapsed yet (skipped).

Risk model: 1R = |entry - stop|.  Win = +reward/risk R.  Loss = -1R.  BE = 0R.

Run:  python backtest_current.py
"""
import statistics as st
from datetime import datetime
import app

def collect():
    app.load_data_safe()
    days = sorted(app.DATA['prices'])               # 2026 trading days that have a close
    trades = []
    counts = {'NF': 0, 'pending': 0, 'no_signal': 0, 'no_plan': 0}
    for ds in days:
        try:
            day = app.build_day(ds)
        except Exception as e:
            print('skip', ds, e); continue
        if day.get('market_closed'):
            continue
        p = day.get('plan4h')
        if not p:
            counts['no_plan'] += 1; continue
        d = p.get('dir')
        if d not in ('BUY', 'SELL'):
            counts['no_signal'] += 1; continue
        oc = p.get('outcome')
        if oc == 'NF':
            counts['NF'] += 1; continue
        if oc not in ('W', 'BE', 'L'):
            counts['pending'] += 1; continue        # None = not resolved yet
        entry, stop, tgt = p.get('entry'), p.get('stop'), p.get('target')
        if None in (entry, stop, tgt):
            counts['pending'] += 1; continue
        risk = abs(entry - stop); reward = abs(tgt - entry)
        if risk <= 0:
            continue
        r = (reward / risk) if oc == 'W' else (-1.0 if oc == 'L' else 0.0)
        trades.append({'date': ds, 'src': day.get('signal_src') or 'normal',
                       'kind': 'decision' if p.get('decision') else 'normal',
                       'dir': d, 'oc': oc, 'r': r, 'risk': risk, 'reward': reward,
                       'regime': day.get('trend_regime'), 'mtf': day.get('mtf_label')})
    return trades, counts

def stats(trades, label):
    if not trades:
        print('%-22s no resolved trades' % label); return
    W = sum(1 for t in trades if t['oc'] == 'W')
    L = sum(1 for t in trades if t['oc'] == 'L')
    BE = sum(1 for t in trades if t['oc'] == 'BE')
    n = len(trades)
    totR = sum(t['r'] for t in trades)
    avgR = totR / n
    gross_win = sum(t['reward'] for t in trades if t['oc'] == 'W')
    gross_loss = sum(t['risk'] for t in trades if t['oc'] == 'L')
    pf = (gross_win / gross_loss) if gross_loss else float('inf')
    # equity curve in R -> max drawdown + worst losing streak
    eq = 0.0; peak = 0.0; maxdd = 0.0; streak = 0; worst_streak = 0
    for t in trades:
        eq += t['r']; peak = max(peak, eq); maxdd = min(maxdd, eq - peak)
        if t['oc'] == 'L': streak += 1; worst_streak = max(worst_streak, streak)
        else: streak = 0
    wr_all = W / n * 100
    wr_wl = W / (W + L) * 100 if (W + L) else 0
    print('=== %s ===' % label)
    print('  trades: %d   (W %d · BE %d · L %d)' % (n, W, BE, L))
    print('  win rate: %.1f%% of all   |   %.1f%% of W/L (ignoring BE)' % (wr_all, wr_wl))
    print('  total R: %+.1f   ·   avg R/trade: %+.3f' % (totR, avgR))
    print('  profit factor: %.2f   (gross win $%.0f / gross loss $%.0f)' % (pf, gross_win, gross_loss))
    print('  worst losing streak: %d   ·   max drawdown: %.1f R' % (worst_streak, maxdd))
    print()

if __name__ == '__main__':
    print('Backtesting the CURRENT live rules (via build_day / plan4h)...\n')
    trades, counts = collect()
    print('Universe: %d resolved trades  |  no-fill(NF): %d  ·  pending(not elapsed): %d  ·  no-signal: %d  ·  no-plan: %d\n'
          % (len(trades), counts['NF'], counts['pending'], counts['no_signal'], counts['no_plan']))
    span = (trades[0]['date'], trades[-1]['date']) if trades else ('-', '-')
    print('trade span: %s -> %s\n' % span)
    stats(trades, 'ALL TRADES (decision + normal)')
    stats([t for t in trades if t['kind'] == 'decision'], 'DECISION-DAY trades only')
    stats([t for t in trades if t['kind'] == 'normal'], 'NORMAL 4H-plan trades only')
    print('---- by period (current $-rules fit recent gold best) ----\n')
    stats([t for t in trades if t['date'] >= '2026-01-01'], 'YEAR 2026 only')
    stats([t for t in trades if t['date'] >= '2026-04-01'], 'RECENT (Apr 2026+)')
    print('---- by direction ----\n')
    stats([t for t in trades if t['dir'] == 'BUY'], 'BUY trades')
    stats([t for t in trades if t['dir'] == 'SELL'], 'SELL trades')
    print('==== MULTI-TIMEFRAME TREND FILTER (daily-trend regime) ====\n')
    wt = [t for t in trades if t['mtf'] == 'WITH-TREND']
    ct = [t for t in trades if t['mtf'] == 'COUNTER-TREND PULLBACK']
    nt = [t for t in trades if t['mtf'] not in ('WITH-TREND', 'COUNTER-TREND PULLBACK')]
    stats(wt, 'WITH-TREND only (the proposed filter)')
    stats(ct, 'COUNTER-TREND PULLBACK only (what we would ignore)')
    stats(wt + nt, 'KEEP with-trend + flat-regime (drop counter-trend)')
    stats(nt, 'FLAT regime (no filter applies)')
    print('---- regime x direction ----\n')
    rd = lambda rg, dr: [t for t in trades if t['regime'] == rg and t['dir'] == dr]
    stats(rd('DOWN', 'BUY'),  'BUY in DOWNtrend  (counter-trend buy = your concern)')
    stats(rd('DOWN', 'SELL'), 'SELL in DOWNtrend (with-trend)')
    stats(rd('UP', 'BUY'),    'BUY in UPtrend    (with-trend)')
    stats(rd('UP', 'SELL'),   'SELL in UPtrend   (counter-trend sell)')

# -*- coding: utf-8 -*-
"""
walk_forward.py — OUT-OF-SAMPLE / walk-forward STABILITY test of the REAL system.

Analysis only. Imports and drives the ACTUAL logic — no re-implementation:
  - signal/plan  : app.build_day()  (sheet forecast -> engine -> movable pullback ->
                   Filter B veto -> decision-day continuation). Entry/stop/target come
                   straight from the real plan4h.
  - execution    : trade_journal.py engine — entry confirms on a 4H CLOSE, stop/take exit
                   on TOUCH (driven by the real H1 candles), trend-break, 3-day time stop,
                   honest fills + $0.50/round-trip cost.

Method: ONE continuous chronological replay (no per-window refit — the rules are fixed).
Each trading day from the warm-up cutoff onward: build_day -> place the directional signal
(if any) into the engine, then feed that day's H4+H1 candles forward. A trade is only ever
driven by candles AFTER it was placed (no look-ahead). Closed trades are then bucketed into
rolling test windows by PLACEMENT date. Run twice: Filter B ON vs OFF.
"""
import os, tempfile, statistics as st
from collections import defaultdict
import app
import trade_journal as tj

WARMUP_END = '2025-07-01'   # require ~6 months of prior data before any test placement

def _grp(cands):
    g = defaultdict(list)
    for c in app._norm_candles(cands):
        g[c['dt'][:10]].append(c)
    return g

def replay(filter_b):
    app.HARD_DOWN_NET = -80.0 if filter_b else -1e12   # OFF = veto can never trigger
    tj.TRADES_FILE = os.path.join(tempfile.gettempdir(), 'wf_%s.json' % ('on' if filter_b else 'off'))
    tj._save({'trades': {}, 'last_seen': {}})
    P = app.DATA['prices']
    tdays = set(d for d in P if P[d].get('close') is not None)
    h4g, h1g = _grp(app.DATA['h4']), _grp(app.DATA['h1'])
    dates = sorted(set(list(h4g) + list(h1g)))
    placed = set()
    for cd in dates:
        if cd < WARMUP_END:
            continue
        if cd in tdays and cd not in placed:
            placed.add(cd)
            try:
                day = app.build_day(cd)
            except Exception:
                day = None
            if day and not day.get('market_closed'):
                pl = day.get('plan4h') or {}
                s = day.get('signal') or ''
                dirn = 'BUY' if 'BUY' in s else 'SELL' if 'SELL' in s else None
                e, stp, tg = pl.get('entry'), pl.get('stop'), pl.get('target')
                if dirn and None not in (e, stp, tg):
                    tag = '%s|%s' % (cd, 'WT' if day.get('mtf_with_trend') else 'X')
                    tj.place(dirn, e, stp, tg, source='wf', note=tag)
        if cd in h4g:
            tj.process_candles('4h', h4g[cd])
        if cd in h1g:
            tj.process_candles('1h', h1g[cd])
    db = tj._load()
    out = []
    for t in db['trades'].values():
        if t['status'] != 'CLOSED':
            continue
        note = t.get('note', '')
        out.append({'place': note[:10], 'wt': note.endswith('WT'),
                    'dir': t['direction'], 'pnl': t['exit']['pnl'], 'r': t['exit']['r_multiple'],
                    'reason': t['exit']['reason']})
    n_open = sum(1 for t in db['trades'].values() if t['status'] in ('OPEN', 'PENDING'))
    return out, n_open

def plan4h_trades():
    """Contrast model: the build_4h_plan resolution backtest_current.py uses (pivot-TOUCH
       entry, 4H-candle resolution, BE trail, NO spread cost) — the model behind the
       in-sample PF 1.52. OOS-only, for an apples-to-oranges comparison vs the real engine."""
    P = app.DATA['prices']; out = []
    for d in sorted(P):
        if d < WARMUP_END or P[d].get('close') is None:
            continue
        try:
            day = app.build_day(d)
        except Exception:
            continue
        if day.get('market_closed'):
            continue
        p = day.get('plan4h')
        if not p or p.get('dir') not in ('BUY', 'SELL'):
            continue
        oc = p.get('outcome')
        if oc not in ('W', 'BE', 'L'):
            continue
        e, s, t = p.get('entry'), p.get('stop'), p.get('target')
        if None in (e, s, t) or abs(e - s) <= 0:
            continue
        risk, reward = abs(e - s), abs(t - e)
        r = (reward / risk) if oc == 'W' else (-1.0 if oc == 'L' else 0.0)
        pnl = reward if oc == 'W' else (-risk if oc == 'L' else 0.0)
        out.append({'place': d, 'wt': bool(day.get('mtf_with_trend')), 'dir': p['dir'],
                    'pnl': pnl, 'r': r, 'reason': oc})
    return out

def stats(trades):
    if not trades:
        return None
    n = len(trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] < 0]
    gw = sum(t['pnl'] for t in wins); gl = abs(sum(t['pnl'] for t in losses))
    pf = (gw / gl) if gl else float('inf')
    totR = sum(t['r'] for t in trades)
    # max drawdown on the R equity curve (chronological by placement)
    eq = 0.0; peak = 0.0; dd = 0.0
    for t in sorted(trades, key=lambda x: x['place']):
        eq += t['r']; peak = max(peak, eq); dd = min(dd, eq - peak)
    return {'n': n, 'win': 100 * len(wins) / max(len(wins) + len(losses), 1),
            'pf': pf, 'totR': totR, 'avgR': totR / n, 'maxdd': dd}

def _bin(date_str, win_months):
    y, m = int(date_str[:4]), int(date_str[5:7])
    if win_months == 1:
        return date_str[:7]
    idx = (y * 12 + (m - 1)) // win_months
    yy, mm = idx * win_months // 12, idx * win_months % 12 + 1
    return '%04d-%02d+' % (yy, mm)

def report(trades, label, win_months=1):
    print('\n========== %s (window=%dmo) ==========' % (label, win_months))
    agg = stats(trades)
    if not agg:
        print('  no trades'); return None
    print('  AGGREGATE: trades=%d  win=%.0f%%  PF=%.2f  totR=%+.1f  avgR=%+.3f  maxDD=%.1fR'
          % (agg['n'], agg['win'], agg['pf'], agg['totR'], agg['avgR'], agg['maxdd']))
    by = defaultdict(list)
    for t in trades:
        by[_bin(t['place'], win_months)].append(t)
    print('  per 1-month test window:')
    print('    window    n   win%   PF    totR')
    bad = 0; nwin = 0
    for mo in sorted(by):
        s = stats(by[mo])
        if s['n'] == 0:
            continue
        nwin += 1
        isbad = (s['pf'] < 1.0)
        bad += 1 if isbad else 0
        pf = '%.2f' % s['pf'] if s['pf'] != float('inf') else 'inf'
        print('    %s  %2d  %4.0f%%  %5s  %+5.1f %s' % (mo, s['n'], s['win'], pf, s['totR'], '  <bad' if isbad else ''))
    print('  windows: %d  |  losing windows (PF<1): %d (%.0f%%)' % (nwin, bad, 100 * bad / max(nwin, 1)))
    # verdict
    pf = agg['pf']; badpct = 100 * bad / max(nwin, 1)
    if pf >= 1.2 and badpct < 30:
        v = 'ROBUST'
    elif pf >= 1.0 and badpct < 50:
        v = 'MARGINAL'
    else:
        v = 'FAILED'
    print('  VERDICT: %s  (PF %.2f, %.0f%% losing windows)' % (v, pf, badpct))
    return agg, nwin, bad

if __name__ == '__main__':
    app.load_data_safe()
    print('H1 live src:', app.DATA.get('h1_live_src'), '(futures = proxy, not spot)')
    on, on_open = replay(True)
    off, off_open = replay(False)
    print('\n=== closed trades: Filter B ON=%d (open/unresolved %d) | OFF=%d (open %d) ===' % (len(on), on_open, len(off), off_open))
    print('\n##### REAL TRADE ENGINE (4H-close confirm, 1H-touch exit, $0.50 cost) #####')
    report(on, 'FILTER B ON — all directional signals', 1)
    report(on, 'FILTER B ON — all directional signals', 2)
    report([t for t in on if t['wt']], 'FILTER B ON — WITH-TREND subset (live-engine gating)', 1)
    report(off, 'FILTER B OFF — all directional signals', 1)
    rc = defaultdict(int)
    for t in on:
        rc[t['reason']] += 1
    print('\nExit reasons (Filter B ON):', dict(rc))

    print('\n##### CONTRAST: build_4h_plan model (pivot-touch, no cost = the in-sample PF 1.52 model), OOS #####')
    p4 = plan4h_trades()
    report(p4, 'plan4h model — all directional', 1)

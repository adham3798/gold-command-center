# -*- coding: utf-8 -*-
"""Backtest surgical fixes for the Jun-10 bad BUY (pullback rule flipped a correct SELL
into a counter-trend BUY in a hard downtrend). Goal: catch THAT case without killing the
profitable counter-trend bucket. Uses build_day/plan4h (live rules) so no drift.

No-lookahead: regime/net/4H/1H are computed from candles STRICTLY BEFORE the day.
"""
import statistics as st
import app

def collect():
    app.load_data_safe()
    P = app.DATA['prices']
    days = sorted(P)
    h4 = sorted(app.DATA.get('h4', []), key=app._cdt)
    h1 = sorted(app.DATA.get('h1', []), key=app._cdt)

    def daily_net(D):                       # trend net of last 5 daily closes BEFORE D
        cl = [(P[d]['close'], P[d]['open']) for d in days if d < D
              and P[d].get('close') is not None and P[d].get('open') is not None]
        t = app._trend_of(cl, 5); return (t['dir'], t['net']) if t else (None, 0)

    def tf(cands, D, n):                     # 4H/1H trend from candles strictly before D
        seq = [(c['close'], c['open']) for c in cands
               if str(c.get('dt', ''))[:10] < D and c.get('close') is not None and c.get('open') is not None]
        t = app._trend_of(seq, n); return t['dir'] if t else None

    trades = []
    for ds in days:
        try:
            day = app.build_day(ds)
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
        entry, stop, tgt = p.get('entry'), p.get('stop'), p.get('target')
        if None in (entry, stop, tgt):
            continue
        risk = abs(entry - stop); reward = abs(tgt - entry)
        if risk <= 0:
            continue
        r = (reward / risk) if oc == 'W' else (-1.0 if oc == 'L' else 0.0)
        ddir, dnet = daily_net(ds)
        trades.append({'date': ds, 'dir': p.get('dir'), 'oc': oc, 'r': r, 'risk': risk, 'reward': reward,
                       'src': day.get('signal_src'), 'mtf': day.get('mtf_label'),
                       'ddir': ddir, 'dnet': dnet, 'h4': tf(h4, ds, 6), 'h1': tf(h1, ds, 8)})
    return trades

def stats(trades, label):
    if not trades:
        print('  %-46s  (no trades)' % label); return
    n = len(trades); W = sum(t['oc'] == 'W' for t in trades); L = sum(t['oc'] == 'L' for t in trades)
    totR = sum(t['r'] for t in trades)
    gw = sum(t['reward'] for t in trades if t['oc'] == 'W'); gl = sum(t['risk'] for t in trades if t['oc'] == 'L')
    pf = (gw / gl) if gl else float('inf')
    wr = W / (W + L) * 100 if (W + L) else 0
    print('  %-46s  n=%-3d  win %4.1f%%  PF %4.2f  totR %+6.1f' % (label, n, wr, pf, totR))

def is_counter_buy(t):  return t['dir'] == 'BUY' and t['ddir'] == 'DOWN'

if __name__ == '__main__':
    T = collect()
    print('Loaded %d resolved trades  (span %s -> %s)\n' % (len(T), T[0]['date'], T[-1]['date']))
    ct = [t for t in T if is_counter_buy(t)]
    print('=== BASELINE ===')
    stats(T, 'ALL trades')
    stats(ct, 'counter-trend BUYs (daily DOWN) [keep these!]')
    print()

    # candidate filters: return True if the trade should be SKIPPED
    def hard(t, thr):   return is_counter_buy(t) and t['h4'] == 'DOWN' and t['h1'] == 'DOWN' and t['dnet'] < -thr
    def pbk(t, thr):    return t['dir'] == 'BUY' and t['src'] == 'pullback' and t['ddir'] == 'DOWN' and t['dnet'] < -thr
    def confirm(t):     return is_counter_buy(t) and not (t['h4'] == 'UP' and t['h1'] == 'UP')  # need EARLY REVERSAL

    cands = []
    for thr in (50, 80, 120):
        cands.append(('A hard-down all-3-down & net<-%d' % thr, lambda t, thr=thr: hard(t, thr)))
    for thr in (50, 80, 120):
        cands.append(('B pullback-BUY & daily DOWN & net<-%d' % thr, lambda t, thr=thr: pbk(t, thr)))
    cands.append(('C counter-BUY needs 4H+1H up (EARLY REV)', confirm))

    for name, f in cands:
        kept = [t for t in T if not f(t)]
        skipped = [t for t in T if f(t)]
        print('=== FILTER: %s ===' % name)
        stats(kept, 'AFTER (kept)')
        stats([t for t in kept if is_counter_buy(t)], '  counter-trend BUYs remaining')
        sk_r = sum(t['r'] for t in skipped)
        print('  skipped %d trades (their totR %+.1f: %s)' % (
            len(skipped), sk_r, ', '.join('%s %s/%+.1fR' % (t['date'], t['oc'], t['r']) for t in skipped[:8])))
        print()

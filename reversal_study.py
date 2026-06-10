# -*- coding: utf-8 -*-
"""Study down->up reversal signals on the real data, to measure their hit-rate before
building a 'Reversal Watch'. Uses the same _trend_of the dashboard uses.

Signals tested:
  A) DAILY trend flips DOWN -> UP (the confirming signal)
  B) EARLY cascade: daily still DOWN, but 4H and 1H trend already UP (catch the bottom)
Hit = price higher N trading days later (and for B, daily actually flips UP within 5d).
"""
import app

def main():
    app.load_data_safe()
    P = app.DATA['prices']
    days = sorted(d for d in P if P[d].get('close') is not None and P[d].get('open') is not None)
    idx = {d: i for i, d in enumerate(days)}

    def daily_trend(D):
        seq = [(P[d]['close'], P[d]['open']) for d in days if d <= D]
        t = app._trend_of(seq, 5); return t['dir'] if t else None

    h4 = sorted(app.DATA.get('h4', []), key=lambda c: str(c.get('dt', '')))
    h1 = sorted(app.DATA.get('h1', []), key=lambda c: str(c.get('dt', '')))
    def tf_trend(cands, D, n):
        seq = [(c['close'], c['open']) for c in cands
               if str(c.get('dt', ''))[:10] <= D and c.get('close') is not None and c.get('open') is not None]
        t = app._trend_of(seq, n); return t['dir'] if t else None

    DT = {d: daily_trend(d) for d in days}
    def fwd(D, K):
        i = idx[D] + K
        return (P[days[i]]['close'] - P[D]['close']) if i < len(days) else None

    print('trend states across %d days: UP %d · DOWN %d · FLAT %d\n' % (
        len(days), sum(v=='UP' for v in DT.values()), sum(v=='DOWN' for v in DT.values()), sum(v=='FLAT' for v in DT.values())))

    # baseline: from ANY downtrend day, how often is price higher in K days?
    down = [d for d in days if DT[d] == 'DOWN']
    print('--- BASELINE: random downtrend day ---')
    for K in (5, 10):
        res = [fwd(d, K) for d in down]; res = [r for r in res if r is not None]
        hit = sum(1 for r in res if r > 0)
        print('  +%2dd higher: %3d/%3d = %.0f%%   avg move %+.1f' % (K, hit, len(res), 100*hit/len(res), sum(res)/len(res)))

    # A) DAILY flip DOWN -> UP
    flips = [days[i] for i in range(1, len(days)) if DT[days[i-1]] == 'DOWN' and DT[days[i]] == 'UP']
    print('\n--- A) DAILY trend flips DOWN -> UP  (n=%d) ---' % len(flips))
    for K in (5, 10):
        res = [fwd(d, K) for d in flips]; res = [r for r in res if r is not None]
        if res:
            hit = sum(1 for r in res if r > 0)
            print('  +%2dd higher: %3d/%3d = %.0f%%   avg move %+.1f' % (K, hit, len(res), 100*hit/len(res), sum(res)/len(res)))

    # ── REVERSAL WATCH STATE per day (exactly what the dashboard card will show) ──
    state_of = {d: app._reversal_state(DT[d], tf_trend(h4, d, 6), tf_trend(h1, d, 8))['state'] for d in days}
    from collections import Counter
    cnt = Counter(state_of.values())
    print('\n=== REVERSAL WATCH state classification (whole history) ===')
    for s in ('DOWNTREND', 'EARLY_REVERSAL', 'CONFIRMED_UPTREND', 'RANGE'):
        print('  %-18s %d days' % (s, cnt.get(s, 0)))

    early = [d for d in days if state_of[d] == 'EARLY_REVERSAL']
    print('\n=== EARLY REVERSAL (yellow) — every date it fired, with what happened ===')
    conf = 0
    for d in early:
        i = idx[d]
        flipped = next((days[i+k] for k in range(1, 6) if i+k < len(days) and DT.get(days[i+k]) == 'UP'), None)
        if flipped:
            conf += 1
        f5, f10 = fwd(d, 5), fwd(d, 10)
        print('  %s  daily-confirm<=5d: %-3s (%s)   +5d %s   +10d %s' % (
            d, 'YES' if flipped else 'no', flipped or '-',
            ('%+.0f' % f5) if f5 is not None else 'n/a',
            ('%+.0f' % f10) if f10 is not None else 'n/a'))
    if early:
        print('  --> confirmed-up within 5d: %d/%d = %.0f%%' % (conf, len(early), 100*conf/len(early)))
        for K in (5, 10):
            res = [fwd(d, K) for d in early if fwd(d, K) is not None]
            hit = sum(1 for r in res if r > 0)
            print('  --> price higher +%dd: %d/%d = %.0f%%  avg %+.1f' % (K, hit, len(res), 100*hit/len(res), sum(res)/len(res)))
    print('\n  sample CONFIRMED_UPTREND dates:', [d for d in days if state_of[d] == 'CONFIRMED_UPTREND'][:4])
    print('  sample DOWNTREND dates:        ', [d for d in days if state_of[d] == 'DOWNTREND'][-4:])
    print('  LATEST day %s -> state: %s' % (days[-1], state_of[days[-1]]))

if __name__ == '__main__':
    main()

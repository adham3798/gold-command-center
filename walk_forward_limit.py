# -*- coding: utf-8 -*-
"""
walk_forward_limit.py — re-run the OOS walk-forward with the LIMIT-AT-PIVOT entry.

Only the ENTRY changes: a PENDING trade fills via a LIMIT at the planned pivot when a 4H
candle TOUCHES it (fill price = the pivot; if the candle gaps past the pivot, fill at the
gap open). Everything else is the REAL trade_journal engine (touch-based H1 exits,
trend-break, 3-day time-stop, $0.50 cost). We reuse walk_forward.py's replay/stats/report
and monkeypatch trade_journal.process_candles for the test only — no live files changed.
"""
import app
import trade_journal as tj
import walk_forward as wf

CONFIRM_TF = tj.CONFIRM_TF
MONITOR_TFS = tj.MONITOR_TFS

def _limit_fill(t, o, h, l):
    """Limit at the pivot: fill when the candle straddles the entry; price = pivot,
       or the gap-open if the candle opened past the pivot."""
    E = t['entry']
    if l <= E <= h:
        if t['direction'] == 'BUY':
            return o if o < E else E
        return o if o > E else E
    return None

def process_candles_limit(timeframe, candles):
    """Copy of trade_journal.process_candles with the entry block swapped to LIMIT-fill.
       Reuses all the real exit helpers (_check_touch_exits, _close_trade, trend-break,
       time-stop) unchanged."""
    if timeframe not in MONITOR_TFS:
        return 0
    db = tj._load()
    last = db['last_seen'].get(timeframe, '')
    fresh = sorted((c for c in candles
                    if c.get('close') is not None and str(c.get('dt', '')) > last),
                   key=lambda c: str(c['dt']))
    if not fresh:
        return 0
    changes = 0
    for c in fresh:
        dt = str(c['dt']); close = float(c['close'])
        o = float(c['open']) if c.get('open') is not None else close
        h = float(c['high']) if c.get('high') is not None else max(o, close)
        l = float(c['low']) if c.get('low') is not None else min(o, close)
        for t in db['trades'].values():
            if t['status'] == 'PENDING':
                if timeframe != CONFIRM_TF:
                    continue
                t['h4_pending'] += 1
                fp = _limit_fill(t, o, h, l)               # <-- LIMIT entry (was: confirm on close)
                if fp is not None:
                    t['status'] = 'OPEN'
                    t['fill'] = {'dt': dt, 'price': fp,
                                 'slip_vs_plan': round(abs(fp - t['entry']), 2)}
                    t['events'].append({'t': tj._now(), 'ev': 'filled_limit_at_pivot',
                                        'dt': dt, 'price': fp})
                    changes += 1
                elif t['h4_pending'] >= tj.ENTRY_EXPIRY_4H:
                    t['status'] = 'CANCELLED'
                    t['events'].append({'t': tj._now(), 'ev': 'entry_expired', 'dt': dt})
                    changes += 1
                continue
            if t['status'] != 'OPEN':
                continue
            if dt <= t['fill']['dt'] and timeframe == CONFIRM_TF:
                continue
            if tj._check_touch_exits(t, dt, o, h, l):
                changes += 1
                continue
            if timeframe == CONFIRM_TF:
                t['h4_open'] += 1
                sgn = 1 if t['direction'] == 'BUY' else -1
                against = (close < o) if sgn > 0 else (close > o)
                t['h4_against_run'] = t['h4_against_run'] + 1 if against else 0
                n = t.get('exit_on_4h_against')
                if n and t['h4_against_run'] >= n:
                    tj._close_trade(t, dt, close, 'trend_break_4h')
                    changes += 1
                elif t['h4_open'] >= tj.TRADE_EXPIRY_4H:
                    tj._close_trade(t, dt, close, 'expiry')
                    changes += 1
        db['last_seen'][timeframe] = dt
    tj._save(db)
    return changes

if __name__ == '__main__':
    tj.process_candles = process_candles_limit          # monkeypatch for the test only
    app.load_data_safe()
    print('H1 live src:', app.DATA.get('h1_live_src'))
    on, on_open = wf.replay(True)
    off, off_open = wf.replay(False)
    import json, os, statistics as st
    db = json.load(open(os.path.join(os.environ.get('TEMP', '/tmp'), 'wf_on.json')))
    T = [t for t in db['trades'].values() if t['status'] == 'CLOSED']
    slip = [t['fill']['slip_vs_plan'] for t in T]
    print('\nLIMIT entry — closed: ON=%d (open %d) | OFF=%d' % (len(on), on_open, len(off)))
    print('avg entry slippage now: $%.2f (median $%.2f, max $%.2f) — should be ~0 vs $27.9 before'
          % (st.mean(slip), st.median(slip), max(slip)))
    print('\n##### LIMIT-AT-PIVOT ENTRY — REAL engine (touch exits, trend-break, time-stop, $0.50 cost) #####')
    wf.report(on, 'LIMIT entry, Filter B ON — all directional', 1)
    wf.report(on, 'LIMIT entry, Filter B ON — all directional', 2)
    wf.report([t for t in on if t['wt']], 'LIMIT entry, Filter B ON — WITH-TREND subset', 1)
    wf.report(off, 'LIMIT entry, Filter B OFF — all directional', 1)
    from collections import defaultdict
    rc = defaultdict(int)
    for t in on:
        rc[t['reason']] += 1
    print('\nExit reasons (LIMIT, Filter B ON):', dict(rc))

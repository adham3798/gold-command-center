# -*- coding: utf-8 -*-
"""
trade_journal.py (v2) — Trade engine + journal for gold-command-center.

THE RULES
1. ENTRY is a LIMIT at the planned PIVOT. A 4H candle that TOUCHES the pivot fills the
   trade AT the pivot price (so the stop/target stay consistent with the level they were
   sized from). If a candle gaps past the pivot, the fill is the gap open. The DIRECTION
   still comes from the daily signal.
2. STOP-LOSS & TAKE-PROFIT fire IMMEDIATELY ON TOUCH (intrabar) on the H1 feed.
Optional trend-break exit: close at the 4H close after N consecutive 4H candles close against (default 3).

NOTE: a prior version confirmed entry on the 4H CLOSE — out-of-sample that filled ~$28 past
the pivot (70% of risk), turning 37% of target-hits into losses (PF 0.71). The limit-at-pivot
entry fixes that mismatch (walk-forward PF ~2.7, ROBUST). See WALK_FORWARD_REPORT.md.
"""

import json
import math
import os
import uuid
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
TRADES_FILE = os.path.join(_HERE, 'trade_journal.json')

CONFIRM_TF = '4h'
MONITOR_TFS = ('30m', '1h', '4h')
ENTRY_EXPIRY_4H = 6
TRADE_EXPIRY_4H = 18
COST_PER_TRADE = 0.50


def _load():
    if not os.path.exists(TRADES_FILE):
        return {'trades': {}, 'last_seen': {}}
    with open(TRADES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(db):
    tmp = TRADES_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=1)
    os.replace(tmp, TRADES_FILE)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def place(direction, entry, stop, take, source='', note='',
          exit_on_4h_against=3):
    if direction not in ('BUY', 'SELL'):
        return None
    entry, stop, take = float(entry), float(stop), float(take)
    ok = (stop < entry < take) if direction == 'BUY' else (take < entry < stop)
    if not ok:
        return None
    db = _load()
    for t in db['trades'].values():
        if (t['status'] in ('PENDING', 'OPEN') and t['direction'] == direction
                and t['entry'] == entry):
            return None
    tid = uuid.uuid4().hex[:10]
    db['trades'][tid] = {
        'id': tid, 'direction': direction,
        'entry': entry, 'stop': stop, 'take': take,
        'planned_risk': round(abs(entry - stop), 2),
        'planned_reward': round(abs(take - entry), 2),
        'rr': round(abs(take - entry) / max(abs(entry - stop), 1e-9), 2),
        'exit_on_4h_against': exit_on_4h_against,
        'source': source, 'note': note,
        'status': 'PENDING', 'placed_at': _now(),
        'h4_pending': 0, 'h4_open': 0, 'h4_against_run': 0,
        'events': [{'t': _now(), 'ev': 'placed'}],
        'fill': None, 'exit': None,
    }
    _save(db)
    return tid


def cancel(tid):
    db = _load()
    t = db['trades'].get(tid)
    if not t or t['status'] != 'PENDING':
        return False
    t['status'] = 'CANCELLED'
    t['events'].append({'t': _now(), 'ev': 'cancelled_manually'})
    _save(db)
    return True


def _limit_fill(t, o, h, l):
    """LIMIT entry at the pivot. A candle that TOUCHES the entry (its range straddles it)
       fills the trade AT the pivot price; if the candle OPENED past the pivot (a gap),
       the fill is the gap open. Returns the fill price, or None if not touched yet."""
    e = t['entry']
    if l <= e <= h:
        if t['direction'] == 'BUY':
            return o if o < e else e
        return o if o > e else e
    return None


def _close_trade(t, dt, price, reason):
    sgn = 1 if t['direction'] == 'BUY' else -1
    pnl = sgn * (price - t['fill']['price']) - COST_PER_TRADE
    risk = t['planned_risk'] or 1e-9
    t['status'] = 'CLOSED'
    t['exit'] = {'dt': dt, 'price': round(price, 2), 'reason': reason,
                 'pnl': round(pnl, 2), 'r_multiple': round(pnl / risk, 2)}
    t['events'].append({'t': _now(), 'ev': 'closed', 'dt': dt,
                        'reason': reason, 'price': round(price, 2),
                        'pnl': round(pnl, 2)})


def _check_touch_exits(t, dt, o, h, l):
    sgn = 1 if t['direction'] == 'BUY' else -1
    stop_hit = (l <= t['stop']) if sgn > 0 else (h >= t['stop'])
    take_hit = (h >= t['take']) if sgn > 0 else (l <= t['take'])
    if stop_hit:
        gapped = (o <= t['stop']) if sgn > 0 else (o >= t['stop'])
        _close_trade(t, dt, o if gapped else t['stop'],
                     'stop_gap' if gapped else 'stop_touch')
        return True
    if take_hit:
        gapped = (o >= t['take']) if sgn > 0 else (o <= t['take'])
        _close_trade(t, dt, o if gapped else t['take'],
                     'take_gap' if gapped else 'take_touch')
        return True
    return False


def process_candles(timeframe, candles):
    if timeframe not in MONITOR_TFS:
        return 0
    db = _load()
    last = db['last_seen'].get(timeframe, '')
    fresh = sorted((c for c in candles
                    if c.get('close') is not None and str(c.get('dt', '')) > last),
                   key=lambda c: str(c['dt']))
    if not fresh:
        return 0
    changes = 0
    for c in fresh:
        dt = str(c['dt'])
        close = float(c['close'])
        o = float(c['open']) if c.get('open') is not None else close
        h = float(c['high']) if c.get('high') is not None else max(o, close)
        l = float(c['low']) if c.get('low') is not None else min(o, close)
        for t in db['trades'].values():
            if t['status'] == 'PENDING':
                if timeframe != CONFIRM_TF:
                    continue
                t['h4_pending'] += 1
                fp = _limit_fill(t, o, h, l)
                if fp is not None:
                    t['status'] = 'OPEN'
                    t['fill'] = {'dt': dt, 'price': fp,
                                 'slip_vs_plan': round(abs(fp - t['entry']), 2)}
                    t['events'].append({'t': _now(), 'ev': 'filled_limit_at_pivot',
                                        'dt': dt, 'price': fp})
                    changes += 1
                elif t['h4_pending'] >= ENTRY_EXPIRY_4H:
                    t['status'] = 'CANCELLED'
                    t['events'].append({'t': _now(), 'ev': 'entry_expired', 'dt': dt})
                    changes += 1
                continue
            if t['status'] != 'OPEN':
                continue
            if dt <= t['fill']['dt'] and timeframe == CONFIRM_TF:
                continue
            if _check_touch_exits(t, dt, o, h, l):
                changes += 1
                continue
            if timeframe == CONFIRM_TF:
                t['h4_open'] += 1
                sgn = 1 if t['direction'] == 'BUY' else -1
                against = (close < o) if sgn > 0 else (close > o)
                t['h4_against_run'] = t['h4_against_run'] + 1 if against else 0
                n = t.get('exit_on_4h_against')
                if n and t['h4_against_run'] >= n:
                    _close_trade(t, dt, close, 'trend_break_4h')
                    changes += 1
                elif t['h4_open'] >= TRADE_EXPIRY_4H:
                    _close_trade(t, dt, close, 'expiry')
                    changes += 1
        db['last_seen'][timeframe] = dt
    _save(db)
    return changes


def _wilson(w, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = w / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    hh = (z / den) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, c - hh), min(1.0, c + hh))


def stats():
    db = _load()
    closed = sorted((t for t in db['trades'].values() if t['status'] == 'CLOSED'),
                    key=lambda t: t['exit']['dt'])
    n = len(closed)
    wins = sum(1 for t in closed if t['exit']['pnl'] > 0)
    lo, hi = _wilson(wins, n)
    reasons = ('take_touch', 'take_gap', 'stop_touch', 'stop_gap',
               'trend_break_4h', 'expiry')
    return {
        'closed': n, 'wins': wins,
        'win_rate_pct': round(wins / n * 100, 1) if n else None,
        'ci95_pct': [round(lo * 100, 1), round(hi * 100, 1)],
        'total_pnl': round(sum(t['exit']['pnl'] for t in closed), 2),
        'avg_r': round(sum(t['exit']['r_multiple'] for t in closed) / n, 2) if n else None,
        'expectancy_usd': round(sum(t['exit']['pnl'] for t in closed) / n, 2) if n else None,
        'avg_entry_slippage': round(sum(t['fill']['slip_vs_plan'] for t in closed) / n, 2) if n else None,
        'exit_reasons': {r: sum(1 for t in closed if t['exit']['reason'] == r)
                         for r in reasons},
        'open': [{'id': t['id'], 'dir': t['direction'], 'fill': t['fill'],
                  'stop': t['stop'], 'take': t['take'],
                  'h4_against_run': t['h4_against_run']}
                 for t in db['trades'].values() if t['status'] == 'OPEN'],
        'pending': [{'id': t['id'], 'dir': t['direction'], 'entry': t['entry'],
                     'h4_waited': t['h4_pending']}
                    for t in db['trades'].values() if t['status'] == 'PENDING'],
        'recent': [{'id': t['id'], 'dir': t['direction'],
                    'entry_fill': t['fill']['price'], 'exit': t['exit']}
                   for t in closed[-15:]],
    }


if __name__ == '__main__':
    import tempfile
    TRADES_FILE = os.path.join(tempfile.gettempdir(), '_tj2_test.json')
    if os.path.exists(TRADES_FILE):
        os.remove(TRADES_FILE)

    def C(dt, o, h, l, c):
        return {'dt': dt, 'open': o, 'high': h, 'low': l, 'close': c}

    # BUY: pivot 100, stop 95, take 110
    tid = place('BUY', 100, 95, 110, source='test')
    assert tid
    # 1H candle does NOT fill entry (entry is judged on 4H only)
    process_candles('1h', [C('2026-06-10 01:00', 99, 103, 98, 102)])
    assert _load()['trades'][tid]['status'] == 'PENDING', '1H must not fill entry'
    # 4H candle that never reaches the pivot (stays above 100) -> no fill
    process_candles('4h', [C('2026-06-10 04:00', 103, 105, 101, 104)])
    assert _load()['trades'][tid]['status'] == 'PENDING', '4H that never touches the pivot must not fill'
    # 4H candle dips to TOUCH the pivot (opens above, low<=100) -> LIMIT fills AT 100 (not the close)
    process_candles('4h', [C('2026-06-10 08:00', 102, 103, 99, 101.0)])
    t = _load()['trades'][tid]
    assert t['status'] == 'OPEN' and t['fill']['price'] == 100, 'limit fills at the pivot'
    # 1H touches the take (110) -> exit at 110, pnl from the pivot fill (100)
    process_candles('1h', [C('2026-06-10 09:00', 101, 110.4, 100.8, 108.0)])
    t = _load()['trades'][tid]
    assert t['status'] == 'CLOSED' and t['exit']['reason'] == 'take_touch'
    assert t['exit']['price'] == 110 and abs(t['exit']['pnl'] - (110 - 100 - 0.5)) < 1e-9

    # GAP entry: BUY pivot 100, a 4H candle OPENS below the pivot -> fill at the gap open (97)
    tg = place('BUY', 100, 90, 120)
    process_candles('4h', [C('2026-06-10 12:00', 97, 101, 96, 98)])      # opens 97 below pivot
    assert _load()['trades'][tg]['fill']['price'] == 97, 'gap-through fills at the open'
    process_candles('1h', [C('2026-06-10 13:00', 100, 121, 99, 118)])    # take 120 touched -> close
    assert _load()['trades'][tg]['status'] == 'CLOSED'

    # SELL: pivot 100, stop 105, take 90 — 4H touches 100 -> fill 100; 1H hits the stop (105)
    tid2 = place('SELL', 100, 105, 90)
    process_candles('4h', [C('2026-06-10 16:00', 98, 102, 97, 99.5)])    # touches 100 -> fill 100
    assert _load()['trades'][tid2]['fill']['price'] == 100
    process_candles('1h', [C('2026-06-10 17:00', 99.5, 105.3, 99, 100)])  # high touches 105
    t2 = _load()['trades'][tid2]
    assert t2['status'] == 'CLOSED' and t2['exit']['reason'] == 'stop_touch' and t2['exit']['price'] == 105

    # trend-break: BUY fills at 100, then 3 bearish 4H closes (never hitting the 90 stop) -> out
    tid3 = place('BUY', 100, 90, 120, exit_on_4h_against=3)
    process_candles('4h', [C('2026-06-10 20:00', 101, 102, 99, 100.5)])  # touch -> fill 100
    process_candles('4h', [C('2026-06-11 00:00', 100.5, 101, 99.5, 99.8),
                           C('2026-06-11 04:00', 99.8, 100.2, 98.5, 99.0),
                           C('2026-06-11 08:00', 99.0, 99.5, 97.8, 98.2)])
    t3 = _load()['trades'][tid3]
    assert t3['status'] == 'CLOSED' and t3['exit']['reason'] == 'trend_break_4h', t3['exit']

    # stop-vs-take same candle: fill 100, then one candle touches BOTH -> stop wins (pessimistic)
    tid4 = place('BUY', 100, 95, 110)
    process_candles('4h', [C('2026-06-11 12:00', 102, 103, 99, 100.8)])  # touch -> fill 100
    process_candles('1h', [C('2026-06-11 13:00', 100.8, 110.5, 94.5, 100)])
    t4 = _load()['trades'][tid4]
    assert t4['exit']['reason'] == 'stop_touch', 'ambiguous candle must take the stop'

    s = stats()
    assert s['closed'] == 5, s['closed']    # tid, tg, tid2, tid3, tid4
    assert s['avg_entry_slippage'] is not None
    print('trade_journal.py self-test OK (limit-at-pivot) — exit reasons:', s['exit_reasons'])

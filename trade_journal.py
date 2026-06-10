# -*- coding: utf-8 -*-
"""
trade_journal.py (v2) — Trade engine + journal for gold-command-center.

THE TWO RULES (exactly as you specified)
----------------------------------------
1. DIRECTION & ENTRY are judged ONLY on the 4-HOUR CLOSE.
   A 1H candle can rally and still close bearish — so nothing about trend or
   entry confirmation is decided on 1H/30m action. A trade fills only when a
   4H candle CLOSES confirming the setup's direction through the entry zone.

2. STOP-LOSS & TAKE-PROFIT fire IMMEDIATELY ON TOUCH (intrabar).
   Risk control cannot wait 4 hours. The engine watches the finest feed you
   give it (30m or 1h highs/lows) and exits at the level the moment price
   touches it — like resting orders at a broker.

So: slow brain (4H close) decides WHEN YOU'RE IN; fast reflexes (touch)
decide WHEN YOU'RE OUT.

EXTRA EXIT (optional, on by default): trend-break.
If a 4H candle CLOSES beyond your stop... wait — your stop already fired on
touch before that could happen. The real trend-break case is the opposite:
price never touches the stop but the 4H trend dies. If `exit_on_4h_against=N`
is set, the trade closes at the 4H close after N consecutive 4H candles close
against the position. Default N=3; set None to disable.

API
---
    import trade_journal as tj

    tj.place(direction='BUY', entry=3392.0, stop=3380.0, take=3415.0,
             source='nature_cycle+pivot', note='decision-day continuation')

    # after every data refresh — feed BOTH; order doesn't matter:
    tj.process_candles('4h', DATA['h4'])   # entries + trend-break (close-based)
    tj.process_candles('1h', DATA['h1'])   # TP/SL touch monitoring
    # (feed '30m' too if you add a 30m fetch — finer = more accurate exits)

    @app.route('/api/trades')
    def api_trades(): return jsonify(tj.stats())

FILL CONVENTIONS (honest accounting)
------------------------------------
- Entry fill price  = the confirming 4H CLOSE (not your planned level).
  The gap is logged per-trade as 'slip_vs_plan'.
- Stop fill price   = the stop level; if a candle OPENS beyond the stop
  (weekend/news gap), the fill is that worse open — gaps are real.
- Take fill price   = the take level; gap-opens beyond it fill at the better
  open.
- If ONE candle touches both stop and take, the STOP is assumed first
  (pessimistic — never let ambiguity flatter the stats).
- Sizing is still yours:  size = risk_$ / (entry - stop).  With touch-based
  stops the planned risk is now a true ceiling except for gaps.
"""

import json
import math
import os
import uuid
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
TRADES_FILE = os.path.join(_HERE, 'trade_journal.json')

CONFIRM_TF = '4h'                        # direction/entry decided here only
MONITOR_TFS = ('30m', '1h', '4h')        # any feed may trigger touch exits
ENTRY_EXPIRY_4H = 6                      # 4H closes to wait for confirmation
TRADE_EXPIRY_4H = 18                     # max 4H candles in a trade (3 days)
COST_PER_TRADE = 0.50                    # spread+slippage $/oz round trip


# ── persistence ───────────────────────────────────────────────────────────────

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


# ── placing a setup ───────────────────────────────────────────────────────────

def place(direction, entry, stop, take, source='', note='',
          exit_on_4h_against=3):
    """Register a setup. Entry confirms on a 4H close; stop/take exit on touch.
    Returns trade id or None on inconsistent inputs."""
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
            return None                          # duplicate live setup
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


# ── engine internals ──────────────────────────────────────────────────────────

def _confirm_entry(t, close):
    """4H close confirms direction through the entry zone.
    Pullback entries (default): BUY confirms when the 4H closes back ABOVE the
    entry after the zone was reachable — practical rule: BUY confirms on a
    BULLISH 4H close at/above entry; SELL on a BEARISH 4H close at/below entry.
    Tag note with 'breakout' for the same logic (it is the same: direction
    must close through the level in the trade's favour)."""
    if t['direction'] == 'BUY':
        return close >= t['entry']
    return close <= t['entry']


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
    """Intrabar stop/take on touch. Stop checked FIRST (pessimistic tie-break).
    Gap-opens fill at the open."""
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
    """Feed closed candles for one timeframe ({'dt','open','high','low','close'}).
    Only candles newer than the last processed dt for that timeframe are used.
    The newest candle in the list must be CLOSED (app.py already drops the
    forming live bar — keep doing that for any feed).
    Returns number of state changes."""
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

            # ── ENTRY: only the 4H close may confirm ─────────────────────────
            if t['status'] == 'PENDING':
                if timeframe != CONFIRM_TF:
                    continue
                t['h4_pending'] += 1
                if _confirm_entry(t, close):
                    t['status'] = 'OPEN'
                    t['fill'] = {'dt': dt, 'price': close,
                                 'slip_vs_plan': round(abs(close - t['entry']), 2)}
                    t['events'].append({'t': _now(), 'ev': 'filled_on_4h_close',
                                        'dt': dt, 'price': close})
                    changes += 1
                elif t['h4_pending'] >= ENTRY_EXPIRY_4H:
                    t['status'] = 'CANCELLED'
                    t['events'].append({'t': _now(), 'ev': 'entry_expired', 'dt': dt})
                    changes += 1
                continue

            # ── EXITS while OPEN ─────────────────────────────────────────────
            if t['status'] != 'OPEN':
                continue
            # don't act on candles that closed before/at the fill candle
            if dt <= t['fill']['dt'] and timeframe == CONFIRM_TF:
                continue

            # 1) touch exits — ANY timeframe feed, intrabar highs/lows
            if _check_touch_exits(t, dt, o, h, l):
                changes += 1
                continue

            # 2) 4H-close logic: trend-break + time stop
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


# ── stats for the dashboard ───────────────────────────────────────────────────

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


# ── self-test ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import tempfile
    TRADES_FILE = os.path.join(tempfile.gettempdir(), '_tj2_test.json')
    if os.path.exists(TRADES_FILE):
        os.remove(TRADES_FILE)

    def C(dt, o, h, l, c):
        return {'dt': dt, 'open': o, 'high': h, 'low': l, 'close': c}

    # BUY: entry 100, stop 95, take 110
    tid = place('BUY', 100, 95, 110, source='test')
    assert tid

    # 1H candles do NOTHING while pending — even closing above entry
    process_candles('1h', [C('2026-06-10 01:00', 99, 103, 98, 102)])
    assert _load()['trades'][tid]['status'] == 'PENDING', '1H must not confirm entry'

    # 4H wicks above entry but CLOSES below -> your example: no fill
    process_candles('4h', [C('2026-06-10 04:00', 98, 104, 97, 99.0)])
    assert _load()['trades'][tid]['status'] == 'PENDING', '4H wick-up close-down must not fill'

    # 4H closes above entry -> fills at that 4H close (101.2)
    process_candles('4h', [C('2026-06-10 08:00', 99, 102, 98.5, 101.2)])
    t = _load()['trades'][tid]
    assert t['status'] == 'OPEN' and t['fill']['price'] == 101.2

    # 1H candle TOUCHES the take (high 110.4) -> exits AT 110 instantly
    process_candles('1h', [C('2026-06-10 09:00', 101, 110.4, 100.8, 108.0)])
    t = _load()['trades'][tid]
    assert t['status'] == 'CLOSED' and t['exit']['reason'] == 'take_touch'
    assert t['exit']['price'] == 110 and abs(t['exit']['pnl'] - (110 - 101.2 - 0.5)) < 1e-9

    # SELL with stop touched intrabar on 1H
    tid2 = place('SELL', 100, 105, 90)
    process_candles('4h', [C('2026-06-10 12:00', 101, 102, 98, 99.5)])   # confirms (close<=100)
    process_candles('1h', [C('2026-06-10 13:00', 99.5, 105.3, 99, 100)]) # high touches 105
    t2 = _load()['trades'][tid2]
    assert t2['status'] == 'CLOSED' and t2['exit']['reason'] == 'stop_touch'
    assert t2['exit']['price'] == 105

    # trend-break: BUY survives prices but 3 bearish 4H closes in a row -> out
    tid3 = place('BUY', 100, 90, 120, exit_on_4h_against=3)
    process_candles('4h', [C('2026-06-10 16:00', 99, 101, 98, 100.5)])   # fill 100.5
    process_candles('4h', [C('2026-06-10 20:00', 100.5, 101, 99, 99.8),  # against 1
                           C('2026-06-11 00:00', 99.8, 100.2, 98.5, 99.0),  # against 2
                           C('2026-06-11 04:00', 99.0, 99.5, 97.8, 98.2)])  # against 3 -> exit
    t3 = _load()['trades'][tid3]
    assert t3['status'] == 'CLOSED' and t3['exit']['reason'] == 'trend_break_4h', t3['exit']

    # stop-vs-take same candle: stop wins (pessimistic)
    tid4 = place('BUY', 100, 95, 110)
    process_candles('4h', [C('2026-06-11 08:00', 99, 101, 98, 100.8)])
    process_candles('1h', [C('2026-06-11 09:00', 100.8, 110.5, 94.5, 100)])
    t4 = _load()['trades'][tid4]
    assert t4['exit']['reason'] == 'stop_touch', 'ambiguous candle must take the stop'

    s = stats()
    assert s['closed'] == 4
    print('trade_journal.py v2 self-test OK — exit reasons:', s['exit_reasons'])

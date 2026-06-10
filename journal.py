# -*- coding: utf-8 -*-
"""
journal.py — Live prediction journal for gold-command-center.

The only un-fakeable test of a trading system: write the signal down BEFORE
the day trades, grade it AFTER the close, and watch the running win rate.

Integration (3 lines in app.py):

    import journal
    journal.record_today(date_str, signal_dict)        # when the day's signal is built
    journal.grade_pending(DATA['prices'])              # after each data refresh

Add an API route to show it on the dashboard:

    @app.route('/api/journal')
    def api_journal():
        return jsonify(journal.stats())

Records are append-only. A signal for a date can only be written once, and
only while that date has no close yet — so it can never be back-filled.
"""

import json
import math
import os
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
JOURNAL_FILE = os.path.join(_HERE, 'prediction_journal.json')


def _load():
    if not os.path.exists(JOURNAL_FILE):
        return {}
    with open(JOURNAL_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(j):
    tmp = JOURNAL_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(j, f, ensure_ascii=False, indent=1)
    os.replace(tmp, JOURNAL_FILE)


def record_today(date_str, signal, source='dashboard', extra=None):
    """Log a prediction for date_str. Refuses to overwrite an existing entry
    (append-only) and stamps the wall-clock time it was made."""
    if signal not in ('BUY', 'SELL', 'WAIT'):
        return False
    j = _load()
    if date_str in j:                      # never rewrite history
        return False
    j[date_str] = {
        'signal': signal,
        'source': source,
        'logged_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'extra': extra or {},
        'outcome': None,                   # graded later
    }
    _save(j)
    return True


def grade_pending(prices):
    """Grade every logged prediction whose day now has a close.
    A BUY wins if close > open; a SELL wins if close < open; WAIT is excluded
    from the win rate but counted (a system that always says WAIT is useless)."""
    j = _load()
    changed = False
    for d, rec in j.items():
        if rec.get('outcome') is not None:
            continue
        bar = prices.get(d)
        if not bar or bar.get('open') is None or bar.get('close') is None:
            continue
        move = bar['close'] - bar['open']
        if rec['signal'] == 'WAIT':
            rec['outcome'] = {'result': 'wait', 'move': round(move, 2)}
        else:
            win = (move > 0) if rec['signal'] == 'BUY' else (move < 0)
            rec['outcome'] = {'result': 'win' if win else 'loss',
                              'move': round(move, 2)}
        changed = True
    if changed:
        _save(j)
    return changed


def _wilson(wins, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = (z / den) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, c - h), min(1.0, c + h))


def stats():
    """Summary for the dashboard: running win rate + 95% CI + recent entries."""
    j = _load()
    graded = [(d, r) for d, r in sorted(j.items())
              if r.get('outcome') and r['outcome']['result'] in ('win', 'loss')]
    n = len(graded)
    wins = sum(1 for _, r in graded if r['outcome']['result'] == 'win')
    lo, hi = _wilson(wins, n)
    rolling = []
    for i in range(n):
        w = graded[max(0, i - 19):i + 1]
        rolling.append({'date': graded[i][0],
                        'win_rate': round(sum(1 for _, r in w
                                              if r['outcome']['result'] == 'win')
                                          / len(w) * 100, 1)})
    return {
        'n_graded': n,
        'wins': wins,
        'win_rate_pct': round(wins / n * 100, 1) if n else None,
        'ci95_pct': [round(lo * 100, 1), round(hi * 100, 1)],
        'distinguishable_from_coinflip': bool(n and (lo > 0.5 or hi < 0.5)),
        'n_wait': sum(1 for r in j.values()
                      if r.get('outcome') and r['outcome']['result'] == 'wait'),
        'n_pending': sum(1 for r in j.values() if r.get('outcome') is None),
        'rolling20': rolling[-60:],
        'recent': [{'date': d, 'signal': r['signal'],
                    'result': r['outcome']['result'],
                    'move': r['outcome']['move']} for d, r in graded[-15:]],
    }

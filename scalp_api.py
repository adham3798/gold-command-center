# -*- coding: utf-8 -*-
"""
Scalp tab live data — registers /api/scalp on the existing Flask app.

Loaded via wsgi.py (after app.py is fully imported), so it can safely use the
app's own `app`, `DATA`, and `_read_tab`. No changes to app.py required.

Returns (same-origin, no CORS):
  price, pdh, pdl, pdc                         -> always (from loaded daily data)
  vwap, ema21, rsi, atr5, atr15, orh, orl      -> when XAU_5m / XAU_15m feed tabs
                                                  exist (produced by intraday_feed.gs)
"""
import app as A
from flask import jsonify


def _ind(bars):
    closes = [b['close'] for b in bars if b.get('close') is not None]
    if not closes:
        return {}
    def _ema(vals, p):
        k = 2.0 / (p + 1); e = vals[0]
        for v in vals[1:]:
            e = v * k + e * (1 - k)
        return e
    def _rsi(vals, p=14):
        if len(vals) <= p:
            return None
        g = l = 0.0
        for i in range(1, p + 1):
            d = vals[i] - vals[i - 1]; g += max(d, 0); l += max(-d, 0)
        ag, al = g / p, l / p
        for i in range(p + 1, len(vals)):
            d = vals[i] - vals[i - 1]
            ag = (ag * (p - 1) + max(d, 0)) / p
            al = (al * (p - 1) + max(-d, 0)) / p
        return 100 - 100 / (1 + (ag / al if al else 1e9))
    def _atr(bb, p=14):
        if len(bb) < p + 1:
            return None
        trs = []
        for i in range(1, len(bb)):
            pc = bb[i - 1]['close']
            trs.append(max(bb[i]['high'] - bb[i]['low'],
                           abs(bb[i]['high'] - pc), abs(bb[i]['low'] - pc)))
        a = sum(trs[:p]) / p
        for i in range(p, len(trs)):
            a = (a * (p - 1) + trs[i]) / p
        return a
    pv = vv = 0.0
    for b in bars:
        pv += (b['high'] + b['low'] + b['close']) / 3.0; vv += 1
    return {'vwap': pv / vv if vv else None,
            'ema21': _ema(closes, 21) if len(closes) >= 21 else None,
            'rsi': _rsi(closes, 14), 'atr': _atr(bars, 14)}


def _load_tab(tab):
    try:
        df = A._read_tab(tab)
        cols = {str(c).strip().lower(): c for c in df.columns}
        if not all(k in cols for k in ('open', 'high', 'low', 'close')):
            return []
        dcol = cols.get('date')
        rows = []
        for _, r in df.iterrows():
            try:
                rows.append({
                    'date': str(r[dcol]) if dcol else '',
                    'open': float(r[cols['open']]), 'high': float(r[cols['high']]),
                    'low':  float(r[cols['low']]),  'close': float(r[cols['close']])})
            except Exception:
                continue
        return rows
    except Exception:
        return []


@A.app.route('/api/scalp')
def api_scalp():
    out = {'price': None, 'pdh': None, 'pdl': None, 'pdc': None, 'vwap': None,
           'ema21': None, 'rsi': None, 'atr5': None, 'atr15': None,
           'orh': None, 'orl': None, 'source': 'levels'}
    try:
        days = sorted(A.DATA.get('prices', {}))
        if days:
            y = A.DATA['prices'][days[-1]]
            out['pdh'], out['pdl'], out['pdc'] = y.get('high'), y.get('low'), y.get('close')
            out['price'] = y.get('close')
    except Exception:
        pass
    try:
        h1 = A.DATA.get('h1') or []
        if h1 and isinstance(h1[-1], dict) and h1[-1].get('close') is not None:
            out['price'] = h1[-1]['close']
    except Exception:
        pass
    b5 = _load_tab('XAU_5m')
    b15 = _load_tab('XAU_15m')
    if len(b5) >= 2:
        ind = _ind(b5)
        out['vwap'] = ind.get('vwap'); out['ema21'] = ind.get('ema21')
        out['rsi'] = ind.get('rsi');   out['atr5'] = ind.get('atr')
        out['price'] = b5[-1]['close']
        if len(b15) >= 16:
            out['atr15'] = _ind(b15).get('atr')
        last_day = (b5[-1]['date'] or '')[:10]
        sess = [b for b in b5 if (b['date'] or '')[:10] == last_day] or b5[-6:]
        orb = sess[:6]
        if orb:
            out['orh'] = max(b['high'] for b in orb)
            out['orl'] = min(b['low'] for b in orb)
        out['source'] = 'intraday-feed'
    return jsonify({k: (round(v, 2) if isinstance(v, float) else v)
                    for k, v in out.items()})

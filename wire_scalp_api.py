#!/usr/bin/env python3
"""
Idempotently add the /api/scalp endpoint to app.py.

Run from the repo root:  python3 wire_scalp_api.py
Safe to run repeatedly — it only appends the route once.

The endpoint returns live readings for the Scalp tab, same-origin (no CORS):
  - price, pdh, pdl, pdc                 -> always (from the data the app already loads)
  - vwap, ema21, rsi, atr5, atr15, orh, orl -> when the XAU_5m / XAU_15m feed tabs
    exist in the Google Sheet (produced by intraday_feed.gs)

It reuses the app's existing _read_tab() and DATA, so it needs no new config.
"""
import os, sys, re

MARKER = "/api/scalp"
ROUTE = r'''

# ── SCALP API (intraday 5m-30m readings for the Scalp tab) ─────────────────────
def _scalp_ind(bars):
    """bars: time-ordered list of {open,high,low,close}. Returns vwap/ema21/rsi/atr."""
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
        tp = (b['high'] + b['low'] + b['close']) / 3.0
        pv += tp; vv += 1
    return {'vwap': pv / vv if vv else None,
            'ema21': _ema(closes, 21) if len(closes) >= 21 else None,
            'rsi': _rsi(closes, 14), 'atr': _atr(bars, 14)}

def _scalp_load_tab(tab):
    """Read an intraday feed tab (Date,Open,High,Low,Close) -> time-ordered rows."""
    try:
        df = _read_tab(tab)
        cols = {str(c).strip().lower(): c for c in df.columns}
        need = ['open', 'high', 'low', 'close']
        if not all(k in cols for k in need):
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

@app.route('/api/scalp')
def api_scalp():
    out = {'price': None, 'pdh': None, 'pdl': None, 'pdc': None, 'vwap': None,
           'ema21': None, 'rsi': None, 'atr5': None, 'atr15': None,
           'orh': None, 'orl': None, 'source': 'levels'}
    # prior-day levels + a price from the daily spot data the app already loads
    try:
        days = sorted(DATA.get('prices', {}))
        if days:
            y = DATA['prices'][days[-1]]
            out['pdh'], out['pdl'], out['pdc'] = y.get('high'), y.get('low'), y.get('close')
            out['price'] = y.get('close')
    except Exception:
        pass
    # near-live price from the latest 1H candle if available
    try:
        h1 = DATA.get('h1') or []
        if h1 and isinstance(h1[-1], dict) and h1[-1].get('close') is not None:
            out['price'] = h1[-1]['close']
    except Exception:
        pass
    # full intraday readings if the 5m/15m feed tabs exist
    b5 = _scalp_load_tab('XAU_5m')
    b15 = _scalp_load_tab('XAU_15m')
    if len(b5) >= 2:
        ind = _scalp_ind(b5)
        out['vwap'] = ind.get('vwap'); out['ema21'] = ind.get('ema21')
        out['rsi'] = ind.get('rsi');   out['atr5'] = ind.get('atr')
        out['price'] = b5[-1]['close']
        if len(b15) >= 16:
            out['atr15'] = _scalp_ind(b15).get('atr')
        # opening range = first 30 min of the most recent session date in the tab
        last_day = (b5[-1]['date'] or '')[:10]
        sess = [b for b in b5 if (b['date'] or '')[:10] == last_day] or b5[-6:]
        orb = sess[:6]
        if orb:
            out['orh'] = max(b['high'] for b in orb)
            out['orl'] = min(b['low'] for b in orb)
        out['source'] = 'intraday-feed'
    return jsonify({k: (round(v, 2) if isinstance(v, float) else v)
                    for k, v in out.items()})
# ── END SCALP API ──────────────────────────────────────────────────────────────
'''

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "app.py"
    if not os.path.exists(path):
        print("ERROR: %s not found (run from the repo root)" % path); sys.exit(1)
    src = open(path, encoding="utf-8").read()
    if MARKER in src:
        print("• /api/scalp already present — nothing to do.")
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(ROUTE)
    print("✓ Added /api/scalp endpoint to %s" % path)

if __name__ == "__main__":
    main()

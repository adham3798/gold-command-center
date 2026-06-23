#!/usr/bin/env python3
"""
Idempotently add the /api/silver endpoint to app.py (gold-command-center repo).

Run from the repo root:  python3 wire_scalp_silver.py
Safe to run repeatedly — appends the route once.

Returns a live gold/silver cross-check for the dashboard badge, reading the
XAG_5m / XAG_15m feed tabs (produced by intraday_feed_v3_silver.gs) alongside the
XAU tabs the existing /api/scalp already uses. Self-contained: it reuses the app's
_read_tab() and the _scalp_load_tab/_scalp_ind helpers added by wire_scalp_api.py,
and inlines the cross-check logic so no extra import is needed.

VERDICTS (see GOLD_SILVER_CORRELATION.md): CONFIRM / DIVERGENCE-VETO /
CHOP-TIEBREAK / IN-SYNC / DIVERGING / UNCONFIRMED / DECOUPLED. This is a real-time
confirmation, NOT a next-day forecast (no daily lead exists in the data).
"""
import os, sys

MARKER = "/api/silver"
ROUTE = r'''

# ── SILVER CROSS-CHECK API (gold/silver confirmation badge) ────────────────────
GSR_MEAN, GSR_SD = 79.3, 13.4   # from 568-day backtest

def _sv_struct(bars):
    """EMA9/21 + fast-EMA slope -> (dir -1/0/1, label, strength 0..1)."""
    cl = [b['close'] for b in bars if b.get('close') is not None]
    if len(cl) < 22:
        return 0, 'THIN', 0.0
    def _ema(v, p):
        k = 2.0 / (p + 1); e = [v[0]]
        for x in v[1:]:
            e.append(x * k + e[-1] * (1 - k))
        return e
    e9, e21 = _ema(cl, 9), _ema(cl, 21)
    spread = (e9[-1] - e21[-1]) / e21[-1] if e21[-1] else 0.0
    slope = (e9[-1] - e9[-6]) / cl[-1] if cl[-1] else 0.0
    strength = min(1.0, abs(spread) * 300 + abs(slope) * 600)
    if e9[-1] > e21[-1] and slope > 0 and strength > 0.35:
        return 1, 'UP', strength
    if e9[-1] < e21[-1] and slope < 0 and strength > 0.35:
        return -1, 'DOWN', strength
    return 0, 'FLAT/CHOP', strength

def _sv_corr(a, b):
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a); vb = sum((y - mb) ** 2 for y in b)
    return cov / ((va * vb) ** 0.5) if va > 0 and vb > 0 else 0.0

@app.route('/api/silver')
def api_silver():
    out = {'ok': False, 'verdict': 'NO-DATA', 'corr': None, 'regime': None,
           'gold_structure': None, 'silver_structure': None,
           'gsr': None, 'gsr_z': None, 'action': 'Silver feed (XAG tabs) not found.'}
    g = _scalp_load_tab('XAU_15m') or _scalp_load_tab('XAU_5m')
    s = _scalp_load_tab('XAG_15m') or _scalp_load_tab('XAG_5m')
    if len(g) < 22 or len(s) < 22:
        return jsonify(out)
    # align on last-N by index (same cadence feed)
    n = min(len(g), len(s))
    gc = [b['close'] for b in g[-n:]]; sc = [b['close'] for b in s[-n:]]
    gr = [gc[i] / gc[i-1] - 1 for i in range(1, len(gc)) if gc[i-1]]
    sr = [sc[i] / sc[i-1] - 1 for i in range(1, len(sc)) if sc[i-1]]
    corr = _sv_corr(gr[-20:], sr[-20:])
    regime = ('LOCKED' if corr >= 0.8 else 'NORMAL' if corr >= 0.5
              else 'DECOUPLED' if corr >= 0.2 else 'INVERTED/BROKEN')
    gd, gl, gs = _sv_struct(g)
    sd, sl, ss_ = _sv_struct(s)
    gsr = gc[-1] / sc[-1] if sc[-1] else None
    z = (gsr - GSR_MEAN) / GSR_SD if gsr else None
    # gold "signal" to validate = gold's own structure direction
    verdict, action = 'NEUTRAL', ''
    if regime in ('DECOUPLED', 'INVERTED/BROKEN'):
        verdict = 'DECOUPLED'
        action = ('Gold/silver correlation broken down (corr %.2f) — silver is not a '
                  'reliable cross-check now; trade gold on its own structure.' % corr)
    elif gd != 0 and sd == gd:
        verdict = 'CONFIRM'
        action = 'Silver %s CONFIRMS gold %s — full conviction.' % (sl, gl)
    elif gd != 0 and sd == -gd and ss_ > 0.4:
        verdict = 'DIVERGENCE-VETO'
        action = ('Silver %s AGAINST gold %s while correlated (corr %.2f) — fakeout risk, '
                  'half size / wait for re-sync.' % (sl, gl, corr))
    elif gd == 0 and sd != 0 and ss_ > 0.45:
        verdict = 'CHOP-TIEBREAK'
        action = ('Gold choppy, silver cleanly %s (corr %.2f) — lean %s.'
                  % (sl, corr, 'LONG' if sd > 0 else 'SHORT'))
    elif gd != 0 and sd == gd:
        verdict = 'IN-SYNC'; action = 'Gold and silver in sync (%s).' % gl
    else:
        verdict = 'UNCONFIRMED'; action = 'Silver flat/mixed — lean on gold confirmation.'
    gsr_note = None
    if z is not None and z >= 1.0:
        gsr_note = 'GSR %.1f (z %+.2f) high — silver cheap vs gold.' % (gsr, z)
    elif z is not None and z <= -1.0:
        gsr_note = 'GSR %.1f (z %+.2f) low — silver rich vs gold.' % (gsr, z)
    out.update({'ok': True, 'verdict': verdict, 'corr': round(corr, 2), 'regime': regime,
                'gold_structure': gl, 'silver_structure': sl,
                'gsr': round(gsr, 1) if gsr else None,
                'gsr_z': round(z, 2) if z is not None else None,
                'gsr_note': gsr_note, 'action': action})
    return jsonify(out)
# ── END SILVER CROSS-CHECK API ─────────────────────────────────────────────────
'''

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "app.py"
    if not os.path.exists(path):
        print("ERROR: %s not found (run from the repo root)" % path); sys.exit(1)
    src = open(path, encoding="utf-8").read()
    if "/api/scalp" not in src:
        print("ERROR: run wire_scalp_api.py first (this reuses its helpers).")
        sys.exit(1)
    if MARKER in src:
        print("• /api/silver already present — nothing to do.")
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(ROUTE)
    print("✓ Added /api/silver endpoint to %s" % path)

if __name__ == "__main__":
    main()

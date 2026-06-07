# -*- coding: utf-8 -*-
"""backtest_4h_v2: DAILY signal (your proven v7 edge) + 4-HOUR trade management.

WHY THIS EXISTS
  backtest_4h.py applied the rule bar-by-bar on 4H candles -> it loses, because the
  astrology signal only changes day-to-day, so a pure-4H signal just chops ONE daily
  decision into 6 noisy ones.

  This version keeps what actually has an edge -- the v7 DAILY direction decision and
  the v7 daily move size -- and only uses the 4-HOUR candles to MANAGE the trade
  (track stop / target / breakeven-trail at 4h resolution instead of the daily
  "assume the adverse move happened first" approximation).

  So: SAME signal as your daily v7, finer (more realistic) execution.

KEPT IDENTICAL TO v7
  - model(): MOVABLE fade-if-same-sign-as-prev-day else follow; FIXED follow; FINISHER fade on FINISH.
  - matching(): avg up/down DAILY move (close-open) for the day's sign+stage.
  - breakeven trail: stop=1*move(1R); at 50% to target stop->entry; then only W or BE.
  - reward:risk 1:1 and 2:1, plus the 0.5:1 no-trail reference; optional weekly filter.

CHANGED FOR 4H (only the execution layer)
  - Trade outcome is walked across the day's 4H candles (and the next days', up to the
    window) instead of across whole daily candles. Within each 4H candle we still assume
    adverse-first (conservative), but a 4H candle is 1/6 the size of a daily one, so the
    stop-vs-target ordering is far more accurate.

The script prints DAILY-managed (=v7, same window) right next to 4H-managed so you can
see exactly what the 4-hour execution changes. Daily files are NOT touched.

Run:  python backtest_4h_v2.py
"""
import pandas as pd, urllib.parse, statistics as st
from datetime import datetime

SID = '12ynlr46bvHSJLnLGs5Z1SrhhlCj6_w7qO6YHMDBY7gs'
def tab(t):
    return pd.read_csv('https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv&sheet=%s' % (SID, urllib.parse.quote(t)))
def col(df, *n):
    import re
    norm = {re.sub(r'\s+', ' ', str(c)).strip().lower(): c for c in df.columns}
    for x in n:
        k = re.sub(r'\s+', ' ', x).strip().lower()
        if k in norm: return norm[k]
    for x in n:
        for k, o in norm.items():
            if x.strip().lower() in k: return o
    return None
def clean(s):
    import re; s = str(s); m = re.search(r'\(([^)]+)\)', s); return m.group(1).strip() if m else s.strip()

# ── DAILY price (gold_price) ──
gp = tab('gold_price'); gp.columns = [str(c).strip() for c in gp.columns]
gp['Date'] = pd.to_datetime(gp['Date'], errors='coerce')
gp = gp.dropna(subset=['Close']).sort_values('Date')
P = {}
for _, r in gp.iterrows():
    P[r['Date'].strftime('%Y-%m-%d')] = {'o': float(r['Open']), 'h': float(r['High']),
        'l': float(r['Low']), 'c': float(r['Close']), 'dir': str(r['Direction']).strip().upper()}

# ── DAILY moon (MOON_REAL) ──
mr = tab('MOON_REAL'); mr.columns = [str(c).strip() for c in mr.columns]
cD, cS, cSt = col(mr, 'Real Date'), col(mr, 'Clean Moon Sign', 'Moon Sign'), col(mr, 'Cycle Stage')
mr[cD] = pd.to_datetime(mr[cD], errors='coerce'); mr = mr.dropna(subset=[cD])
MOON = {r[cD].strftime('%Y-%m-%d'): {'sign': clean(r[cS]), 'stage': str(r[cSt]).strip()} for _, r in mr.iterrows()}

# ── Nature library ──
sl = tab('SIGN_LIBRARY'); sl.columns = [str(c).strip() for c in sl.columns]
NAT = {str(r['Sign']).strip(): str(r['Nature']).strip().upper()
       for _, r in sl.iterrows() if str(r['Sign']).strip() and str(r['Sign']).strip().lower() != 'nan'}

# ── 4-HOUR candles grouped by calendar day (execution layer) ──
h4 = tab('H4_DATA'); h4.columns = [str(c).strip() for c in h4.columns]
h4['DateTime'] = pd.to_datetime(h4['DateTime'], errors='coerce')
for c in ('Open', 'High', 'Low', 'Close'):
    h4[c] = pd.to_numeric(h4[c], errors='coerce')
h4 = h4.dropna(subset=['DateTime', 'Open', 'High', 'Low', 'Close']).sort_values('DateTime')
DAY_BARS = {}   # 'YYYY-MM-DD' -> [ {o,h,l,c} ... ] in time order
for _, r in h4.iterrows():
    d = r['DateTime'].strftime('%Y-%m-%d')
    DAY_BARS.setdefault(d, []).append({'o': float(r['Open']), 'h': float(r['High']),
                                       'l': float(r['Low']), 'c': float(r['Close'])})

# trading days = price + moon + 4H candles all present
DAYS = sorted(d for d in P if d in MOON and d in DAY_BARS)
IDX = {d: i for i, d in enumerate(DAYS)}

def matching(ds, sign, stage):
    ups, dns = [], []
    for d in DAYS:
        if d >= ds: break
        if MOON[d]['sign'] == sign and MOON[d]['stage'] == stage:
            ch = P[d]['c'] - P[d]['o']; (ups if ch >= 0 else dns).append(abs(ch))
    gu = st.mean([abs(P[d]['c'] - P[d]['o']) for d in DAYS if P[d]['c'] >= P[d]['o']])
    gd = st.mean([abs(P[d]['c'] - P[d]['o']) for d in DAYS if P[d]['c'] <  P[d]['o']])
    return (st.mean(ups) if len(ups) >= 2 else gu), (st.mean(dns) if len(dns) >= 2 else gd)

def PP(ds):
    i = IDX[ds]
    if i == 0: return None
    y = P[DAYS[i-1]]; return (y['h'] + y['l'] + y['c']) / 3

def model(i):
    pa = 1 if P[DAYS[i-1]]['dir'] == 'BULL' else -1
    ds = DAYS[i]; pv = DAYS[i-1]
    nat = NAT.get(MOON[ds]['sign'], ''); stage = MOON[ds]['stage']
    if nat == 'MOVABLE': return -pa if MOON[pv]['sign'] == MOON[ds]['sign'] else pa
    if nat == 'FIXED':   return pa
    return -pa if stage == 'FINISH' else pa

# ── DAILY-managed outcome (this is exactly v7) ──
def outcome_be_daily(entry, i, d, mv, R, n):
    if entry is None or mv <= 0: return None
    if d > 0: stop0, be, tgt = entry-mv, entry+0.5*R*mv, entry+R*mv
    else:     stop0, be, tgt = entry+mv, entry-0.5*R*mv, entry-R*mv
    armed = False
    for k in range(i, min(i+n, len(DAYS))):
        h, l = P[DAYS[k]]['h'], P[DAYS[k]]['l']
        res = _step(d, h, l, entry, stop0, be, tgt, armed)
        if res in ('W', 'BE', 'L'): return res
        armed = res
    return 'BE' if armed else 'L'

# ── 4H-managed outcome: walk the day's 4H candles, then following days' ──
def outcome_be_4h(entry, i, d, mv, R, n):
    if entry is None or mv <= 0: return None
    if d > 0: stop0, be, tgt = entry-mv, entry+0.5*R*mv, entry+R*mv
    else:     stop0, be, tgt = entry+mv, entry-0.5*R*mv, entry-R*mv
    armed = False
    for k in range(i, min(i+n, len(DAYS))):
        for bar in DAY_BARS[DAYS[k]]:
            res = _step(d, bar['h'], bar['l'], entry, stop0, be, tgt, armed)
            if res in ('W', 'BE', 'L'): return res
            armed = res
    return 'BE' if armed else 'L'

def _step(d, h, l, entry, stop0, be, tgt, armed):
    """One candle of breakeven-trail logic. Returns 'W'/'BE'/'L' (terminal) or the new armed bool."""
    if d > 0:
        if not armed:
            if l <= stop0: return 'L'
            if h >= tgt:   return 'W'
            if h >= be:    return True
        else:
            if l <= entry: return 'BE'
            if h >= tgt:   return 'W'
    else:
        if not armed:
            if h >= stop0: return 'L'
            if l <= tgt:   return 'W'
            if l <= be:    return True
        else:
            if h >= entry: return 'BE'
            if l <= tgt:   return 'W'
    return armed

# ── 0.5:1 no-trail reference (daily and 4h) ──
def outcome_orig_daily(entry, i, d, mv, n):
    if entry is None or mv <= 0: return None
    tp = entry+0.5*mv if d > 0 else entry-0.5*mv; stop = entry-mv if d > 0 else entry+mv
    for k in range(i, min(i+n, len(DAYS))):
        h, l = P[DAYS[k]]['h'], P[DAYS[k]]['l']
        ht = (h >= tp) if d > 0 else (l <= tp); hs = (l <= stop) if d > 0 else (h >= stop)
        if ht and hs: return 'L'
        if ht: return 'W'
        if hs: return 'L'
    return 'L'

def outcome_orig_4h(entry, i, d, mv, n):
    if entry is None or mv <= 0: return None
    tp = entry+0.5*mv if d > 0 else entry-0.5*mv; stop = entry-mv if d > 0 else entry+mv
    for k in range(i, min(i+n, len(DAYS))):
        for bar in DAY_BARS[DAYS[k]]:
            h, l = bar['h'], bar['l']
            ht = (h >= tp) if d > 0 else (l <= tp); hs = (l <= stop) if d > 0 else (h >= stop)
            if ht and hs: return 'L'   # both inside same 4h candle -> conservative loss
            if ht: return 'W'
            if hs: return 'L'
    return 'L'

# ── weekly filter ──
def isoweek(ds):
    dt = datetime.strptime(ds, '%Y-%m-%d'); y, w, _ = dt.isocalendar(); return (y, w)
weeks = {}
for d in DAYS: weeks.setdefault(isoweek(d), []).append(d)
wk_dir = {}
for wk, ds in weeks.items():
    net = P[ds[-1]]['c'] - P[ds[0]]['o']; wk_dir[wk] = 1 if net >= 0 else -1
def prior_week_bias(ds):
    y, w = isoweek(ds); return wk_dir.get((y, w-1))

def run(entry_mode, flt, mode, R, n, exec_tf):
    W = BE = L = 0; trades = 0
    for i in range(n, len(DAYS)):
        ds = DAYS[i]; d = model(i)
        if flt == 'weekly':
            b = prior_week_bias(ds)
            if b is not None and ((b > 0 and d < 0) or (b < 0 and d > 0)): continue
        up, dn = matching(ds, MOON[ds]['sign'], MOON[ds]['stage']); mv = up if d > 0 else dn
        entry = P[ds]['o'] if entry_mode == 'open' else PP(ds)
        if mode == 'orig':
            r = (outcome_orig_4h if exec_tf == '4h' else outcome_orig_daily)(entry, i, d, mv, n)
        else:
            r = (outcome_be_4h if exec_tf == '4h' else outcome_be_daily)(entry, i, d, mv, R, n)
        if r is None: continue
        trades += 1
        if r == 'W': W += 1
        elif r == 'BE': BE += 1
        else: L += 1
    rew = R if mode != 'orig' else 0.5
    return W, BE, L, trades, W*rew - L*1.0

def line(name, a):
    W, BE, L, T, R = a
    wr  = (W/T*100) if T else 0
    wl  = (W/(W+L)*100) if (W+L) else 0
    per = (R/T) if T else 0
    print('%-30s W%-3d BE%-3d L%-3d  win%%%5.1f  W/(W+L)%5.1f  | totR %+6.1f  perTrade %+.3f'
          % (name, W, BE, L, wr, wl, R, per))

print('=== DAILY v7 signal, managed on DAILY vs 4-HOUR candles ===')
print('trading days: %d  (%s -> %s)' % (len(DAYS), DAYS[0], DAYS[-1]))
print('window = 3 days | risk = 1*move | outcomes W=target BE=trail(0) L=loss(-1R)\n')

N = 3
print('--- REFERENCE 0.5:1, no trail ---')
for em in ('pp',):
    for flt in (None, 'weekly'):
        nm = 'entry=PIVOT %s' % (flt or 'all')
        line(nm + '  [daily]', run(em, flt, 'orig', 1.0, N, 'daily'))
        line(nm + '  [4H]',    run(em, flt, 'orig', 1.0, N, '4h'))
print()
for R in (1.0, 2.0):
    print('--- REWARD:RISK %d:1  breakeven trail ---' % int(R))
    for em in ('open', 'pp'):
        for flt in (None, 'weekly'):
            nm = 'entry=%-5s %s' % (em, flt or 'all')
            line(nm + ' [daily]', run(em, flt, 'be', R, N, 'daily'))
            line(nm + ' [4H]',    run(em, flt, 'be', R, N, '4h'))
    print()

# -*- coding: utf-8 -*-
"""backtest_4h: your LATEST v7 formula, run on the 4-HOUR timeframe (H4_DATA).

This is a faithful port of backtest_v7.py from the DAILY chart to the 4-HOUR chart.
Everywhere v7 said "day" we now say "4H candle (bar)".

WHAT IS THE SAME AS v7 (your latest rules, untouched):
  - Direction rule  model(): MOVABLE -> fade if same sign as previous bar else follow;
                             FIXED -> follow previous bar; FINISHER -> fade on FINISH stage.
  - Take-profit     outcome_be(): stop = 1*move (1R). When price travels 50% to target the
                    stop moves to ENTRY (breakeven). After that: only WIN or BREAKEVEN.
                    Outcomes: W (full target), BE (breakeven, 0), L (full loss -1R).
  - Conservative OHLC ordering: adverse move assumed first inside each bar.
  - Reward:risk tested at 1:1 and 2:1, plus the original 0.5:1 no-trail reference.
  - Optional prior-week directional filter.

WHAT CHANGED FOR 4H (unavoidable, the daily project is NOT touched):
  - Price = H4_DATA (4-hour OHLC). Direction computed = BULL if close>=open else BEAR
    (the H4 tab has no Direction column).
  - Astrology is DAILY in your sheet, so every 4H candle inherits its calendar day's
    moon Sign + Cycle Stage. The MOVABLE "same sign as previous bar" test therefore
    compares the previous *candle's* day-sign (within one day, candles share a sign).
  - History is short: H4_DATA only spans ~3 months, so sample sizes are smaller than daily.
  - Holding "window" is counted in BARS. 3 daily bars = 3 days; 3 four-hour bars = 12h.
    So we report several window sizes so you can see the holding-period effect.

Run:  python backtest_4h.py
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

# ── 4-HOUR PRICE (H4_DATA): build OHLC + computed direction, keyed by DateTime ──
h4 = tab('H4_DATA'); h4.columns = [str(c).strip() for c in h4.columns]
h4['DateTime'] = pd.to_datetime(h4['DateTime'], errors='coerce')
for c in ('Open', 'High', 'Low', 'Close'):
    h4[c] = pd.to_numeric(h4[c], errors='coerce')
h4 = h4.dropna(subset=['DateTime', 'Open', 'High', 'Low', 'Close']).sort_values('DateTime')
P = {}        # bar-key -> OHLC + dir + date
BARS = []     # ordered bar keys
for _, r in h4.iterrows():
    key = r['DateTime'].strftime('%Y-%m-%d %H:%M')
    o, c = float(r['Open']), float(r['Close'])
    P[key] = {'o': o, 'h': float(r['High']), 'l': float(r['Low']), 'c': c,
              'dir': 'BULL' if c >= o else 'BEAR', 'date': r['DateTime'].strftime('%Y-%m-%d')}
    BARS.append(key)

# ── DAILY MOON (MOON_REAL) -> each bar inherits its calendar day's sign + stage ──
mr = tab('MOON_REAL'); mr.columns = [str(c).strip() for c in mr.columns]
cD, cS, cSt = col(mr, 'Real Date'), col(mr, 'Clean Moon Sign', 'Moon Sign'), col(mr, 'Cycle Stage')
mr[cD] = pd.to_datetime(mr[cD], errors='coerce'); mr = mr.dropna(subset=[cD])
MOON_DAY = {r[cD].strftime('%Y-%m-%d'): {'sign': clean(r[cS]), 'stage': str(r[cSt]).strip()} for _, r in mr.iterrows()}
def moon(bar):
    return MOON_DAY.get(P[bar]['date'])

# ── SIGN_LIBRARY -> Nature (MOVABLE / FIXED / FINISHER) ──
sl = tab('SIGN_LIBRARY'); sl.columns = [str(c).strip() for c in sl.columns]
NAT = {str(r['Sign']).strip(): str(r['Nature']).strip().upper()
       for _, r in sl.iterrows() if str(r['Sign']).strip() and str(r['Sign']).strip().lower() != 'nan'}

# keep only bars that have moon data, in order
BARS = [b for b in BARS if moon(b) is not None]
IDX = {b: i for i, b in enumerate(BARS)}

# ── matching(): avg up / down move (close-open) for bars sharing this sign+stage ──
_GU = st.mean([abs(P[b]['c'] - P[b]['o']) for b in BARS if P[b]['c'] >= P[b]['o']])
_GD = st.mean([abs(P[b]['c'] - P[b]['o']) for b in BARS if P[b]['c'] <  P[b]['o']])
def matching(bar, sign, stage):
    ups, dns = [], []
    for b in BARS:
        if b >= bar: break
        m = moon(b)
        if m['sign'] == sign and m['stage'] == stage:
            ch = P[b]['c'] - P[b]['o']; (ups if ch >= 0 else dns).append(abs(ch))
    return (st.mean(ups) if len(ups) >= 2 else _GU), (st.mean(dns) if len(dns) >= 2 else _GD)

# ── pivot entry: classic pivot from the PREVIOUS bar's H/L/C ──
def PP(bar):
    i = IDX[bar]
    if i == 0: return None
    y = P[BARS[i-1]]; return (y['h'] + y['l'] + y['c']) / 3

# ── DIRECTION RULE (v7 model, ported bar-by-bar) ──
def model(i):
    prev = BARS[i-1]; cur = BARS[i]
    pa = 1 if P[prev]['dir'] == 'BULL' else -1
    m = moon(cur); nat = NAT.get(m['sign'], ''); stage = m['stage']
    if nat == 'MOVABLE':
        return -pa if moon(prev)['sign'] == m['sign'] else pa
    if nat == 'FIXED':
        return pa
    return -pa if stage == 'FINISH' else pa    # FINISHER

# ── outcome with breakeven trail (v7), window n counted in BARS ──
def outcome_be(entry, i, d, mv, R, n):
    if entry is None or mv <= 0: return None
    if d > 0:
        stop0 = entry - mv; be = entry + 0.5*R*mv; tgt = entry + R*mv
    else:
        stop0 = entry + mv; be = entry - 0.5*R*mv; tgt = entry - R*mv
    armed = False
    for k in range(i, min(i+n, len(BARS))):
        h, l = P[BARS[k]]['h'], P[BARS[k]]['l']
        if d > 0:
            if not armed:
                if l <= stop0: return 'L'
                if h >= tgt:   return 'W'
                if h >= be:    armed = True
            else:
                if l <= entry: return 'BE'
                if h >= tgt:   return 'W'
        else:
            if not armed:
                if h >= stop0: return 'L'
                if l <= tgt:   return 'W'
                if l <= be:    armed = True
            else:
                if h >= entry: return 'BE'
                if l <= tgt:   return 'W'
    return 'BE' if armed else 'L'

# ── original (no trail) reference: TP1 = 0.5*move, stop = 1*move ──
def outcome_orig(entry, i, d, mv, n):
    if entry is None or mv <= 0: return None
    tp = entry + 0.5*mv if d > 0 else entry - 0.5*mv
    stop = entry - mv if d > 0 else entry + mv
    for k in range(i, min(i+n, len(BARS))):
        h, l = P[BARS[k]]['h'], P[BARS[k]]['l']
        ht = (h >= tp) if d > 0 else (l <= tp)
        hs = (l <= stop) if d > 0 else (h >= stop)
        if ht and hs: return 'L'
        if ht: return 'W'
        if hs: return 'L'
    return 'L'

# ── prior-week directional filter (by ISO week of the bar's calendar date) ──
def isoweek(datestr):
    dt = datetime.strptime(datestr, '%Y-%m-%d'); y, w, _ = dt.isocalendar(); return (y, w)
weeks = {}
for b in BARS: weeks.setdefault(isoweek(P[b]['date']), []).append(b)
wk_dir = {}
for wk, bs in weeks.items():
    net = P[bs[-1]]['c'] - P[bs[0]]['o']; wk_dir[wk] = 1 if net >= 0 else -1
def prior_week_bias(bar):
    y, w = isoweek(P[bar]['date']); return wk_dir.get((y, w-1))

# ── run one configuration ──
def run(entry_mode, flt, mode, R, n):
    W = BE = L = 0; trades = 0
    for i in range(n, len(BARS)):     # warmup = window length
        bar = BARS[i]; d = model(i)
        if flt == 'weekly':
            b = prior_week_bias(bar)
            if b is not None and ((b > 0 and d < 0) or (b < 0 and d > 0)): continue
        m = moon(bar)
        up, dn = matching(bar, m['sign'], m['stage']); mv = up if d > 0 else dn
        entry = P[bar]['o'] if entry_mode == 'open' else PP(bar)
        r = outcome_orig(entry, i, d, mv, n) if mode == 'orig' else outcome_be(entry, i, d, mv, R, n)
        if r is None: continue
        trades += 1
        if r == 'W': W += 1
        elif r == 'BE': BE += 1
        else: L += 1
    rew = R if mode != 'orig' else 0.5
    totR = W*rew - L*1.0
    return W, BE, L, trades, totR

def line(name, a):
    W, BE, L, T, R = a
    wr  = (W/T*100) if T else 0
    wl  = (W/(W+L)*100) if (W+L) else 0
    per = (R/T) if T else 0
    print('%-44s W%-4d BE%-4d L%-4d  win%%%5.1f  W/(W+L)%5.1f  | totR %+7.1f  perTrade %+.3f'
          % (name, W, BE, L, wr, wl, R, per))

print('=== 4-HOUR backtest of your LATEST v7 formula (H4_DATA) ===')
print('bars loaded: %d   span: %s -> %s' % (len(BARS), P[BARS[0]]['date'], P[BARS[-1]]['date']))
print('Model = v7 current (9-cycle off) | risk = 1*move | astrology inherited per calendar day')
print('outcomes: W=hit target  BE=breakeven trail(0)  L=full loss(-1R)\n')

for n in (3, 6):
    hours = n * 4
    print('############  HOLDING WINDOW = %d bars (~%dh)  ############' % (n, hours))
    print('--- REFERENCE: original TP1=0.5*move, stop=1*move, NO trail (0.5:1) ---')
    line('entry=PIVOT  all',    run('pp', None, 'orig', 1.0, n))
    line('entry=PIVOT  weekly', run('pp', 'weekly', 'orig', 1.0, n))
    print()
    for R in (1.0, 2.0):
        print('--- REWARD:RISK %d:1  WITH breakeven trail (stop->entry at 50%% to target) ---' % int(R))
        line('entry=open   all',    run('open', None, 'be', R, n))
        line('entry=PIVOT  all',    run('pp',   None, 'be', R, n))
        line('entry=open   weekly', run('open', 'weekly', 'be', R, n))
        line('entry=PIVOT  weekly', run('pp',   'weekly', 'be', R, n))
        print()
    print()

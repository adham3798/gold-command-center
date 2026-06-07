# -*- coding: utf-8 -*-
"""strategy_4h: THE 4-hour strategy.

Plain-English rules (exactly as requested):
  1. DIRECTION  -> the DAILY signal. Whatever the daily v7 formula says (BUY or SELL),
                   we take that trade. The daily chart is the brain.
  2. ENTRY      -> the classic PIVOT POINT of the signal day  PP=(prevH+prevL+prevC)/3.
                   We enter on the signal day when a 4H candle trades to the pivot
                   (a real intraday fill). If the pivot is never touched that day -> no trade.
  3. STOP & TP  -> sized and trailed from the 4-HOUR candles:
                   * unit = 4H ATR (average 4-hour candle range over the last `atr_n` bars)
                   * stop distance = atr_mult * unit
                   * take-profit   = R * stop distance      (R = reward:risk)
                   * breakeven trail: when price travels 50% to TP, stop moves to ENTRY,
                     after that the trade can only WIN (full TP) or BREAK EVEN (0).
                   All of this is checked candle-by-candle on the 4H chart.

  Conservative: inside one 4H candle we assume the adverse move happens first.
  Outcomes per trade: W (hit TP, +R), BE (breakeven, 0), L (full loss, -1R).

The DAILY direction rule itself is your v7 `model()` -- unchanged. Daily project untouched.

Run:  python strategy_4h.py
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

# ── DAILY price + moon + nature (the signal brain) ──
gp = tab('gold_price'); gp.columns = [str(c).strip() for c in gp.columns]
gp['Date'] = pd.to_datetime(gp['Date'], errors='coerce'); gp = gp.dropna(subset=['Close']).sort_values('Date')
P = {r['Date'].strftime('%Y-%m-%d'): {'o': float(r['Open']), 'h': float(r['High']), 'l': float(r['Low']),
     'c': float(r['Close']), 'dir': str(r['Direction']).strip().upper()} for _, r in gp.iterrows()}
mr = tab('MOON_REAL'); mr.columns = [str(c).strip() for c in mr.columns]
cD, cS, cSt = col(mr, 'Real Date'), col(mr, 'Clean Moon Sign', 'Moon Sign'), col(mr, 'Cycle Stage')
mr[cD] = pd.to_datetime(mr[cD], errors='coerce'); mr = mr.dropna(subset=[cD])
MOON = {r[cD].strftime('%Y-%m-%d'): {'sign': clean(r[cS]), 'stage': str(r[cSt]).strip()} for _, r in mr.iterrows()}
sl = tab('SIGN_LIBRARY'); sl.columns = [str(c).strip() for c in sl.columns]
NAT = {str(r['Sign']).strip(): str(r['Nature']).strip().upper()
       for _, r in sl.iterrows() if str(r['Sign']).strip() and str(r['Sign']).strip().lower() != 'nan'}

# ── 4-HOUR candles: flat ordered list + per-day groups (execution + stop/TP sizing) ──
h4 = tab('H4_DATA'); h4.columns = [str(c).strip() for c in h4.columns]
h4['DateTime'] = pd.to_datetime(h4['DateTime'], errors='coerce')
for c in ('Open', 'High', 'Low', 'Close'):
    h4[c] = pd.to_numeric(h4[c], errors='coerce')
h4 = h4.dropna(subset=['DateTime', 'Open', 'High', 'Low', 'Close']).sort_values('DateTime')
BARS4 = []                 # flat, time-ordered
DAY_FIRST = {}             # day -> index of its first 4H bar in BARS4
for _, r in h4.iterrows():
    d = r['DateTime'].strftime('%Y-%m-%d')
    if d not in DAY_FIRST: DAY_FIRST[d] = len(BARS4)
    BARS4.append({'day': d, 'o': float(r['Open']), 'h': float(r['High']),
                  'l': float(r['Low']), 'c': float(r['Close'])})

# trading days = price + moon + 4H candles all present
DAYS = sorted(d for d in P if d in MOON and d in DAY_FIRST)
IDX = {d: i for i, d in enumerate(DAYS)}

def PP(ds):                # pivot of the signal day, from the PREVIOUS day's H/L/C
    i = IDX[ds]
    if i == 0: return None
    y = P[DAYS[i-1]]; return (y['h'] + y['l'] + y['c']) / 3

def model(i):              # v7 DAILY direction rule, unchanged
    pa = 1 if P[DAYS[i-1]]['dir'] == 'BULL' else -1
    ds = DAYS[i]; pv = DAYS[i-1]
    nat = NAT.get(MOON[ds]['sign'], ''); stage = MOON[ds]['stage']
    if nat == 'MOVABLE': return -pa if MOON[pv]['sign'] == MOON[ds]['sign'] else pa
    if nat == 'FIXED':   return pa
    return -pa if stage == 'FINISH' else pa

# 4H ATR (average candle range) over the last atr_n bars BEFORE this day starts
_GLOBAL_RANGE = st.mean([b['h'] - b['l'] for b in BARS4]) or 1.0
def atr_4h(ds, atr_n):
    start = DAY_FIRST[ds]
    rng = [BARS4[j]['h'] - BARS4[j]['l'] for j in range(max(0, start - atr_n), start)]
    return st.mean(rng) if len(rng) >= max(3, atr_n // 2) else _GLOBAL_RANGE

# weekly filter (prior-week net direction)
def isoweek(ds):
    dt = datetime.strptime(ds, '%Y-%m-%d'); y, w, _ = dt.isocalendar(); return (y, w)
weeks = {}
for d in DAYS: weeks.setdefault(isoweek(d), []).append(d)
wk_dir = {wk: (1 if (P[ds[-1]]['c'] - P[ds[0]]['o']) >= 0 else -1) for wk, ds in weeks.items()}
def prior_week_bias(ds):
    y, w = isoweek(ds); return wk_dir.get((y, w - 1))

def trade(i, d, atr_mult, R, atr_n, max_days):
    """Return ('W'|'BE'|'L'|'NF', detail). NF = pivot never touched (no fill)."""
    ds = DAYS[i]
    entry = PP(ds)
    if entry is None: return 'NF', None
    unit = atr_4h(ds, atr_n)
    stopd = atr_mult * unit
    if stopd <= 0: return 'NF', None
    if d > 0: stop0, be, tgt = entry - stopd, entry + 0.5*R*stopd, entry + R*stopd
    else:     stop0, be, tgt = entry + stopd, entry - 0.5*R*stopd, entry - R*stopd

    # walk 4H candles from the signal day forward; fill when pivot is first touched
    start = DAY_FIRST[ds]
    end_day = DAYS[min(i + max_days, len(DAYS)) - 1]
    last = DAY_FIRST[end_day] + _day_len(end_day)
    filled = False; armed = False
    for j in range(start, last):
        b = BARS4[j]
        if not filled:
            if b['l'] <= entry <= b['h']:
                filled = True            # entered at pivot inside this candle
            else:
                continue
        # management (conservative: adverse first within the candle)
        h, l = b['h'], b['l']
        if d > 0:
            if not armed:
                if l <= stop0: return 'L', None
                if h >= tgt:   return 'W', None
                if h >= be:    armed = True
            else:
                if l <= entry: return 'BE', None
                if h >= tgt:   return 'W', None
        else:
            if not armed:
                if h >= stop0: return 'L', None
                if l <= tgt:   return 'W', None
                if l <= be:    armed = True
            else:
                if h >= entry: return 'BE', None
                if l <= tgt:   return 'W', None
    if not filled: return 'NF', None
    return ('BE' if armed else 'L'), None

def _day_len(day):
    s = DAY_FIRST[day]; n = 0
    while s + n < len(BARS4) and BARS4[s + n]['day'] == day: n += 1
    return n

def run(atr_mult, R, atr_n, max_days, weekly):
    W = BE = L = NF = 0
    for i in range(1, len(DAYS)):
        d = model(i)
        if weekly:
            b = prior_week_bias(DAYS[i])
            if b is not None and ((b > 0 and d < 0) or (b < 0 and d > 0)): continue
        r, _ = trade(i, d, atr_mult, R, atr_n, max_days)
        if   r == 'W':  W += 1
        elif r == 'BE': BE += 1
        elif r == 'L':  L += 1
        else:           NF += 1
    T = W + BE + L
    totR = W * R - L
    return W, BE, L, NF, T, totR

def line(name, a):
    W, BE, L, NF, T, R = a
    wr  = (W/T*100) if T else 0
    wl  = (W/(W+L)*100) if (W+L) else 0
    per = (R/T) if T else 0
    print('%-34s W%-3d BE%-3d L%-3d (skip %-3d) win%%%5.1f W/(W+L)%5.1f | totR %+6.1f perTrade %+.3f'
          % (name, W, BE, L, NF, wr, wl, R, per))

print('=== 4-HOUR STRATEGY: daily signal -> pivot entry -> 4H stop/TP ===')
print('trading days: %d (%s -> %s) | stop=atr_mult*4H-ATR | TP=R*stop | window=3 days' % (len(DAYS), DAYS[0], DAYS[-1]))
print('outcomes: W=hit TP(+R)  BE=breakeven trail(0)  L=full loss(-1R)  skip=pivot not touched\n')

ATR_N, MAXD = 30, 3   # ATR lookback ~5 days of 4H bars; hold up to 3 days
for R in (1.0, 2.0):
    for mult in (1.0, 1.5, 2.0):
        print('--- reward:risk %.0f:1 | stop = %.1f x 4H-ATR ---' % (R, mult))
        line('all days', run(mult, R, ATR_N, MAXD, False))
        line('weekly filter', run(mult, R, ATR_N, MAXD, True))
        print()

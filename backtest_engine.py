# -*- coding: utf-8 -*-
"""
backtest_engine.py — backtests the ACTUAL dashboard signal (engine.compute_signal),
so the number you see is the system you trade. Also runs an ABLATION:

    1. Astro engine (engine.compute_signal)   <- what the dashboard shows
    2. Nature rule  (the simple model() from backtest_v7)
    3. Always-BULL baseline (the bull base rate of the sample)

For each it reports point-in-time DIRECTIONAL accuracy, plus the same
breakeven-trail money-management outcome as backtest_v7 (W / BE / L, totR).

Run:  python backtest_engine.py     (needs engine.py beside it + internet to the sheet)
"""
import pandas as pd, urllib.parse, statistics as st, re
import engine as E

SID = '12ynlr46bvHSJLnLGs5Z1SrhhlCj6_w7qO6YHMDBY7gs'
def tab(t): return pd.read_csv('https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv&sheet=%s' % (SID, urllib.parse.quote(t)))
def col(df, *n):
    norm = {re.sub(r'\s+', ' ', str(c)).strip().lower(): c for c in df.columns}
    for x in n:
        k = re.sub(r'\s+', ' ', x).strip().lower()
        if k in norm: return norm[k]
    for x in n:
        for k, o in norm.items():
            if x.strip().lower() in k: return o
    return None
def clean(s):
    s = str(s); m = re.search(r'\(([^)]+)\)', s); return m.group(1).strip() if m else s.strip()

# ---- price ----
gp = tab('gold_price'); gp.columns = [str(c).strip() for c in gp.columns]
gp['Date'] = pd.to_datetime(gp['Date'], errors='coerce'); gp = gp.dropna(subset=['Close']).sort_values('Date')
P = {}
for _, r in gp.iterrows():
    o, c = float(r['Open']), float(r['Close'])
    P[r['Date'].strftime('%Y-%m-%d')] = {'o': o, 'h': float(r['High']), 'l': float(r['Low']), 'c': c,
                                         'dir': 'BULL' if c >= o else 'BEAR'}

# ---- moon (sign, stage, + extra fields the engine wants) ----
mr = tab('MOON_REAL'); mr.columns = [str(c).strip() for c in mr.columns]
cD  = col(mr, 'Real Date', 'Date')
cS  = col(mr, 'Clean Moon Sign', 'Moon Sign')
cSt = col(mr, 'Cycle Stage', 'Stage')
cDn = col(mr, 'Day Number')
cPh = col(mr, 'Moon Phase', 'Phase')
cG  = col(mr, 'Gender')
cSn = col(mr, 'Stage Number')
cSun= col(mr, 'Sun Sign')
mr[cD] = pd.to_datetime(mr[cD], errors='coerce'); mr = mr.dropna(subset=[cD])
MOON = {}
for _, r in mr.iterrows():
    d = r[cD].strftime('%Y-%m-%d')
    def g(c):
        try: return r[c] if c else None
        except Exception: return None
    dn = g(cDn)
    try: dn = int(float(dn))
    except Exception: dn = None
    sn = g(cSn)
    try: sn = int(float(sn))
    except Exception: sn = None
    MOON[d] = {'sign': clean(g(cS)), 'stage': str(g(cSt)).strip(),
               'day_number': dn, 'phase': str(g(cPh) or '').strip(),
               'gender': str(g(cG) or '').strip().upper(), 'stage_num': sn,
               'sun_sign': clean(g(cSun)) if cSun else E.get_sun_sign(d)}

DAYS = sorted(d for d in P if d in MOON)
NAT  = {s: E.ZODIAC_DB[s]['nature'] for s in E.ZODIAC_DB}

def nature_dir(i):
    pa = 1 if P[DAYS[i-1]]['dir'] == 'BULL' else -1
    ds, pv = DAYS[i], DAYS[i-1]; nat = NAT.get(MOON[ds]['sign'], ''); stage = MOON[ds]['stage']
    if nat == 'MOVABLE': return -pa if MOON[pv]['sign'] == MOON[ds]['sign'] else pa
    if nat == 'FIXED':   return pa
    return -pa if stage == 'FINISH' else pa

def engine_dir(i):
    ds = DAYS[i]; bull = bear = 0
    for d in DAYS:
        if d >= ds: break
        if MOON[d]['sign'] == MOON[ds]['sign'] and MOON[d]['stage'] == MOON[ds]['stage']:
            bull += P[d]['dir'] == 'BULL'; bear += P[d]['dir'] == 'BEAR'
    hist = [MOON[d] for d in DAYS if d < ds]
    r = E.compute_signal(ds, MOON[ds], {'bull': bull, 'bear': bear}, hist, mtf=None)
    b = r['bias']
    return 1 if b >= 6 else (-1 if b <= -6 else 0)

def always(i): return 1

def matching(i):
    ds = DAYS[i]; ups, dns = [], []
    for d in DAYS:
        if d >= ds: break
        if MOON[d]['sign'] == MOON[ds]['sign'] and MOON[d]['stage'] == MOON[ds]['stage']:
            ch = P[d]['c'] - P[d]['o']; (ups if ch >= 0 else dns).append(abs(ch))
    # FIX 5: point-in-time global fallback (only days strictly before ds)
    prior = [P[d]['c'] - P[d]['o'] for d in DAYS if d < ds]
    gu = st.mean([abs(x) for x in prior if x >= 0]) if any(x >= 0 for x in prior) else 1
    gd = st.mean([abs(x) for x in prior if x < 0]) if any(x < 0 for x in prior) else 1
    return (st.mean(ups) if len(ups) >= 2 else gu), (st.mean(dns) if len(dns) >= 2 else gd)

def outcome_be(entry, i, d, mv, R=1.0, n=3):
    if entry is None or mv <= 0: return None
    if d > 0: stop0, be, tgt = entry-mv, entry+0.5*R*mv, entry+R*mv
    else:     stop0, be, tgt = entry+mv, entry-0.5*R*mv, entry-R*mv
    armed = False
    for k in range(i, min(i+n, len(DAYS))):
        h, l = P[DAYS[k]]['h'], P[DAYS[k]]['l']
        if d > 0:
            if not armed:
                if l <= stop0: return 'L'
                if h >= tgt:  return 'W'
                if h >= be:   armed = True
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

def report(name, dir_fn, R=1.0):
    dw = dt = 0; W = BE = L = 0
    for i in range(3, len(DAYS)):
        d = dir_fn(i)
        if d == 0: continue
        real = 1 if P[DAYS[i]]['dir'] == 'BULL' else -1
        dt += 1; dw += (d == real)
        up, dn = matching(i); mv = up if d > 0 else dn
        r = outcome_be(P[DAYS[i]]['o'], i, d, mv, R)
        if r == 'W': W += 1
        elif r == 'BE': BE += 1
        elif r == 'L': L += 1
    acc = dw/dt*100 if dt else 0
    totR = W*R - L
    per = totR/(W+BE+L) if (W+BE+L) else 0
    print('  %-26s dir-acc %5.1f%% (%d/%d)  | mgmt W%-3d BE%-3d L%-3d  totR %+6.1f  perTrade %+.3f'
          % (name, acc, dw, dt, W, BE, L, totR, per))

if __name__ == '__main__':
    nb = sum(1 for d in DAYS[3:] if P[d]['dir'] == 'BULL')
    print('Sample: %d days  %s -> %s   (bull base rate %.1f%%)\n' % (len(DAYS), DAYS[0], DAYS[-1], nb/(len(DAYS)-3)*100))
    print('ABLATION — directional accuracy + breakeven-trail management (R=1):')
    report('Astro engine (dashboard)', engine_dir)
    report('Nature rule (model v7)',   nature_dir)
    report('Always-BULL baseline',     always)
    print('\nIf the astro engine does not beat the nature rule AND neither beats the\n'
          'bull base rate, the directional layer is not earning its place — simplify,\n'
          'and put the work into the management (R:R, trail trigger, time-stop).')

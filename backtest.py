# -*- coding: utf-8 -*-
"""
EXPERIMENT — does the nature/cycle direction model beat the current engine?
Standalone backtest. Does NOT touch the live app. Compares win rates under the
SAME TP1(50%) win/loss model, isolating the DIRECTION logic.
"""
import pandas as pd, urllib.parse, statistics as st

SID = '12ynlr46bvHSJLnLGs5Z1SrhhlCj6_w7qO6YHMDBY7gs'
def tab(t):
    return pd.read_csv('https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv&sheet=%s'
                       % (SID, urllib.parse.quote(t)))

def col(df, *names):
    import re
    norm = {re.sub(r'\s+',' ',str(c)).strip().lower(): c for c in df.columns}
    for n in names:
        k = re.sub(r'\s+',' ',n).strip().lower()
        if k in norm: return norm[k]
    for n in names:
        for k,o in norm.items():
            if n.strip().lower() in k: return o
    return None

def clean(s):
    import re
    s=str(s); m=re.search(r'\(([^)]+)\)',s); return m.group(1).strip() if m else s.replace('Moon Sign','').strip()

def droot(dom):
    while dom>9: dom=sum(int(c) for c in str(dom))
    return dom

# ── load ──
gp=tab('gold_price'); gp.columns=[str(c).strip() for c in gp.columns]
gp['Date']=pd.to_datetime(gp['Date'],errors='coerce'); gp=gp.dropna(subset=['Close']).sort_values('Date')
PRICES={}
for _,r in gp.iterrows():
    PRICES[r['Date'].strftime('%Y-%m-%d')]={'o':round(float(r['Open']),2),'h':round(float(r['High']),2),
        'l':round(float(r['Low']),2),'c':round(float(r['Close']),2),
        'chg':round(float(r['Close'])-float(r['Open']),2),'dir':str(r['Direction']).strip().upper()}

mr=tab('MOON_REAL'); mr.columns=[str(c).strip() for c in mr.columns]
cD,cS,cSt=col(mr,'Real Date'),col(mr,'Clean Moon Sign','Moon Sign'),col(mr,'Cycle Stage')
mr[cD]=pd.to_datetime(mr[cD],errors='coerce'); mr=mr.dropna(subset=[cD])
MOON={r[cD].strftime('%Y-%m-%d'):{'sign':clean(r[cS]),'stage':str(r[cSt]).strip()} for _,r in mr.iterrows()}

sl=tab('SIGN_LIBRARY'); sl.columns=[str(c).strip() for c in sl.columns]
NATURE={str(r['Sign']).strip():str(r['Nature']).strip().upper() for _,r in sl.iterrows() if str(r['Sign']).strip() and str(r['Sign']).strip().lower()!='nan'}

DAYS=sorted(d for d in PRICES if d in MOON)   # trading days with astro

def matching(ds,sign,stage):
    ups,downs=[],[]
    for d in DAYS:
        if d>=ds: break
        m=MOON[d]
        if m['sign']==sign and m['stage']==stage:
            ch=PRICES[d]['chg']; (ups if ch>=0 else downs).append(abs(ch))
    g_up=st.mean([abs(PRICES[d]['chg']) for d in DAYS if PRICES[d]['chg']>=0])
    g_dn=st.mean([abs(PRICES[d]['chg']) for d in DAYS if PRICES[d]['chg']<0])
    return (st.mean(ups) if len(ups)>=2 else g_up), (st.mean(downs) if len(downs)>=2 else g_dn)

def tp1_win(ds, pred):           # pred: +1 buy / -1 sell ; TP1=50% move, stop=full move
    p=PRICES[ds]; up,dn=matching(ds,MOON[ds]['sign'],MOON[ds]['stage'])
    mv=up if pred>0 else dn
    o,h,l=p['o'],p['h'],p['l']
    if pred>0: tp,sLv=o+0.5*mv,o-mv; tp_hit,sl_hit=h>=tp,l<=sLv
    else:      tp,sLv=o-0.5*mv,o+mv; tp_hit,sl_hit=l<=tp,h>=sLv
    return tp_hit and not sl_hit

# ── models ──
def experimental_dir(ds, prev):
    pa = 1 if PRICES[prev]['dir']=='BULL' else -1     # yesterday's ACTUAL
    nat=NATURE.get(MOON[ds]['sign'],''); stage=MOON[ds]['stage']
    nine=droot(int(ds[-2:]))==9; prevNine=droot(int(prev[-2:]))==9
    if prevNine:            return -pa            # day after 9-date: turn fires
    if nine:                return pa             # 9-date: final exhaustion push
    if nat=='MOVABLE':      return -pa            # movable reverses
    if nat=='FIXED':        return pa             # fixed continues old trend
    return (-pa if stage=='FINISH' else pa)       # finisher: turn at FINISH else continue

def exp_v2_dir(ds, prev):                          # variant: MOVABLE continues (not reverse)
    pa = 1 if PRICES[prev]['dir']=='BULL' else -1
    nat=NATURE.get(MOON[ds]['sign'],''); stage=MOON[ds]['stage']
    nine=droot(int(ds[-2:]))==9; prevNine=droot(int(prev[-2:]))==9
    if prevNine: return -pa
    if nine:     return pa
    if nat=='MOVABLE': return pa                   # <-- continue instead of reverse
    if nat=='FIXED':   return pa
    return (-pa if stage=='FINISH' else pa)

def exp_v3_dir(ds, prev):                          # variant: movable reverses ONLY on 2nd day of the sign
    pa = 1 if PRICES[prev]['dir']=='BULL' else -1
    nat=NATURE.get(MOON[ds]['sign'],''); stage=MOON[ds]['stage']
    nine=droot(int(ds[-2:]))==9; prevNine=droot(int(prev[-2:]))==9
    if prevNine: return -pa
    if nine:     return pa
    if nat=='MOVABLE':
        same = MOON.get(prev,{}).get('sign')==MOON[ds]['sign']   # 2nd day of same movable sign
        return -pa if same else pa
    if nat=='FIXED':   return pa
    return (-pa if stage=='FINISH' else pa)

def baseline_persist_dir(ds, prev):               # naive: today repeats yesterday's actual
    return 1 if PRICES[prev]['dir']=='BULL' else -1

# ── run ──
def run(fn):
    w=n=0
    for i in range(1,len(DAYS)):
        ds,prev=DAYS[i],DAYS[i-1]
        if tp1_win(ds, fn(ds,prev)): w+=1
        n+=1
    return w,n

models=[('EXPERIMENTAL v1 (movable=reverse)',experimental_dir),
        ('EXPERIMENTAL v2 (movable=continue)',exp_v2_dir),
        ('EXPERIMENTAL v3 (movable reverse 2nd-day only)',exp_v3_dir),
        ('BASELINE naive persistence',baseline_persist_dir)]
print('=== BACKTEST (TP1 50%% win/loss, same model for all) ===')
print('Trading days tested: %d\n' % (len(DAYS)-1))
for name,fn in models:
    w,n=run(fn); print('%-46s %d/%d = %.1f%%' % (name,w,n,w/n*100))
print('\n(Current live engine on its strong-signal days = ~36.4%% / 44 days, for reference.)')

# -*- coding: utf-8 -*-
"""Empirically test the cheat-sheet factors against the real price history.
Read-only analysis. No app changes."""
import pandas as pd, urllib.parse, statistics as st

SID='12ynlr46bvHSJLnLGs5Z1SrhhlCj6_w7qO6YHMDBY7gs'
def tab(t): return pd.read_csv('https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv&sheet=%s'%(SID,urllib.parse.quote(t)))
def col(df,*n):
    import re
    norm={re.sub(r'\s+',' ',str(c)).strip().lower():c for c in df.columns}
    for x in n:
        k=re.sub(r'\s+',' ',x).strip().lower()
        if k in norm:return norm[k]
    for x in n:
        for k,o in norm.items():
            if x.strip().lower() in k:return o
    return None
def clean(s):
    import re; s=str(s); m=re.search(r'\(([^)]+)\)',s); return m.group(1).strip() if m else s.strip()
def droot(d):
    while d>9:d=sum(int(c) for c in str(d))
    return d

gp=tab('gold_price'); gp.columns=[str(c).strip() for c in gp.columns]
gp['Date']=pd.to_datetime(gp['Date'],errors='coerce'); gp=gp.dropna(subset=['Close']).sort_values('Date')
P={}
for _,r in gp.iterrows():
    P[r['Date'].strftime('%Y-%m-%d')]={'o':float(r['Open']),'h':float(r['High']),'l':float(r['Low']),'c':float(r['Close']),'dir':str(r['Direction']).strip().upper()}
mr=tab('MOON_REAL'); mr.columns=[str(c).strip() for c in mr.columns]
cD,cS,cSt=col(mr,'Real Date'),col(mr,'Clean Moon Sign','Moon Sign'),col(mr,'Cycle Stage')
mr[cD]=pd.to_datetime(mr[cD],errors='coerce'); mr=mr.dropna(subset=[cD])
MOON={r[cD].strftime('%Y-%m-%d'):{'sign':clean(r[cS]),'stage':str(r[cSt]).strip()} for _,r in mr.iterrows()}
sl=tab('SIGN_LIBRARY'); sl.columns=[str(c).strip() for c in sl.columns]
NAT={str(r['Sign']).strip():str(r['Nature']).strip().upper() for _,r in sl.iterrows() if str(r['Sign']).strip() and str(r['Sign']).strip().lower()!='nan'}

DAYS=sorted(d for d in P if d in MOON)
def pct(a,b): return '%.1f%%'%(a/b*100) if b else 'n/a'
N=len(DAYS)
bull_rate=sum(1 for d in DAYS if P[d]['dir']=='BULL')/N
print('Trading days (2026, with astro):',N,'| overall bullish-day rate:',pct(sum(1 for d in DAYS if P[d]['dir']=='BULL'),N))
print('='*64)

# 1) Sign NATURE -> reversal rate (does today flip yesterday's direction?)
print('\n[1] NATURE -> does today REVERSE the prior day?  (movable should be HIGH)')
natrev={}
for i in range(1,N):
    d,pv=DAYS[i],DAYS[i-1]; nat=NAT.get(MOON[d]['sign'],'?')
    rev=P[d]['dir']!=P[pv]['dir']
    natrev.setdefault(nat,[0,0]); natrev[nat][1]+=1; natrev[nat][0]+=1 if rev else 0
for nat,(r,n) in sorted(natrev.items()): print('   %-9s reversal rate %s  (%d/%d)'%(nat,pct(r,n),r,n))

# 2) 9-date behaviour + day AFTER a 9-date
print('\n[2] 9-DATE (9/18/27) and the day AFTER it')
nine_cont=[0,0]; after9_rev=[0,0]
for i in range(1,N):
    d,pv=DAYS[i],DAYS[i-1]
    if droot(int(d[-2:]))==9:
        nine_cont[1]+=1; nine_cont[0]+=1 if P[d]['dir']==P[pv]['dir'] else 0   # continues prior?
    if droot(int(pv[-2:]))==9:
        after9_rev[1]+=1; after9_rev[0]+=1 if P[d]['dir']!=P[pv]['dir'] else 0  # reverses?
print('   9-date CONTINUES prior dir: %s (%d/%d)'%(pct(*nine_cont[::-1]) if False else pct(nine_cont[0],nine_cont[1]),nine_cont[0],nine_cont[1]))
print('   day AFTER 9-date REVERSES:  %s (%d/%d)'%(pct(after9_rev[0],after9_rev[1]),after9_rev[0],after9_rev[1]))

# 3) Pivot PP bias: P(bullish day | open > PP)
print('\n[3] PIVOT PP  (open above PP -> bullish day?)')
ab=[0,0]; bl=[0,0]
for i in range(1,N):
    d,pv=DAYS[i],DAYS[i-1]; y=P[pv]; PP=(y['h']+y['l']+y['c'])/3
    tgt=ab if P[d]['o']>PP else bl
    tgt[1]+=1; tgt[0]+=1 if P[d]['dir']=='BULL' else 0
print('   open ABOVE PP -> bullish: %s (%d/%d)'%(pct(ab[0],ab[1]),ab[0],ab[1]))
print('   open BELOW PP -> bullish: %s (%d/%d)'%(pct(bl[0],bl[1]),bl[0],bl[1]))

# 4) Entry fill / target reach rates (S1 dip fill, R1 reach)
print('\n[4] LEVEL FILL RATES  (how often price touches the level intraday)')
s1f=[0,0]; r1r=[0,0]; yhB=[0,0]; ylB=[0,0]
for i in range(1,N):
    d,pv=DAYS[i],DAYS[i-1]; y=P[pv]; PP=(y['h']+y['l']+y['c'])/3; R1=2*PP-y['l']; S1=2*PP-y['h']
    s1f[1]+=1; s1f[0]+=1 if P[d]['l']<=S1 else 0
    r1r[1]+=1; r1r[0]+=1 if P[d]['h']>=R1 else 0
    yhB[1]+=1; yhB[0]+=1 if P[d]['h']>y['h'] else 0
    ylB[1]+=1; ylB[0]+=1 if P[d]['l']<y['l'] else 0
print('   today LOW reaches S1 (buy-dip fills): %s (%d/%d)'%(pct(s1f[0],s1f[1]),s1f[0],s1f[1]))
print('   today HIGH reaches R1:                %s (%d/%d)'%(pct(r1r[0],r1r[1]),r1r[0],r1r[1]))
print('   today breaks YESTERDAY HIGH:          %s (%d/%d)'%(pct(yhB[0],yhB[1]),yhB[0],yhB[1]))
print('   today breaks YESTERDAY LOW:           %s (%d/%d)'%(pct(ylB[0],ylB[1]),ylB[0],ylB[1]))

# 5) Important date (3/7/9) move size vs normal
print('\n[5] IMPORTANT DATES (digit-root 3/7/9) -> bigger move?')
imp=[]; non=[]
for d in DAYS:
    rng=P[d]['h']-P[d]['l']
    (imp if droot(int(d[-2:])) in (3,7,9) else non).append(rng)
print('   avg daily RANGE on 3/7/9 dates: $%.1f (%d days)'%(st.mean(imp),len(imp)))
print('   avg daily RANGE other dates:    $%.1f (%d days)'%(st.mean(non),len(non)))

# 6) Stage behaviour
print('\n[6] CYCLE STAGE -> reversal rate')
stg={}
for i in range(1,N):
    d,pv=DAYS[i],DAYS[i-1]; s=MOON[d]['stage']
    stg.setdefault(s,[0,0]); stg[s][1]+=1; stg[s][0]+=1 if P[d]['dir']!=P[pv]['dir'] else 0
for s,(r,n) in sorted(stg.items()): print('   %-7s reversal rate %s (%d/%d)'%(s,pct(r,n),r,n))

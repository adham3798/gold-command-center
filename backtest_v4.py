# -*- coding: utf-8 -*-
"""Backtest the NEW framework (v4) vs the current model (v3).
Same TP1(50%)+full-stop win/loss for all -> isolates DIRECTION logic."""
import pandas as pd, urllib.parse, statistics as st
SID='12ynlr46bvHSJLnLGs5Z1SrhhlCj6_w7qO6YHMDBY7gs'
def tab(t): return pd.read_csv('https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv&sheet=%s'%(SID,urllib.parse.quote(t)))
def col(df,*n):
    import re; norm={re.sub(r'\s+',' ',str(c)).strip().lower():c for c in df.columns}
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
    d=int(d)
    while d>9:d=sum(int(c) for c in str(d))
    return d
from datetime import datetime
def wd(ds): return datetime.strptime(ds,'%Y-%m-%d').weekday()  # 0=Mon..4=Fri

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

def matching(ds,sign,stage):
    ups,dns=[],[]
    for d in DAYS:
        if d>=ds:break
        if MOON[d]['sign']==sign and MOON[d]['stage']==stage:
            ch=P[d]['c']-P[d]['o']; (ups if ch>=0 else dns).append(abs(ch))
    gu=st.mean([abs(P[d]['c']-P[d]['o']) for d in DAYS if P[d]['c']>=P[d]['o']])
    gd=st.mean([abs(P[d]['c']-P[d]['o']) for d in DAYS if P[d]['c']<P[d]['o']])
    return (st.mean(ups) if len(ups)>=2 else gu),(st.mean(dns) if len(dns)>=2 else gd)
def tp1(ds,d):
    up,dn=matching(ds,MOON[ds]['sign'],MOON[ds]['stage']); mv=up if d>0 else dn
    o,h,l=P[ds]['o'],P[ds]['h'],P[ds]['l']
    if d>0: tp,sv=o+0.5*mv,o-mv; return (h>=tp) and not (l<=sv)
    else:   tp,sv=o-0.5*mv,o+mv; return (l<=tp) and not (h>=sv)

def eff_prior(i, shape=True):
    """prior effective direction; if prior body is small, use the prevailing trend."""
    pv=DAYS[i-1]; p=P[pv]; raw=1 if p['c']>=p['o'] else -1
    if not shape: return raw
    body=abs(p['c']-p['o']); rng=p['h']-p['l']; ratio=body/rng if rng else 1
    if ratio<0.33 and i>=3:
        trend=P[DAYS[i-1]]['c']-P[DAYS[i-3]]['c']
        return 1 if trend>=0 else -1
    return raw

# ---- models ----
def v3(i):  # current model
    pv=DAYS[i-1]; pa=1 if P[pv]['dir']=='BULL' else -1; ds=DAYS[i]
    nat=NAT.get(MOON[ds]['sign'],''); stage=MOON[ds]['stage']
    nine=droot(ds[-2:])==9; pnine=droot(pv[-2:])==9
    if pnine: return -pa
    if nine: return pa
    if nat=='MOVABLE': return -pa if MOON[pv]['sign']==MOON[ds]['sign'] else pa
    if nat=='FIXED': return pa
    return -pa if stage=='FINISH' else pa

def v4(i, shape=True, gap=True):
    ds=DAYS[i]; pv=DAYS[i-1]; ep=eff_prior(i,shape)
    sign=MOON[ds]['sign']; pnine=droot(pv[-2:])==9
    d=ep                                   # CONTINUE the trend by default (fixed/finisher/scorpio/movable-leg)
    if pnine and not (gap and wd(pv)==4):  # day after a 9-date = turn (skip if it's across a weekend)
        d=-ep
    if sign=='Libra':  d=-ep               # balance/reverse the half-cycle
    if sign=='Capricorn': d=1              # gold-friendly bull lean
    return d

def v4_noshape(i): return v4(i,shape=False,gap=True)
def v4_nogap(i):   return v4(i,shape=True,gap=False)
def v4_plain(i):   return v4(i,shape=False,gap=False)
def v4_full(i):    return v4(i,shape=True,gap=True)
def naive(i):      return 1 if P[DAYS[i-1]]['dir']=='BULL' else -1

# --- targeted: take v3 and change ONE thing at a time ---
def v3_movcont(i):  # v3 but movable -> continue (not reverse)
    pv=DAYS[i-1]; pa=1 if P[pv]['dir']=='BULL' else -1; ds=DAYS[i]
    nat=NAT.get(MOON[ds]['sign'],''); stage=MOON[ds]['stage']
    nine=droot(ds[-2:])==9; pnine=droot(pv[-2:])==9
    if pnine: return -pa
    if nine: return pa
    if nat=='MOVABLE': return pa
    if nat=='FIXED': return pa
    return -pa if stage=='FINISH' else pa
def v3_no9(i):      # v3 but drop the 9-cycle specials
    pv=DAYS[i-1]; pa=1 if P[pv]['dir']=='BULL' else -1; ds=DAYS[i]
    nat=NAT.get(MOON[ds]['sign'],''); stage=MOON[ds]['stage']
    if nat=='MOVABLE': return -pa if MOON[pv]['sign']==MOON[ds]['sign'] else pa
    if nat=='FIXED': return pa
    return -pa if stage=='FINISH' else pa
def v3_dropbad(i):  # v3 minus the two worst rules: movable->continue AND no 9-cycle
    pv=DAYS[i-1]; pa=1 if P[pv]['dir']=='BULL' else -1; ds=DAYS[i]
    nat=NAT.get(MOON[ds]['sign'],''); stage=MOON[ds]['stage']
    if nat=='FIXED': return pa
    if nat=='MOVABLE': return pa
    return -pa if stage=='FINISH' else pa
def v3_shape(i):    # v3 but prior direction uses candle-shape (small body -> trend)
    pv=DAYS[i-1]; pa=eff_prior(i,True); ds=DAYS[i]
    nat=NAT.get(MOON[ds]['sign'],''); stage=MOON[ds]['stage']
    nine=droot(ds[-2:])==9; pnine=droot(pv[-2:])==9
    if pnine: return -pa
    if nine: return pa
    if nat=='MOVABLE': return -pa if MOON[pv]['sign']==MOON[ds]['sign'] else pa
    if nat=='FIXED': return pa
    return -pa if stage=='FINISH' else pa
def v3_cap(i):      # v3 + Capricorn bull lean
    pv=DAYS[i-1]; ds=DAYS[i]
    if MOON[ds]['sign']=='Capricorn': return 1
    return v3(i)

def run(fn):
    w=n=0
    for i in range(1,len(DAYS)):
        if i<3: continue
        if tp1(DAYS[i], fn(i)): w+=1
        n+=1
    return w,n

print('Backtest days:',len(DAYS)-3,' (TP1 50%% / full-stop, same for all)\n')
for name,fn in [('v3 (current model)',v3),
                ('v4 full framework',v4_full),
                ('v4 best (no-shape+gap-skip)',v4_noshape),
                ('--- targeted single-change tests ---',None),
                ('v3 + movable=continue (not reverse)',v3_movcont),
                ('v3 - drop 9-cycle rules',v3_no9),
                ('v3 - drop BOTH bad rules (mov=cont + no9)',v3_dropbad),
                ('v3 + candle-shape on prior',v3_shape),
                ('v3 + Capricorn bull-lean',v3_cap),
                ('naive persistence',naive)]:
    if fn is None: print(name); continue
    w,n=run(fn); print('%-44s %d/%d = %.1f%%'%(name,w,n,w/n*100))

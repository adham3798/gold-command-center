# -*- coding: utf-8 -*-
"""Test: (A) entry from PIVOT POINT vs open, (B) weekly-direction filter / sell-only.
Model = current (v3, 9-cycle removed). Win = TP1(50%) within 3-day window before stop."""
import pandas as pd, urllib.parse, statistics as st
from datetime import datetime
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
IDX={d:i for i,d in enumerate(DAYS)}

def matching(ds,sign,stage):
    ups,dns=[],[]
    for d in DAYS:
        if d>=ds:break
        if MOON[d]['sign']==sign and MOON[d]['stage']==stage:
            ch=P[d]['c']-P[d]['o']; (ups if ch>=0 else dns).append(abs(ch))
    gu=st.mean([abs(P[d]['c']-P[d]['o']) for d in DAYS if P[d]['c']>=P[d]['o']])
    gd=st.mean([abs(P[d]['c']-P[d]['o']) for d in DAYS if P[d]['c']<P[d]['o']])
    return (st.mean(ups) if len(ups)>=2 else gu),(st.mean(dns) if len(dns)>=2 else gd)
def PP(ds):
    i=IDX[ds];
    if i==0: return None
    y=P[DAYS[i-1]]; return (y['h']+y['l']+y['c'])/3
def model(i):
    pa=1 if P[DAYS[i-1]]['dir']=='BULL' else -1; ds=DAYS[i]; pv=DAYS[i-1]
    nat=NAT.get(MOON[ds]['sign'],''); stage=MOON[ds]['stage']
    if nat=='MOVABLE': return -pa if MOON[pv]['sign']==MOON[ds]['sign'] else pa
    if nat=='FIXED': return pa
    return -pa if stage=='FINISH' else pa
def win_from(entry, i, d, mv, n=3):
    if entry is None: return None
    tp=entry+0.5*mv if d>0 else entry-0.5*mv; stop=entry-mv if d>0 else entry+mv
    for k in range(i,min(i+n,len(DAYS))):
        h,l=P[DAYS[k]]['h'],P[DAYS[k]]['l']
        ht=(h>=tp) if d>0 else (l<=tp); hs=(l<=stop) if d>0 else (h>=stop)
        if ht and hs: return False
        if ht: return True
        if hs: return False
    return False
# weekly bias = prior calendar week net (first open -> last close)
def isoweek(ds): dt=datetime.strptime(ds,'%Y-%m-%d'); y,w,_=dt.isocalendar(); return (y,w)
weeks={}
for d in DAYS: weeks.setdefault(isoweek(d),[]).append(d)
wk_dir={}
for wk,ds in weeks.items():
    net=P[ds[-1]]['c']-P[ds[0]]['o']; wk_dir[wk]=1 if net>=0 else -1
def prior_week_bias(ds):
    y,w=isoweek(ds); pw=(y,w-1)
    if pw in wk_dir: return wk_dir[pw]
    return None

def run(entry_mode, flt):
    w=n=0
    for i in range(3,len(DAYS)):
        ds=DAYS[i]; d=model(i)
        # filters
        if flt=='sell' and d>0: continue
        if flt=='buy' and d<0: continue
        if flt=='weekly':
            b=prior_week_bias(ds)
            if b is not None and ((b>0 and d<0) or (b<0 and d>0)): continue
        if flt=='weekly_sell':
            b=prior_week_bias(ds)
            if not (b is not None and b<0 and d<0): continue   # only sells in bearish weeks
        up,dn=matching(ds,MOON[ds]['sign'],MOON[ds]['stage']); mv=up if d>0 else dn
        entry = P[ds]['o'] if entry_mode=='open' else PP(ds)
        r=win_from(entry,i,d,mv,3)
        if r is None: continue
        n+=1; w+=1 if r else 0
    return w,n

print('Model=current(9-cycle off) · TP1 50% · 3-day window\n')
cfgs=[('BASELINE  entry=open · all trades','open',None),
      ('entry=PIVOT · all trades','pp',None),
      ('entry=open · weekly-direction filter','open','weekly'),
      ('entry=PIVOT · weekly-direction filter','pp','weekly'),
      ('entry=open · SELL only','open','sell'),
      ('entry=PIVOT · SELL only','pp','sell'),
      ('entry=PIVOT · SELL only in BEARISH weeks','pp','weekly_sell'),
      ('entry=open · SELL only in BEARISH weeks','open','weekly_sell')]
for name,em,fl in cfgs:
    w,n=run(em,fl); print('%-44s %s  (%d trades)'%(name, ('%.1f%%'%(w/n*100)) if n else 'n/a', n))

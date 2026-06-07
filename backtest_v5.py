# -*- coding: utf-8 -*-
"""Test refinements vs current model (56%): candle-shape prior, multi-day trend,
multi-day TP window. Same matching-move TP1(50%)+full-stop sizing."""
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

def trend3(i):
    j=max(0,i-3); return 1 if P[DAYS[i-1]]['c']-P[DAYS[j]]['c']>=0 else -1
def shape_dir(p, tf):
    o,h,l,c=p['o'],p['h'],p['l'],p['c']; body=c-o; rng=(h-l) or 1
    if abs(body)<0.30*rng:
        uw=h-max(o,c); lw=min(o,c)-l
        if uw>lw*1.3: return -1
        if lw>uw*1.3: return 1
        return tf
    return 1 if body>=0 else -1

def prior(i, mode):
    if mode=='raw':    return 1 if P[DAYS[i-1]]['dir']=='BULL' else -1
    if mode=='trend3': return trend3(i)
    if mode=='shape':  return shape_dir(P[DAYS[i-1]], trend3(i))
    return 1 if P[DAYS[i-1]]['dir']=='BULL' else -1

def model(i, mode):
    pa=prior(i,mode); ds=DAYS[i]; pv=DAYS[i-1]
    nat=NAT.get(MOON[ds]['sign'],''); stage=MOON[ds]['stage']
    if nat=='MOVABLE': return -pa if MOON[pv]['sign']==MOON[ds]['sign'] else pa
    if nat=='FIXED': return pa
    return -pa if stage=='FINISH' else pa

def win(i, d, N):
    ds=DAYS[i]; up,dn=matching(ds,MOON[ds]['sign'],MOON[ds]['stage']); mv=up if d>0 else dn
    o=P[ds]['o']; tp=o+0.5*mv if d>0 else o-0.5*mv; stop=o-mv if d>0 else o+mv
    for k in range(i, min(i+N,len(DAYS))):
        h,l=P[DAYS[k]]['h'],P[DAYS[k]]['l']
        if d>0: ht,hs=h>=tp,l<=stop
        else:   ht,hs=l<=tp,h>=stop
        if ht and not hs: return True
        if hs: return False
    return False

def run(mode,N):
    w=n=0
    for i in range(3,len(DAYS)):
        if win(i, model(i,mode), N): w+=1
        n+=1
    return w,n

print('Days:',len(DAYS)-3,'\n')
cfgs=[('CURRENT: raw prior, same-day (N=1)','raw',1),
      ('raw prior, 2-day TP window','raw',2),
      ('raw prior, 3-day TP window','raw',3),
      ('candle-shape prior, same-day','shape',1),
      ('multi-day-trend prior, same-day','trend3',1),
      ('shape prior + 2-day window','shape',2),
      ('shape prior + 3-day window','shape',3),
      ('trend3 prior + 2-day window','trend3',2),
      ('trend3 prior + 3-day window','trend3',3)]
for name,mode,N in cfgs:
    w,n=run(mode,N); print('%-40s %d/%d = %.1f%%'%(name,w,n,w/n*100))

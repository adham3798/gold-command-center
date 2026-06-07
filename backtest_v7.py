# -*- coding: utf-8 -*-
"""v7: reward:risk 1:1 and 2:1 WITH breakeven-stop trail.
Rule: stop = 1*move (=1R risk). When price travels 50% of the way to target,
      the stop is moved to ENTRY (breakeven) -> after that the trade cannot lose,
      it can only WIN (full target) or BREAKEVEN (0).
Outcomes per trade: W (win), BE (breakeven, 0), L (full loss -1R).
Conservative OHLC ordering: adverse move assumed to happen first each day.
Model = current (v3, 9-cycle removed). 3-day window."""
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
    i=IDX[ds]
    if i==0: return None
    y=P[DAYS[i-1]]; return (y['h']+y['l']+y['c'])/3
def model(i):
    pa=1 if P[DAYS[i-1]]['dir']=='BULL' else -1; ds=DAYS[i]; pv=DAYS[i-1]
    nat=NAT.get(MOON[ds]['sign'],''); stage=MOON[ds]['stage']
    if nat=='MOVABLE': return -pa if MOON[pv]['sign']==MOON[ds]['sign'] else pa
    if nat=='FIXED': return pa
    return -pa if stage=='FINISH' else pa

def outcome_be(entry,i,d,mv,R,n=3):
    """R = reward:risk ratio (1.0 or 2.0). risk(stop)=1*mv. Returns 'W','BE','L'."""
    if entry is None or mv<=0: return None
    if d>0:
        stop0=entry-mv; be=entry+0.5*R*mv; tgt=entry+R*mv
    else:
        stop0=entry+mv; be=entry-0.5*R*mv; tgt=entry-R*mv
    armed=False
    for k in range(i,min(i+n,len(DAYS))):
        h,l=P[DAYS[k]]['h'],P[DAYS[k]]['l']
        if d>0:
            if not armed:
                if l<=stop0: return 'L'      # adverse-first: full loss
                if h>=tgt:  return 'W'
                if h>=be:   armed=True
            else:
                if l<=entry: return 'BE'      # trail to breakeven
                if h>=tgt:   return 'W'
        else:
            if not armed:
                if h>=stop0: return 'L'
                if l<=tgt:   return 'W'
                if l<=be:    armed=True
            else:
                if h>=entry: return 'BE'
                if l<=tgt:   return 'W'
    return 'BE' if armed else 'L'

# original (no trail) for reference: TP1=0.5*move, stop=1*move
def outcome_orig(entry,i,d,mv,n=3):
    if entry is None or mv<=0: return None
    tp=entry+0.5*mv if d>0 else entry-0.5*mv; stop=entry-mv if d>0 else entry+mv
    for k in range(i,min(i+n,len(DAYS))):
        h,l=P[DAYS[k]]['h'],P[DAYS[k]]['l']
        ht=(h>=tp) if d>0 else (l<=tp); hs=(l<=stop) if d>0 else (h>=stop)
        if ht and hs: return 'L'
        if ht: return 'W'
        if hs: return 'L'
    return 'L'

def isoweek(ds): dt=datetime.strptime(ds,'%Y-%m-%d'); y,w,_=dt.isocalendar(); return (y,w)
weeks={}
for d in DAYS: weeks.setdefault(isoweek(d),[]).append(d)
wk_dir={}
for wk,ds in weeks.items():
    net=P[ds[-1]]['c']-P[ds[0]]['o']; wk_dir[wk]=1 if net>=0 else -1
def prior_week_bias(ds):
    y,w=isoweek(ds); pw=(y,w-1)
    return wk_dir.get(pw)

def run(entry_mode,flt,mode,R=1.0):
    W=BE=L=0; trades=0
    for i in range(3,len(DAYS)):
        ds=DAYS[i]; d=model(i)
        if flt=='weekly':
            b=prior_week_bias(ds)
            if b is not None and ((b>0 and d<0) or (b<0 and d>0)): continue
        up,dn=matching(ds,MOON[ds]['sign'],MOON[ds]['stage']); mv=up if d>0 else dn
        entry=P[ds]['o'] if entry_mode=='open' else PP(ds)
        if mode=='orig': r=outcome_orig(entry,i,d,mv,3)
        else:            r=outcome_be(entry,i,d,mv,R,3)
        if r is None: continue
        trades+=1
        if r=='W': W+=1
        elif r=='BE': BE+=1
        else: L+=1
    # expectancy in R: win=+R, loss=-1, be=0
    rew = R if mode!='orig' else 0.5
    totR = W*rew - L*1.0
    return W,BE,L,trades,totR

def line(name,*a):
    W,BE,L,T,R = a
    wr = (W/T*100) if T else 0
    wl = (W/(W+L)*100) if (W+L) else 0
    per = (R/T) if T else 0
    print('%-46s W%-3d BE%-3d L%-3d  win%%%5.1f  W/(W+L)%5.1f  | totR %+6.1f  perTrade %+.3f'%(name,W,BE,L,wr,wl,R,per))

print('Model=current(9-cycle off) | 3-day window | risk=1*move')
print('outcomes: W=hit target  BE=breakeven trail (0)  L=full loss(-1R)\n')

print('--- REFERENCE: original TP1=0.5*move, stop=1*move, NO trail (0.5:1) ---')
line('entry=PIVOT  all',        *run('pp',None,'orig'))
line('entry=PIVOT  weekly',     *run('pp','weekly','orig'))
print()
for R in (1.0,2.0):
    print('--- REWARD:RISK %d:1  WITH breakeven trail (stop->entry at 50%% to target) ---'%int(R))
    line('entry=open   all',     *run('open',None,'be',R))
    line('entry=PIVOT  all',     *run('pp',  None,'be',R))
    line('entry=open   weekly',  *run('open','weekly','be',R))
    line('entry=PIVOT  weekly',  *run('pp',  'weekly','be',R))
    print()

# -*- coding: utf-8 -*-
"""LEVEL REACTION study: when price TOUCHES each level, does the market REACT
(reject/bounce = level holds) or break through?  Read-only, daily OHLC.
  Resistance L: touched if High>=L ; REACTED if High>=L and Close<L (poked, closed back below)
  Support   L: touched if Low<=L  ; REACTED if Low<=L  and Close>L (poked, closed back above)
"""
import pandas as pd, urllib.parse
SID='12ynlr46bvHSJLnLGs5Z1SrhhlCj6_w7qO6YHMDBY7gs'
def tab(t): return pd.read_csv('https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv&sheet=%s'%(SID,urllib.parse.quote(t)))
gp=tab('gold_price'); gp.columns=[str(c).strip() for c in gp.columns]
gp['Date']=pd.to_datetime(gp['Date'],errors='coerce'); gp=gp.dropna(subset=['Close']).sort_values('Date')
rows=[{'d':r['Date'].strftime('%Y-%m-%d'),'o':float(r['Open']),'h':float(r['High']),'l':float(r['Low']),'c':float(r['Close'])} for _,r in gp.iterrows()]

def pct(a,b): return ('%.0f%%'%(a/b*100)) if b else 'n/a'

# resistance: (touched, reacted/rejected, broken)
RES={'R1':[0,0,0],'R2':[0,0,0],'R3':[0,0,0],'Yest High':[0,0,0]}
SUP={'S1':[0,0,0],'S2':[0,0,0],'S3':[0,0,0],'Yest Low':[0,0,0]}
PP_touch=[0,0]
for i in range(1,len(rows)):
    t=rows[i]; y=rows[i-1]
    PP=(y['h']+y['l']+y['c'])/3; rng=y['h']-y['l']
    R1=2*PP-y['l']; R2=PP+rng; R3=R1+rng; S1=2*PP-y['h']; S2=PP-rng; S3=S1-rng
    res={'R1':R1,'R2':R2,'R3':R3,'Yest High':y['h']}
    sup={'S1':S1,'S2':S2,'S3':S3,'Yest Low':y['l']}
    for k,L in res.items():
        if t['h']>=L:
            RES[k][0]+=1
            if t['c']<L: RES[k][1]+=1      # rejected (reacted down)
            else:        RES[k][2]+=1      # broke through (closed above)
    for k,L in sup.items():
        if t['l']<=L:
            SUP[k][0]+=1
            if t['c']>L: SUP[k][1]+=1      # bounced (reacted up)
            else:        SUP[k][2]+=1      # broke through (closed below)
    PP_touch[1]+=1; PP_touch[0]+=1 if (t['l']<=PP<=t['h']) else 0

n=len(rows)-1
print('Days analysed:',n)
print('\n=== RESISTANCE LEVELS (price came UP into them) ===')
print('%-10s %8s %12s %10s'%('LEVEL','touched','REACTED(held)','broke thru'))
for k,(tch,rej,brk) in RES.items():
    print('%-10s %8s %12s %10s'%(k, pct(tch,n), pct(rej,tch)+' (%d/%d)'%(rej,tch), pct(brk,tch)))
print('\n=== SUPPORT LEVELS (price came DOWN into them) ===')
print('%-10s %8s %12s %10s'%('LEVEL','touched','REACTED(held)','broke thru'))
for k,(tch,bnc,brk) in SUP.items():
    print('%-10s %8s %12s %10s'%(k, pct(tch,n), pct(bnc,tch)+' (%d/%d)'%(bnc,tch), pct(brk,tch)))
print('\n=== PIVOT PP ===')
print('PP inside the day range (price touched/crossed PP): %s (%d/%d)'%(pct(PP_touch[0],PP_touch[1]),PP_touch[0],PP_touch[1]))

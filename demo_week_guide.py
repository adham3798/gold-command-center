# -*- coding: utf-8 -*-
"""DEMO v2: richer Week Guide — move story + trade plan + levels + nuance.
Text mock of what the in-app 'Week Guide' tab would show. No app changes."""
import json, urllib.request
from datetime import datetime
def g(p): return json.load(urllib.request.urlopen('http://localhost:5000'+p, timeout=15))

ORDER=['Aries','Taurus','Gemini','Cancer','Leo','Virgo','Libra','Scorpio','Sagittarius','Capricorn','Aquarius','Pisces']
NATURE={s:('MOVABLE','FIXED','FINISHER')[i%3] for i,s in enumerate(ORDER)}
EMOJI={'Aries':'♈','Taurus':'♉','Gemini':'♊','Cancer':'♋','Leo':'♌','Virgo':'♍','Libra':'♎','Scorpio':'♏','Sagittarius':'♐','Capricorn':'♑','Aquarius':'♒','Pisces':'♓'}
def nuance(sign, reason, mdir):
    s=sign
    if s=='Libra': return 'BALANCE day — rebalances the trend; reversal risk'
    if s=='Scorpio': return 'sharp & emotional — may run with NO pullback (fakeout risk)'
    if s=='Capricorn': return 'gold-friendly bull lean (movable, can swing)'
    if 'fixed' in reason: return 'continuation — ride it; pullback = entry'
    if 'FINISH' in reason: return 'last push — expect a pullback / possible turn'
    if 'finisher' in reason: return 'last push — likely continues; pullback to re-enter'
    if '2nd-day' in reason: return 'pullback day (counter to yesterday)'
    if '1st-day' in reason: return 'new move starting — fresh leg'
    return reason
def move_of(s):
    i=ORDER.index(s); return i//3+1, ('male-led' if (i//3+1) in (1,3) else 'female-led')

lv=g('/api/levels')['levels']
fr=g('/api/forecast-range/16/16')
past=[d for d in fr if d['is_past']][-5:]
fut=[d for d in fr if not d['is_past'] and not d.get('is_today')][:5]

def card(d, future):
    s=d['sign']; nat=NATURE.get(s,'?'); mv,led=move_of(s); em=EMOJI.get(s,'')
    role={'MOVABLE':'START','FIXED':'BUILD','FINISHER':'END'}[nat]
    wd=datetime.strptime(d['date'],'%Y-%m-%d').strftime('%a').upper()
    md=d.get('model_dir','?'); arr='▲' if md=='BUY' else '▼'
    anchor=d.get('target_anchor') or d.get('open'); mvsz=d.get('expected_move')
    out=['%s %s  %s %s (%s · %s/%s)'%(wd,d['date'][5:],em,s,d.get('gender','')[:1],nat.title(),role)]
    out.append('  STORY : Move %d (%s) · %s'%(mv,led,nuance(s,d.get('model_reason',''),md)))
    if future and anchor and mvsz:
        if md=='BUY': tp=round(anchor+0.5*mvsz,1); inv=round(anchor-mvsz,1); hi=round(anchor+mvsz,1); lo=round(anchor-0.4*mvsz,1)
        else:         tp=round(anchor-0.5*mvsz,1); inv=round(anchor+mvsz,1); hi=round(anchor+0.4*mvsz,1); lo=round(anchor-mvsz,1)
        out.append('  PLAN  : %s %s  · act from ~%s · TP1 %s · invalidate %s'%(arr,md,round(anchor,1),tp,inv))
        out.append('  RANGE : exp High ~%s / Low ~%s (move ~$%s)'%(hi,lo,round(mvsz,1)))
    else:
        ok=d.get('model_correct'); mark='✓ WIN' if ok else ('✗ LOSS' if ok is False else '—')
        out.append('  RESULT: model %s %s | actual %s | %s'%(arr,md,d.get('direction','?'),mark))
    return '\n'.join(out)

print('#'*64)
print('  GOLD WEEK GUIDE — astrology + plan')
print('#'*64)
print('\n KEY LEVELS THIS WEEK (reaction reference):')
for L in lv:
    h=('holds %d%%/breaks %d%%'%(L['hold_pct'],L['break_pct'])) if L['hold_pct'] is not None else 'magnet'
    star=' ★' if (L['hold_pct'] or 0)>=60 else ''
    print('   %-10s %9.1f  %s%s'%(L['name'],L['price'],h,star))
print('\n'+'='*64+'\n  ◀ LAST WEEK (graded)\n'+'='*64)
for d in past: print(card(d,False),'\n')
print('='*64+'\n  ▶ NEXT WEEK (plan)\n'+'='*64)
for d in fut: print(card(d,True),'\n')

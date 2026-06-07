# -*- coding: utf-8 -*-
"""DEMO: Last trading week + Next trading week astrology guide (text mock).
Pulls from the running app; no app changes."""
import json, urllib.request
from datetime import datetime
def g(p): return json.load(urllib.request.urlopen('http://localhost:5000'+p, timeout=15))

ORDER=['Aries','Taurus','Gemini','Cancer','Leo','Virgo','Libra','Scorpio','Sagittarius','Capricorn','Aquarius','Pisces']
NATURE={s:('MOVABLE','FIXED','FINISHER')[i%3] for i,s in enumerate(ORDER)}
EMOJI={'Aries':'♈','Taurus':'♉','Gemini':'♊','Cancer':'♋','Leo':'♌','Virgo':'♍','Libra':'♎','Scorpio':'♏','Sagittarius':'♐','Capricorn':'♑','Aquarius':'♒','Pisces':'♓'}
GUIDE={
 'Aries':'fresh START — bull or bear, expect a pullback',
 'Taurus':'BUILD — steady accumulation, pullback = entry',
 'Gemini':'END — volatile last push; if strong, pullback to re-enter',
 'Cancer':'START — emotional, plays around / choppy open',
 'Leo':'BUILD — confident trend continuation',
 'Virgo':'END — completion/reversal; if strong, pullback + continue',
 'Libra':'⚖ BALANCE — rebalances the recent trend (reversal point)',
 'Scorpio':'⚡ sharp & emotional — fake-outs or runs with no pullback',
 'Sagittarius':'END — expansion, final leg of the move',
 'Capricorn':'START — gold-friendly, bullish lean (can still swing)',
 'Aquarius':'BUILD — one direction, can be unexpected',
 'Pisces':'END — exhaustion, the move winds down',
}
def move_of(sign):
    i=ORDER.index(sign); mv=i//3+1; led='male-led (move 1≡3)' if mv in (1,3) else 'female-led (move 2≡4)'
    return mv,led

fr=g('/api/forecast-range/16/16')
past=[d for d in fr if d['is_past']][-5:]
fut=[d for d in fr if (not d['is_past'] and not d.get('is_today'))][:5]

def line(d, future):
    sign=d['sign']; nat=NATURE.get(sign,'?'); mv,led=move_of(sign)
    em=EMOJI.get(sign,''); wd=datetime.strptime(d['date'],'%Y-%m-%d').strftime('%a')
    role={'MOVABLE':'START','FIXED':'BUILD','FINISHER':'END'}[nat]
    head='%s %s  %s %s · %s · %s · Stage %s'%(d['date'],wd,em,sign,d.get('gender','?'),nat+' ('+role+')',d.get('stage','?'))
    md=d.get('model_dir','?'); arrow='▲' if md=='BUY' else '▼'
    body='   Move %d %s | %s'%(mv,led,GUIDE.get(sign,''))
    if future:
        tgt = (' → ~%s'%d.get('target')) if d.get('target') else ''
        res='   ➜ MODEL: %s %s%s'%(arrow,md,tgt)
    else:
        act=d.get('direction','?'); ok=d.get('model_correct')
        mark = '✓ WIN' if ok else ('✗ LOSS' if ok is False else '—')
        res='   ➜ model said %s %s | actual %s | %s'%(arrow,md,act,mark)
    return head+'\n'+body+'\n'+res

print('='*70)
print('  ◀ LAST TRADING WEEK')
print('='*70)
for d in past: print(line(d,False),'\n')
print('='*70)
print('  ▶ NEXT TRADING WEEK')
print('='*70)
for d in fut: print(line(d,True),'\n')

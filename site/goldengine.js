/* ===================================================================
   GOLD ENGINE — client-side port of engine.py + app.py data layer.
   Loads the Google Sheet in-browser and answers the same /api/* calls
   the UI makes (via a fetch shim), so the dashboard runs with NO server.
   =================================================================== */
const GoldEngine = (function () {
  const SHEET_ID = '12ynlr46bvHSJLnLGs5Z1SrhhlCj6_w7qO6YHMDBY7gs';

  // ---- static reference data (mirrors engine.py) ----
  const ZODIAC_DB = {
    Aries:{gender:'MALE',nature:'MOVABLE',keyword:'START',bias:'BREAKOUT',stageNum:1},
    Taurus:{gender:'FEMALE',nature:'FIXED',keyword:'BUILD',bias:'ACCUMULATION',stageNum:2},
    Gemini:{gender:'MALE',nature:'FINISHER',keyword:'MOVE',bias:'VOLATILE',stageNum:3},
    Cancer:{gender:'FEMALE',nature:'MOVABLE',keyword:'START',bias:'EMOTIONAL',stageNum:1},
    Leo:{gender:'MALE',nature:'FIXED',keyword:'BUILD',bias:'TREND',stageNum:2},
    Virgo:{gender:'FEMALE',nature:'FINISHER',keyword:'FINISH',bias:'REVERSAL',stageNum:3},
    Libra:{gender:'MALE',nature:'MOVABLE',keyword:'START',bias:'RANGE',stageNum:1},
    Scorpio:{gender:'FEMALE',nature:'FIXED',keyword:'BUILD',bias:'SHARP MOVE',stageNum:2},
    Sagittarius:{gender:'MALE',nature:'FINISHER',keyword:'FINISH',bias:'EXPANSION',stageNum:3},
    Capricorn:{gender:'FEMALE',nature:'MOVABLE',keyword:'START',bias:'TREND',stageNum:1},
    Aquarius:{gender:'MALE',nature:'FIXED',keyword:'BUILD',bias:'UNEXPECTED',stageNum:2},
    Pisces:{gender:'FEMALE',nature:'FINISHER',keyword:'FINISH',bias:'EXHAUSTION',stageNum:3},
  };
  const SIGN_EMOJI = {Aries:'♈',Taurus:'♉',Gemini:'♊',Cancer:'♋',Leo:'♌',Virgo:'♍',Libra:'♎',Scorpio:'♏',Sagittarius:'♐',Capricorn:'♑',Aquarius:'♒',Pisces:'♓'};
  const PHASE_EMOJI = {'new moon':'🌑','waxing crescent':'🌒','first quarter':'🌓','waxing gibbous':'🌔','full moon':'🌕','waning gibbous':'🌖','last quarter':'🌗','third quarter':'🌗','waning crescent':'🌘'};
  const RETRO_DB=[{e:'Chiron Direct',d:'1/2/2026'},{e:'Uranus Direct',d:'2/4/2026'},{e:'Mercury Retrograde',d:'2/26/2026'},{e:'Jupiter Direct',d:'3/11/2026'},{e:'Mercury Direct',d:'3/20/2026'},{e:'Pluto Retrograde',d:'5/6/2026'},{e:'Mercury Retrograde',d:'6/29/2026'},{e:'Neptune Retrograde',d:'7/7/2026'},{e:'Mercury Direct',d:'7/23/2026'},{e:'Saturn Retrograde',d:'7/26/2026'},{e:'Chiron Retrograde',d:'8/3/2026'},{e:'Uranus Retrograde',d:'9/10/2026'},{e:'Venus Retrograde',d:'10/3/2026'},{e:'Pluto Direct',d:'10/16/2026'},{e:'Mercury Retrograde',d:'10/24/2026'},{e:'Mercury Direct',d:'11/13/2026'},{e:'Venus Direct',d:'11/14/2026'},{e:'Saturn Direct',d:'12/10/2026'},{e:'Neptune Direct',d:'12/12/2026'},{e:'Jupiter Retrograde',d:'12/13/2026'}];
  const MOON_DB2=[{e:'Full Moon',d:'1/3/2026'},{e:'New Moon',d:'1/18/2026'},{e:'Full Moon',d:'2/1/2026'},{e:'New Moon',d:'2/17/2026'},{e:'Solar Eclipse',d:'2/17/2026'},{e:'Lunar Eclipse',d:'3/3/2026'},{e:'Full Moon',d:'3/3/2026'},{e:'New Moon',d:'3/19/2026'},{e:'Full Moon',d:'4/2/2026'},{e:'New Moon',d:'4/17/2026'},{e:'Full Moon',d:'5/1/2026'},{e:'New Moon',d:'5/16/2026'},{e:'Full Moon',d:'5/31/2026'},{e:'New Moon',d:'6/15/2026'},{e:'Full Moon',d:'6/29/2026'},{e:'New Moon',d:'7/14/2026'},{e:'Full Moon',d:'7/29/2026'},{e:'New Moon',d:'8/12/2026'},{e:'Solar Eclipse',d:'8/12/2026'},{e:'Lunar Eclipse',d:'8/28/2026'},{e:'Full Moon',d:'8/28/2026'},{e:'New Moon',d:'9/11/2026'},{e:'Full Moon',d:'9/26/2026'},{e:'New Moon',d:'10/10/2026'},{e:'Full Moon',d:'10/26/2026'},{e:'New Moon',d:'11/9/2026'},{e:'Full Moon',d:'11/24/2026'},{e:'New Moon',d:'12/9/2026'},{e:'Full Moon',d:'12/24/2026'}];
  const ASPECT_DB=[{e:'Sun Conjunction Venus',d:'1/6/2026'},{e:'Sun Conjunction Mars',d:'1/9/2026'},{e:'Sun Conjunction Mercury',d:'1/21/2026'},{e:'Sun Conjunction Pluto',d:'1/23/2026'},{e:'Sun Conjunction Node',d:'2/27/2026'},{e:'Sun Conjunction Mercury',d:'3/7/2026'},{e:'Sun Conjunction Neptune',d:'3/22/2026'},{e:'Sun Conjunction Saturn',d:'3/25/2026'},{e:'Sun Conjunction Chiron',d:'4/16/2026'},{e:'Sun Conjunction Mercury',d:'5/14/2026'},{e:'Sun Conjunction Uranus',d:'5/22/2026'},{e:'Sun Conjunction Mercury',d:'7/13/2026'},{e:'Sun Conjunction Jupiter',d:'7/29/2026'},{e:'Sun Conjunction Mercury',d:'8/27/2026'},{e:'Sun Conjunction Venus',d:'10/24/2026'},{e:'Sun Conjunction Mercury',d:'11/4/2026'}];
  const INGRESS_DB=[{e:'Mercury enters Capricorn',d:'1/1/2026'},{e:'Venus enters Aquarius',d:'1/17/2026'},{e:'Mars enters Aquarius',d:'1/23/2026'},{e:'Neptune enters Aries',d:'1/26/2026'},{e:'Saturn enters Aries',d:'2/14/2026'},{e:'Venus enters Aries',d:'3/6/2026'},{e:'Mars enters Aries',d:'4/9/2026'},{e:'Uranus enters Gemini',d:'4/26/2026'},{e:'Chiron enters Taurus',d:'6/19/2026'},{e:'Jupiter enters Leo',d:'6/30/2026'},{e:'Mars enters Cancer',d:'8/11/2026'},{e:'Mars enters Leo',d:'9/28/2026'},{e:'Mars enters Virgo',d:'11/25/2026'}];
  const SUN_DB=[{e:'Aquarius',d:'1/20/2026'},{e:'Pisces',d:'2/18/2026'},{e:'Aries',d:'3/20/2026'},{e:'Taurus',d:'4/20/2026'},{e:'Gemini',d:'5/21/2026'},{e:'Cancer',d:'6/21/2026'},{e:'Leo',d:'7/22/2026'},{e:'Virgo',d:'8/23/2026'},{e:'Libra',d:'9/23/2026'},{e:'Scorpio',d:'10/23/2026'},{e:'Sagittarius',d:'11/22/2026'},{e:'Capricorn',d:'12/21/2026'}];
  const POWER_NUMBERS = new Set([3,7,9]);
  const GOLD_HOLIDAYS = new Set(['2026-01-01','2026-01-19','2026-02-16','2026-04-03','2026-05-25','2026-06-19','2026-07-03','2026-09-07','2026-11-26','2026-12-25']);
  const MOON_BULL=['Aries','Leo','Sagittarius','Cancer'], MOON_BEAR=['Capricorn','Scorpio','Virgo'];
  const SUN_BULL=['Aries','Leo','Sagittarius'], SUN_BEAR=['Capricorn','Scorpio','Virgo'];
  const PHASE_REL={'full moon':85,'new moon':80,'first quarter':75,'third quarter':75,'last quarter':75,'waxing gibbous':65,'waning gibbous':65,'waxing crescent':50,'waning crescent':45};

  // ---- state ----
  const DATA = {prices:{},moon:{},signs:{},phases:{},h1:[],h4:[],forecast:{},moves:{}};
  const _matchCache = {}, _moveCache = {};

  // ---- helpers ----
  const clamp=(v,lo,hi)=>Math.max(lo,Math.min(hi,v));
  const r2=v=>Math.round(v*100)/100, r1=v=>Math.round(v*10)/10;
  function parseDate(s){ if(!s)return null; s=String(s).trim();
    let m=s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/); if(m)return new Date(+m[3],+m[1]-1,+m[2]);
    m=s.match(/^(\d{4})-(\d{2})-(\d{2})/); if(m)return new Date(+m[1],+m[2]-1,+m[3]); return null; }
  const iso=d=>d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
  const todayISO=()=>iso(new Date());
  function daysDiff(a,b){ return Math.round((b-a)/86400000); }
  function cleanSign(s){ s=String(s); const m=s.match(/\(([^)]+)\)/); return m?m[1].trim():s.replace('Moon Sign','').replace('Sun Sign','').trim(); }
  function getPhaseEmoji(p){ p=String(p).toLowerCase(); for(const k in PHASE_EMOJI) if(p.includes(k))return PHASE_EMOJI[k]; return '🌙'; }

  // ---- CSV ----
  function parseCSV(text){
    const rows=[]; let row=[],cur='',q=false;
    for(let i=0;i<text.length;i++){const c=text[i];
      if(q){ if(c==='"'){ if(text[i+1]==='"'){cur+='"';i++;} else q=false; } else cur+=c; }
      else { if(c==='"')q=true; else if(c===','){row.push(cur);cur='';} else if(c==='\n'){row.push(cur);rows.push(row);row=[];cur='';} else if(c==='\r'){} else cur+=c; } }
    if(cur.length||row.length){row.push(cur);rows.push(row);}
    if(!rows.length)return [];
    const hdr=rows[0].map(h=>h.trim());
    return rows.slice(1).map(r=>{const o={};hdr.forEach((h,i)=>o[h]=r[i]!==undefined?r[i]:'');return o;});
  }
  function findCol(obj,...names){ const keys=Object.keys(obj); const norm={}; keys.forEach(k=>norm[k.replace(/\s+/g,' ').trim().toLowerCase()]=k);
    for(const n of names){const k=n.replace(/\s+/g,' ').trim().toLowerCase(); if(norm[k])return norm[k];}
    for(const n of names){const nk=n.trim().toLowerCase(); for(const k in norm) if(k.includes(nk))return norm[k];} return null; }
  const num=v=>{ if(v===null||v===undefined)return null; const s=String(v).replace('%','').replace(/,/g,'').trim(); if(s===''||s.toLowerCase()==='nan')return null; const f=parseFloat(s); return isNaN(f)?null:f; };

  async function fetchCSV(tab){
    const target='https://docs.google.com/spreadsheets/d/'+SHEET_ID+'/gviz/tq?tqx=out:csv&sheet='+encodeURIComponent(tab);
    const tries=['https://api.allorigins.win/raw?url='+encodeURIComponent(target),
                 target,
                 'https://corsproxy.io/?url='+encodeURIComponent(target),
                 'https://api.codetabs.com/v1/proxy?quest='+encodeURIComponent(target)];
    for(const u of tries){ try{ const r=await fetch(u,{cache:'no-store'}); if(r.ok){const t=await r.text(); if(t&&t.length>20&&t.includes(','))return t;} }catch(e){} }
    throw new Error('CSV fetch failed: '+tab);
  }

  // ---- transit / astro (mirror engine.py) ----
  function getActiveRetrogrades(ds){ const t=parseDate(ds); if(!t)return[]; const st={}; for(const e of RETRO_DB){const d=parseDate(e.d); if(!d||d>t)continue; const p=e.e.split(' ')[0]; st[p]=e.e.includes('Retrograde')?'R':'D';} return Object.keys(st).filter(p=>st[p]==='R'); }
  function getTodayTransits(ds,win=3){ const t=parseDate(ds); if(!t)return[]; const all=RETRO_DB.concat(MOON_DB2,INGRESS_DB,ASPECT_DB); return all.map(e=>({e:e.e,d:e.d,diff:daysDiff(t,parseDate(e.d))})).filter(x=>!isNaN(x.diff)&&Math.abs(x.diff)<=win).sort((a,b)=>Math.abs(a.diff)-Math.abs(b.diff)); }
  function scoreTransits(ds){ const retros=getActiveRetrogrades(ds), tr=getTodayTransits(ds); let s=0; const sig=[];
    if(retros.includes('Mercury')){s-=10;sig.push('Mercury Rx: avoid news trades, fog');}
    if(retros.includes('Venus')){s-=8;sig.push('Venus Rx: gold may be choppy');}
    if(retros.includes('Pluto')){s-=5;sig.push('Pluto Rx: hidden pressure on gold');}
    if(retros.includes('Saturn')){s-=7;sig.push('Saturn Rx: bearish pressure');}
    if(retros.includes('Jupiter')){s+=5;sig.push('Jupiter Rx: expansion paused');}
    for(const t of tr){ if(Math.abs(t.diff)>1)continue; const e=t.e;
      if(e.includes('Full Moon')){s-=5;sig.push('Full Moon: peak, reversal risk');}
      if(e.includes('New Moon')){s+=5;sig.push('New Moon: fresh start, buy bias');}
      if(e.includes('Solar Eclipse')){s-=15;sig.push('Solar Eclipse: NO TRADE - extreme volatility');}
      if(e.includes('Lunar Eclipse')){s-=15;sig.push('Lunar Eclipse: NO TRADE - extreme volatility');}
      if(e.includes('Sun Conjunction Jupiter')){s+=12;sig.push('Sun-Jupiter: strong bullish expansion');}
      if(e.includes('Sun Conjunction Saturn')){s-=10;sig.push('Sun-Saturn: bearish contraction');}
      if(e.includes('Sun Conjunction Mars')){s+=8;sig.push('Sun-Mars: high energy, sharp moves');}
      if(e.includes('Sun Conjunction Pluto')){s-=8;sig.push('Sun-Pluto: intense pressure, reversal');}
      if(e.includes('Sun Conjunction Venus')){s+=6;sig.push('Sun-Venus: gold supportive');}
      if(e.includes('Sun Conjunction Neptune')){s-=6;sig.push('Sun-Neptune: confusion, false moves');}
      if(e.includes('Jupiter enters')){s+=8;sig.push('Jupiter ingress: expansion energy');}
      if(e.includes('Saturn enters')){s-=8;sig.push('Saturn ingress: contraction energy');}
      if(e.includes('Mars enters')){s+=5;sig.push('Mars ingress: momentum shift');}
    }
    return {score:clamp(s,-30,30),signals:sig};
  }
  function getSunSign(ds){ const t=parseDate(ds); if(!t)return null; let cur='Capricorn'; for(const e of SUN_DB){const d=parseDate(e.d); if(d&&d<=t)cur=e.e;} return cur; }
  function mtfScore(h1,h4){ let s=0; if(h4&&h4.length){const last=h4.slice(-3); const bull=last.filter(c=>(c.close||0)>=(c.open||0)).length; s+=bull>=2?15:-15;} if(h1&&h1.length){const c=h1[h1.length-1]; if(c.direction==='BULL'||c.trend==='BUY')s+=10; else if(c.direction==='BEAR'||c.trend==='SELL')s-=10;} return clamp(s,-30,30); }
  function moonScore(sign,stage,dir){ const z=ZODIAC_DB[sign]||{}; let s=0; if(MOON_BULL.includes(sign))s+=15; else if(MOON_BEAR.includes(sign))s-=15;
    if(z.bias==='REVERSAL')s-=5; if(z.bias==='TREND'&&dir===1)s+=8; if(z.bias==='TREND'&&dir===-1)s-=8; if(z.bias==='SHARP MOVE')s+=(s>=0?5:-5); if(stage==='FINISH')s*=0.7; return s; }
  function sunScore(sun){ const z=ZODIAC_DB[sun]||{}; let s=0; if(SUN_BULL.includes(sun))s+=10; else if(SUN_BEAR.includes(sun))s-=10; if(z.bias==='EXPANSION')s+=8; if(z.bias==='REVERSAL')s-=8; if(z.bias==='ACCUMULATION')s+=5; if(z.bias==='EXHAUSTION')s-=8; return s; }
  function dayWeight(dn){ const t={1:0.85,2:0.90,3:1.20,4:0.85,5:0.90,6:0.90,7:1.30,8:0.85,9:1.40}; return t[dn]||1.0; }
  function phaseScore(p){ p=String(p).toLowerCase().trim(); for(const k in PHASE_REL) if(p.includes(k))return PHASE_REL[k]; return 60; }
  function calcConfidence(today,history){ if(history.length<5)return {conf:50}; const f1=history.filter(r=>r.sign===today.sign&&r.stage===today.stage); const f1s=Math.min(100,f1.length/8*100); const f2=history.filter(r=>r.stage_num===today.stage_num&&r.sign===today.sign); const f2s=Math.min(100,f2.length/6*100); const f3s=phaseScore(today.phase); const f4=history.filter(r=>r.day_number===today.day_number&&r.gender===today.gender); const f4s=Math.min(100,f4.length/4*100); let conf=f1s*.30+f2s*.25+f3s*.25+f4s*.20; if(POWER_NUMBERS.has(today.day_number))conf=Math.min(100,conf+8); return {conf:Math.round(conf)}; }
  function signalLabel(b){ if(b>=50)return'STRONG BUY'; if(b>=16)return'BUY'; if(b<=-50)return'STRONG SELL'; if(b<=-16)return'SELL'; if(Math.abs(b)>=6)return'WAIT'; return'NO TRADE'; }

  function computeSignal(ds,moon,counts,history,price,mtf){
    if(!moon)return null; const sign=moon.sign,stage=moon.stage,dn=moon.day_number,sun=moon.sun_sign;
    let dir=null; if(price&&(price.direction==='BULL'||price.direction==='BEAR'))dir=price.direction==='BULL'?1:-1;
    const mS=moonScore(sign,stage,dir), sS=sunScore(sun); const {score:tScore,signals:tSigs}=scoreTransits(ds);
    const bull=counts.bull||0,bear=counts.bear||0,total=bull+bear; let bp=0,brp=0,histScore=0;
    if(total>=2){bp=bull/total*100;brp=bear/total*100;histScore=(bp-brp)/100*30;}
    let raw=histScore*0.35+mS*0.30+tScore*0.20+sS*0.15; let mtfVal=null; if(mtf!==null&&mtf!==undefined){mtfVal=mtf;raw+=mtf*0.30;}
    const dmult=dayWeight(dn); raw*=dmult; const biasPct=r1(clamp(raw/25*100,-100,100));
    const sig=signalLabel(biasPct); const {conf}=calcConfidence({sign,stage,stage_num:moon.stage_num,day_number:dn,gender:moon.gender,phase:moon.phase},history);
    const retros=getActiveRetrogrades(ds); const tt=getTodayTransits(ds).filter(t=>Math.abs(t.diff)<=1);
    const out={signal:sig,bias:biasPct,confidence:conf,moon_score:r1(mS),sun_score:r1(sS),transit_score:tScore,hist_score:r1(histScore),
      day_number:dn,power_day:POWER_NUMBERS.has(dn),day_mult:dmult,mtf_score:mtfVal,bull_pct:r1(bp),bear_pct:r1(brp),matches:total,
      zodiac_bias:(ZODIAC_DB[sign]||{}).bias||'',sun_bias:(ZODIAC_DB[sun]||{}).bias||'',retrogrades:retros,transit_signals:tSigs,transits_today:tt.map(t=>t.e)};
    // win/loss decided in buildDay via the take-profit model (not close-vs-open)
    return out;
  }

  // ---- data-derived helpers ----
  function histCounts(ds,sign,stage){ let bull=0,bear=0; for(const d in DATA.prices){ if(d>=ds)continue; const m=DATA.moon[d]; if(m&&m.sign===sign&&m.stage===stage){ if(DATA.prices[d].direction==='BULL')bull++; else if(DATA.prices[d].direction==='BEAR')bear++; } } return {bull,bear}; }
  function pastMoonHistory(ds){ const out=[]; for(const d in DATA.moon) if(d<ds)out.push(DATA.moon[d]); return out; }
  function computeMoves(){ const ups=[],downs=[],rng=[]; for(const d in DATA.prices){const v=DATA.prices[d]; const ch=v.change; if(ch!=null){(ch>=0?ups:downs).push(Math.abs(ch));} if(v.high&&v.low)rng.push(v.high-v.low);} const mean=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:0; const last=Object.keys(DATA.prices).sort().pop(); DATA.moves={avg_up:ups.length?r2(mean(ups)):0,avg_down:downs.length?r2(mean(downs)):0,avg_range:rng.length?r2(mean(rng)):0,last_close:last?DATA.prices[last].close:0}; }
  function pivotsFrom(y){ const yH=y.high,yL=y.low,yC=y.close,rng=yH-yL,PP=(yH+yL+yC)/3; return {R3:2*PP-yL+rng,R2:PP+rng,R1:2*PP-yL,'Yest High':yH,PP:PP,'Yest Low':yL,S1:2*PP-yH,S2:PP-rng,S3:(2*PP-yH)-rng}; }
  function computeReactionStats(){ const days=Object.keys(DATA.prices).sort(); const RES={R1:[0,0],R2:[0,0],R3:[0,0],'Yest High':[0,0]},SUP={S1:[0,0],S2:[0,0],S3:[0,0],'Yest Low':[0,0]}; let pp0=0,pp1=0,total=0;
    for(let i=1;i<days.length;i++){ const t=DATA.prices[days[i]],y=DATA.prices[days[i-1]]; if([t.high,t.low,y.high,y.low,y.close].some(x=>x==null))continue; total++; const lv=pivotsFrom(y),th=t.high,tl=t.low,tc=t.close;
      for(const k in RES){const L=lv[k]; if(th>=L){RES[k][0]++; if(tc<L)RES[k][1]++;}}
      for(const k in SUP){const L=lv[k]; if(tl<=L){SUP[k][0]++; if(tc>L)SUP[k][1]++;}}
      pp1++; if(tl<=lv.PP&&lv.PP<=th)pp0++; }
    const stats={}; for(const k in RES){const tch=RES[k][0],held=RES[k][1]; stats[k]={type:'resistance',touch_pct:total?Math.round(tch/total*100):0,hold_pct:tch?Math.round(held/tch*100):0,n:tch};}
    for(const k in SUP){const tch=SUP[k][0],held=SUP[k][1]; stats[k]={type:'support',touch_pct:total?Math.round(tch/total*100):0,hold_pct:tch?Math.round(held/tch*100):0,n:tch};}
    stats.PP={type:'pivot',touch_pct:pp1?Math.round(pp0/pp1*100):0,hold_pct:null,n:pp0}; DATA.level_stats=stats; }
  function levelsApi(){ const days=Object.keys(DATA.prices).sort(); if(!days.length)return {levels:[]}; const y=DATA.prices[days[days.length-1]]; if([y.high,y.low,y.close].some(x=>x==null))return {levels:[]}; const lv=pivotsFrom(y),ls=DATA.level_stats||{}; const out=[]; for(const name in lv){const s=ls[name]||{},hold=s.hold_pct; out.push({name,price:r2(lv[name]),type:s.type,touch_pct:s.touch_pct,hold_pct:hold,break_pct:hold!=null?100-hold:null,n:s.n});} out.sort((a,b)=>b.price-a.price); return {based_on:days[days.length-1],levels:out}; }

  function matchingMoves(ds,sign,stage){ if(_matchCache[ds])return _matchCache[ds]; const ups=[],downs=[],rng=[]; for(const d in DATA.prices){ if(d>=ds)continue; const m=DATA.moon[d]; if(!m||m.sign!==sign||m.stage!==stage)continue; const p=DATA.prices[d],ch=p.change; if(ch!=null)(ch>=0?ups:downs).push(Math.abs(ch)); if(p.high&&p.low)rng.push(p.high-p.low);} const g=DATA.moves,mean=a=>a.reduce((x,y)=>x+y,0)/a.length; const res={avg_up:ups.length>=2?r2(mean(ups)):g.avg_up,avg_down:downs.length>=2?r2(mean(downs)):g.avg_down,avg_range:rng.length?r2(mean(rng)):g.avg_range,n:ups.length+downs.length}; _matchCache[ds]=res; return res; }
  function marketClosed(ds,today){ const dt=parseDate(ds); if(!dt)return null; const wd=dt.getDay(); if(wd===0||wd===6)return 'Weekend'; if(GOLD_HOLIDAYS.has(ds))return 'Holiday'; if(ds<today && !(ds in DATA.prices))return 'Holiday'; return null; }
  function signedMove(ds,today){ if(ds in _moveCache)return _moveCache[ds]; let val=0; if(!marketClosed(ds,today)){ const pb=pullbackDirection(ds,today); const m0=DATA.moon[ds]; const fc=DATA.forecast[ds];
    if(pb&&m0){ const mm=matchingMoves(ds,m0.sign,m0.stage); val=pb==='BUY'?mm.avg_up:-mm.avg_down; }
    else if(fc&&(fc.direction==='BUY'||fc.direction==='SELL')){ if(fc.direction==='BUY'&&fc.avg_bull)val=Math.abs(fc.avg_bull); else if(fc.direction==='SELL'&&fc.avg_bear)val=-Math.abs(fc.avg_bear); }
    else { const m=DATA.moon[ds]; if(m){ const sig=computeSignal(ds,m,histCounts(ds,m.sign,m.stage),pastMoonHistory(ds),null,null); const s=sig?sig.signal:''; const mm=matchingMoves(ds,m.sign,m.stage); const mult=s.includes('STRONG')?1.4:1.0; if(s.includes('BUY'))val=mm.avg_up*mult; else if(s.includes('SELL'))val=-mm.avg_down*mult; } } } val=r2(val); _moveCache[ds]=val; return val; }
  function chainedAnchor(ds,today){ const keys=Object.keys(DATA.prices); if(!keys.length)return null; const lastD=keys.sort().pop(); if(ds<=lastD)return null; let anchor=DATA.prices[lastD].close; let cur=parseDate(lastD); for(;;){ cur=new Date(cur.getTime()+86400000); const cs=iso(cur); if(cs>=ds)break; const mv=signedMove(cs,today); if(mv)anchor=r2(anchor+mv); } return anchor; }

  const MOVABLE=new Set(['Aries','Cancer','Libra','Capricorn']);
  function dateDigitRoot(ds){ let d=parseInt(ds.split('-')[2],10); if(isNaN(d))return null; while(d>9)d=String(d).split('').reduce((a,c)=>a+(+c),0); return d; }
  function prevTradingDay(ds,today){ let cur=parseDate(ds); for(let i=0;i<12;i++){cur=new Date(cur.getTime()-86400000);const cs=iso(cur);if(!marketClosed(cs,today))return cs;} return null; }
  function baseDirection(ds){ const fc=DATA.forecast[ds]; if(fc&&['BUY','SELL','WAIT'].includes(fc.direction))return fc.direction; const m=DATA.moon[ds]; if(!m)return null; const sig=computeSignal(ds,m,histCounts(ds,m.sign,m.stage),pastMoonHistory(ds),null,null); const s=sig?sig.signal:''; return s.includes('BUY')?'BUY':(s.includes('SELL')?'SELL':'WAIT'); }
  function pullbackDirection(ds,today){ const m=DATA.moon[ds]; if(!m||!MOVABLE.has(m.sign))return null; const prev=prevTradingDay(ds,today); if(!prev)return null; const pm=DATA.moon[prev]; if(!pm||pm.sign!==m.sign)return null; const prev2=prevTradingDay(prev,today); const pm2=prev2?DATA.moon[prev2]:null; if(pm2&&pm2.sign===m.sign)return null; const d1=baseDirection(prev); if(d1==='BUY')return'SELL'; if(d1==='SELL')return'BUY'; return null; }

  // ---- nature-cycle model (v3) ----
  const _modelCache={};
  function priorActualDir(ds,today){ const prev=prevTradingDay(ds,today); if(!prev)return[null,null]; const pp=DATA.prices[prev]; if(pp&&(pp.direction==='BULL'||pp.direction==='BEAR'))return[pp.direction==='BULL'?1:-1,prev]; const md=modelDirection(prev,today); if(md==='BUY')return[1,prev]; if(md==='SELL')return[-1,prev]; return[null,prev]; }
  function modelDirection(ds,today){ if(ds in _modelCache)return _modelCache[ds]; _modelCache[ds]=null; const m=DATA.moon[ds]; if(!m)return null; const pr=priorActualDir(ds,today),pa=pr[0],prev=pr[1]; if(pa==null||!prev)return null; const nat=String((DATA.signs[m.sign]||{}).nature||'').toUpperCase(); const stage=m.stage; let d; /* 9-cycle rules removed (lifts win rate ~52%->~56%) */ if(nat==='MOVABLE')d=(DATA.moon[prev]&&DATA.moon[prev].sign===m.sign)?-pa:pa; else if(nat==='FIXED')d=pa; else d=(stage==='FINISH'?-pa:pa); const res=d>0?'BUY':'SELL'; _modelCache[ds]=res; return res; }
  function modelInfo(ds,today){ const d=modelDirection(ds,today); if(!d)return null; const m=DATA.moon[ds],prev=prevTradingDay(ds,today); const nat=String((DATA.signs[m.sign]||{}).nature||'').toUpperCase(),stage=m.stage; let why; if(nat==='MOVABLE')why=(DATA.moon[prev]&&DATA.moon[prev].sign===m.sign)?'movable 2nd-day → pullback':'movable 1st-day → continue'; else if(nat==='FIXED')why='fixed → continue trend'; else why=(stage==='FINISH'?'finisher at FINISH → turn':'finisher → continue'); return {dir:d,reason:why}; }

  function signalReason(day){ const sig=day.signal; if(!sig)return''; const parts=[];
    if(day.signal_src==='sheet'&&day.buy_score!=null&&day.sell_score!=null){ parts.push('buy/sell score '+Math.round(day.buy_score)+'/'+Math.round(day.sell_score)); if(day.transition)parts.push(String(day.transition).toLowerCase()); }
    else { const ms=day.moon_score||0; if(ms>0)parts.push('bullish moon ('+day.sign+')'); else if(ms<0)parts.push('bearish moon ('+day.sign+')'); const retro=day.retrogrades||[]; const ts=day.transit_score||0; if(retro.length)parts.push(retro.join(', ')+' Rx pressure'); else if(ts>0)parts.push('transit support'); else if(ts<0)parts.push('transit drag'); }
    const bp=day.bull_pct,brp=day.bear_pct; if(bp!=null&&(bp||brp)){ if(sig.includes('BUY'))parts.push(bp+'% bull history'); else if(sig.includes('SELL'))parts.push(brp+'% bear history'); }
    if(day.power_day)parts.push('day-'+day.day_number+' power(3·7·9)'); if(day.mtf_score)parts.push('multi-TF '+(day.mtf_score>0?'up':'down'));
    if(day.pullback)parts.unshift('movable 2-day pullback (reverse of prior day)');
    if(day.power_date)parts.push('★ important date (3·7·9) — bigger move');
    const verb={'STRONG BUY':'Strong BUY','BUY':'BUY','SELL':'SELL','STRONG SELL':'Strong SELL','WAIT':'WAIT','NO TRADE':'NO TRADE'}[sig]||sig;
    if(!parts.length)return verb+' — '+((sig==='WAIT'||sig==='NO TRADE')?'mixed signals — no clear edge':'weak edge');
    return verb+' — '+parts.slice(0,4).join('; '); }

  function ppFor(ds){ const prior=Object.keys(DATA.prices).sort().filter(d=>d<ds); if(!prior.length)return null; const y=DATA.prices[prior[prior.length-1]]; if(y.high==null||y.low==null||y.close==null)return null; return (y.high+y.low+y.close)/3; }
  function weekKey(ds){ const dt=new Date(ds+'T00:00:00'); const day=(dt.getDay()+6)%7; const mon=new Date(dt); mon.setDate(dt.getDate()-day); return mon.getFullYear()+'-'+String(mon.getMonth()+1).padStart(2,'0')+'-'+String(mon.getDate()).padStart(2,'0'); }
  function computeWeeks(){ const wk={}; for(const d of Object.keys(DATA.prices).sort()){ const k=weekKey(d); (wk[k]=wk[k]||[]).push(d);} const wd={}; for(const k in wk){const ds=wk[k]; wd[k]=(DATA.prices[ds[ds.length-1]].close-DATA.prices[ds[0]].open)>=0?1:-1;} DATA.week_dir=wd; DATA.week_keys=Object.keys(wk).sort(); }
  function weeklyBias(ds){ const k=weekKey(ds); const prior=(DATA.week_keys||[]).filter(x=>x<k); if(!prior.length)return null; return DATA.week_dir[prior[prior.length-1]]; }
  // 1:1 reward:risk WITH breakeven trail. risk=1*move, reward=R*move; when price travels
  // be_frac of the way to target, stop moves to ENTRY (breakeven). Returns [outcome,tp_hit,sl_hit];
  // outcome ∈ 'W'/'BE'/'L'/null (null=pending). Conservative: adverse move assumed first each day.
  function tpWindow(ds,direction,mv,entry,n,R,beFrac){ n=n||3; R=R||1.0; beFrac=beFrac==null?0.5:beFrac;
    if(!mv||entry==null)return[null,false,false];
    const pdays=Object.keys(DATA.prices).sort().filter(d=>d>=ds).slice(0,n); if(!pdays.length)return[null,false,false];
    const buy=direction==='BUY';
    const stop0=buy?entry-mv:entry+mv, be=buy?entry+beFrac*R*mv:entry-beFrac*R*mv, tgt=buy?entry+R*mv:entry-R*mv;
    let armed=false;
    for(const d of pdays){const pp=DATA.prices[d],hi=pp.high,lo=pp.low; if(hi==null||lo==null)continue;
      if(buy){
        if(!armed){ if(lo<=stop0)return['L',false,true]; if(hi>=tgt)return['W',true,false]; if(hi>=be)armed=true; }
        else     { if(lo<=entry)return['BE',false,false]; if(hi>=tgt)return['W',true,false]; }
      } else {
        if(!armed){ if(hi>=stop0)return['L',false,true]; if(lo<=tgt)return['W',true,false]; if(lo<=be)armed=true; }
        else     { if(hi>=entry)return['BE',false,false]; if(lo<=tgt)return['W',true,false]; }
      }
    }
    if(pdays.length<n)return[null,false,false];
    return[armed?'BE':'L',false,!armed]; }
  function candleNote(p){ const o=p.open,h=p.high,l=p.low,c=p.close; if([o,h,l,c].some(x=>x==null))return null; const rng=(h-l)||1,body=c-o,uw=h-Math.max(o,c),lw=Math.min(o,c)-l; if(Math.abs(body)<0.30*rng){ if(uw>lw*1.3)return'small body · upper-wick rejection (bearish tilt)'; if(lw>uw*1.3)return'small body · lower-wick rejection (bullish tilt)'; return'small body · indecision (continuation)';} return body>0?'strong bull body':'strong bear body'; }
  function trendNote(ds){ const back=Object.keys(DATA.prices).sort().filter(d=>d<ds).slice(-3); if(back.length<2)return null; const net=DATA.prices[back[back.length-1]].close-DATA.prices[back[0]].open; return net>=0?'up':'down'; }

  // ---- build a day (mirror build_day) ----
  function buildDay(ds){
    const today=todayISO(); const m=DATA.moon[ds]; const p=DATA.prices[ds];
    const day={date:ds,is_past:ds<today,is_today:ds===today};
    const closed=marketClosed(ds,today);
    if(closed){ day.market_closed=true; day.closed_reason=closed;
      if(m)Object.assign(day,{sign:m.sign,sun_sign:m.sun_sign,phase:m.phase,phase_emoji:m.phase_emoji,stage:m.stage,gender:m.gender,day_number:m.day_number,stage_num:m.stage_num,sign_emoji:(DATA.signs[m.sign]||{}).emoji||'*'});
      if(p)Object.assign(day,{open:p.open,high:p.high,low:p.low,close:p.close,change:p.change,rng:p.rng,direction:p.direction,mid:(p.high&&p.low)?r2((p.high+p.low)/2):null});
      const nw=NEWS[ds]||[]; day.usd_news=nw; day.usd_news_count=nw.length; return day; }
    if(m){ const counts=histCounts(ds,m.sign,m.stage); const history=pastMoonHistory(ds); const mtf=ds===today?mtfScore(DATA.h1,DATA.h4):null;
      const sig=computeSignal(ds,m,counts,history,p,mtf); const si=DATA.signs[m.sign]||{}; let pi={};
      for(const pk in DATA.phases){ if(pk.toLowerCase().includes(m.phase.toLowerCase())||m.phase.toLowerCase().includes(pk.toLowerCase())){pi=DATA.phases[pk];break;} }
      Object.assign(day,{sign:m.sign,sun_sign:m.sun_sign,phase:m.phase,phase_emoji:m.phase_emoji,stage:m.stage,gender:m.gender,day_number:m.day_number,stage_num:m.stage_num,
        sign_emoji:si.emoji||'*',sign_meaning:si.meaning||'',sign_bias:si.market_bias||'',sign_nature:si.nature||'',sign_keyword:si.keyword||'',phase_mood:pi.mood||'',phase_meaning:pi.meaning||''});
      if(sig)Object.assign(day,sig);
    }
    if(p){ const mid=(p.high&&p.low)?r2((p.high+p.low)/2):null; Object.assign(day,{open:p.open,high:p.high,low:p.low,close:p.close,change:p.change,rng:p.rng,direction:p.direction,mid}); }
    // sheet override
    const fc=DATA.forecast[ds];
    if(fc&&['BUY','SELL','WAIT'].includes(fc.direction)){ day.signal=fc.direction; day.signal_src='sheet'; day.buy_score=fc.buy_score; day.sell_score=fc.sell_score; day.transition=fc.transition;
      if(fc.confidence!=null)day.confidence=Math.round(fc.confidence); if(fc.buy_score!=null&&fc.sell_score!=null)day.bias=clamp(r1(fc.buy_score-fc.sell_score),-100,100);
      const today2=todayISO(); const anchor=day.open||chainedAnchor(ds,today2)||DATA.moves.last_close||0;
      if(fc.direction==='BUY'&&fc.avg_bull){const mv=r2(Math.abs(fc.avg_bull));day.expected_move=mv;day.target_dir='up';if(anchor){day.target=r2(anchor+mv);day.target_anchor=r2(anchor);day.target_is_est=day.open==null;}}
      else if(fc.direction==='SELL'&&fc.avg_bear){const mv=r2(Math.abs(fc.avg_bear));day.expected_move=mv;day.target_dir='down';if(anchor){day.target=r2(anchor-mv);day.target_anchor=r2(anchor);day.target_is_est=day.open==null;}}
      if(fc.avg_range)day.expected_range=r2(Math.abs(fc.avg_range));
    }
    // RULE 2: movable-sign 2-day pullback (overrides sheet + engine direction)
    const pb=pullbackDirection(ds,todayISO());
    if(pb&&['BUY','STRONG BUY','SELL','STRONG SELL','WAIT','NO TRADE'].includes(day.signal)){
      day.signal=pb; day.signal_src='pullback'; day.pullback=true;
      const b=Math.abs(day.bias||20); day.bias=pb==='BUY'?b:-b;
      ['expected_move','target','target_dir','target_anchor','target_is_est','expected_range','move_match_n'].forEach(k=>delete day[k]);
    }
    // engine projection (only if not set by sheet)
    const sn=day.signal;
    if(!('expected_move'in day)&&DATA.moves&&['BUY','STRONG BUY','SELL','STRONG SELL'].includes(sn)){
      const today2=todayISO(); const mm=matchingMoves(ds,day.sign,day.stage); const anchor=day.open||chainedAnchor(ds,today2)||DATA.moves.last_close||0; const strong=sn.includes('STRONG');
      let mv; if(sn.includes('BUY')){mv=mm.avg_up*(strong?1.4:1.0);day.target_dir='up';} else {mv=mm.avg_down*(strong?1.4:1.0);day.target_dir='down';}
      mv=r2(mv); day.expected_move=mv; day.expected_range=mm.avg_range; day.move_match_n=mm.n;
      if(anchor){ day.target=r2(sn.includes('BUY')?anchor+mv:anchor-mv); day.target_anchor=r2(anchor); day.target_is_est=day.open==null; }
    }
    // RULE 3: important DATE (day-of-month digit-root 3/7/9) amplifies the move
    day.power_date=[3,7,9].includes(dateDigitRoot(ds));
    if(day.power_date&&day.expected_move){ day.expected_move=r2(day.expected_move*1.2); const anc=day.target_anchor; if(anc!=null&&day.target_dir)day.target=r2(day.target_dir==='up'?anc+day.expected_move:anc-day.expected_move); if(day.confidence)day.confidence=Math.min(100,day.confidence+6); }
    // WIN/LOSS via take-profit model (past days only)
    const sg=day.signal;
    if(p&&day.is_past&&['BUY','STRONG BUY','SELL','STRONG SELL'].includes(sg)&&day.expected_move){
      const mv=day.expected_move,ddir=sg.includes('BUY')?'BUY':'SELL'; const entry=ppFor(ds)||p.open;
      if(entry){ if(ddir==='BUY'){day.tp=r2(entry+mv);day.sl=r2(entry-mv);day.be=r2(entry+0.5*mv);}else{day.tp=r2(entry-mv);day.sl=r2(entry+mv);day.be=r2(entry-0.5*mv);}
        day.entry=r2(entry);day.rr='1:1';day.tp_window=3;
        const wr=tpWindow(ds,ddir,mv,entry,3); day.tp_hit=wr[1];day.sl_hit=wr[2]; if(wr[0]!=null){day.outcome=wr[0];day.correct=(wr[0]==='W');} }
    }
    if(p){const cn=candleNote(p); if(cn)day.candle_note=cn;} const tn=trendNote(ds); if(tn)day.trend_note=tn;
    // nature-cycle model (second opinion)
    const mi=modelInfo(ds,todayISO());
    if(mi){ day.model_dir=mi.dir; day.model_reason=mi.reason; const prim=day.signal||''; const pd2=prim.includes('BUY')?'BUY':(prim.includes('SELL')?'SELL':null); day.model_agree=pd2?(pd2===mi.dir):null;
      if(m){ const mm=matchingMoves(ds,m.sign,m.stage); const mv=r2(mi.dir==='BUY'?mm.avg_up:mm.avg_down); const T=todayISO();
        const anchor=(ds<=T)?(ppFor(ds)||day.open||chainedAnchor(ds,T)||(DATA.moves&&DATA.moves.last_close)||0):(chainedAnchor(ds,T)||(DATA.moves&&DATA.moves.last_close)||0); day.model_move=mv;
        if(anchor){ if(mi.dir==='BUY'){day.model_anchor=r2(anchor);day.model_tp=r2(anchor+mv);day.model_be=r2(anchor+0.5*mv);day.model_invalidate=r2(anchor-mv);day.model_exp_high=r2(anchor+mv);day.model_exp_low=r2(anchor-0.4*mv);} else {day.model_anchor=r2(anchor);day.model_tp=r2(anchor-mv);day.model_be=r2(anchor-0.5*mv);day.model_invalidate=r2(anchor+mv);day.model_exp_high=r2(anchor+0.4*mv);day.model_exp_low=r2(anchor-mv);} }
        if(p&&day.is_past&&anchor){ const wr=tpWindow(ds,mi.dir,mv,anchor,3); day.model_tp_hit=wr[1];day.model_sl_hit=wr[2]; if(wr[0]!=null){day.model_outcome=wr[0];day.model_correct=(wr[0]==='W');} } } }
    // weekly-direction filter flags
    const wb=weeklyBias(ds); day.weekly_bias=(wb===1?'bull':wb===-1?'bear':null);
    const md2=day.model_dir; day.model_with_trend=(md2&&wb!=null)?((md2==='BUY'&&wb===1)||(md2==='SELL'&&wb===-1)):true;
    const sgd=(sg&&sg.includes('BUY'))?'BUY':((sg&&sg.includes('SELL'))?'SELL':null); day.with_trend=(sgd&&wb!=null)?((sgd==='BUY'&&wb===1)||(sgd==='SELL'&&wb===-1)):true;
    day.reason=signalReason(day);
    const nw=NEWS[ds]||[]; day.usd_news=nw; day.usd_news_count=nw.length;
    return day;
  }

  // ---- aggregate endpoints ----
  function calendar(y,mn){ const days=new Date(y,mn,0).getDate(); const out=[]; for(let d=1;d<=days;d++)out.push(buildDay(y+'-'+String(mn).padStart(2,'0')+'-'+String(d).padStart(2,'0'))); return out; }
  function forecastRange(past,future){ past=past||20;future=future||30; const t=new Date(); const out=[]; for(let i=-past;i<=future;i++){const d=new Date(t.getTime()+i*86400000);const day=buildDay(iso(d)); if(day.sign&&!day.market_closed)out.push(day);} return out; }
  function pricesHist(n){ const items=Object.keys(DATA.prices).sort().slice(-n); return items.map(d=>{const v=DATA.prices[d];return {date:d,open:v.open,high:v.high,low:v.low,close:v.close,change:v.change,rng:v.rng,direction:v.direction};}); }
  function stats(){ const today=todayISO(); const monthly={},mMonthly={}; let tc=0,ts=0,tbe=0,tl=0,tb=0,tbr=0,streak=0,cur=0,last=null,mc=0,mt=0,mbe=0,ml=0,pmd=0;
    for(const d of Object.keys(DATA.prices).sort()){ const p=DATA.prices[d]; if(p.direction==='BULL')tb++;else tbr++; if(d>today)continue; const m=DATA.moon[d]; if(!m)continue; const day=buildDay(d); pmd++;
      if(day.model_outcome!=null&&day.model_with_trend){ const o=day.model_outcome; mt++; const k=d.slice(0,7); const mm=mMonthly[k]||(mMonthly[k]={correct:0,total:0,pnl:0}); mm.total++; if(o==='W'){mc++;mm.correct++;mm.pnl+=100;} else if(o==='BE'){mbe++;} else {ml++;mm.pnl-=100;} }
      const sig=day.signal; if(!['BUY','SELL','STRONG BUY','STRONG SELL'].includes(sig))continue; if(!day.with_trend)continue; const isBuy=sig.includes('BUY'); const mo=d.slice(0,7); if(!monthly[mo])monthly[mo]={correct:0,total:0,pnl:0,buy:0,sell:0}; monthly[mo].total++;ts++; if(isBuy)monthly[mo].buy++;else monthly[mo].sell++;
      const o=day.outcome; if(o==='W'){monthly[mo].correct++;monthly[mo].pnl+=100;tc++; cur=last===true?cur+1:1; last=true;} else if(o==='BE'){tbe++;} else {tl++;monthly[mo].pnl-=100; cur=last===false?cur-1:-1; last=false;} streak=cur; }
    const mean=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:0; const bm=Object.values(DATA.prices).filter(v=>v.direction==='BULL'&&v.change).map(v=>v.change); const brm=Object.values(DATA.prices).filter(v=>v.direction==='BEAR'&&v.change).map(v=>v.change);
    return {total_prices:Object.keys(DATA.prices).length,total_signals:ts,total_correct:tc,total_be:tbe,total_loss:tl,win_rate:ts?r1(tc/ts*100):0,total_r:tc-tl,expectancy:ts?Math.round((tc-tl)/ts*1000)/1000:0,total_pnl:(tc-tl)*100,streak,total_bull:tb,total_bear:tbr,avg_bull_move:bm.length?r2(mean(bm)):0,avg_bear_move:brm.length?r2(mean(brm)):0,model_correct:mc,model_total:mt,model_be:mbe,model_loss:ml,model_win_rate:mt?r1(mc/mt*100):0,model_total_r:mc-ml,model_expectancy:mt?Math.round((mc-ml)/mt*1000)/1000:0,model_no_signal:Math.max(0,pmd-mt),model_monthly:mMonthly,monthly}; }
  function analysis(){ const combos={}; for(const d in DATA.prices){const p=DATA.prices[d],m=DATA.moon[d]; if(!m)continue; const k=m.sign+'|'+m.stage; if(!combos[k])combos[k]={bull:0,bear:0,bm:[],brm:[]}; if(p.direction==='BULL'){combos[k].bull++;if(p.change)combos[k].bm.push(p.change);}else{combos[k].bear++;if(p.change)combos[k].brm.push(p.change);}} const res=[]; const mean=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:0; for(const k in combos){const v=combos[k],[sign,stage]=k.split('|'),total=v.bull+v.bear; if(total<2)continue; const bp=v.bull/total,brp=v.bear/total; res.push({sign,stage,total,bull:v.bull,bear:v.bear,bull_pct:r1(bp*100),bear_pct:r1(brp*100),bias:bp>brp?'BUY':(brp>bp?'SELL':'WAIT'),win_rate:r1(Math.max(bp,brp)*100),sign_emoji:(DATA.signs[sign]||{}).emoji||'',avg_bull:v.bm.length?r1(mean(v.bm)):0,avg_bear:v.brm.length?r1(mean(v.brm)):0});} res.sort((a,b)=>b.win_rate-a.win_rate); return res; }
  function dashboard(){ const t=todayISO(); const today=buildDay(t); const recent=[]; for(let i=1;i<=12&&recent.length<5;i++){const d=iso(new Date(Date.now()-i*86400000));const day=buildDay(d);if(day.close&&!day.market_closed)recent.push(day);} const up=[]; for(let i=1;i<=16&&up.length<7;i++){const d=iso(new Date(Date.now()+i*86400000));const day=buildDay(d);if(day.sign&&!day.market_closed)up.push(day);} return {today,recent,upcoming:up}; }

  // ---- live price (spot) ----
  async function livePrice(){
    let current=0; try{const g=await fetch('https://api.gold-api.com/price/XAU',{cache:'no-store'}).then(r=>r.json());current=parseFloat(g.price)||0;}catch(e){}
    const today=todayISO(); const closed=marketClosed(today,today); const keys=Object.keys(DATA.prices).sort();
    let last_close=null,prev=current;
    if(keys.length){const ld=keys[keys.length-1],lp=DATA.prices[ld]; const mid=(lp.high&&lp.low)?r2((lp.high+lp.low)/2):null; let cv=lp.close; if(closed&&current)cv=r2(current); last_close={date:ld,open:lp.open,high:lp.high,low:lp.low,close:cv,mid,direction:lp.direction}; prev=(closed&&keys.length>=2)?DATA.prices[keys[keys.length-2]].close||current:(lp.close||current);}
    const change=r2(current-prev),chgPct=prev?r2(change/prev*100):0;
    let t_open=null,t_high=null,t_low=null; if(!closed){const tc=DATA.h1.filter(c=>String(c.dt).startsWith(today)); if(tc.length){t_open=r2(tc[0].open);const hs=tc.map(c=>c.high).filter(x=>x!=null),ls=tc.map(c=>c.low).filter(x=>x!=null);t_high=hs.length?r2(Math.max(...hs)):null;t_low=ls.length?r2(Math.min(...ls)):null;if(t_high!=null&&current>t_high)t_high=r2(current);if(t_low!=null&&current&&current<t_low)t_low=r2(current);}}
    return {status:'ok',price:r2(current),prev_close:r2(prev),change,change_pct:chgPct,market_state:closed?'CLOSED':'OPEN',market_closed:!!closed,closed_reason:closed,time:'--',today_open:t_open,today_high:t_high,today_low:t_low,last_close,source:'gold-api.com (spot)'}; }

  // ---- USD news (Forex Factory via proxy) ----
  let NEWS={};
  async function loadNews(){ try{ const url='https://nfs.faireconomy.media/ff_calendar_thisweek.json'; let data=null;
      for(const u of ['https://api.allorigins.win/raw?url='+encodeURIComponent(url),url]){try{const r=await fetch(u,{cache:'no-store'});if(r.ok){data=await r.json();break;}}catch(e){}}
      if(data){const wk={}; data.forEach(ev=>{ if(ev.country!=='USD'||ev.impact!=='High')return; const ds=String(ev.date); if(!ds.includes('T'))return; const day=ds.split('T')[0],tm=ds.split('T')[1].slice(0,5); (wk[day]=wk[day]||[]).push({time:tm,title:ev.title,impact:ev.impact}); }); NEWS=wk;}
    }catch(e){} }

  // ---- trades (localStorage) ----
  const TKEY='goldos_trades';
  function getTrades(){ try{return JSON.parse(localStorage.getItem(TKEY)||'[]');}catch(e){return[];} }
  function saveTrades(t){ localStorage.setItem(TKEY,JSON.stringify(t)); }

  // ---- main load ----
  async function load(){
    const [gp,mr,sl,pl,h1,h4,wf]=await Promise.all(['gold_price','MOON_REAL','SIGN_LIBRARY','MOON_PHASE_LIBRARY','H1_DATA','H4_DATA','WEEKLY_FORECAST'].map(fetchCSV));
    // prices
    const rn=v=>v==null?null:r2(v);   // round OHLC to 2dp to match the Python loader (boundary parity)
    DATA.prices={}; parseCSV(gp).forEach(r=>{const d=parseDate(r.Date);if(!d||num(r.Close)==null)return;DATA.prices[iso(d)]={open:rn(num(r.Open)),high:rn(num(r.High)),low:rn(num(r.Low)),close:rn(num(r.Close)),change:rn(num(r.Change)),rng:rn(num(r.Range)),direction:String(r.Direction||'').trim().toUpperCase()};});
    // moon
    DATA.moon={}; const moonRows=parseCSV(mr); if(moonRows.length){const c0=moonRows[0]; const cDate=findCol(c0,'Real Date','date'),cSign=findCol(c0,'Clean Moon Sign','Moon Sign'),cPhase=findCol(c0,'Moon Phase (Lunar Phase)','Moon Phase'),cStage=findCol(c0,'Cycle Stage'),cGen=findCol(c0,'Gender'),cSnum=findCol(c0,'Stage Number'),cDnum=findCol(c0,'day number','Day Number');
      moonRows.forEach(r=>{const d=parseDate(r[cDate]);if(!d)return;const ds=iso(d);const phase=String(r[cPhase]||'').trim();DATA.moon[ds]={sign:cleanSign(r[cSign]),sun_sign:getSunSign(ds),phase,phase_emoji:getPhaseEmoji(phase),stage:String(r[cStage]||'').trim(),gender:String(r[cGen]||'').trim(),day_number:num(r[cDnum])!=null?Math.round(num(r[cDnum])):null,stage_num:num(r[cSnum])!=null?Math.round(num(r[cSnum])):null};});}
    // libs
    DATA.signs={}; parseCSV(sl).forEach(r=>{const nm=String(r.Sign||'').trim();if(!nm||nm.toLowerCase()==='nan')return;DATA.signs[nm]={gender:String(r.Gender||'').trim(),nature:String(r.Nature||'').trim(),keyword:String(r.Keyword||'').trim(),meaning:String(r.Meaning||'').trim(),market_bias:String(r['Market Bias']||'').trim(),emoji:SIGN_EMOJI[nm]||'*'};});
    DATA.phases={}; parseCSV(pl).forEach(r=>{const nm=String(r['Moon Phase']||'').trim();if(!nm||nm.toLowerCase()==='nan')return;DATA.phases[nm]={mood:String(r['Market Mood']||'').trim(),meaning:String(r['Trading Meaning']||'').trim()};});
    // candles
    const cand=txt=>parseCSV(txt).map(r=>({dt:String(r.DateTime||''),open:num(r.Open),close:num(r.Close),high:num(r.High),low:num(r.Low),direction:r.Direction?String(r.Direction).trim().toUpperCase():null,trend:r.Trend?String(r.Trend).trim().toUpperCase():null})).filter(c=>c.open!=null&&c.close!=null);
    DATA.h1=cand(h1); DATA.h4=cand(h4);
    // forecast
    DATA.forecast={}; const wfRows=parseCSV(wf); if(wfRows.length){const c0=wfRows[0];const cDir=findCol(c0,'Expected Direction'),cBuy=findCol(c0,'Buy Score'),cSell=findCol(c0,'Sell Score'),cConf=findCol(c0,'Confidence'),cBull=findCol(c0,'Average Bull Move'),cBear=findCol(c0,'Average Bear Move'),cRange=findCol(c0,'Avg Range'),cTrans=findCol(c0,'Transition Type');
      wfRows.forEach(r=>{const d=parseDate(r.Date);if(!d)return;const dir=String(r[cDir]||'').trim().toUpperCase();if(!dir||dir==='NAN')return;DATA.forecast[iso(d)]={direction:dir,buy_score:num(r[cBuy]),sell_score:num(r[cSell]),confidence:num(r[cConf]),avg_bull:num(r[cBull]),avg_bear:num(r[cBear]),avg_range:num(r[cRange]),transition:cTrans?String(r[cTrans]||'').trim():''};});}
    Object.keys(_matchCache).forEach(k=>delete _matchCache[k]); Object.keys(_moveCache).forEach(k=>delete _moveCache[k]); Object.keys(_modelCache).forEach(k=>delete _modelCache[k]);
    computeMoves();
    computeWeeks();
    computeReactionStats();
    await loadNews();
    console.log('GoldEngine loaded:',Object.keys(DATA.prices).length,'prices,',Object.keys(DATA.moon).length,'moon,',DATA.h1.length,'h1,',Object.keys(DATA.forecast).length,'forecast');
  }

  // ---- /api router (returns Response-like) ----
  function resp(data){ return {ok:true,status:200,json:async()=>data,text:async()=>JSON.stringify(data)}; }
  async function api(path,opts){ opts=opts||{}; const method=(opts.method||'GET').toUpperCase();
    let m;
    if(path.startsWith('/api/live-price'))return resp(await livePrice());
    if(path.startsWith('/api/dashboard'))return resp(dashboard());
    if(path.startsWith('/api/stats'))return resp(stats());
    if(path.startsWith('/api/analysis'))return resp(analysis());
    if(m=path.match(/^\/api\/calendar\/(\d+)\/(\d+)/))return resp(calendar(+m[1],+m[2]));
    if(path.startsWith('/api/levels'))return resp(levelsApi());
    if(m=path.match(/^\/api\/day\/(.+)/))return resp(buildDay(m[1]));
    if(m=path.match(/^\/api\/forecast-range\/(\d+)\/(\d+)/))return resp(forecastRange(+m[1],+m[2]));
    if(path.startsWith('/api/forecast-range'))return resp(forecastRange(20,30));
    if(m=path.match(/^\/api\/forecast\/(\d+)/))return resp(forecastRange(0,+m[1]));
    if(m=path.match(/^\/api\/prices\/(\d+)/))return resp(pricesHist(+m[1]));
    if(path.startsWith('/api/refresh-prices')){await load();return resp({status:'ok',total_in_db:Object.keys(DATA.prices).length,message:'Reloaded from Google Sheet.'});}
    if(path.startsWith('/api/news-refresh')){await loadNews();return resp({status:'ok'});}
    if(path.startsWith('/api/trades')){
      let trades=getTrades();
      if(m=path.match(/^\/api\/trades\/(.+)/)){ const id=m[1];
        if(method==='DELETE'){trades=trades.filter(t=>t.id!==id);saveTrades(trades);return resp({status:'deleted'});}
        if(method==='PUT'){const body=JSON.parse(opts.body||'{}');const i=trades.findIndex(t=>t.id===id);if(i>=0){Object.assign(trades[i],body);saveTrades(trades);return resp(trades[i]);}return resp({});}
      }
      if(method==='POST'){const t=JSON.parse(opts.body||'{}');t.id=(trades.length+1)+'_'+Date.now();t.created_at=new Date().toISOString();trades.unshift(t);saveTrades(trades);return resp(t);}
      return resp(trades);
    }
    return resp({status:'error',message:'unknown endpoint '+path});
  }

  return {load,api,DATA};
})();

// ---- fetch shim: route /api/* to the client engine ----
(function(){ const orig=window.fetch.bind(window);
  window.fetch=function(url,opts){ try{ if(typeof url==='string'&&url.indexOf('/api/')===0)return GoldEngine.api(url,opts); }catch(e){} return orig(url,opts); };
})();

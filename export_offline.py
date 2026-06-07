# -*- coding: utf-8 -*-
"""Build a SINGLE self-contained HTML file with all the 4-hour / Decision-Day data
baked in, so you can open it on your PHONE, fully OFFLINE (no Python, no internet).

Run:  python export_offline.py
Output:  naser_gold_offline.html   (copy this one file to your phone)
"""
import os, json
from datetime import datetime, timedelta
import app   # reuses your live engine (build_day, etc.)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'naser_gold_offline.html')

def collect(start='2026-01-01', end='2026-12-31'):
    app.load_data_safe()                       # live if online, else from data_cache.json
    d0 = datetime.strptime(start, '%Y-%m-%d')
    d1 = datetime.strptime(end, '%Y-%m-%d')
    days = {}
    cur = d0
    while cur <= d1:
        ds = cur.strftime('%Y-%m-%d')
        day = app.build_day(ds)
        if day.get('sign') or day.get('close'):     # keep days that actually have data
            days[ds] = day
        cur += timedelta(days=1)
    return days

TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Naser Gold · 4H (offline)</title>
<style>
:root{--bg:#0b1020;--card:#141b2e;--card2:#1b2540;--border:#26304d;--text:#e7ecf5;
--text2:#9fb0cc;--text3:#6b7a99;--gold:#f5a420;--goldbg:rgba(245,164,32,.12);
--buy:#23c08a;--sell:#ef4b6b;--nd:#6b7a99;}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
header{position:sticky;top:0;background:#0d1426;border-bottom:1px solid var(--border);
padding:12px 14px;z-index:5}
.htitle{font-weight:800;letter-spacing:.5px;font-size:16px}
.htitle small{color:var(--text3);font-weight:600;font-size:11px}
.bar{display:flex;gap:8px;align-items:center;margin-top:10px}
select{flex:1;background:var(--card2);color:var(--text);border:1px solid var(--border);
border-radius:9px;padding:9px 10px;font-size:14px}
.wrap{padding:12px 12px 60px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;
padding:12px 14px;margin-bottom:10px;cursor:pointer}
.card:active{background:var(--card2)}
.crow{display:flex;justify-content:space-between;align-items:center;gap:10px}
.cdate{font-weight:700}.cdate small{color:var(--text3);font-weight:500}
.pill{display:inline-block;padding:3px 10px;border-radius:20px;font-weight:800;font-size:12px}
.p-buy{background:rgba(35,192,138,.16);color:var(--buy)}
.p-sell{background:rgba(239,75,107,.16);color:var(--sell)}
.p-wait{background:rgba(245,164,32,.16);color:var(--gold)}
.p-nd{background:rgba(107,122,153,.16);color:var(--nd)}
.adv{color:var(--text2);font-size:12.5px;margin-top:7px}
.tag{font-size:10px;font-weight:800;padding:2px 7px;border-radius:6px;margin-left:6px}
.tag-dec{background:var(--goldbg);color:var(--gold)}
.tag-win{background:rgba(35,192,138,.16);color:var(--buy)}
.tag-loss{background:rgba(239,75,107,.16);color:var(--sell)}
.tag-be{background:var(--goldbg);color:var(--gold)}
/* detail */
#ov{position:fixed;inset:0;background:rgba(0,0,0,.6);display:none;z-index:20}
#panel{position:fixed;top:0;right:0;bottom:0;width:100%;max-width:460px;background:var(--bg);
border-left:1px solid var(--border);transform:translateX(100%);transition:.22s;z-index:21;
overflow-y:auto;-webkit-overflow-scrolling:touch}
#panel.open{transform:translateX(0)}
.phead{position:sticky;top:0;background:#0d1426;border-bottom:1px solid var(--border);
padding:14px;display:flex;justify-content:space-between;align-items:center}
.pbody{padding:14px}
.sec{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:13px;margin-bottom:12px}
.sec.gold{border-color:rgba(245,164,32,.4)}
.sectitle{font-size:11px;letter-spacing:.6px;color:var(--text3);font-weight:800;margin-bottom:9px;text-transform:uppercase}
.row{display:flex;justify-content:space-between;gap:10px;padding:4px 0;font-size:13.5px}
.lbl{color:var(--text2)}.val{font-weight:700;text-align:right}
.buy{color:var(--buy)}.sell{color:var(--sell)}.gold{color:var(--gold)}.muted{color:var(--text3)}
.big{font-size:13px;font-weight:800;line-height:1.5;margin-bottom:10px}
.x{font-size:24px;color:var(--text2);cursor:pointer;padding:0 6px}
.empty{color:var(--text3);text-align:center;padding:40px 10px}
</style></head>
<body>
<header>
  <div class="htitle">🥇 Naser Gold <small>· 4-HOUR · OFFLINE</small></div>
  <div class="bar"><select id="month" onchange="renderList()"></select></div>
</header>
<div class="wrap"><div id="list"></div></div>
<div id="ov" onclick="closePanel()"></div>
<div id="panel"><div class="phead"><div id="ptitle" style="font-weight:800"></div><div class="x" onclick="closePanel()">✕</div></div><div class="pbody" id="pbody"></div></div>

<script>
const DAYS = __DATA__;
const GEN = "__GEN__";
const fmt = v => (v==null||isNaN(v))?'—':'$'+Number(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const dir2 = s => s&&s.indexOf('BUY')>=0?'BUY':(s&&s.indexOf('SELL')>=0?'SELL':null);
function pillClass(s){const d=dir2(s);if(d==='BUY')return'p-buy';if(d==='SELL')return'p-sell';if(s==='WAIT')return'p-wait';return'p-nd';}
function pill(s){s=s||'NO DATA';return '<span class="pill '+pillClass(s)+'">'+s+'</span>';}
function wd(ds){return new Date(ds+'T12:00').toLocaleDateString('en-US',{weekday:'short'});}
function longd(ds){return new Date(ds+'T12:00').toLocaleDateString('en-US',{weekday:'long',month:'long',day:'numeric',year:'numeric'});}

function months(){
  const set=[...new Set(Object.keys(DAYS).map(d=>d.slice(0,7)))].sort();
  return set;
}
function fillMonths(){
  const sel=document.getElementById('month');const ms=months();
  sel.innerHTML=ms.map(m=>{const dt=new Date(m+'-01T12:00');
    return '<option value="'+m+'">'+dt.toLocaleDateString('en-US',{month:'long',year:'numeric'})+'</option>';}).join('');
  // default: month containing the most recent day that has price (a completed day), else last
  const done=Object.keys(DAYS).filter(d=>DAYS[d].close!=null).sort();
  sel.value=(done.length?done[done.length-1]:ms[ms.length-1]).slice(0,7);
}
function outTag(o){if(o==='W')return'<span class="tag tag-win">WIN</span>';if(o==='L')return'<span class="tag tag-loss">LOSS</span>';if(o==='BE')return'<span class="tag tag-be">BE</span>';if(o==='NF')return'<span class="tag tag-be">NO TRADE</span>';return'';}

function renderList(){
  const m=document.getElementById('month').value;
  const ds=Object.keys(DAYS).filter(d=>d.startsWith(m)).sort();
  const el=document.getElementById('list');
  const rows=ds.filter(d=>!DAYS[d].market_closed).map(d=>{
    const x=DAYS[d];const p=x.plan4h||{};
    const adv=(p.advice)||(x.reason)||'';
    return '<div class="card" onclick="openDay(\''+d+'\')"><div class="crow">'
      +'<div class="cdate">'+new Date(d+'T12:00').toLocaleDateString('en-US',{month:'short',day:'numeric'})+' <small>'+wd(d)+'</small>'
      +(x.decision_day?'<span class="tag tag-dec">⚠ DECISION</span>':'')
      +(x.after_decision?'<span class="tag tag-dec">CONTINUATION</span>':'')
      +outTag(p.outcome)+'</div>'
      +'<div>'+pill(x.signal)+'</div></div>'
      +(adv?'<div class="adv">'+adv+'</div>':'')+'</div>';
  });
  el.innerHTML=rows.length?rows.join(''):'<div class="empty">No trading days this month</div>';
}

function planCard(p){
  if(!p)return'';
  const oc=p.outcome;
  const badge=oc==='W'?'<span class="tag tag-win">✓ WIN +1R</span>':oc==='L'?'<span class="tag tag-loss">✗ LOSS −1R</span>':oc==='BE'?'<span class="tag tag-be">⊘ BE 0R</span>':oc==='NF'?'<span class="tag tag-be">— NO TRADE</span>':'';
  const tag=t=>({'fill':'<span class="gold">● ENTER</span>','tp':'<span class="buy">✓ TARGET</span>','sl':'<span class="sell">✗ STOP</span>','be-armed':'<span class="muted">→ BE</span>','be-exit':'<span class="gold">⊘ BE</span>'}[t]||'');
  const cnd=(p.candles||[]).map(c=>'<div class="row"><span class="lbl">'+(c.time||'')+' <span class="'+(c.dir==='BULL'?'buy':'sell')+'">'+(c.dir==='BULL'?'▲':'▼')+'</span></span><span class="val">H '+fmt(c.high)+' · L '+fmt(c.low)+(c.tags&&c.tags.length?' '+c.tags.map(tag).join(' '):'')+'</span></div>').join('');
  let entries;
  if(p.decision){
    entries='<div class="row"><span class="lbl">Action</span><span class="val '+(p.dir==='BUY'?'buy':'sell')+'">'+(p.dir==='BUY'?'▲ BUY':'▼ SELL')+' — trigger: '+(p.trigger||'')+'</span></div>'
      +'<div class="row"><span class="lbl">Entry 1 — midpoint</span><span class="val">'+fmt(p.entry1)+'</span></div>'
      +'<div class="row"><span class="lbl">Entry 2 — pivot</span><span class="val">'+(p.entry2!=null?fmt(p.entry2):'—')+'</span></div>'
      +'<div class="row"><span class="lbl">Filled</span><span class="val gold">'+(p.filled?fmt(p.entry)+' · '+(p.entry_label||'')+(p.fill_time?' ('+p.fill_time+')':''):'not triggered')+'</span></div>';
  }else{
    entries='<div class="row"><span class="lbl">Action</span><span class="val '+(p.dir==='BUY'?'buy':'sell')+'">'+(p.dir==='BUY'?'▲ BUY':'▼ SELL')+' at the pivot</span></div>'
      +'<div class="row"><span class="lbl">Entry — '+(p.entry_label||'pivot point')+'</span><span class="val gold">'+fmt(p.entry)+'</span></div>';
  }
  return '<div class="sec gold"><div class="sectitle">⏱ 4-Hour Trading Plan '+badge+'</div>'
    +(p.advice?'<div class="big '+(p.dir==='BUY'?'buy':'sell')+'">'+p.advice+'</div>':'')
    +entries
    +'<div class="row"><span class="lbl">Take-profit ('+(p.rr||'1:1')+')</span><span class="val buy">'+(p.target!=null?fmt(p.target):'—')+'</span></div>'
    +'<div class="row"><span class="lbl">Move stop to breakeven</span><span class="val">'+(p.be!=null?fmt(p.be):'—')+'</span></div>'
    +'<div class="row"><span class="lbl">Stop-loss</span><span class="val sell">'+(p.stop!=null?fmt(p.stop):'—')+'</span></div>'
    +'<div class="row"><span class="lbl">Stop size</span><span class="val">'+(p.atr_mult||'')+'× 4H-ATR ($'+(p.atr!=null?Number(p.atr).toFixed(2):'—')+')</span></div>'
    +(cnd?'<div class="sectitle" style="margin-top:12px">The day\'s 4-hour candles</div>'+cnd:'')
    +'</div>';
}

function openDay(d){
  const x=DAYS[d];if(!x)return;
  document.getElementById('ptitle').textContent=longd(d);
  let h='';
  // Signal
  h+='<div class="sec"><div class="sectitle">Signal'
    +(x.signal_src==='decision'?' <span class="tag tag-dec">⚠ DECISION-DAY CONTINUATION</span>':x.signal_src==='pullback'?' <span class="tag tag-loss">PULLBACK</span>':x.signal_src==='sheet'?' <span class="tag tag-dec">FROM SHEET</span>':'')
    +(x.power_date?' <span class="tag tag-dec">★ POWER 3·7·9</span>':'')+'</div>'
    +'<div style="margin-bottom:8px">'+pill(x.signal)+'</div>'
    +(x.reason?'<div class="adv">💡 '+x.reason+'</div>':'')
    +(x.after_decision?'<div class="big gold">⚠️ Continuation: '+x.prev_decision_date+' was a Decision Day, closed at '+x.decision_close_pos+'% of range ('+(x.decision_close_pos<=50?'near/below':'above')+' midpoint '+fmt(x.decision_mid)+') → today '+x.decision_dir+', entry at midpoint '+fmt(x.decision_entry)+'.</div>':'')
    +(x.outcome!=null?'<div class="row"><span class="lbl">Daily result</span><span class="val '+(x.outcome==='W'?'buy':x.outcome==='BE'?'gold':'sell')+'">'+(x.outcome==='W'?'✓ WIN':x.outcome==='BE'?'⊘ BE':'✗ LOSS')+'</span></div>':'')
    +'</div>';
  // 4H plan
  h+=planCard(x.plan4h);
  // Price
  if(x.close!=null){h+='<div class="sec"><div class="sectitle">Price Data</div>'
    +'<div class="row"><span class="lbl">Open</span><span class="val">'+fmt(x.open)+'</span></div>'
    +'<div class="row"><span class="lbl">High</span><span class="val buy">'+fmt(x.high)+'</span></div>'
    +'<div class="row"><span class="lbl">Low</span><span class="val sell">'+fmt(x.low)+'</span></div>'
    +'<div class="row"><span class="lbl">Close</span><span class="val">'+fmt(x.close)+'</span></div>'
    +'<div class="row"><span class="lbl">Midpoint (H+L)/2</span><span class="val gold">'+fmt(x.mid)+'</span></div>'
    +'<div class="row"><span class="lbl">Change</span><span class="val '+((x.change||0)>=0?'buy':'sell')+'">'+((x.change||0)>=0?'+':'')+Number(x.change||0).toFixed(2)+'</span></div>'
    +'<div class="row"><span class="lbl">Direction</span><span class="val '+(x.direction==='BULL'?'buy':'sell')+'">'+(x.direction||'—')+'</span></div>'
    +(x.decision_day?'<div class="row"><span class="lbl">Decision Day</span><span class="val gold">⚠️ small move (±$10) — next day important</span></div>':'')
    +'</div>';}
  // Astro
  if(x.sign){h+='<div class="sec"><div class="sectitle">Astrology</div>'
    +'<div class="row"><span class="lbl">Moon Sign</span><span class="val">'+(x.sign_emoji||'')+' '+x.sign+'</span></div>'
    +'<div class="row"><span class="lbl">Sun Sign</span><span class="val">☀ '+(x.sun_sign||'—')+'</span></div>'
    +'<div class="row"><span class="lbl">Moon Phase</span><span class="val">'+(x.phase_emoji||'')+' '+((x.phase||'').split('\n')[0])+'</span></div>'
    +'<div class="row"><span class="lbl">Cycle Stage</span><span class="val">'+(x.stage||'—')+'</span></div>'
    +'<div class="row"><span class="lbl">Day Number</span><span class="val">'+(x.day_number==null?'—':x.day_number)+'</span></div>'
    +'</div>';}
  document.getElementById('pbody').innerHTML=h;
  document.getElementById('panel').classList.add('open');
  document.getElementById('ov').style.display='block';
}
function closePanel(){document.getElementById('panel').classList.remove('open');document.getElementById('ov').style.display='none';}

fillMonths();renderList();
</script>
</body></html>
"""

if __name__ == '__main__':
    print("Collecting all days from the engine...")
    days = collect()
    gen = datetime.today().strftime('%Y-%m-%d %H:%M')
    html = TEMPLATE.replace('__DATA__', json.dumps(days, ensure_ascii=False)).replace('__GEN__', gen)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(html)
    kb = os.path.getsize(OUT) // 1024
    print("Wrote %s  (%d days, %d KB)" % (OUT, len(days), kb))
    print("Copy this ONE file to your phone and open it in any browser — works offline.")

# -*- coding: utf-8 -*-
"""Export the FULL dashboard (your real one) as ONE self-contained offline HTML file.

It renders your actual dashboard template and bakes every /api/... response into the
page, then swaps window.fetch so the dashboard's own code runs UNCHANGED but reads the
baked data instead of the Flask server. Result: identical look, works offline, no Python.

Run:  python export_dashboard_offline.py
Output: naser_gold_dashboard_offline.html  (also copied to gold-4h-github/index.html)
"""
import os, json
from datetime import datetime, timedelta
import app

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, 'naser_gold_dashboard_offline.html')

# range of history to bake (days + calendar months)
START = datetime(2025, 6, 1)
END   = datetime(2026, 12, 31)

def build():
    app.load_data_safe()
    client = app.app.test_client()

    def gj(path):
        return client.get(path).get_json()

    # the real rendered dashboard HTML
    html = client.get('/gold').get_data(as_text=True)

    bake = {}
    for p in ['/api/dashboard', '/api/levels', '/api/stats', '/api/analysis',
              '/api/live-price', '/api/trades',
              '/api/forecast-range/16/16', '/api/forecast-range/20/30', '/api/forecast-range/30/60',
              '/api/prices/30', '/api/prices/90', '/api/prices/180']:
        bake[p] = gj(p)

    # calendar months across the range
    y, m = START.year, START.month
    while (y < END.year) or (y == END.year and m <= END.month):
        bake['/api/calendar/%d/%d' % (y, m)] = gj('/api/calendar/%d/%d' % (y, m))
        m += 1
        if m > 12:
            m = 1; y += 1

    # every day in the range (for the detail panel on tap)
    cur = START
    while cur <= END:
        ds = cur.strftime('%Y-%m-%d')
        bake['/api/day/%s' % ds] = gj('/api/day/%s' % ds)
        cur += timedelta(days=1)

    shim = """<script>
(function(){
  var B=__BAKE__;
  var real=window.fetch?window.fetch.bind(window):null;
  function R(d){return Promise.resolve(new Response(JSON.stringify(d),{status:200,headers:{'Content-Type':'application/json'}}));}
  window.fetch=function(u,o){
    var url=(typeof u==='string')?u:((u&&u.url)||'');
    var path=url.replace(/^https?:\\/\\/[^/]+/,'').split('?')[0];
    if(Object.prototype.hasOwnProperty.call(B,path)) return R(B[path]);
    if(path.indexOf('/api/calendar/')===0) return R([]);
    if(path.indexOf('/api/day/')===0) return R({date:path.split('/').pop(),market_closed:false});
    if(path.indexOf('/api/prices/')===0) return R([]);
    if(path.indexOf('/api/forecast')===0) return R([]);
    if(path.indexOf('/api/')===0) return R({ok:true,status:'static (offline snapshot)'});
    return real?real(u,o):R({});
  };
})();
</script>"""
    shim = shim.replace('__BAKE__', json.dumps(bake, ensure_ascii=False))
    # inject the shim FIRST in <head> so it overrides fetch before the dashboard runs
    if '<head>' in html:
        html = html.replace('<head>', '<head>\n' + shim, 1)
    else:
        html = shim + html
    return html, len(bake)

if __name__ == '__main__':
    print("Rendering your real dashboard and baking all data...")
    html, n = build()
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(html)
    # also drop it as the single GitHub file
    ghdir = r'C:\Users\PC-1\Desktop\gold-4h-github'
    if os.path.isdir(ghdir):
        with open(os.path.join(ghdir, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(html)
    kb = os.path.getsize(OUT) // 1024
    print("Wrote %s  (%d API snapshots, %d KB)" % (OUT, n, kb))
    print("Also updated gold-4h-github\\index.html — upload that ONE file to GitHub.")

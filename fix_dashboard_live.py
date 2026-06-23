#!/usr/bin/env python3
"""
Two fixes so the live layer actually shows in the dashboard. Idempotent.
Run from the gold-command-center repo root:  python3 fix_dashboard_live.py

FIX 1 — gviz cache-buster. The app reads tabs from a fixed gviz URL; Google
edge-cached the EMPTY response from before the XAU_5m tab existed and keeps
serving it. Append a per-minute &cb=... so every read is fresh.

FIX 2 — silver timeframe selection. /api/silver preferred XAG_15m (only ~6 bars
so far) via `or`, so it never reached the 12-bar gate. Use the matched 5-minute
tabs when both metals have >=12 there (they do), else fall back to 15m.
"""
import sys, os

F = "app.py"
if not os.path.exists(F):
    print("ERROR: app.py not found — run from the repo root.")
    sys.exit(1)

s = open(F, encoding="utf-8").read()
orig = s

# ---- FIX 1: cache-buster on the gviz URL ----
if "&cb=%d" in s:
    print("fix1: cache-buster already present")
else:
    a = "&sheet=%s' % ("
    b = "&sheet=%s&cb=%d' % ("
    c = "        SHEET_ID, urllib.parse.quote(tab))"
    d = "        SHEET_ID, urllib.parse.quote(tab), int(__import__('time').time()//60))"
    if a in s and c in s:
        s = s.replace(a, b, 1).replace(c, d, 1)
        print("fix1: cache-buster added")
    else:
        print("fix1: WARN patterns not found — gviz URL builder may differ; skipped")

# ---- FIX 2: matched-timeframe selection in api_silver ----
old = ("    g = _scalp_load_tab('XAU_15m') or _scalp_load_tab('XAU_5m')\n"
       "    s = _scalp_load_tab('XAG_15m') or _scalp_load_tab('XAG_5m')")
new = ("    _g5 = _scalp_load_tab('XAU_5m'); _s5 = _scalp_load_tab('XAG_5m')\n"
       "    _g15 = _scalp_load_tab('XAU_15m'); _s15 = _scalp_load_tab('XAG_15m')\n"
       "    if len(_g5) >= 12 and len(_s5) >= 12:\n"
       "        g, s = _g5, _s5\n"
       "    elif len(_g15) >= 12 and len(_s15) >= 12:\n"
       "        g, s = _g15, _s15\n"
       "    else:\n"
       "        g, s = (_g15 or _g5), (_s15 or _s5)")
if "_g5 = _scalp_load_tab('XAU_5m')" in s:
    print("fix2: matched-timeframe already present")
elif old in s:
    s = s.replace(old, new, 1)
    print("fix2: matched-timeframe selection applied")
else:
    print("fix2: WARN selection lines not found; skipped")

if s != orig:
    open(F, "w", encoding="utf-8").write(s)
    print("app.py updated")
else:
    print("no changes written")

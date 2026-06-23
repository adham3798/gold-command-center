#!/usr/bin/env python3
"""
Lower the silver cross-check warm-up from 22 bars to 12 so the /api/silver badge
appears sooner (~35 min of feed instead of ~110). Idempotent.

Run from the gold-command-center repo root:  python3 lower_silver_warmup.py
Edits app.py: the api_silver bar-count gate and the _sv_struct EMA guard.
Trade-off: structure read is a bit noisier in the first ~20 bars, self-corrects.
"""
import sys, os

F = "app.py"
if not os.path.exists(F):
    print("ERROR: app.py not found — run from the repo root.")
    sys.exit(1)

s = open(F, encoding="utf-8").read()
reps = [
    ("if len(g) < 22 or len(s) < 22:", "if len(g) < 12 or len(s) < 12:"),
    ("if len(cl) < 22:",               "if len(cl) < 12:"),
]
changed = 0
for old, new in reps:
    if old in s:
        s = s.replace(old, new)
        changed += 1
    elif new in s:
        pass  # already lowered
    else:
        print("WARN: pattern not found (skipped): %r" % old)

if changed:
    open(F, "w", encoding="utf-8").write(s)
    print("warm-up lowered to 12 bars (%d edits)" % changed)
else:
    print("already at 12 bars — nothing to change")

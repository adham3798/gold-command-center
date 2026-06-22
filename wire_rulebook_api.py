#!/usr/bin/env python3
"""
Idempotently add the /api/rulebook endpoint to app.py.

Run from the repo root:  python3 wire_rulebook_api.py
Safe to run repeatedly — it only appends the route once.

The endpoint powers the new "Rulebook" tab. It is a read-only snapshot that
combines the layers from the Gold Master Rulebook into a single Confluence Gate
score and a TRADE / WAIT / STAND DOWN verdict:

  - bias        -> from build_day(today)['signal']  (LONG/SHORT/NEUTRAL)
  - price       -> live spot (gold-api.com) with sheet fallback
  - level       -> nearest pivot from _pivots_from() + distance
  - news        -> next USD high-impact event + 15-min blackout (news.get_for)
  - session     -> London / NY overlap / Asia window (UTC clock)
  - astro       -> moon phase + numerology day-number (3/6/9 power day)
  - gate        -> 0..8 score, grade A/B/C
  - verdict     -> TRADE (A) / WAIT (B) / STAND DOWN (hard gate or no edge)

It reuses helpers already defined in app.py (build_day, _trading_day,
_pivots_from, DATA, news, req, jsonify, datetime, pytz) so it needs no new
config and adds no new dependency.
"""
import os, sys

MARKER = "/api/rulebook"
ROUTE = r'''

# ── RULEBOOK API (confluence gate + verdict for the Rulebook tab) ───────────────
def _rb_session(now_utc):
    """Classify the current trading session from the UTC clock (summer-time map).
    Returns (name, grade, allowed). 'allowed' = a primary trend window per the
    rulebook (London / overlap / NY). Asia + rollover = reversion-only -> False."""
    h = now_utc.hour + now_utc.minute / 60.0
    if 7 <= h < 12:
        return ('London', 'B', True)
    if 12 <= h < 16:
        return ('London-NY Overlap', 'A', True)
    if 16 <= h < 21:
        return ('New York', 'B', True)
    if 21 <= h < 23:
        return ('Thin / rollover', 'D', False)
    return ('Asia (Tokyo)', 'C', False)


def _rb_news(et_today, now_utc):
    """Next USD high-impact event + 15-min blackout flag, from the news cache.
    Event times are stored as HH:MM US-Eastern; convert to UTC to compare."""
    out = {'blackout': False, 'next': None, 'today_count': 0, 'events': []}
    try:
        try:
            et_tz = pytz.timezone('America/New_York')
        except Exception:
            et_tz = None
        evs = news.get_for(et_today) or []
        out['today_count'] = len(evs)
        now_ts = now_utc.timestamp()
        soonest = None
        for ev in evs:
            t = str(ev.get('time') or '')
            epoch = None
            mins = None
            if ':' in t and et_tz is not None:
                try:
                    hh, mm = (int(x) for x in t.split(':')[:2])
                    y, mo, d = (int(x) for x in et_today.split('-'))
                    naive = datetime(y, mo, d, hh, mm)
                    et_dt = et_tz.localize(naive)
                    epoch = et_dt.timestamp()
                    mins = (epoch - now_ts) / 60.0
                    if -15 <= mins <= 15:
                        out['blackout'] = True
                except Exception:
                    pass
            row = {'time': t, 'title': ev.get('title', ''),
                   'impact': ev.get('impact', ''),
                   'epoch': int(epoch) if epoch else None,
                   'minutes': round(mins) if mins is not None else None}
            out['events'].append(row)
            if mins is not None and mins >= -15 and (soonest is None or mins < soonest['minutes']):
                soonest = row
        out['next'] = soonest
    except Exception:
        pass
    return out


@app.route('/api/rulebook')
def api_rulebook():
    out = {'status': 'ok'}
    try:
        now_utc = datetime.now(pytz.utc)
        try:
            et_today = datetime.now(pytz.timezone('America/New_York')).strftime('%Y-%m-%d')
        except Exception:
            et_today = _trading_day()
        today = _trading_day()
        day = build_day(today) or {}

        # ── bias from the daily model signal ──
        sig = (day.get('signal') or 'WAIT').upper()
        if 'BUY' in sig:
            bias = 'LONG'
        elif 'SELL' in sig:
            bias = 'SHORT'
        else:
            bias = 'NEUTRAL'
        market_closed = bool(day.get('market_closed'))

        # ── live price (spot) with sheet fallback ──
        price = None
        try:
            g = req.get('https://api.gold-api.com/price/XAU', timeout=6).json()
            price = float(g.get('price') or 0) or None
        except Exception:
            price = None
        days_sorted = sorted(DATA.get('prices', {}))
        last = DATA['prices'][days_sorted[-1]] if days_sorted else None
        if price is None and last:
            price = last.get('close')

        # ── nearest pivot level ──
        level = {'nearest': None, 'price': None, 'dist': None, 'dist_pct': None, 'at_level': False}
        if last and None not in (last.get('high'), last.get('low'), last.get('close')) and price:
            piv = _pivots_from(last)
            nm, lp = min(piv.items(), key=lambda kv: abs(price - kv[1]))
            dist = abs(price - lp)
            dist_pct = dist / price * 100 if price else None
            level = {'nearest': nm, 'price': round(lp, 2), 'dist': round(dist, 2),
                     'dist_pct': round(dist_pct, 3) if dist_pct is not None else None,
                     'at_level': bool(dist_pct is not None and dist_pct <= 0.12)}

        # ── session + news ──
        session = _rb_session(now_utc)
        sess = {'name': session[0], 'grade': session[1], 'allowed': session[2]}
        news_block = _rb_news(et_today, now_utc)

        # ── astro overlay ──
        dn = day.get('day_number')
        phase = (day.get('phase') or '')
        pl = phase.lower()
        moon_event = 'New Moon' if 'new' in pl else ('Full Moon' if 'full' in pl else None)
        power = dn in (3, 6, 9)
        watch = bool(moon_event) or power
        astro = {'day_number': dn, 'power': power, 'phase': phase,
                 'emoji': day.get('phase_emoji', ''), 'moon_event': moon_event, 'watch': watch}

        # ── confluence gate (0..8) ──
        bd = []
        s_level = 2 if level['at_level'] else 0
        bd.append({'label': 'Price at a ranked level', 'pts': s_level, 'max': 2})
        s_bias = 2 if bias in ('LONG', 'SHORT') else 0
        bd.append({'label': 'Directional daily bias (%s)' % bias, 'pts': s_bias, 'max': 2})
        s_sess = 2 if (sess['allowed'] and not news_block['blackout'] and not market_closed) else 0
        bd.append({'label': 'Active session, clear of news', 'pts': s_sess, 'max': 2})
        s_mtf = 1 if day.get('with_trend') else 0
        bd.append({'label': 'Multi-timeframe alignment', 'pts': s_mtf, 'max': 1})
        s_astro = 1 if watch else 0
        bd.append({'label': 'Astro confluence (bonus)', 'pts': s_astro, 'max': 1})
        score = s_level + s_bias + s_sess + s_mtf + s_astro
        grade = 'A' if score >= 6 else ('B' if score >= 4 else 'C')

        # ── verdict ──
        if market_closed:
            verdict = {'state': 'STAND DOWN', 'reason': 'Market closed (%s)' % (day.get('closed_reason') or 'weekend/holiday')}
        elif news_block['blackout']:
            verdict = {'state': 'STAND DOWN', 'reason': 'High-impact news blackout (±15 min)'}
        elif grade == 'A':
            verdict = {'state': 'TRADE', 'reason': 'A-grade confluence — execute the valid setup'}
        elif grade == 'B':
            verdict = {'state': 'WAIT', 'reason': 'B-grade — only A-setup at reduced size, or skip'}
        else:
            verdict = {'state': 'STAND DOWN', 'reason': 'No edge (score %d/8) — walk away' % score}

        out.update({
            'as_of_utc': int(now_utc.timestamp()),
            'trading_day': today,
            'bias': bias, 'signal': sig, 'confidence': day.get('confidence'),
            'market_closed': market_closed,
            'price': round(price, 2) if price else None,
            'level': level, 'session': sess, 'news': news_block, 'astro': astro,
            'gate': {'score': score, 'max': 8, 'grade': grade, 'breakdown': bd},
            'verdict': verdict,
        })
    except Exception as e:
        out = {'status': 'error', 'message': str(e)}
    return jsonify(out)
# ── END RULEBOOK API ────────────────────────────────────────────────────────────
'''


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "app.py"
    if not os.path.exists(path):
        print("ERROR: %s not found (run from the repo root)" % path); sys.exit(1)
    src = open(path, encoding="utf-8").read()
    if MARKER in src:
        print("• /api/rulebook already present — nothing to do.")
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(ROUTE)
    print("✓ Added /api/rulebook endpoint to %s" % path)


if __name__ == "__main__":
    main()

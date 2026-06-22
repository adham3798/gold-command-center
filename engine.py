# -*- coding: utf-8 -*-
"""
ADHAM-style prediction engine (Python port of the ADHAM SYSTEM scoring logic).

Produces a daily directional signal from:
  - Astrology  (Moon Sign, Sun Sign, Cycle Stage, Moon Phase  -> ZODIAC_DB biases)
  - Transit    (retrogrades, eclipses, Full/New Moon, conjunctions, ingresses)
  - Day Number (1-9 numerology; 3, 6, 9 are the strongest "power" numbers)
  - History    (Moon Sign x Cycle Stage historical win-rate from local price data)
  - Price      (layered only where OHLC exists: MTF structure / pivots)

For FUTURE days (no price) the signal is astro + transit + day-number + history.
For PAST days we also know the realized Direction, so the caller can mark win/loss.

------------------------------------------------------------------------------
FIXES (vs original) — see CHANGES.md:
  1. POWER_NUMBERS corrected to {3,6,9} to match the documented 3/6/9 rule
     (was {3,7,9}); day_number_weight retuned so 6 is a power day, 7 is not.
  2. Scoring is now NORMALISED: every component is scaled to [-1,1] first, then
     blended with weights that always sum to 1.0, then * day multiplier. This
     removes the old raw/25 saturation where STRONG signals fired far too easily.
  3. NO LOOK-AHEAD: moon_score no longer takes the realized close direction.
     The TREND bias now follows only price *structure* (MTF momentum), which is
     known before the close — so a backtest of compute_signal can't see the answer.
  4. MTF is folded INTO the weighted blend (weights re-normalised) instead of
     being added on top, so price structure has a consistent, bounded influence.
------------------------------------------------------------------------------
"""
from datetime import datetime

# ───────────────────────── ZODIAC DATABASE (from ADHAM) ────────────────────────
ZODIAC_DB = {
    'Aries':      {'gender':'MALE',  'nature':'MOVABLE',  'keyword':'START',  'bias':'BREAKOUT',     'stageNum':1},
    'Taurus':     {'gender':'FEMALE','nature':'FIXED',    'keyword':'BUILD',  'bias':'ACCUMULATION', 'stageNum':2},
    'Gemini':     {'gender':'MALE',  'nature':'FINISHER', 'keyword':'MOVE',   'bias':'VOLATILE',     'stageNum':3},
    'Cancer':     {'gender':'FEMALE','nature':'MOVABLE',  'keyword':'START',  'bias':'EMOTIONAL',    'stageNum':1},
    'Leo':        {'gender':'MALE',  'nature':'FIXED',    'keyword':'BUILD',  'bias':'TREND',        'stageNum':2},
    'Virgo':      {'gender':'FEMALE','nature':'FINISHER', 'keyword':'FINISH', 'bias':'REVERSAL',     'stageNum':3},
    'Libra':      {'gender':'MALE',  'nature':'MOVABLE',  'keyword':'START',  'bias':'RANGE',        'stageNum':1},
    'Scorpio':    {'gender':'FEMALE','nature':'FIXED',    'keyword':'BUILD',  'bias':'SHARP MOVE',   'stageNum':2},
    'Sagittarius':{'gender':'MALE',  'nature':'FINISHER', 'keyword':'FINISH', 'bias':'EXPANSION',    'stageNum':3},
    'Capricorn':  {'gender':'FEMALE','nature':'MOVABLE',  'keyword':'START',  'bias':'TREND',        'stageNum':1},
    'Aquarius':   {'gender':'MALE',  'nature':'FIXED',    'keyword':'BUILD',  'bias':'UNEXPECTED',   'stageNum':2},
    'Pisces':     {'gender':'FEMALE','nature':'FINISHER', 'keyword':'FINISH', 'bias':'EXHAUSTION',   'stageNum':3},
}

# ───────────────────────── TRANSIT DATA (2026, from ADHAM) ──────────────────────
RETRO_DB = [
    {'e':'Chiron Direct','d':'1/2/2026'},{'e':'Uranus Direct','d':'2/4/2026'},
    {'e':'Mercury Retrograde','d':'2/26/2026'},{'e':'Jupiter Direct','d':'3/11/2026'},
    {'e':'Mercury Direct','d':'3/20/2026'},{'e':'Pluto Retrograde','d':'5/6/2026'},
    {'e':'Mercury Retrograde','d':'6/29/2026'},{'e':'Neptune Retrograde','d':'7/7/2026'},
    {'e':'Mercury Direct','d':'7/23/2026'},{'e':'Saturn Retrograde','d':'7/26/2026'},
    {'e':'Chiron Retrograde','d':'8/3/2026'},{'e':'Uranus Retrograde','d':'9/10/2026'},
    {'e':'Venus Retrograde','d':'10/3/2026'},{'e':'Pluto Direct','d':'10/16/2026'},
    {'e':'Mercury Retrograde','d':'10/24/2026'},{'e':'Mercury Direct','d':'11/13/2026'},
    {'e':'Venus Direct','d':'11/14/2026'},{'e':'Saturn Direct','d':'12/10/2026'},
    {'e':'Neptune Direct','d':'12/12/2026'},{'e':'Jupiter Retrograde','d':'12/13/2026'},
]
MOON_DB2 = [
    {'e':'Full Moon','d':'1/3/2026'},{'e':'New Moon','d':'1/18/2026'},{'e':'Full Moon','d':'2/1/2026'},
    {'e':'New Moon','d':'2/17/2026'},{'e':'Solar Eclipse','d':'2/17/2026'},{'e':'Lunar Eclipse','d':'3/3/2026'},
    {'e':'Full Moon','d':'3/3/2026'},{'e':'New Moon','d':'3/19/2026'},{'e':'Full Moon','d':'4/2/2026'},
    {'e':'New Moon','d':'4/17/2026'},{'e':'Full Moon','d':'5/1/2026'},{'e':'New Moon','d':'5/16/2026'},
    {'e':'Full Moon','d':'5/31/2026'},{'e':'New Moon','d':'6/15/2026'},{'e':'Full Moon','d':'6/29/2026'},
    {'e':'New Moon','d':'7/14/2026'},{'e':'Full Moon','d':'7/29/2026'},{'e':'New Moon','d':'8/12/2026'},
    {'e':'Solar Eclipse','d':'8/12/2026'},{'e':'Lunar Eclipse','d':'8/28/2026'},{'e':'Full Moon','d':'8/28/2026'},
    {'e':'New Moon','d':'9/11/2026'},{'e':'Full Moon','d':'9/26/2026'},{'e':'New Moon','d':'10/10/2026'},
    {'e':'Full Moon','d':'10/26/2026'},{'e':'New Moon','d':'11/9/2026'},{'e':'Full Moon','d':'11/24/2026'},
    {'e':'New Moon','d':'12/9/2026'},{'e':'Full Moon','d':'12/24/2026'},
]
ASPECT_DB = [
    {'e':'Sun Conjunction Venus','d':'1/6/2026'},{'e':'Sun Conjunction Mars','d':'1/9/2026'},
    {'e':'Sun Conjunction Mercury','d':'1/21/2026'},{'e':'Sun Conjunction Pluto','d':'1/23/2026'},
    {'e':'Sun Conjunction Node','d':'2/27/2026'},{'e':'Sun Conjunction Mercury','d':'3/7/2026'},
    {'e':'Sun Conjunction Neptune','d':'3/22/2026'},{'e':'Sun Conjunction Saturn','d':'3/25/2026'},
    {'e':'Sun Conjunction Chiron','d':'4/16/2026'},{'e':'Sun Conjunction Mercury','d':'5/14/2026'},
    {'e':'Sun Conjunction Uranus','d':'5/22/2026'},{'e':'Sun Conjunction Mercury','d':'7/13/2026'},
    {'e':'Sun Conjunction Jupiter','d':'7/29/2026'},{'e':'Sun Conjunction Mercury','d':'8/27/2026'},
    {'e':'Sun Conjunction Venus','d':'10/24/2026'},{'e':'Sun Conjunction Mercury','d':'11/4/2026'},
]
INGRESS_DB = [
    {'e':'Mercury enters Capricorn','d':'1/1/2026'},{'e':'Venus enters Aquarius','d':'1/17/2026'},
    {'e':'Mars enters Aquarius','d':'1/23/2026'},{'e':'Neptune enters Aries','d':'1/26/2026'},
    {'e':'Saturn enters Aries','d':'2/14/2026'},{'e':'Venus enters Aries','d':'3/6/2026'},
    {'e':'Mars enters Aries','d':'4/9/2026'},{'e':'Uranus enters Gemini','d':'4/26/2026'},
    {'e':'Jupiter enters Leo','d':'6/30/2026'},{'e':'Chiron enters Taurus','d':'6/19/2026'},
    {'e':'Mars enters Cancer','d':'8/11/2026'},{'e':'Mars enters Leo','d':'9/28/2026'},
    {'e':'Mars enters Virgo','d':'11/25/2026'},
]

SUN_DB = [
    {'e':'Sun enters Aquarius','d':'1/20/2026'},{'e':'Sun enters Pisces','d':'2/18/2026'},
    {'e':'Sun enters Aries','d':'3/20/2026'},{'e':'Sun enters Taurus','d':'4/20/2026'},
    {'e':'Sun enters Gemini','d':'5/21/2026'},{'e':'Sun enters Cancer','d':'6/21/2026'},
    {'e':'Sun enters Leo','d':'7/22/2026'},{'e':'Sun enters Virgo','d':'8/23/2026'},
    {'e':'Sun enters Libra','d':'9/23/2026'},{'e':'Sun enters Scorpio','d':'10/23/2026'},
    {'e':'Sun enters Sagittarius','d':'11/22/2026'},{'e':'Sun enters Capricorn','d':'12/21/2026'},
]

# FIX 1: power numbers are 3/6/9 (Tesla / ADHAM rule), matching the docs.
POWER_NUMBERS = {3, 6, 9}


# ───────────────────────── helpers ─────────────────────────
def _parse(ds):
    """Parse 'M/D/YYYY' (transit data) or 'YYYY-MM-DD' (app dates)."""
    if not ds:
        return None
    ds = str(ds).strip()
    for fmt in ('%m/%d/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(ds, fmt)
        except ValueError:
            continue
    return None

def _days_diff(a, b):
    return (b - a).days

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ───────────────────────── transit analysis ────────────────────────
def get_active_retrogrades(ds):
    today = _parse(ds)
    if not today:
        return []
    status = {}
    for e in RETRO_DB:
        d = _parse(e['d'])
        if not d or d > today:
            continue
        planet = e['e'].split(' ')[0]
        status[planet] = 'Retrograde' if 'Retrograde' in e['e'] else 'Direct'
    return [p for p, s in status.items() if s == 'Retrograde']

def get_today_transits(ds, window=3):
    today = _parse(ds)
    if not today:
        return []
    out = []
    for e in (RETRO_DB + MOON_DB2 + INGRESS_DB + ASPECT_DB):
        d = _parse(e['d'])
        if d and abs(_days_diff(today, d)) <= window:
            out.append({'e': e['e'], 'd': e['d'], 'diff': _days_diff(today, d)})
    out.sort(key=lambda x: abs(x['diff']))
    return out

def get_sun_sign(ds):
    """Sun sign for a date, from SUN_DB ingress dates (Capricorn before Jan 20)."""
    today = _parse(ds)
    if not today:
        return None
    current = 'Capricorn'
    for e in SUN_DB:
        d = _parse(e['d'])
        if d and d <= today:
            current = e['e'].replace('Sun enters', '').strip()
    return current

def mtf_score(h1, h4):
    """Multi-timeframe score (-30..+30) from recent 1H/4H candles (ADHAM-style)."""
    score = 0
    if h4:
        last = h4[-3:]
        bull = sum(1 for c in last if (c.get('close') or 0) >= (c.get('open') or 0))
        score += 15 if bull >= 2 else -15
    if h1:
        c = h1[-1]
        d, t = c.get('direction'), c.get('trend')
        if d == 'BULL' or t == 'BUY':
            score += 10
        elif d == 'BEAR' or t == 'SELL':
            score -= 10
    return _clamp(score, -30, 30)

def score_transits(ds):
    """Returns (score clamped -30..+30, list of signal strings)."""
    retros = get_active_retrogrades(ds)
    transits = get_today_transits(ds)
    score = 0
    signals = []
    if 'Mercury' in retros: score -= 10; signals.append('Mercury Rx: avoid news trades, fog')
    if 'Venus'   in retros: score -= 8;  signals.append('Venus Rx: gold may be choppy')
    if 'Pluto'   in retros: score -= 5;  signals.append('Pluto Rx: hidden pressure on gold')
    if 'Saturn'  in retros: score -= 7;  signals.append('Saturn Rx: bearish pressure')
    if 'Jupiter' in retros: score += 5;  signals.append('Jupiter Rx: expansion paused')

    for t in transits:
        if abs(t['diff']) > 1:
            continue
        e = t['e']
        if 'Full Moon' in e:               score -= 5;  signals.append('Full Moon: peak, reversal risk')
        if 'New Moon' in e:                score += 5;  signals.append('New Moon: fresh start, buy bias')
        if 'Solar Eclipse' in e:           score -= 15; signals.append('Solar Eclipse: NO TRADE - extreme volatility')
        if 'Lunar Eclipse' in e:           score -= 15; signals.append('Lunar Eclipse: NO TRADE - extreme volatility')
        if 'Sun Conjunction Jupiter' in e: score += 12; signals.append('Sun-Jupiter: strong bullish expansion')
        if 'Sun Conjunction Saturn' in e:  score -= 10; signals.append('Sun-Saturn: bearish contraction')
        if 'Sun Conjunction Mars' in e:    score += 8;  signals.append('Sun-Mars: high energy, sharp moves')
        if 'Sun Conjunction Pluto' in e:   score -= 8;  signals.append('Sun-Pluto: intense pressure, reversal')
        if 'Sun Conjunction Venus' in e:   score += 6;  signals.append('Sun-Venus: gold supportive')
        if 'Sun Conjunction Neptune' in e: score -= 6;  signals.append('Sun-Neptune: confusion, false moves')
        if 'Jupiter enters' in e:          score += 8;  signals.append('Jupiter ingress: expansion energy')
        if 'Saturn enters' in e:           score -= 8;  signals.append('Saturn ingress: contraction energy')
        if 'Mars enters' in e:             score += 5;  signals.append('Mars ingress: momentum shift')
    return _clamp(score, -30, 30), signals


# ───────────────────────── astro scores ─────────────────────────
MOON_BULL = ('Aries', 'Leo', 'Sagittarius', 'Cancer')
MOON_BEAR = ('Capricorn', 'Scorpio', 'Virgo')
SUN_BULL  = ('Aries', 'Leo', 'Sagittarius')
SUN_BEAR  = ('Capricorn', 'Scorpio', 'Virgo')

def moon_score(sign, cycle_stage, struct_dir=None):
    """Moon-sign score.

    FIX 3: `struct_dir` is the price-STRUCTURE direction (+1/-1) from the MTF /
    momentum read — NOT the realized close direction. It is known before the
    close, so using it for the TREND bias does not leak the outcome into a
    backtest. Pass None when no structure is available (pure astro forecast).
    """
    z = ZODIAC_DB.get(sign, {})
    s = 0
    if sign in MOON_BULL:   s += 15
    elif sign in MOON_BEAR: s -= 15
    bias = z.get('bias')
    if bias == 'REVERSAL':  s -= 5
    if bias == 'TREND' and struct_dir == 1:  s += 8
    if bias == 'TREND' and struct_dir == -1: s -= 8
    if bias == 'SHARP MOVE': s += 5 if s >= 0 else -5
    if cycle_stage == 'FINISH':
        s *= 0.7
    return s

def sun_score(sun_sign):
    z = ZODIAC_DB.get(sun_sign, {})
    s = 0
    if sun_sign in SUN_BULL:   s += 10
    elif sun_sign in SUN_BEAR: s -= 10
    bias = z.get('bias')
    if bias == 'EXPANSION':    s += 8
    if bias == 'REVERSAL':     s -= 8
    if bias == 'ACCUMULATION': s += 5
    if bias == 'EXHAUSTION':   s -= 8
    return s

def day_number_weight(dn):
    """Magnitude multiplier from the 1-9 day number.
    REVIEW 2026-06-22: the 3/6/9 'power day' edge does NOT hold on verified spot data
    (day 9 was the WEAKEST at 48.7%, 3/6 middling, move-size identical to other days).
    Neutralized to 1.0 so the day number no longer amplifies the direction/conviction.
    `power_day` is kept downstream as a context LABEL only — never a size or direction
    driver. See ASTRO_EDGE_FINDINGS.md and SYSTEM_REVIEW_2026-06-22.md."""
    return 1.0

# moon-phase reliability (for confidence) — keys normalised to lower-case
PHASE_RELIABILITY = {
    'full moon':85, 'new moon':80, 'first quarter':75, 'third quarter':75, 'last quarter':75,
    'waxing gibbous':65, 'waning gibbous':65, 'waxing crescent':50, 'waning crescent':45,
}

def phase_score(phase):
    p = str(phase).lower().strip()
    for k, v in PHASE_RELIABILITY.items():
        if k in p:
            return v
    return 60


def calc_confidence(today, history):
    """
    Port of ADHAM calcAndShowConf. `today` = dict(sign,stage,stage_num,day_number,gender,phase).
    `history` = list of past moon dicts (same keys). Returns (conf%, breakdown dict).
    3/6/9 power days get a small confidence boost.
    """
    if len(history) < 5:
        return 50, {'sign_stage':0, 'stage_num':0, 'phase':phase_score(today.get('phase')), 'day_num':0, 'note':'insufficient history'}
    sign, stage = today.get('sign'), today.get('stage')
    sn, dn, g = today.get('stage_num'), today.get('day_number'), today.get('gender')
    f1m = [r for r in history if r.get('sign') == sign and r.get('stage') == stage]
    f1s = min(100, len(f1m) / 8 * 100)
    f2m = [r for r in history if r.get('stage_num') == sn and r.get('sign') == sign]
    f2s = min(100, len(f2m) / 6 * 100)
    f3s = phase_score(today.get('phase'))
    f4m = [r for r in history if r.get('day_number') == dn and r.get('gender') == g]
    f4s = min(100, len(f4m) / 4 * 100)
    conf = f1s * .30 + f2s * .25 + f3s * .25 + f4s * .20
    # REVIEW 2026-06-22: removed the +8 power-day conviction boost — 3/6/9 carries no
    # directional edge on verified spot data, so it must not inflate confidence either.
    return round(conf), {
        'sign_stage': len(f1m), 'stage_num': len(f2m),
        'phase': f3s, 'day_num': len(f4m), 'power_day': dn in POWER_NUMBERS,
    }


# ───────────────────────── main per-day signal ─────────────────────────
def signal_label(bias_pct):
    """bias_pct in -100..+100 -> (signal, css-ish key)."""
    if bias_pct >= 50:  return 'STRONG BUY', 'strong-buy'
    if bias_pct >= 16:  return 'BUY', 'buy'
    if bias_pct <= -50: return 'STRONG SELL', 'strong-sell'
    if bias_pct <= -16: return 'SELL', 'sell'
    if abs(bias_pct) >= 6: return 'WAIT', 'wait'
    return 'NO TRADE', 'no-trade'


# FIX 2/4: component normalisation constants (each raw component is divided by
# its natural scale to land in roughly [-1,1] before the weighted blend).
_NORM = {'hist': 30.0, 'moon': 23.0, 'transit': 30.0, 'sun': 23.0, 'mtf': 30.0}
# blend weights — two sets, each summing to 1.0 (with vs without MTF price structure)
_W_NO_MTF = {'hist': 0.40, 'moon': 0.30, 'transit': 0.18, 'sun': 0.12}
_W_MTF    = {'hist': 0.30, 'moon': 0.24, 'transit': 0.14, 'sun': 0.10, 'mtf': 0.22}


def signphase_bias(sign_counts, phase_counts, overall_counts, min_n=6):
    """NEW direction rule — the one the spot-data study actually supports.

    The edge lives in the MOON SIGN and MOON PHASE, not the day number. This scores how
    the current sign and phase have historically biased gold RELATIVE to its own drift
    (so it isolates the astrological signal, not 'gold went up'). All counts are
    point-in-time (prior days only), so there is no look-ahead.

    Returns (bias_pct -100..100, p_up 0-1, detail dict). p_up>0.5 leans long.
    """
    def rate(c):
        c = c or {}
        b, r = c.get('bull', 0), c.get('bear', 0)
        t = b + r
        return (b / t, t) if t else (None, 0)

    o_p, _ = rate(overall_counts)
    s_p, s_t = rate(sign_counts)
    p_p, p_t = rate(phase_counts)
    if o_p is None:
        o_p = 0.5
    edge, used = 0.0, False
    if s_p is not None and s_t >= min_n:
        edge += 0.6 * (s_p - o_p); used = True
    if p_p is not None and p_t >= min_n:
        edge += 0.4 * (p_p - o_p); used = True
    p_up = o_p + edge
    bias = _clamp((p_up - 0.5) * 350, -100, 100)   # ~0.546 -> +16 (BUY), ~0.454 -> -16 (SELL)
    return round(bias, 1), round(p_up, 3), {
        'sign_bull': None if s_p is None else round(s_p, 3), 'sign_n': s_t,
        'phase_bull': None if p_p is None else round(p_p, 3), 'phase_n': p_t,
        'overall_bull': round(o_p, 3), 'used': used,
    }


def compute_signal(date_str, moon, hist_counts, history, price=None, mtf=None,
                   sign_counts=None, phase_counts=None, overall_counts=None):
    """
    Full ADHAM-style daily signal.

    moon        : dict for this date (sign, stage, stage_num, day_number, gender, phase, sun_sign)
    hist_counts : dict {'bull':int,'bear':int} from Moon-Sign x Cycle-Stage historical match
                  (CALLER MUST build this from days STRICTLY BEFORE date_str — point-in-time)
    history     : list of past moon dicts (for confidence)
    price       : optional dict (open,high,low,close,direction). NOTE: only the
                  realized direction is *never* fed into the signal anymore (no leak).
    mtf         : optional multi-timeframe structure score (-30..+30) from prior/forming
                  candles. Used both as a forecast component and as the TREND-bias direction.

    Returns a dict with the signal, bias, all component scores and detail bars.
    """
    if not moon:
        return None
    sign  = moon.get('sign')
    stage = moon.get('stage')
    dn    = moon.get('day_number')
    sun   = moon.get('sun_sign')

    # FIX 3: TREND bias follows price STRUCTURE (mtf), never the realized close.
    struct_dir = None
    if mtf is not None:
        struct_dir = 1 if mtf > 0 else (-1 if mtf < 0 else None)

    mS = moon_score(sign, stage, struct_dir)
    sS = sun_score(sun)
    tScore, tSigs = score_transits(date_str)

    # historical directional score from Moon x Stage win-rate (point-in-time counts)
    bull, bear = hist_counts.get('bull', 0), hist_counts.get('bear', 0)
    total = bull + bear
    if total >= 2:
        bull_pct = bull / total * 100
        bear_pct = bear / total * 100
        histScore = (bull_pct - bear_pct) / 100 * 30      # -30..+30
    else:
        bull_pct = bear_pct = 0
        histScore = 0

    # FIX 2/4: normalise each component to ~[-1,1], then blend with weights that sum to 1.
    nHist = _clamp(histScore / _NORM['hist'], -1, 1)
    nMoon = _clamp(mS       / _NORM['moon'], -1, 1)
    nTran = _clamp(tScore   / _NORM['transit'], -1, 1)
    nSun  = _clamp(sS       / _NORM['sun'],  -1, 1)

    if mtf is not None:
        nMtf = _clamp(mtf / _NORM['mtf'], -1, 1)
        w = _W_MTF
        blend = nHist*w['hist'] + nMoon*w['moon'] + nTran*w['transit'] + nSun*w['sun'] + nMtf*w['mtf']
    else:
        w = _W_NO_MTF
        blend = nHist*w['hist'] + nMoon*w['moon'] + nTran*w['transit'] + nSun*w['sun']

    # 3/6/9 power-day amplifier on magnitude, then map [-1,1] -> [-100,100]
    dmult = day_number_weight(dn)
    bias_pct = round(_clamp(blend * dmult * 100, -100, 100), 1)
    bias_raw = round(blend * dmult, 3)

    retros = get_active_retrogrades(date_str)
    transits_today = [t for t in get_today_transits(date_str) if abs(t['diff']) <= 1]

    # ── NEW DIRECTION RULE (opt-in): when point-in-time sign/phase counts are supplied,
    #    the moon SIGN + PHASE rule decides direction (it beats the old blend on spot data:
    #    ~55% vs ~45%). The old blend stays the fallback when counts are absent. ──
    method = 'blend'
    sp_pup = None
    sp_detail = None
    if sign_counts is not None and phase_counts is not None and overall_counts is not None:
        sp_bias, sp_pup, sp_detail = signphase_bias(sign_counts, phase_counts, overall_counts)
        if any('Eclipse' in t['e'] for t in transits_today):   # risk-off near eclipses
            sp_bias = 0.0
            sp_detail['eclipse_standaside'] = True
        bias_pct = round(sp_bias, 1)
        bias_raw = round(sp_bias / 100.0, 3)
        method = 'signphase'

    sig, key = signal_label(bias_pct)

    if method == 'signphase':
        n = (sp_detail['sign_n'] + sp_detail['phase_n'])
        conf = int(_clamp(50 + abs(bias_pct) / 2.5 + min(15, n / 8.0), 0, 95))
        conf_break = {'method': 'signphase', 'sign_n': sp_detail['sign_n'],
                      'phase_n': sp_detail['phase_n'], 'p_up': sp_pup}
    else:
        conf, conf_break = calc_confidence(
            {'sign':sign,'stage':stage,'stage_num':moon.get('stage_num'),
             'day_number':dn,'gender':moon.get('gender'),'phase':moon.get('phase')},
            history)

    out = {
        'signal': sig, 'signal_key': key,
        'bias': bias_pct, 'bias_raw': bias_raw,
        'confidence': conf, 'conf_break': conf_break,
        'moon_score': round(mS, 1), 'sun_score': round(sS, 1),
        'transit_score': tScore, 'hist_score': round(histScore, 1),
        'day_number': dn, 'power_day': dn in POWER_NUMBERS, 'day_mult': dmult,
        'mtf_score': mtf,
        'bull_pct': round(bull_pct, 1), 'bear_pct': round(bear_pct, 1), 'matches': total,
        'zodiac_bias': ZODIAC_DB.get(sign, {}).get('bias', ''),
        'sun_bias': ZODIAC_DB.get(sun, {}).get('bias', ''),
        'retrogrades': retros,
        'transit_signals': tSigs,
        'transits_today': [t['e'] for t in transits_today],
        'method': method, 'p_up': sp_pup, 'sign_phase': sp_detail,
    }
    # win/loss is decided by the caller's take-profit model (did Low reach the
    # downside TP for SELL / High reach upside TP for BUY), not close-vs-open.
    return out

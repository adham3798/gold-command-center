# -*- coding: utf-8 -*-
from flask import Flask, render_template, jsonify, request, send_file
import pandas as pd
import json
from datetime import datetime
from calendar import monthrange
import os
import requests as req
import engine
import news
import notify

app = Flask(__name__)
import re, urllib.parse

# ── DATA SOURCE: live Google Sheet (spot OHLC, auto-updating) ──────────────────
SHEET_ID    = '12ynlr46bvHSJLnLGs5Z1SrhhlCj6_w7qO6YHMDBY7gs'
EXCEL_PATH  = r'C:\Users\PC-1\Downloads\gold price 1.xlsx'   # offline emergency fallback only
_HERE       = os.path.dirname(os.path.abspath(__file__))
TRADES_FILE = os.path.join(_HERE, 'trades.json')
# Portable offline snapshot: written after every successful sheet load, read when offline.
# Travels with the project (e.g. in the GitHub copy), so the app runs with no internet.
LOCAL_CACHE = os.path.join(_HERE, 'data_cache.json')
TG_SENT_FILE = os.path.join(_HERE, 'telegram_sent.json')   # remembers the last alerted date
DATA = {'prices': {}, 'moon': {}, 'signs': {}, 'phases': {}, 'h1': [], 'h4': [], 'forecast': {}}

# 4-hour candle index (built from DATA['h4']): for the per-day 4H trading plan
_H4_SORTED = []        # all 4H candles, time-ordered, each with 'date' + 'time'
_H4_BY_DAY = {}        # 'YYYY-MM-DD' -> [candles in order]
# 1-hour candle index (built from DATA['h1']): for the decision-day entry trigger
_H1_SORTED = []
_H1_BY_DAY = {}

def _sheet_csv(tab):
    return 'https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv&sheet=%s' % (
        SHEET_ID, urllib.parse.quote(tab))

def _read_tab(tab):
    return pd.read_csv(_sheet_csv(tab))

def _find_col(df, *names):
    """Find a column by name, tolerant of whitespace/newlines/case; falls back to substring."""
    norm = {re.sub(r'\s+', ' ', str(c)).strip().lower(): c for c in df.columns}
    for n in names:
        k = re.sub(r'\s+', ' ', n).strip().lower()
        if k in norm:
            return norm[k]
    for n in names:
        nk = n.strip().lower()
        for k, orig in norm.items():
            if nk in k:
                return orig
    return None

def _clean_sign(s):
    s = str(s)
    m = re.search(r'\(([^)]+)\)', s)
    return m.group(1).strip() if m else s.replace('Moon Sign', '').replace('Sun Sign', '').strip()

SIGN_EMOJI = {
    'Aries':'♈','Taurus':'♉','Gemini':'♊','Cancer':'♋',
    'Leo':'♌','Virgo':'♍','Libra':'♎','Scorpio':'♏',
    'Sagittarius':'♐','Capricorn':'♑','Aquarius':'♒','Pisces':'♓'
}
PHASE_EMOJI = {
    'new moon':'\U0001f311','waxing crescent':'\U0001f312','first quarter':'\U0001f313',
    'waxing gibbous':'\U0001f314','full moon':'\U0001f315','waning gibbous':'\U0001f316',
    'last quarter':'\U0001f317','third quarter':'\U0001f317','waning crescent':'\U0001f318'
}

def get_phase_emoji(phase_str):
    p = phase_str.lower()
    for k, v in PHASE_EMOJI.items():
        if k in p:
            return v
    return '\U0001f319'

def _load_candles(tab):
    """Load intraday candles (H1_DATA / H4_DATA) for the MTF price forecast."""
    df = _read_tab(tab)
    df.columns = [str(c).strip() for c in df.columns]
    out = []
    has_dir, has_trend = 'Direction' in df.columns, 'Trend' in df.columns
    for _, r in df.iterrows():
        try:
            o = float(r['Open']); c = float(r['Close'])
        except (ValueError, TypeError):
            continue
        out.append({
            'dt':    str(r.get('DateTime', '')),
            'open':  o, 'close': c,
            'high':  float(r['High']) if pd.notna(r.get('High')) else None,
            'low':   float(r['Low'])  if pd.notna(r.get('Low'))  else None,
            'direction': str(r['Direction']).strip().upper() if has_dir and pd.notna(r.get('Direction')) else None,
            'trend':     str(r['Trend']).strip().upper()     if has_trend and pd.notna(r.get('Trend'))   else None,
        })
    return out

def _fetch_h1_yahoo(rng='1mo'):
    """Recent 1-hour gold candles from Yahoo (GC=F futures). No API key needed.
       Returns [{dt,open,high,low,close,direction}, ...] oldest->newest, or None."""
    try:
        r = req.get('https://query1.finance.yahoo.com/v8/finance/chart/GC=F',
                    params={'interval': '1h', 'range': rng},
                    headers={'User-Agent': 'Mozilla/5.0'}, timeout=15).json()
        res = (r.get('chart', {}).get('result') or [None])[0]
        if not res:
            return None
        ts = res.get('timestamp') or []
        q = (res.get('indicators', {}).get('quote') or [{}])[0]
        o, h, l, c = q.get('open', []), q.get('high', []), q.get('low', []), q.get('close', [])
        out = []
        for i, t in enumerate(ts):
            try:
                oo, hh, ll, cc = o[i], h[i], l[i], c[i]
                if None in (oo, hh, ll, cc):
                    continue
                out.append({'dt': datetime.utcfromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S'),
                            'open': float(oo), 'high': float(hh), 'low': float(ll), 'close': float(cc),
                            'direction': 'BULL' if cc >= oo else 'BEAR', 'trend': None})
            except (IndexError, TypeError, ValueError):
                continue
        return out or None
    except Exception as e:
        print("Yahoo 1H fetch failed:", e)
        return None

def _fetch_h1_twelvedata():
    """Higher-accuracy spot XAU/USD 1H from Twelve Data IF env TWELVEDATA_KEY is set."""
    key = os.environ.get('TWELVEDATA_KEY')
    if not key:
        return None
    try:
        r = req.get('https://api.twelvedata.com/time_series',
                    params={'symbol': 'XAU/USD', 'interval': '1h', 'outputsize': 500,
                            'apikey': key, 'timezone': 'UTC'}, timeout=15).json()
        out = []
        for v in (r.get('values') or []):
            try:
                oo, cc = float(v['open']), float(v['close'])
                out.append({'dt': v['datetime'], 'open': oo, 'high': float(v['high']),
                            'low': float(v['low']), 'close': cc,
                            'direction': 'BULL' if cc >= oo else 'BEAR', 'trend': None})
            except (KeyError, ValueError, TypeError):
                continue
        out.sort(key=lambda x: x['dt'])
        return out or None
    except Exception as e:
        print("Twelve Data 1H fetch failed:", e)
        return None

def fetch_live_h1():
    """Fresh 1H gold candles to keep the dashboard current when the sheet's H1_DATA lags.
       Prefers Twelve Data spot (if a key is set), else free Yahoo GC=F futures."""
    return _fetch_h1_twelvedata() or _fetch_h1_yahoo()

def load_data():
    """Pull everything live from the Google Sheet (spot). Raises on fetch failure."""
    # ── GOLD PRICES (spot OHLC) ──
    gp = _read_tab('gold_price')
    gp.columns = [str(c).strip() for c in gp.columns]
    gp['Date'] = pd.to_datetime(gp['Date'], errors='coerce')
    for col in ['Open', 'High', 'Low', 'Close', 'Change', 'Range']:
        if col in gp.columns:
            gp[col] = pd.to_numeric(gp[col], errors='coerce')
    gp['Direction'] = gp['Direction'].astype(str).str.strip().str.upper()
    gp = gp.dropna(subset=['Date', 'Close']).sort_values('Date')
    prices = {}
    for _, r in gp.iterrows():
        prices[r['Date'].strftime('%Y-%m-%d')] = {
            'open':  round(float(r['Open']),  2) if pd.notna(r.get('Open'))   else None,
            'high':  round(float(r['High']),  2) if pd.notna(r.get('High'))   else None,
            'low':   round(float(r['Low']),   2) if pd.notna(r.get('Low'))    else None,
            'close': round(float(r['Close']), 2),
            'change':round(float(r['Change']),2) if pd.notna(r.get('Change')) else None,
            'rng':   round(float(r['Range']), 2) if pd.notna(r.get('Range'))  else None,
            'direction': r['Direction'],
        }

    # ── MOON_REAL (sun sign computed from date) ──
    mr = _read_tab('MOON_REAL')
    c_date   = _find_col(mr, 'Real Date', 'date')
    c_sign   = _find_col(mr, 'Clean Moon Sign', 'Moon Sign')
    c_phase  = _find_col(mr, 'Moon Phase (Lunar Phase)', 'Moon Phase')
    c_stage  = _find_col(mr, 'Cycle Stage')
    c_gender = _find_col(mr, 'Gender')
    c_snum   = _find_col(mr, 'Stage Number')
    c_dnum   = _find_col(mr, 'day number', 'Day Number')
    mr[c_date] = pd.to_datetime(mr[c_date], errors='coerce')
    mr[c_snum] = pd.to_numeric(mr[c_snum], errors='coerce')
    mr[c_dnum] = pd.to_numeric(mr[c_dnum], errors='coerce')
    mr = mr.dropna(subset=[c_date])
    moon = {}
    for _, r in mr.iterrows():
        d = r[c_date].strftime('%Y-%m-%d')
        phase = str(r[c_phase]).strip()
        moon[d] = {
            'sign':        _clean_sign(r[c_sign]),
            'sun_sign':    engine.get_sun_sign(d),
            'phase':       phase,
            'phase_emoji': get_phase_emoji(phase),
            'stage':       str(r[c_stage]).strip(),
            'gender':      str(r[c_gender]).strip(),
            'day_number':  int(r[c_dnum]) if pd.notna(r[c_dnum]) else None,
            'stage_num':   int(r[c_snum]) if pd.notna(r[c_snum]) else None,
        }

    # ── SIGN_LIBRARY ──
    sl = _read_tab('SIGN_LIBRARY'); sl.columns = [str(c).strip() for c in sl.columns]
    signs = {}
    for _, r in sl.iterrows():
        nm = str(r['Sign']).strip()
        if not nm or nm.lower() == 'nan':
            continue
        signs[nm] = {
            'gender': str(r['Gender']).strip(), 'nature': str(r['Nature']).strip(),
            'keyword': str(r['Keyword']).strip(), 'meaning': str(r['Meaning']).strip(),
            'market_bias': str(r['Market Bias']).strip(), 'emoji': SIGN_EMOJI.get(nm, '*'),
        }

    # ── MOON_PHASE_LIBRARY ──
    pl = _read_tab('MOON_PHASE_LIBRARY'); pl.columns = [str(c).strip() for c in pl.columns]
    phases = {}
    for _, r in pl.iterrows():
        nm = str(r['Moon Phase']).strip()
        if not nm or nm.lower() == 'nan':
            continue
        phases[nm] = {'mood': str(r['Market Mood']).strip(), 'meaning': str(r['Trading Meaning']).strip()}

    # ── intraday candles for MTF ──
    try:
        h1 = _load_candles('H1_DATA')
        h4 = _load_candles('H4_DATA')
    except Exception as e:
        print("Candle load skipped:", e); h1, h4 = DATA.get('h1', []), DATA.get('h4', [])

    # keep the 1-hour series CURRENT even if the sheet's H1_DATA tab lags: pull fresh
    # 1H gold candles from a live source and append the ones newer than the sheet's latest
    try:
        live = fetch_live_h1()
        if live:
            latest = max((str(c.get('dt', '')) for c in h1), default='')
            fresh = [c for c in live if str(c.get('dt', '')) > latest]
            if fresh:
                h1 = h1 + fresh
                print("Live 1H: added %d fresh candles (newest %s)" % (len(fresh), fresh[-1]['dt']))
    except Exception as e:
        print("Live 1H merge skipped:", e)

    # ── WEEKLY_FORECAST: your sheet's own Expected Direction (source of truth) ──
    try:
        forecast = _load_forecast()
    except Exception as e:
        print("Forecast load skipped:", e); forecast = DATA.get('forecast', {})

    DATA.update({'prices': prices, 'moon': moon, 'signs': signs, 'phases': phases,
                 'h1': h1, 'h4': h4, 'forecast': forecast})
    _MOVE_CACHE.clear()
    _MATCH_CACHE.clear()
    _MODEL_CACHE.clear()
    _compute_moves()
    _compute_weeks()
    _compute_reaction_stats()
    _compute_h4_index()
    print("Loaded from Google Sheet: %d price days, %d moon days, %d signs, %d h1, %d h4"
          % (len(prices), len(moon), len(signs), len(h1), len(h4)))
    _save_cache()

def _save_cache():
    """Write a portable offline snapshot of the live data to LOCAL_CACHE (JSON)."""
    try:
        snap = {k: DATA.get(k) for k in ('prices', 'moon', 'signs', 'phases', 'h1', 'h4', 'forecast')}
        with open(LOCAL_CACHE, 'w', encoding='utf-8') as f:
            json.dump(snap, f, ensure_ascii=False)
    except Exception as e:
        print("Cache save skipped:", e)

def _load_from_cache():
    """Load the offline snapshot from LOCAL_CACHE and rebuild all derived indexes."""
    with open(LOCAL_CACHE, 'r', encoding='utf-8') as f:
        snap = json.load(f)
    DATA.update({k: snap.get(k, DATA.get(k)) for k in ('prices', 'moon', 'signs', 'phases', 'h1', 'h4', 'forecast')})
    _MOVE_CACHE.clear(); _MATCH_CACHE.clear(); _MODEL_CACHE.clear()
    _compute_moves(); _compute_weeks(); _compute_reaction_stats(); _compute_h4_index()
    print("Loaded from OFFLINE cache: %d price days, %d h1, %d h4"
          % (len(DATA['prices']), len(DATA['h1']), len(DATA['h4'])))

def _load_forecast():
    """Read WEEKLY_FORECAST → {date: {direction, buy_score, sell_score, confidence,
    avg_bull, avg_bear, avg_range, transition}}. Stops at the non-dated live-map rows."""
    df = _read_tab('WEEKLY_FORECAST')
    df.columns = [str(c).strip() for c in df.columns]
    c_dir   = _find_col(df, 'Expected Direction')
    c_buy   = _find_col(df, 'Buy Score')
    c_sell  = _find_col(df, 'Sell Score')
    c_conf  = _find_col(df, 'Confidence')
    c_bull  = _find_col(df, 'Average Bull Move')
    c_bear  = _find_col(df, 'Average Bear Move')
    c_range = _find_col(df, 'Avg Range')
    c_trans = _find_col(df, 'Transition Type')
    def num(x):
        try:
            if pd.isna(x):
                return None
            v = float(str(x).replace('%', '').replace(',', '').strip())
            return None if v != v else v          # drop NaN
        except (ValueError, TypeError):
            return None
    out = {}
    for _, r in df.iterrows():
        d = pd.to_datetime(str(r.get('Date', '')), errors='coerce')
        if pd.isna(d):
            continue
        direction = str(r.get(c_dir, '')).strip().upper()
        if direction in ('', 'NAN'):
            continue
        out[d.strftime('%Y-%m-%d')] = {
            'direction':  direction,
            'buy_score':  num(r.get(c_buy)),
            'sell_score': num(r.get(c_sell)),
            'confidence': num(r.get(c_conf)),
            'avg_bull':   num(r.get(c_bull)),
            'avg_bear':   num(r.get(c_bear)),
            'avg_range':  num(r.get(c_range)),
            'transition': str(r.get(c_trans, '')).strip() if c_trans else '',
        }
    return out

def _pivots_from(y):
    """Pivot levels for the NEXT day from a day's OHLC dict y."""
    yH, yL, yC = y['high'], y['low'], y['close']; rng = yH - yL; PP = (yH + yL + yC) / 3
    return {'R3': 2*PP - yL + rng, 'R2': PP + rng, 'R1': 2*PP - yL, 'Yest High': yH,
            'PP': PP, 'Yest Low': yL, 'S1': 2*PP - yH, 'S2': PP - rng, 'S3': (2*PP - yH) - rng}

def _compute_weeks():
    """Net direction of each calendar week (first open -> last close)."""
    from collections import defaultdict
    wk = defaultdict(list)
    for d in sorted(DATA['prices']):
        wk[datetime.strptime(d, '%Y-%m-%d').isocalendar()[:2]].append(d)
    wd = {}
    for k, ds in wk.items():
        wd[k] = 1 if (DATA['prices'][ds[-1]]['close'] - DATA['prices'][ds[0]]['open']) >= 0 else -1
    DATA['week_dir'] = wd
    DATA['week_keys'] = sorted(wk.keys())

def _compute_reaction_stats():
    """Over all history: when price TOUCHES each level, how often does it HOLD (react)
    vs BREAK through? Resistance held = poked above but closed below; support held = poked
    below but closed above."""
    days = sorted(DATA['prices'])
    RES = {k: [0, 0] for k in ('R1', 'R2', 'R3', 'Yest High')}   # [touched, held]
    SUP = {k: [0, 0] for k in ('S1', 'S2', 'S3', 'Yest Low')}
    pp = [0, 0]; total = 0
    for i in range(1, len(days)):
        t = DATA['prices'][days[i]]; y = DATA['prices'][days[i-1]]
        if None in (t.get('high'), t.get('low'), y.get('high'), y.get('low'), y.get('close')):
            continue
        total += 1
        lv = _pivots_from(y); th, tl, tc = t['high'], t['low'], t['close']
        for k in RES:
            L = lv[k]
            if th >= L:
                RES[k][0] += 1; RES[k][1] += 1 if tc < L else 0
        for k in SUP:
            L = lv[k]
            if tl <= L:
                SUP[k][0] += 1; SUP[k][1] += 1 if tc > L else 0
        pp[1] += 1; pp[0] += 1 if (tl <= lv['PP'] <= th) else 0
    stats = {}
    for k, (tch, held) in RES.items():
        stats[k] = {'type': 'resistance', 'touch_pct': round(tch/total*100) if total else 0,
                    'hold_pct': round(held/tch*100) if tch else 0, 'n': tch}
    for k, (tch, held) in SUP.items():
        stats[k] = {'type': 'support', 'touch_pct': round(tch/total*100) if total else 0,
                    'hold_pct': round(held/tch*100) if tch else 0, 'n': tch}
    stats['PP'] = {'type': 'pivot', 'touch_pct': round(pp[0]/pp[1]*100) if pp[1] else 0, 'hold_pct': None, 'n': pp[0]}
    DATA['level_stats'] = stats

def _compute_moves():
    """Average historical move sizes used to project up/down targets per signal."""
    import statistics as st
    ups, downs, ranges = [], [], []
    for v in DATA['prices'].values():
        ch = v.get('change')
        if ch is not None:
            if v['direction'] == 'BULL' and ch > 0:  ups.append(ch)
            elif v['direction'] == 'BEAR' and ch < 0: downs.append(-ch)
        if v.get('high') and v.get('low'):
            ranges.append(v['high'] - v['low'])
    last = DATA['prices'][max(DATA['prices'])]['close'] if DATA['prices'] else 0
    # recent average RANGE (last 30 trading days) — current volatility, not the old low-price era
    recent_days = sorted(DATA['prices'])[-30:]
    recent_rng = [DATA['prices'][d]['high'] - DATA['prices'][d]['low']
                  for d in recent_days if DATA['prices'][d].get('high') and DATA['prices'][d].get('low')]
    DATA['moves'] = {
        'avg_up':    round(st.mean(ups), 2)    if ups    else 0,
        'avg_down':  round(st.mean(downs), 2)  if downs  else 0,
        'avg_range': round(st.mean(ranges), 2) if ranges else 0,
        'recent_range': round(st.mean(recent_rng), 2) if recent_rng else 0,
        'last_close': last,
    }

def _signstage_range(date_str):
    """Average daily RANGE for days matching this date's moon sign+stage (or None)."""
    m = DATA['moon'].get(date_str)
    if not m:
        return None
    return _matching_moves(date_str, m['sign'], m['stage']).get('avg_range')

def _trend_of(seq, n):
    """seq = list of (close, open) recent-last. Trend over the last n candles =
       direction of the net move; FLAT only when net is small vs the window's range
       (i.e. choppy / no real direction)."""
    seq = [(c, o) for c, o in seq if c is not None and o is not None][-n:]
    if len(seq) < 2:
        return None
    closes = [c for c, o in seq]
    net = closes[-1] - closes[0]
    rng = (max(closes) - min(closes)) or 1
    bull = sum(1 for c, o in seq if c >= o)
    if abs(net) < 0.25 * rng:  d = 'FLAT'      # choppy: no clear direction
    elif net > 0:              d = 'UP'
    else:                      d = 'DOWN'
    return {'dir': d, 'net': round(net, 2), 'bull': bull, 'bars': len(seq), 'last': round(closes[-1], 2)}

def _daily_trend_asof(date_str, n=5):
    """The daily trend (UP/DOWN/FLAT) as known GOING INTO date_str — i.e. from the
       last n daily candles strictly before it. Used as the regime filter."""
    days = [d for d in sorted(DATA['prices'])
            if d < date_str and DATA['prices'][d].get('open') is not None and DATA['prices'][d].get('close') is not None]
    seq = [(DATA['prices'][d]['close'], DATA['prices'][d]['open']) for d in days]
    tr = _trend_of(seq, n)
    return tr['dir'] if tr else None

def _combined_move(date_str):
    """Take-profit move = average of (recent 30-day range) and (this day's moon
       sign+stage average range). Blends current volatility with the astro setup."""
    recent = DATA.get('moves', {}).get('recent_range') or 0
    ss = _signstage_range(date_str)
    vals = [v for v in (recent, ss) if v]
    return round(sum(vals) / len(vals), 2) if vals else None

def load_data_safe():
    """Load from sheet; on failure keep existing data, or fall back to Excel on cold start."""
    try:
        load_data()
        return True
    except Exception as e:
        print("Sheet load failed (offline?):", e)
        if not DATA['prices']:
            if os.path.exists(LOCAL_CACHE):          # portable offline snapshot (preferred)
                print("Falling back to offline cache...")
                try:
                    _load_from_cache(); return False
                except Exception as ce:
                    print("Cache load failed:", ce)
            if os.path.exists(EXCEL_PATH):           # legacy local Excel
                print("Falling back to local Excel...")
                _load_data_from_excel()
        return False

def _load_data_from_excel():
    """Emergency offline fallback using the local .xlsx (gold_price + MOON sheets)."""
    xl = pd.read_excel(EXCEL_PATH, sheet_name=None)
    gp = xl['gold_price']; gp.columns = [str(c).strip() for c in gp.columns]
    gp['Date'] = pd.to_datetime(gp['Date'], errors='coerce')
    gp = gp.dropna(subset=['Date', 'Close']).sort_values('Date')
    prices = {r['Date'].strftime('%Y-%m-%d'): {
        'open': round(float(r['Open']),2), 'high': round(float(r['High']),2),
        'low': round(float(r['Low']),2), 'close': round(float(r['Close']),2),
        'change': round(float(r['Change']),2) if pd.notna(r.get('Change')) else None,
        'rng': round(float(r['Range']),2) if pd.notna(r.get('Range')) else None,
        'direction': str(r['Direction']).strip().upper()} for _, r in gp.iterrows()}
    DATA.update({'prices': prices})
    print("Loaded %d price days from Excel fallback" % len(prices))

# Gold-market holidays (no trading → no signal). Edit as needed.
GOLD_HOLIDAYS = {
    '2026-01-01',  # New Year's Day
    '2026-01-19',  # Martin Luther King Jr. Day
    '2026-02-16',  # Presidents' Day
    '2026-04-03',  # Good Friday
    '2026-05-25',  # Memorial Day
    '2026-06-19',  # Juneteenth
    '2026-07-03',  # Independence Day (observed; Jul 4 is Saturday)
    '2026-09-07',  # Labor Day
    '2026-11-26',  # Thanksgiving Day
    '2026-12-25',  # Christmas Day
}

MOVABLE_SIGNS = {'Aries', 'Cancer', 'Libra', 'Capricorn'}   # nature = MOVABLE

def _date_digit_root(date_str):
    """Day-of-month reduced to a single digit (e.g. 18 -> 9). 3/7/9 = 'important date'."""
    try:
        d = int(date_str.split('-')[2])
    except (ValueError, IndexError):
        return None
    while d > 9:
        d = sum(int(c) for c in str(d))
    return d

def _prev_trading_day(date_str, today):
    from datetime import timedelta
    cur = datetime.strptime(date_str, '%Y-%m-%d')
    for _ in range(12):
        cur -= timedelta(days=1)
        cs = cur.strftime('%Y-%m-%d')
        if not market_closed_reason(cs, today):
            return cs
    return None

def _base_direction(date_str):
    """Direction from the sheet (if present) else the engine signal — WITHOUT the pullback rule."""
    fc = DATA.get('forecast', {}).get(date_str)
    if fc and fc['direction'] in ('BUY', 'SELL', 'WAIT'):
        return fc['direction']
    m = DATA['moon'].get(date_str)
    if not m:
        return None
    sig = engine.compute_signal(date_str, m, hist_counts(date_str, m['sign'], m['stage']),
                                past_moon_history(date_str), price=None)
    s = sig['signal'] if sig else ''
    return 'BUY' if 'BUY' in s else ('SELL' if 'SELL' in s else 'WAIT')

def _pullback_direction(date_str, today):
    """Rule 2: the 2nd consecutive trading day of a MOVABLE sign reverses day-1's call."""
    m = DATA['moon'].get(date_str)
    if not m or m.get('sign') not in MOVABLE_SIGNS:
        return None
    prev = _prev_trading_day(date_str, today)
    if not prev:
        return None
    pm = DATA['moon'].get(prev)
    if not pm or pm.get('sign') != m['sign']:   # need the same movable sign on the prior trading day
        return None
    prev2 = _prev_trading_day(prev, today)       # ...and prev must be DAY 1 (its prior day differs)
    pm2 = DATA['moon'].get(prev2) if prev2 else None
    if pm2 and pm2.get('sign') == m['sign']:     # this is the 3rd+ day of the run -> not a 2-day pullback
        return None
    d1 = _effective_direction(prev, today)   # reverse the prior day's FINAL shown signal
    if d1 == 'BUY':  return 'SELL'
    if d1 == 'SELL': return 'BUY'
    return None

def _effective_direction(ds, today):
    """The prior day's FINAL shown direction, in the same precedence build_day uses:
       Decision-Day continuation > 2-day pullback > sheet/engine base. This is what the
       pullback rule must reverse (not the hidden engine base)."""
    dc = decision_continuation(ds, today)
    if dc:
        return dc['dir']
    pb = _pullback_direction(ds, today)        # day-1 of a run returns None → no deep recursion
    if pb:
        return pb
    return _base_direction(ds)

# ── NATURE-CYCLE MODEL (v3, backtested ~52% vs 36% baseline) ───────────────────
# Predicts direction from yesterday's ACTUAL move + today's sign nature + cycle date:
#   movable -> reverse on its 2nd day (pullback) else continue · fixed -> continue
#   finisher -> reverse at FINISH else continue · 9-date -> final push (continue) ·
#   day AFTER a 9-date -> the turn fires (reverse). Self-corrects (uses real prior move).
_MODEL_CACHE = {}
def _prior_actual_dir(ds, today):
    """(+1/-1, prevdate) from the prior trading day: ACTUAL if it traded, else its model pred."""
    prev = _prev_trading_day(ds, today)
    if not prev:
        return None, None
    pp = DATA['prices'].get(prev)
    if pp and pp.get('direction') in ('BULL', 'BEAR'):
        return (1 if pp['direction'] == 'BULL' else -1), prev
    md = _model_direction(prev, today)        # future chain
    if md == 'BUY':  return 1, prev
    if md == 'SELL': return -1, prev
    return None, prev

def _model_direction(ds, today):
    if ds in _MODEL_CACHE:
        return _MODEL_CACHE[ds]
    _MODEL_CACHE[ds] = None                    # recursion guard
    m = DATA['moon'].get(ds)
    if not m:
        return None
    pa, prev = _prior_actual_dir(ds, today)
    if pa is None or not prev:
        return None
    nat = DATA['signs'].get(m['sign'], {}).get('nature', '').upper()
    stage = m['stage']
    # 9-cycle rules removed (backtest: they hurt; dropping them lifts win rate ~52% -> ~56%)
    if nat == 'MOVABLE':     d = (-pa if DATA['moon'].get(prev, {}).get('sign') == m['sign'] else pa)
    elif nat == 'FIXED':     d = pa
    else:                    d = (-pa if stage == 'FINISH' else pa)   # finisher
    res = 'BUY' if d > 0 else 'SELL'
    _MODEL_CACHE[ds] = res
    return res

def _model_info(ds, today):
    d = _model_direction(ds, today)
    if not d:
        return None
    m = DATA['moon'].get(ds); prev = _prev_trading_day(ds, today)
    nat = DATA['signs'].get(m['sign'], {}).get('nature', '').upper(); stage = m['stage']
    if nat == 'MOVABLE':   why = ('movable 2nd-day → pullback' if DATA['moon'].get(prev, {}).get('sign') == m['sign'] else 'movable 1st-day → continue')
    elif nat == 'FIXED':   why = 'fixed → continue trend'
    else:                  why = ('finisher at FINISH → turn' if stage == 'FINISH' else 'finisher → continue')
    return {'dir': d, 'reason': why}

import math
def _clean_nan(o):
    """Recursively replace NaN/Inf floats with None so jsonify emits valid JSON."""
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: _clean_nan(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean_nan(v) for v in o]
    return o

def _signal_reason(day):
    """One-line plain-English explanation of why the signal is BUY/SELL/WAIT."""
    sig = day.get('signal')
    if not sig:
        return ''
    parts = []
    if day.get('signal_src') == 'sheet' and day.get('buy_score') is not None and day.get('sell_score') is not None:
        parts.append("buy/sell score %d/%d" % (int(day['buy_score']), int(day['sell_score'])))
        if day.get('transition'):
            parts.append(str(day['transition']).lower())
    else:
        ms = day.get('moon_score') or 0
        if ms > 0:   parts.append("bullish moon (%s)" % day.get('sign'))
        elif ms < 0: parts.append("bearish moon (%s)" % day.get('sign'))
        retro = day.get('retrogrades') or []
        ts = day.get('transit_score') or 0
        if retro:   parts.append("%s Rx pressure" % ', '.join(retro))
        elif ts > 0: parts.append("transit support")
        elif ts < 0: parts.append("transit drag")
    bp, brp = day.get('bull_pct'), day.get('bear_pct')
    if bp is not None and (bp or brp):
        if 'BUY' in sig:    parts.append("%g%% bull history" % bp)
        elif 'SELL' in sig: parts.append("%g%% bear history" % brp)
    if day.get('power_day'):
        parts.append("day-%s power(3·7·9)" % day.get('day_number'))
    if day.get('mtf_score'):
        parts.append("multi-TF %s" % ('up' if day['mtf_score'] > 0 else 'down'))
    if day.get('pullback'):
        parts.insert(0, 'movable 2-day pullback (reverse of prior day)')
    if day.get('power_date'):
        parts.append('★ important date (3·7·9) — bigger move')
    verb = {'STRONG BUY':'Strong BUY','BUY':'BUY','SELL':'SELL','STRONG SELL':'Strong SELL',
            'WAIT':'WAIT','NO TRADE':'NO TRADE'}.get(sig, sig)
    if not parts:
        parts = ['mixed signals — no clear edge'] if sig in ('WAIT', 'NO TRADE') else ['weak edge']
    return verb + " — " + "; ".join(parts[:4])

def market_closed_reason(date_str, today):
    """Return 'Weekend' / 'Holiday' if gold market is closed that day, else None."""
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return None
    if dt.weekday() >= 5:                       # Sat=5, Sun=6
        return 'Weekend'
    if date_str in GOLD_HOLIDAYS:
        return 'Holiday'
    # past weekday with no trading row in the sheet = market was closed (holiday)
    if date_str < today and date_str not in DATA['prices']:
        return 'Holiday'
    return None

def hist_counts(date_str, sign, stage):
    """Bull/bear count of PAST price days matching this Moon Sign + Cycle Stage."""
    bull = bear = 0
    for d, p in DATA['prices'].items():
        if d >= date_str:
            continue
        m = DATA['moon'].get(d)
        if m and m['sign'] == sign and m['stage'] == stage:
            if p['direction'] == 'BULL':   bull += 1
            elif p['direction'] == 'BEAR': bear += 1
    return {'bull': bull, 'bear': bear}

def past_moon_history(date_str):
    """All moon-day dicts strictly before date_str (for confidence calc)."""
    return [m for d, m in DATA['moon'].items() if d < date_str]

_MATCH_CACHE = {}
def _matching_moves(date_str, sign, stage):
    """Avg up/down move + range from PAST days matching this Moon Sign + Cycle Stage.
    Falls back to the global average when fewer than 2 matching bull/bear days exist."""
    import statistics as st
    if date_str in _MATCH_CACHE:
        return _MATCH_CACHE[date_str]
    ups, downs, ranges = [], [], []
    for d, p in DATA['prices'].items():
        if d >= date_str:
            continue
        m = DATA['moon'].get(d)
        if not m or m.get('sign') != sign or m.get('stage') != stage:
            continue
        ch = p.get('change')
        if ch is not None:
            (ups if ch >= 0 else downs).append(abs(ch))
        if p.get('high') and p.get('low'):
            ranges.append(p['high'] - p['low'])
    g = DATA.get('moves', {})
    res = {
        'avg_up':    round(st.mean(ups), 2)    if len(ups) >= 2   else g.get('avg_up', 0),
        'avg_down':  round(st.mean(downs), 2)  if len(downs) >= 2 else g.get('avg_down', 0),
        'avg_range': round(st.mean(ranges), 2) if ranges          else g.get('avg_range', 0),
        'up_n': len(ups), 'down_n': len(downs), 'n': len(ups) + len(downs),
    }
    _MATCH_CACHE[date_str] = res
    return res

_MOVE_CACHE = {}
def _signed_move(date_str, today):
    """Signed expected move ($) for a trading day: +up for BUY, -down for SELL, 0 otherwise.
    Used to chain forecast anchors. Anchor-independent → safe to cache."""
    if date_str in _MOVE_CACHE:
        return _MOVE_CACHE[date_str]
    val = 0
    if not market_closed_reason(date_str, today):
        moves = DATA.get('moves', {})
        pb = _pullback_direction(date_str, today)
        m0 = DATA['moon'].get(date_str)
        fc = DATA.get('forecast', {}).get(date_str)
        if pb and m0:                                  # Rule 2 pullback flips the move direction
            mm = _matching_moves(date_str, m0['sign'], m0['stage'])
            val = mm['avg_up'] if pb == 'BUY' else -mm['avg_down']
        elif fc and fc['direction'] in ('BUY', 'SELL'):
            if fc['direction'] == 'BUY' and fc.get('avg_bull'):  val = abs(fc['avg_bull'])
            elif fc['direction'] == 'SELL' and fc.get('avg_bear'): val = -abs(fc['avg_bear'])
        else:
            m = DATA['moon'].get(date_str)
            if m:
                sig = engine.compute_signal(date_str, m, hist_counts(date_str, m['sign'], m['stage']),
                                            past_moon_history(date_str), price=None)
                s = sig['signal'] if sig else ''
                mult = 1.4 if 'STRONG' in s else 1.0
                mm = _matching_moves(date_str, m['sign'], m['stage'])
                if 'BUY' in s:    val = mm['avg_up'] * mult
                elif 'SELL' in s: val = -mm['avg_down'] * mult
    val = round(val, 2)
    _MOVE_CACHE[date_str] = val
    return val

def _chained_anchor(date_str, today):
    """Projection anchor for a FUTURE day = prior trading day's projected close,
    chained forward from the last actual close in the sheet."""
    from datetime import timedelta
    if not DATA['prices']:
        return None
    last_d = max(DATA['prices'])
    if date_str <= last_d:
        return None
    anchor = DATA['prices'][last_d]['close']
    cur = datetime.strptime(last_d, '%Y-%m-%d')
    target = datetime.strptime(date_str, '%Y-%m-%d')
    while True:
        cur += timedelta(days=1)
        ds = cur.strftime('%Y-%m-%d')
        if ds >= date_str:
            break
        mv = _signed_move(ds, today)
        if mv:
            anchor = round(anchor + mv, 2)
    return anchor

def _pp_for(date_str):
    """Pivot point for a day = (H+L+C)/3 of the most recent trading day before it."""
    prior = [d for d in sorted(DATA['prices']) if d < date_str]
    if not prior:
        return None
    y = DATA['prices'][prior[-1]]
    if None in (y.get('high'), y.get('low'), y.get('close')):
        return None
    return (y['high'] + y['low'] + y['close']) / 3

def _weekly_bias(date_str):
    """Prior calendar week's net direction (+1 bull / -1 bear / None)."""
    try:
        key = datetime.strptime(date_str, '%Y-%m-%d').isocalendar()[:2]
    except ValueError:
        return None
    prior = [k for k in DATA.get('week_keys', []) if k < key]
    if not prior:
        return None
    return DATA['week_dir'].get(prior[-1])

def _tp_window(date_str, direction, mv, entry, n=3, R=1.0, be_frac=0.5):
    """Multi-day outcome with a BREAKEVEN STOP TRAIL (1:1 by default).
       risk(stop)=1*move, reward(target)=R*move. When price travels be_frac of the way
       to target, the stop is moved to ENTRY (breakeven). After that the trade can only
       WIN or break even (never a full loss). Conservative OHLC ordering: the adverse move
       is assumed to happen first each day.
       Returns (outcome, tp_hit, sl_hit). outcome ∈ {'W','BE','L',None}; None = pending."""
    if not mv or entry is None:
        return None, False, False
    pdays = [d for d in sorted(DATA['prices']) if d >= date_str][:n]
    if not pdays:
        return None, False, False
    buy = direction == 'BUY'
    if buy:
        stop0 = entry - mv; be = entry + be_frac*R*mv; tgt = entry + R*mv
    else:
        stop0 = entry + mv; be = entry - be_frac*R*mv; tgt = entry - R*mv
    armed = False
    for d in pdays:
        pp = DATA['prices'][d]; hi, lo = pp.get('high'), pp.get('low')
        if hi is None or lo is None:
            continue
        if buy:
            if not armed:
                if lo <= stop0: return 'L', False, True       # full stop hit first
                if hi >= tgt:   return 'W', True, False         # target hit
                if hi >= be:    armed = True                    # trail stop to entry
            else:
                if lo <= entry: return 'BE', False, False       # trailed out at breakeven
                if hi >= tgt:   return 'W', True, False
        else:
            if not armed:
                if hi >= stop0: return 'L', False, True
                if lo <= tgt:   return 'W', True, False
                if lo <= be:    armed = True
            else:
                if hi >= entry: return 'BE', False, False
                if lo <= tgt:   return 'W', True, False
    if len(pdays) < n:
        return None, False, False                               # window not elapsed -> pending
    return ('BE' if armed else 'L'), False, (not armed)         # expired: protected if armed

def _candle_note(p):
    """Context label for a day's candle shape (display only — does not affect the signal)."""
    o, h, l, c = p.get('open'), p.get('high'), p.get('low'), p.get('close')
    if None in (o, h, l, c):
        return None
    rng = (h - l) or 1; body = c - o
    uw = h - max(o, c); lw = min(o, c) - l
    if abs(body) < 0.30 * rng:
        if uw > lw * 1.3: return 'small body · upper-wick rejection (bearish tilt)'
        if lw > uw * 1.3: return 'small body · lower-wick rejection (bullish tilt)'
        return 'small body · indecision (continuation)'
    return 'strong bull body' if body > 0 else 'strong bear body'

def _trend_note(date_str):
    """3-day trend direction (display context only)."""
    back = [d for d in sorted(DATA['prices']) if d < date_str][-3:]
    if len(back) < 2:
        return None
    net = DATA['prices'][back[-1]]['close'] - DATA['prices'][back[0]]['open']
    return 'up' if net >= 0 else 'down'

# ── DECISION DAY ────────────────────────────────────────────────────────────────
# A day whose net Change is small (between +10 and -10) is a "Decision Day":
# the market is undecided / coiling, which makes the NEXT day important (the breakout).
DECISION_MAX = 10.0    # |Change| <= this  ->  Decision Day

def _is_decision_day(date_str):
    p = DATA['prices'].get(date_str)
    if not p:
        return False
    ch = p.get('change')
    return ch is not None and abs(ch) <= DECISION_MAX

def _prev_completed_day(date_str):
    """Most recent prior date that has price data (a completed trading day)."""
    prior = [d for d in sorted(DATA['prices']) if d < date_str and DATA['prices'][d].get('change') is not None]
    return prior[-1] if prior else None

def _first_trading_day_after(d, today):
    """First non-closed calendar day strictly after d (used for the future boundary)."""
    from datetime import timedelta
    dt = datetime.strptime(d, '%Y-%m-%d')
    for i in range(1, 8):
        cand = (dt + timedelta(days=i)).strftime('%Y-%m-%d')
        if not market_closed_reason(cand, today):
            return cand
    return None

def decision_continuation(date_str, today):
    """A Decision Day is a PAUSE inside the main trend, so the next day RESUMES that
       trend (it does not flip). Direction = net of the last 3 trading days BEFORE the
       decision day (down -> SELL, up -> BUY). Entry/stop are built off the decision
       day's HIGH/LOW. Only fires on the decision day's immediate next trading day."""
    prev = _prev_completed_day(date_str)
    if not prev or not _is_decision_day(prev):
        return None
    if date_str > today and date_str != _first_trading_day_after(prev, today):
        return None
    pv = DATA['prices'][prev]
    hi, lo = pv.get('high'), pv.get('low')
    if hi is None or lo is None:
        return None
    # main trend = net change of the last 3 trading days BEFORE the decision day
    before = [d for d in sorted(DATA['prices'])
              if d < prev and DATA['prices'][d].get('change') is not None][-3:]
    net = sum(DATA['prices'][d]['change'] for d in before)
    if not before or net == 0:
        return None
    return {
        'prev': prev, 'prev_change': round(pv['change'], 2),
        'dir': 'SELL' if net < 0 else 'BUY',
        'decision_high': round(hi, 2), 'decision_low': round(lo, 2),
        'trend_net': round(net, 2), 'trend_days': before,
    }

# ── 4-HOUR TRADING PLAN ─────────────────────────────────────────────────────────
# Strategy (matches strategy_4h.py): the DAILY signal decides direction; you enter at
# the day's PIVOT POINT; the STOP and TAKE-PROFIT are sized from the 4-HOUR ATR and
# trailed to breakeven on the 4H candles. Recommended config below.
H4_ATR_N    = 30      # 4H candles of look-back for ATR (~5 trading days)
H4_ATR_MULT = 1.5     # stop distance = 1.5 x 4H-ATR  (best in backtest)
H4_RR       = 1.0     # reward:risk 1:1
H4_MAX_DAYS = 3       # hold/manage up to 3 trading days

def _index_candles(src):
    """Group a candle list into (time-ordered list, per-day buckets)."""
    rows = []
    for c in src:
        dt = str(c.get('dt', '')).strip()
        if len(dt) < 10 or c.get('high') is None or c.get('low') is None:
            continue
        parts = dt.split(' ')
        tc = (parts[1].split(':') if len(parts) > 1 else [])
        time = ('%s:%s' % (tc[0].zfill(2), tc[1].zfill(2))) if len(tc) >= 2 else ''
        rows.append({'date': dt[:10], 'time': time,
                     'o': c.get('open'), 'c': c.get('close'), 'h': c.get('high'), 'l': c.get('low')})
    rows.sort(key=lambda r: (r['date'], r['time']))
    by_day = {}
    for r in rows:
        by_day.setdefault(r['date'], []).append(r)
    return rows, by_day

def _compute_h4_index():
    """Group DATA['h4'] and DATA['h1'] into time-ordered lists + per-day buckets."""
    global _H4_SORTED, _H4_BY_DAY, _H1_SORTED, _H1_BY_DAY
    _H4_SORTED, _H4_BY_DAY = _index_candles(DATA.get('h4', []))
    _H1_SORTED, _H1_BY_DAY = _index_candles(DATA.get('h1', []))

def _h4_atr(date_str):
    """Average 4H candle range over the last H4_ATR_N candles BEFORE this day."""
    if not _H4_SORTED:
        return None
    # first candle index on/after this date
    start = 0
    for i, r in enumerate(_H4_SORTED):
        if r['date'] >= date_str:
            start = i; break
    else:
        start = len(_H4_SORTED)
    window = _H4_SORTED[max(0, start - H4_ATR_N):start]
    rng = [r['h'] - r['l'] for r in window if r['h'] is not None and r['l'] is not None]
    if len(rng) < max(3, H4_ATR_N // 2):
        return None
    return sum(rng) / len(rng)

def _h4_window_candles(date_str):
    """The 4H candles for this day plus the next (H4_MAX_DAYS-1) days that have candles."""
    days = sorted(d for d in _H4_BY_DAY if d >= date_str)[:H4_MAX_DAYS]
    out = []
    for d in days:
        out.extend(_H4_BY_DAY[d])
    return out, days

def _pivot_levels(date_str):
    """Pivot ladder for date_str, from the most recent prior trading day's OHLC."""
    prior = [d for d in sorted(DATA['prices']) if d < date_str and None not in (
        DATA['prices'][d].get('high'), DATA['prices'][d].get('low'), DATA['prices'][d].get('close'))]
    if not prior:
        return None
    y = DATA['prices'][prior[-1]]
    p = {k: round(v, 2) for k, v in _pivots_from(y).items()}   # R1/R2/R3, PP, S1/S2/S3, Yest High/Low
    p['MID'] = round((y['high'] + y['low']) / 2, 2)            # midpoint (rounded to match entries)
    return p

# pivot ladder used for level-based stops (R/PP/MID/S — Yest High/Low excluded on purpose)
_LADDER = ('R3', 'R2', 'R1', 'PP', 'MID', 'S1', 'S2', 'S3')
_LV_NAME = {'MID': 'midpoint', 'PP': 'PP'}

def _level_sltp(direction, entry, lv):
    """(stop, target, stop_ref, target_ref) — rule (ii): stop $2 beyond the NEXT
       pivot level past the entry; target = next R (buy) / next S (sell)."""
    entry = round(entry, 2)                   # match the 2dp pivot levels (avoid rounding slips)
    ladder = [(k, lv[k]) for k in _LADDER if lv.get(k) is not None]
    Rs = [(k, lv[k]) for k in ('R1', 'R2', 'R3') if lv.get(k) is not None]
    Ss = [(k, lv[k]) for k in ('S1', 'S2', 'S3') if lv.get(k) is not None]
    if direction == 'BUY':
        below = [(k, v) for k, v in ladder if v < entry - 1e-6]
        if not below:
            return None, None, None, None
        sk, sv = max(below, key=lambda x: x[1])          # nearest level below entry
        above = [(k, v) for k, v in Rs if v > entry + 1e-6]
        tk, tv = min(above, key=lambda x: x[1]) if above else (None, None)
        return round(sv - 2, 2), (round(tv, 2) if tv is not None else None), _LV_NAME.get(sk, sk), tk
    else:
        above = [(k, v) for k, v in ladder if v > entry + 1e-6]
        if not above:
            return None, None, None, None
        rk, rv = min(above, key=lambda x: x[1])          # nearest level above entry
        below = [(k, v) for k, v in Ss if v < entry - 1e-6]
        tk, tv = max(below, key=lambda x: x[1]) if below else (None, None)
        return round(rv + 2, 2), (round(tv, 2) if tv is not None else None), _LV_NAME.get(rk, rk), tk

def _plan_sltp(date_str, direction, entry, atr):
    """ATR-based stop/target (the version that backtested positive):
       stop = 1.5×ATR from entry, target = 1:1, breakeven at 50% to target.
       Returns (stop, target, be, stop_ref, target_ref)."""
    if not atr or entry is None:
        return None, None, None, None, None
    sd = round(H4_ATR_MULT * atr, 2)
    td = round(H4_RR * sd, 2)
    if direction == 'BUY':
        stop, tgt, be = round(entry - sd, 2), round(entry + td, 2), round(entry + 0.5 * td, 2)
    else:
        stop, tgt, be = round(entry + sd, 2), round(entry - td, 2), round(entry - 0.5 * td, 2)
    return stop, tgt, be, '%g×ATR' % H4_ATR_MULT, '%g:1' % H4_RR

def build_4h_plan(date_str, direction, today, entry=None, entry_label='pivot point'):
    """Build the per-day 4-hour plan dict, or None if not applicable.
       direction: 'BUY' or 'SELL'. Entry defaults to the pivot, but a decision-day
       midpoint can be passed in. Stop/target = pivot levels (rule ii). BE trail on 4H."""
    if entry is None:
        entry = _pp_for(date_str)
    atr = _h4_atr(date_str)
    if entry is None:
        return None
    buy = direction == 'BUY'
    sl, tgt, be, stop_ref, target_ref = _plan_sltp(date_str, direction, entry, atr)
    if sl is None or tgt is None or be is None:
        return None
    stop_dist = round(abs(entry - sl), 2); tp_dist = round(abs(tgt - entry), 2)

    day_candles = _H4_BY_DAY.get(date_str, [])
    win_candles, win_days = _h4_window_candles(date_str)

    # walk the 4H window: fill at pivot, then breakeven-trail management
    filled = False; fill_time = None; armed = False; outcome = None
    tagged = []   # the signal-day candles annotated with what happened
    day_set = set(c['date'] for c in day_candles)
    for r in win_candles:
        tags = []
        h, l = r['h'], r['l']
        if not filled:
            if l <= entry <= h:
                filled = True; fill_time = r['time']; tags.append('fill')
            else:
                if r['date'] in day_set:
                    tagged.append({**_pub_candle(r), 'tags': tags})
                continue
        if outcome is None:
            if buy:
                if not armed:
                    if l <= sl:  outcome = 'L'; tags.append('sl')
                    elif h >= tgt: outcome = 'W'; tags.append('tp')
                    elif h >= be: armed = True; tags.append('be-armed')
                else:
                    if l <= entry: outcome = 'BE'; tags.append('be-exit')
                    elif h >= tgt: outcome = 'W'; tags.append('tp')
            else:
                if not armed:
                    if h >= sl:  outcome = 'L'; tags.append('sl')
                    elif l <= tgt: outcome = 'W'; tags.append('tp')
                    elif l <= be: armed = True; tags.append('be-armed')
                else:
                    if h >= entry: outcome = 'BE'; tags.append('be-exit')
                    elif l <= tgt: outcome = 'W'; tags.append('tp')
        if r['date'] in day_set:
            tagged.append({**_pub_candle(r), 'tags': tags})
        if outcome is not None:
            break

    is_past = date_str < today
    # finalize outcome only when the full window has elapsed (past days)
    if outcome is None and filled and is_past and len(win_days) >= 1:
        last_win_day = win_days[-1]
        if last_win_day < today:               # window fully in the past
            outcome = 'BE' if armed else 'L'
    if not filled and is_past:
        # no fill possible anymore only if the whole window is past
        if win_days and win_days[-1] < today:
            outcome = 'NF'

    advice = _h4_advice(direction, entry, sl, tgt, filled, fill_time, outcome,
                        is_past, date_str == today)
    return {
        'dir': direction, 'entry': round(entry, 2), 'entry_label': entry_label,
        'stop': round(sl, 2), 'target': round(tgt, 2), 'be': round(be, 2),
        'atr': round(atr, 2) if atr else None, 'stop_dist': stop_dist, 'tp_dist': tp_dist,
        'stop_ref': stop_ref, 'target_ref': target_ref,
        'filled': filled, 'fill_time': fill_time, 'outcome': outcome,
        'candles': tagged, 'n_candles': len(day_candles),
        'advice': advice,
    }

def _pub_candle(r):
    return {'time': r['time'], 'open': _r2(r['o']), 'high': _r2(r['h']),
            'low': _r2(r['l']), 'close': _r2(r['c']),
            'dir': 'BULL' if (r['c'] or 0) >= (r['o'] or 0) else 'BEAR'}

def _r2(x):
    return round(x, 2) if isinstance(x, (int, float)) else x

def _h4_advice(direction, entry, sl, tgt, filled, fill_time, outcome, is_past, is_today):
    e, s, t = ('$%.2f' % entry), ('$%.2f' % sl), ('$%.2f' % tgt)
    if outcome == 'W':  return 'WIN — price reached the target %s. Trade closed +1R.' % t
    if outcome == 'BE': return 'BREAKEVEN — stop trailed to entry, closed at 0. No loss.'
    if outcome == 'L':  return 'LOSS — stopped out at %s before the target. −1R.' % s
    if outcome == 'NF': return 'NO TRADE — price never reached the pivot %s today.' % e
    if is_today:
        if filled:
            return ('LIVE — entered %s at the pivot %s (%s). Stop %s, target %s. '
                    'Managing on 4H with a move-to-breakeven trail.' % (direction, e, fill_time or '', s, t))
        return 'WAITING — enter %s only when price trades to the pivot %s. Then stop %s, target %s.' % (direction, e, s, t)
    # future
    return ('PLAN — when price trades to the pivot %s, go %s. Stop %s, target %s, '
            'trailed to breakeven on the 4H candles.' % (e, direction, s, t))

def _h1_window(date_str):
    """1-hour candles for this day + the next (H4_MAX_DAYS-1) days that have candles."""
    days = sorted(d for d in _H1_BY_DAY if d >= date_str)[:H4_MAX_DAYS]
    out = []
    for d in days:
        out.extend(_H1_BY_DAY[d])
    return out, days

def build_decision_plan(date_str, dc, today):
    """Decision-day continuation plan (trend resumes after the pause):
       - direction = dc['dir'] (net of the 3 days before the decision day)
       - ENTRY = a ZONE $8-10 beyond the decision day's extreme (sell above its HIGH /
         buy below its LOW) — you fade the bounce back into the trend
       - STOP/TARGET = 1.5×ATR / 1:1 with a breakeven trail (same as the normal plan)
       Fills when price trades into the zone; then BE-trail management on the candles."""
    direction = dc['dir']; sell = direction == 'SELL'
    dhigh = dc.get('decision_high'); dlow = dc.get('decision_low')
    atr = _h4_atr(date_str)
    if dhigh is None or dlow is None or not atr:
        return None
    if sell:
        zlo = round(dhigh + 8, 2); zhi = round(dhigh + 10, 2); entry = zlo   # sell zone, near edge = entry
    else:
        zhi = round(dlow - 8, 2); zlo = round(dlow - 10, 2); entry = zhi     # buy zone
    sl, tgt, be, stop_ref, target_ref = _plan_sltp(date_str, direction, entry, atr)
    if sl is None or tgt is None or be is None:
        return None
    stop_dist = round(abs(entry - sl), 2); tp_dist = round(abs(tgt - entry), 2)

    win_h1, win_days = _h1_window(date_str)
    if not win_h1:                            # no 1-hour data -> use 4-hour intraday
        win_h1, win_days = _h4_window_candles(date_str)
    is_past = date_str < today
    day_candles = [{**_pub_candle(r), 'tags': []} for r in _H4_BY_DAY.get(date_str, [])]

    # fill when price trades INTO the zone, then breakeven-trail management
    filled = False; fill_time = None; armed = False; outcome = None
    for r in (win_h1 or []):
        h, l = r['h'], r['l']
        if not filled:
            if (sell and h >= zlo) or ((not sell) and l <= zhi):
                filled = True; fill_time = r['time']
            else:
                continue
        if outcome is None:
            if sell:
                if not armed:
                    if h >= sl:  outcome = 'L'; break
                    if l <= tgt: outcome = 'W'; break
                    if l <= be:  armed = True
                else:
                    if h >= entry: outcome = 'BE'; break
                    if l <= tgt:   outcome = 'W'; break
            else:
                if not armed:
                    if l <= sl:  outcome = 'L'; break
                    if h >= tgt: outcome = 'W'; break
                    if h >= be:  armed = True
                else:
                    if l <= entry: outcome = 'BE'; break
                    if h >= tgt:   outcome = 'W'; break
    if outcome is None and filled and is_past and win_days and win_days[-1] < today:
        outcome = 'BE' if armed else 'L'
    if not filled and is_past and win_days and win_days[-1] < today:
        outcome = 'NF'

    adv = _decision_advice(direction, entry, zlo, zhi, sl, tgt, dc, filled, fill_time, outcome, is_past, date_str == today)
    return {'dir': direction, 'decision': True,
            'zone_low': zlo, 'zone_high': zhi, 'entry': entry, 'entry_label': 'decision zone',
            'stop': sl, 'stop_ref': stop_ref, 'target': tgt, 'target_ref': target_ref, 'be': be,
            'stop_dist': stop_dist, 'tp_dist': tp_dist,
            'trend_net': dc.get('trend_net'), 'prev_decision_date': dc.get('prev'),
            'filled': filled, 'fill_time': fill_time, 'outcome': outcome,
            'candles': day_candles, 'n_candles': len(day_candles),
            'trigger': 'price trades into the zone', 'advice': adv}

def _decision_advice(direction, entry, zlo, zhi, stop, tgt, dc, filled, fill_time, outcome, is_past, is_today):
    zone = '$%.2f–$%.2f' % (zlo, zhi)
    base = '%s zone %s · stop $%.2f · target $%.2f (1:1, BE trail)' % (direction, zone, stop, tgt)
    trend = 'downtrend' if dc.get('dir') == 'SELL' else 'uptrend'
    if outcome == 'W':  return 'WIN — %s. Hit target $%.2f.' % (base, tgt)
    if outcome == 'BE': return 'BREAKEVEN — %s. Trailed to entry (0).' % base
    if outcome == 'L':  return 'LOSS — %s. Stopped at $%.2f.' % (base, stop)
    if outcome == 'NF': return 'NO TRADE — price never reached the %s entry zone %s.' % (direction, zone)
    if is_today:
        return ('%s — %s. Decision day was a pause in the %s; %s the bounce into %s.'
                % ('LIVE (filled)' if filled else 'WAITING', base, trend, 'sell' if direction == 'SELL' else 'buy', zone))
    return ('PLAN — decision day was a pause in the %s, so trend resumes: %s. Enter when price trades into %s.'
            % (trend, base, zone))

def build_day(date_str):
    today = datetime.today().strftime('%Y-%m-%d')
    m = DATA['moon'].get(date_str)
    p = DATA['prices'].get(date_str)
    day = {'date': date_str, 'is_past': date_str < today, 'is_today': date_str == today}

    # ── MARKET CLOSED (weekend / gold-market holiday) → no calculation ──
    closed = market_closed_reason(date_str, today)
    if closed:
        day['market_closed'] = True
        day['closed_reason'] = closed          # 'Weekend' or 'Holiday'
        if m:                                  # show astro context only (no signal)
            day.update({
                'sign': m['sign'], 'sun_sign': m.get('sun_sign'),
                'phase': m['phase'], 'phase_emoji': m['phase_emoji'],
                'stage': m['stage'], 'gender': m['gender'],
                'day_number': m['day_number'], 'stage_num': m.get('stage_num'),
                'sign_emoji': DATA['signs'].get(m['sign'], {}).get('emoji', '*'),
            })
        if p:
            day.update({'open': p['open'], 'high': p['high'], 'low': p['low'],
                        'close': p['close'], 'change': p['change'], 'rng': p['rng'],
                        'direction': p['direction'],
                        'mid': round((p['high'] + p['low']) / 2, 2) if (p.get('high') and p.get('low')) else None})
        nws = news.get_for(date_str)
        day['usd_news'] = nws; day['usd_news_count'] = len(nws)
        return _clean_nan(day)

    if m:
        counts  = hist_counts(date_str, m['sign'], m['stage'])
        history = past_moon_history(date_str)
        # multi-timeframe price forecast only for today (intraday candles are "now")
        mtf = engine.mtf_score(DATA.get('h1'), DATA.get('h4')) if date_str == today else None
        sig = engine.compute_signal(date_str, m, counts, history, price=p, mtf=mtf)

        sign_info = DATA['signs'].get(m['sign'], {})
        phase_info = {}
        for pk, pv in DATA['phases'].items():
            if pk.lower() in m['phase'].lower() or m['phase'].lower() in pk.lower():
                phase_info = pv; break
        day.update({
            'sign': m['sign'], 'sun_sign': m.get('sun_sign'),
            'phase': m['phase'], 'phase_emoji': m['phase_emoji'],
            'stage': m['stage'], 'gender': m['gender'],
            'day_number': m['day_number'], 'stage_num': m.get('stage_num'),
            'sign_emoji':   sign_info.get('emoji','*'),
            'sign_meaning': sign_info.get('meaning',''),
            'sign_bias':    sign_info.get('market_bias',''),
            'sign_nature':  sign_info.get('nature',''),
            'sign_keyword': sign_info.get('keyword',''),
            'phase_mood':   phase_info.get('mood',''),
            'phase_meaning':phase_info.get('meaning',''),
        })
        if sig:
            day.update(sig)

    if p:
        mid = round((p['high'] + p['low']) / 2, 2) if (p.get('high') and p.get('low')) else None
        day.update({
            'open': p['open'], 'high': p['high'],
            'low':  p['low'],  'close': p['close'],
            'change': p['change'], 'rng': p['rng'],
            'direction': p['direction'], 'mid': mid,
        })

    # ── SHEET OVERRIDE: use WEEKLY_FORECAST Expected Direction as source of truth ──
    fc = DATA.get('forecast', {}).get(date_str)
    if fc and fc['direction'] in ('BUY', 'SELL', 'WAIT'):
        day['signal'] = fc['direction']
        day['signal_src'] = 'sheet'
        day['buy_score'] = fc['buy_score']
        day['sell_score'] = fc['sell_score']
        day['transition'] = fc.get('transition')
        if fc['confidence'] is not None:
            day['confidence'] = round(fc['confidence'])
        if fc['buy_score'] is not None and fc['sell_score'] is not None:
            day['bias'] = max(-100, min(100, round(fc['buy_score'] - fc['sell_score'], 1)))
        # per-day expected move from the sheet's own averages
        anchor = day.get('open') or _chained_anchor(date_str, today) or DATA.get('moves', {}).get('last_close') or 0
        if fc['direction'] == 'BUY' and fc.get('avg_bull'):
            mv = round(abs(fc['avg_bull']), 2); day['expected_move'] = mv; day['target_dir'] = 'up'
            if anchor:
                day['target'] = round(anchor + mv, 2); day['target_anchor'] = round(anchor, 2)
                day['target_is_est'] = day.get('open') is None
        elif fc['direction'] == 'SELL' and fc.get('avg_bear'):
            mv = round(abs(fc['avg_bear']), 2); day['expected_move'] = mv; day['target_dir'] = 'down'
            if anchor:
                day['target'] = round(anchor - mv, 2); day['target_anchor'] = round(anchor, 2)
                day['target_is_est'] = day.get('open') is None
        if fc.get('avg_range'):
            day['expected_range'] = round(abs(fc['avg_range']), 2)

    # ── RULE 2: movable-sign 2-day PULLBACK (overrides sheet + engine direction) ──
    pb = _pullback_direction(date_str, today)
    if pb and day.get('signal') in ('BUY', 'STRONG BUY', 'SELL', 'STRONG SELL', 'WAIT', 'NO TRADE'):
        day['signal'] = pb
        day['signal_src'] = 'pullback'
        day['pullback'] = True
        b = abs(day.get('bias') or 20)
        day['bias'] = b if pb == 'BUY' else -b
        for k in ('expected_move', 'target', 'target_dir', 'target_anchor', 'target_is_est', 'expected_range', 'move_match_n'):
            day.pop(k, None)                       # recompute projection for the flipped direction

    # ── DECISION-DAY CONTINUATION (highest priority on the day after a Decision Day) ──
    # the decision day is a PAUSE; the trend (net of the 3 days before it) RESUMES today.
    dc = decision_continuation(date_str, today) if not day.get('market_closed') else None
    if dc:
        day['after_decision'] = True
        day['prev_decision_date'] = dc['prev']
        day['prev_decision_change'] = dc['prev_change']
        day['decision_dir'] = dc['dir']
        day['decision_high'] = dc['decision_high']
        day['decision_low'] = dc['decision_low']
        day['trend_net'] = dc['trend_net']
        day['signal'] = dc['dir']
        day['signal_src'] = 'decision'
        b = abs(day.get('bias') or 30)
        day['bias'] = b if dc['dir'] == 'BUY' else -b
        for k in ('expected_move', 'target', 'target_dir', 'target_anchor', 'target_is_est', 'expected_range', 'move_match_n'):
            day.pop(k, None)                       # recompute projection for the decision direction

    # Directional projection: how far it can go (up for BUY, down for SELL)
    signame = day.get('signal')
    moves = DATA.get('moves', {})
    if 'expected_move' not in day and moves and signame in ('BUY', 'STRONG BUY', 'SELL', 'STRONG SELL'):
        mm = _matching_moves(date_str, day.get('sign'), day.get('stage'))   # same Sign+Stage history
        anchor = day.get('open') or _chained_anchor(date_str, today) or moves.get('last_close') or 0
        strong = 'STRONG' in signame
        if 'BUY' in signame:
            mv = mm['avg_up'] * (1.4 if strong else 1.0)
            day['target_dir'] = 'up'
        else:
            mv = mm['avg_down'] * (1.4 if strong else 1.0)
            day['target_dir'] = 'down'
        mv = round(mv, 2)
        day['expected_move'] = mv                                   # $ it can move
        day['expected_range'] = mm.get('avg_range')
        day['move_match_n'] = mm.get('n')                           # # of matching days used
        if anchor:
            day['target'] = round(anchor + mv if 'BUY' in signame else anchor - mv, 2)
            day['target_anchor'] = round(anchor, 2)
            day['target_is_est'] = day.get('open') is None          # future days anchor on last close

    # ── RULE 3: important DATE (day-of-month digit-root 3/7/9) amplifies the move ──
    day['power_date'] = _date_digit_root(date_str) in (3, 7, 9)
    if day.get('power_date') and day.get('expected_move'):
        day['expected_move'] = round(day['expected_move'] * 1.2, 2)
        anc = day.get('target_anchor')
        if anc is not None and day.get('target_dir'):
            day['target'] = round(anc + day['expected_move'] if day['target_dir'] == 'up' else anc - day['expected_move'], 2)
        if day.get('confidence'):
            day['confidence'] = min(100, day['confidence'] + 6)

    # WIN/LOSS via 1:1 target + breakeven-stop trail, evaluated over a 3-trading-day window
    # (a correct call can pay off within ~3 days, e.g. June-2 SELL -> June-3 drop).
    sg = day.get('signal')
    if (p and day.get('is_past') and sg in ('BUY', 'STRONG BUY', 'SELL', 'STRONG SELL')
            and day.get('expected_move') and day.get('signal_src') != 'decision'):  # decision days handled by plan4h
        mv = day['expected_move']; ddir = 'BUY' if 'BUY' in sg else 'SELL'
        entry = _pp_for(date_str) or p.get('open')
        if entry:
            if ddir == 'BUY':
                day['tp'] = round(entry + mv, 2); day['sl'] = round(entry - mv, 2); day['be'] = round(entry + 0.5*mv, 2)
            else:
                day['tp'] = round(entry - mv, 2); day['sl'] = round(entry + mv, 2); day['be'] = round(entry - 0.5*mv, 2)
            day['entry'] = round(entry, 2); day['rr'] = '1:1'; day['tp_window'] = 3
            out, th, sh = _tp_window(date_str, ddir, mv, entry, 3)   # 1:1 + breakeven trail
            day['tp_hit'] = th; day['sl_hit'] = sh
            if out is not None:
                day['outcome'] = out; day['correct'] = (out == 'W')

    # candle-shape & trend context (display only — does NOT drive the signal)
    if p:
        cn = _candle_note(p)
        if cn: day['candle_note'] = cn
    tn = _trend_note(date_str)
    if tn: day['trend_note'] = tn

    # ── NATURE-CYCLE MODEL (second opinion, shown alongside) ──
    mi = _model_info(date_str, today)
    if mi:
        day['model_dir'] = mi['dir']
        day['model_reason'] = mi['reason']
        prim = day.get('signal') or ''
        prim_dir = 'BUY' if 'BUY' in prim else ('SELL' if 'SELL' in prim else None)
        day['model_agree'] = (prim_dir == mi['dir']) if prim_dir else None
        if m:
            mm = _matching_moves(date_str, m['sign'], m['stage'])
            mv = round(mm['avg_up'] if mi['dir'] == 'BUY' else mm['avg_down'], 2)
            # entry = Pivot Point for past/today; chained projection for future days
            if date_str <= today:
                anchor = _pp_for(date_str) or day.get('open') or _chained_anchor(date_str, today) or DATA.get('moves', {}).get('last_close') or 0
            else:
                anchor = _chained_anchor(date_str, today) or DATA.get('moves', {}).get('last_close') or 0
            day['model_move'] = mv
            if anchor:
                if mi['dir'] == 'BUY':
                    day['model_anchor'] = round(anchor, 2); day['model_tp'] = round(anchor + mv, 2)
                    day['model_be'] = round(anchor + 0.5*mv, 2); day['model_invalidate'] = round(anchor - mv, 2)
                    day['model_exp_high'] = round(anchor + mv, 2); day['model_exp_low'] = round(anchor - 0.4*mv, 2)
                else:
                    day['model_anchor'] = round(anchor, 2); day['model_tp'] = round(anchor - mv, 2)
                    day['model_be'] = round(anchor - 0.5*mv, 2); day['model_invalidate'] = round(anchor + mv, 2)
                    day['model_exp_high'] = round(anchor + 0.4*mv, 2); day['model_exp_low'] = round(anchor - mv, 2)
            if p and day.get('is_past') and anchor:
                out, th, sh = _tp_window(date_str, mi['dir'], mv, anchor, 3)   # entry=PP, 1:1 + BE trail
                day['model_tp_hit'] = th; day['model_sl_hit'] = sh
                if out is not None:
                    day['model_outcome'] = out; day['model_correct'] = (out == 'W')

    # ── WEEKLY-DIRECTION FILTER (trade only WITH the week's bias) ──
    wb = _weekly_bias(date_str)
    day['weekly_bias'] = ('bull' if wb == 1 else 'bear' if wb == -1 else None)
    md = day.get('model_dir')
    if md and wb is not None:
        day['model_with_trend'] = (md == 'BUY' and wb == 1) or (md == 'SELL' and wb == -1)
    else:
        day['model_with_trend'] = True
    sgd = 'BUY' if (sg and 'BUY' in sg) else ('SELL' if (sg and 'SELL' in sg) else None)
    if sgd and wb is not None:
        day['with_trend'] = (sgd == 'BUY' and wb == 1) or (sgd == 'SELL' and wb == -1)
    else:
        day['with_trend'] = True

    # ── DECISION DAY flag (this day itself closed small, within ±10) ──
    if not day.get('market_closed'):
        ch = day.get('change')
        if ch is not None and abs(ch) <= DECISION_MAX:
            day['decision_day'] = True
            day['decision_change'] = round(ch, 2)

    # ── 4-HOUR TRADING PLAN (daily/decision signal → entry → 4H stop/TP) ──
    sg2 = day.get('signal') or ''
    pdir = 'BUY' if 'BUY' in sg2 else ('SELL' if 'SELL' in sg2 else None)
    if pdir and not day.get('market_closed'):
        plan = None
        if day.get('signal_src') == 'decision' and dc:
            plan = build_decision_plan(date_str, dc, today)   # trend-continuation zone plan
        if plan is None:
            plan = build_4h_plan(date_str, pdir, today)       # normal pivot plan
        if plan:
            day['plan4h'] = plan
            # for decision days, mirror the plan's entry/stop/target into the Signal section
            if day.get('signal_src') == 'decision':
                day['entry'] = plan.get('entry'); day['tp'] = plan.get('target')
                day['sl'] = plan.get('stop'); day['be'] = plan.get('be')
                if plan.get('outcome') in ('W', 'L', 'NF'):
                    day['outcome'] = plan['outcome']; day['correct'] = (plan['outcome'] == 'W')

    # ── MULTI-TIMEFRAME TREND FILTER: label the signal with-trend vs counter-trend ──
    regime = _daily_trend_asof(date_str)            # daily trend going into this day
    day['trend_regime'] = regime
    sdir = 'BUY' if 'BUY' in (day.get('signal') or '') else ('SELL' if 'SELL' in (day.get('signal') or '') else None)
    if sdir and regime in ('UP', 'DOWN'):
        wt = (sdir == 'BUY' and regime == 'UP') or (sdir == 'SELL' and regime == 'DOWN')
        day['mtf_with_trend'] = wt
        day['mtf_label'] = 'WITH-TREND' if wt else 'COUNTER-TREND PULLBACK'
    else:
        day['mtf_with_trend'] = None
        day['mtf_label'] = None                     # no directional signal, or flat regime

    # one-line "why" explanation
    day['reason'] = _signal_reason(day)

    # USD high-impact news (Forex Factory)
    nws = news.get_for(date_str)
    day['usd_news'] = nws
    day['usd_news_count'] = len(nws)
    return _clean_nan(day)

# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    # Unified shell: tab bar that switches between the two dashboards
    return render_template('shell.html')

@app.route('/gold')
def gold_dashboard():
    # The moon-calendar / prediction dashboard (uses local Excel via Flask APIs)
    return render_template('index.html')

@app.route('/adham')
def adham_dashboard():
    # The ADHAM intraday XAUUSD dashboard (self-contained, fetches Google Sheets + gold-api)
    return send_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'adham.html'))

@app.route('/api/calendar/<int:year>/<int:month>')
def api_calendar(year, month):
    days = monthrange(year, month)[1]
    return jsonify([build_day('%d-%02d-%02d' % (year, month, d)) for d in range(1, days+1)])

@app.route('/api/day/<date_str>')
def api_day(date_str):
    return jsonify(build_day(date_str))

@app.route('/api/levels')
def api_levels():
    """Today's pivot/reference levels + each level's historical hold/break reaction %."""
    days = sorted(DATA['prices'])
    if not days:
        return jsonify({'levels': []})
    y = DATA['prices'][days[-1]]
    if None in (y.get('high'), y.get('low'), y.get('close')):
        return jsonify({'levels': []})
    lv = _pivots_from(y); ls = DATA.get('level_stats', {})
    out = []
    for name, price in lv.items():
        s = ls.get(name, {})
        hold = s.get('hold_pct')
        out.append({'name': name, 'price': round(price, 2), 'type': s.get('type'),
                    'touch_pct': s.get('touch_pct'), 'hold_pct': hold,
                    'break_pct': (100 - hold) if hold is not None else None, 'n': s.get('n')})
    out.sort(key=lambda x: -x['price'])
    return jsonify({'based_on': days[-1], 'levels': out})

# ── LIVE PRICE (spot, matches broker/chart) ───────────────────────────────────
@app.route('/api/live-price')
def live_price():
    try:
        # SPOT gold from gold-api.com (same instrument as your chart / ADHAM side)
        g = req.get('https://api.gold-api.com/price/XAU', timeout=8).json()
        current = float(g.get('price') or 0)

        today_str = datetime.today().strftime('%Y-%m-%d')
        closed = market_closed_reason(today_str, today_str)   # weekend / holiday now?

        # Last close (most recent trading day) from the sheet — spot OHLC + midpoint
        last_close = None
        prev = current
        dates_sorted = sorted(DATA['prices'])
        if dates_sorted:
            ld = dates_sorted[-1]
            lp = DATA['prices'][ld]
            mid = round((lp['high'] + lp['low']) / 2, 2) if (lp.get('high') and lp.get('low')) else None
            # Pivot Point (PP) = (High + Low + Close) / 3 — the day's pivot / tomorrow's entry level
            pp = round((lp['high'] + lp['low'] + lp['close']) / 3, 2) if (
                lp.get('high') is not None and lp.get('low') is not None and lp.get('close') is not None) else None
            close_val = lp['close']
            if closed and current:
                # market shut → the live spot IS that day's true last-traded close
                close_val = round(current, 2)
            last_close = {
                'date': ld, 'open': lp['open'], 'high': lp['high'],
                'low': lp['low'], 'close': close_val, 'mid': mid, 'pp': pp,
                'direction': lp['direction'],
            }
            if closed and len(dates_sorted) >= 2:
                prev = DATA['prices'][dates_sorted[-2]]['close'] or current  # prior day → real day-move
            else:
                prev = lp['close'] or current

        change  = round(current - float(prev), 2)
        chg_pct = round(change / float(prev) * 100, 2) if prev else 0

        # Today's running O/H/L from H1 candles (+ fold in the live price)
        today  = datetime.today().strftime('%Y-%m-%d')
        closed = market_closed_reason(today, today)        # weekend / holiday → no running OHLC
        todays = [] if closed else [c for c in DATA.get('h1', []) if str(c.get('dt', '')).startswith(today)]
        if not todays and not closed:
            # sheet has no 1-hour data for today yet → use today's 4-hour candles
            todays = [c for c in DATA.get('h4', []) if str(c.get('dt', '')).startswith(today)]
        t_open = t_high = t_low = None
        if todays:
            t_open = round(todays[0]['open'], 2)
            highs = [c['high'] for c in todays if c.get('high') is not None]
            lows  = [c['low']  for c in todays if c.get('low')  is not None]
            t_high = round(max(highs), 2) if highs else None
            t_low  = round(min(lows), 2) if lows else None
            if t_high is not None and current and current > t_high: t_high = round(current, 2)
            if t_low  is not None and current and current < t_low:  t_low  = round(current, 2)

        time_str = '--'
        ua = str(g.get('updatedAt', ''))
        if 'T' in ua:
            time_str = ua.split('T', 1)[1][:5] + ' UTC'

        return jsonify({
            'status': 'ok',
            'price': round(current, 2),
            'prev_close': round(float(prev), 2),
            'change': change,
            'change_pct': chg_pct,
            'market_state': 'CLOSED' if closed else 'OPEN',
            'market_closed': bool(closed),
            'closed_reason': closed,
            'time': time_str,
            'today_open': t_open,
            'today_high': t_high,
            'today_low':  t_low,
            'last_close': last_close,
            'source': 'gold-api.com (spot)',
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/news-refresh')
def news_refresh():
    try:
        touched = news.refresh()
        return jsonify({'status': 'ok', 'days_updated': touched, 'message': 'USD news refreshed for %d days this week.' % touched})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ── REFRESH (re-pull the whole Google Sheet) ──────────────────────────────────
@app.route('/api/refresh-prices')
def refresh_prices():
    try:
        before = len(DATA['prices'])
        ok = load_data_safe()
        return jsonify({
            'status': 'ok' if ok else 'error',
            'total_in_db': len(DATA['prices']),
            'new_days': max(0, len(DATA['prices']) - before),
            'message': 'Reloaded live from Google Sheet (%d price days, %d h1, %d h4).'
                       % (len(DATA['prices']), len(DATA.get('h1', [])), len(DATA.get('h4', []))),
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ── TRADES ────────────────────────────────────────────────────────────────────
@app.route('/api/trades', methods=['GET'])
def get_trades():
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, encoding='utf-8') as f:
            return jsonify(json.load(f))
    return jsonify([])

@app.route('/api/trades', methods=['POST'])
def add_trade():
    trades = []
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, encoding='utf-8') as f:
            trades = json.load(f)
    t = request.json
    t['id'] = '%d_%s' % (len(trades)+1, datetime.now().strftime('%Y%m%d%H%M%S'))
    t['created_at'] = datetime.now().isoformat()
    trades.insert(0, t)
    with open(TRADES_FILE, 'w', encoding='utf-8') as f:
        json.dump(trades, f, indent=2)
    return jsonify(t), 201

@app.route('/api/trades/<tid>', methods=['PUT'])
def update_trade(tid):
    if not os.path.exists(TRADES_FILE): return jsonify({}), 404
    with open(TRADES_FILE, encoding='utf-8') as f: trades = json.load(f)
    for i, t in enumerate(trades):
        if t['id'] == tid:
            trades[i].update(request.json)
            with open(TRADES_FILE, 'w', encoding='utf-8') as f: json.dump(trades, f, indent=2)
            return jsonify(trades[i])
    return jsonify({}), 404

@app.route('/api/trades/<tid>', methods=['DELETE'])
def delete_trade(tid):
    if not os.path.exists(TRADES_FILE): return jsonify({}), 404
    with open(TRADES_FILE, encoding='utf-8') as f: trades = json.load(f)
    trades = [t for t in trades if t['id'] != tid]
    with open(TRADES_FILE, 'w', encoding='utf-8') as f: json.dump(trades, f, indent=2)
    return jsonify({'status': 'deleted'})

# ── PRICE HISTORY (for charts) ────────────────────────────────────────────────
@app.route('/api/prices/<int:days>')
def price_history(days):
    sorted_items = sorted(DATA['prices'].items())[-days:]
    return jsonify([{
        'date': d, 'open': v['open'], 'high': v['high'],
        'low': v['low'], 'close': v['close'],
        'change': v['change'], 'rng': v['rng'], 'direction': v['direction'],
    } for d, v in sorted_items])

# ── FORECAST (future predictions) ─────────────────────────────────────────────
@app.route('/api/forecast/<int:days>')
def forecast(days):
    # Kept for backward-compat: pure future window of N days
    from datetime import timedelta
    today = datetime.today()
    result = []
    for i in range(days):
        d = (today + timedelta(days=i)).strftime('%Y-%m-%d')
        day = build_day(d)
        if day.get('sign'):
            result.append(day)
    return jsonify(result)

@app.route('/api/forecast-range')
@app.route('/api/forecast-range/<int:past>/<int:future>')
def forecast_range(past=20, future=30):
    """Combined window: last `past` days + next `future` days (default 20 + 30)."""
    from datetime import timedelta
    today = datetime.today()
    result = []
    for i in range(-past, future + 1):
        d = (today + timedelta(days=i)).strftime('%Y-%m-%d')
        day = build_day(d)
        if day.get('sign') and not day.get('market_closed'):   # trading days only
            result.append(day)
    return jsonify(result)

# ── ANALYSIS ──────────────────────────────────────────────────────────────────
@app.route('/api/analysis')
def analysis():
    from collections import defaultdict
    combos = defaultdict(lambda: {'bull': 0, 'bear': 0, 'bull_moves': [], 'bear_moves': []})
    for d, p in DATA['prices'].items():
        m = DATA['moon'].get(d)
        if not m: continue
        key = '%s|%s' % (m['sign'], m['stage'])
        if p['direction'] == 'BULL':
            combos[key]['bull'] += 1
            if p.get('change'): combos[key]['bull_moves'].append(p['change'])
        else:
            combos[key]['bear'] += 1
            if p.get('change'): combos[key]['bear_moves'].append(p['change'])
    result = []
    for key, v in combos.items():
        sign, stage = key.split('|')
        total = v['bull'] + v['bear']
        if total < 2: continue
        bp = v['bull'] / total; brp = v['bear'] / total
        bias = 'BUY' if bp > brp else ('SELL' if brp > bp else 'WAIT')
        sign_info = DATA['signs'].get(sign, {})
        result.append({
            'sign': sign, 'stage': stage, 'total': total,
            'bull': v['bull'], 'bear': v['bear'],
            'bull_pct': round(bp * 100, 1), 'bear_pct': round(brp * 100, 1),
            'bias': bias, 'win_rate': round(max(bp, brp) * 100, 1),
            'sign_emoji': sign_info.get('emoji', ''),
            'avg_bull': round(sum(v['bull_moves']) / len(v['bull_moves']), 1) if v['bull_moves'] else 0,
            'avg_bear': round(sum(v['bear_moves']) / len(v['bear_moves']), 1) if v['bear_moves'] else 0,
        })
    result.sort(key=lambda x: x['win_rate'], reverse=True)
    return jsonify(result)

# ── STATS (overall + monthly) ─────────────────────────────────────────────────
@app.route('/api/stats')
def stats():
    today = datetime.today().strftime('%Y-%m-%d')
    monthly = {}
    total_correct = total_signals = total_bull = total_bear = 0
    total_be = total_loss = 0
    model_correct = model_total = past_moon_days = 0
    model_be = model_loss = 0
    model_monthly = {}
    streak = cur_streak = 0
    last_correct = None

    for d in sorted(DATA['prices']):
        p = DATA['prices'][d]
        if p['direction'] == 'BULL': total_bull += 1
        else: total_bear += 1
        if d > today: continue
        m = DATA['moon'].get(d)
        if not m: continue
        day = build_day(d)
        past_moon_days += 1
        # MODEL track record — only trades WITH the weekly bias (counter-trend = pullback, skipped)
        # outcome ∈ W/BE/L (1:1 + breakeven trail): R = +1 win, 0 breakeven, -1 loss
        if day.get('model_outcome') is not None and day.get('model_with_trend'):
            mo = day['model_outcome']
            model_total += 1
            mmo = model_monthly.setdefault(d[:7], {'correct': 0, 'total': 0, 'pnl': 0})
            mmo['total'] += 1
            if mo == 'W':
                model_correct += 1; mmo['correct'] += 1; mmo['pnl'] += 100
            elif mo == 'BE':
                model_be += 1
            else:
                model_loss += 1; mmo['pnl'] -= 100
        sig = day.get('signal')
        if sig not in ('BUY', 'SELL', 'STRONG BUY', 'STRONG SELL'): continue
        if not day.get('with_trend'): continue        # primary: skip counter-trend trades
        is_buy = 'BUY' in sig
        month = d[:7]
        if month not in monthly:
            monthly[month] = {'correct': 0, 'total': 0, 'pnl': 0, 'buy': 0, 'sell': 0}
        monthly[month]['total'] += 1
        total_signals += 1
        if is_buy: monthly[month]['buy']  += 1
        else:      monthly[month]['sell'] += 1
        out = day.get('outcome')                       # W / BE / L (1:1 + breakeven trail)
        if out == 'W':
            monthly[month]['correct'] += 1
            monthly[month]['pnl'] += 100
            total_correct += 1
            if last_correct is True: cur_streak += 1
            else: cur_streak = 1
            last_correct = True
        elif out == 'BE':
            total_be += 1                              # breakeven: no streak change, 0 P&L
        else:
            total_loss += 1
            monthly[month]['pnl'] -= 100
            if last_correct is False: cur_streak -= 1
            else: cur_streak = -1
            last_correct = False
        streak = cur_streak

    total_prices = len(DATA['prices'])
    avg_bull_move = avg_bear_move = 0
    bull_moves = [v['change'] for v in DATA['prices'].values() if v['direction']=='BULL' and v.get('change')]
    bear_moves = [v['change'] for v in DATA['prices'].values() if v['direction']=='BEAR' and v.get('change')]
    if bull_moves: avg_bull_move = round(sum(bull_moves)/len(bull_moves), 2)
    if bear_moves: avg_bear_move = round(sum(bear_moves)/len(bear_moves), 2)

    return jsonify({
        'total_prices': total_prices,
        'total_signals': total_signals,
        'total_correct': total_correct,
        'total_be': total_be, 'total_loss': total_loss,
        'win_rate': round(total_correct / total_signals * 100, 1) if total_signals else 0,
        'total_r': total_correct - total_loss,                          # 1:1 → +1 win / -1 loss / 0 BE
        'expectancy': round((total_correct - total_loss) / total_signals, 3) if total_signals else 0,
        'total_pnl': (total_correct - total_loss) * 100,
        'streak': streak,
        'total_bull': total_bull, 'total_bear': total_bear,
        'avg_bull_move': avg_bull_move, 'avg_bear_move': avg_bear_move,
        'model_correct': model_correct, 'model_total': model_total,
        'model_be': model_be, 'model_loss': model_loss,
        'model_win_rate': round(model_correct / model_total * 100, 1) if model_total else 0,
        'model_total_r': model_correct - model_loss,                    # Total Expected R (model)
        'model_expectancy': round((model_correct - model_loss) / model_total, 3) if model_total else 0,
        'model_no_signal': max(0, past_moon_days - model_total),
        'model_monthly': model_monthly,
        'monthly': monthly,
    })

# ── DASHBOARD SUMMARY ─────────────────────────────────────────────────────────
@app.route('/api/trends')
def trends():
    """Trend direction on three timeframes: daily / 4-hour / 1-hour."""
    today_str = datetime.today().strftime('%Y-%m-%d')
    pdays = sorted(DATA['prices'])
    daily_seq = [(DATA['prices'][d].get('close'), DATA['prices'][d].get('open')) for d in pdays]
    h4 = sorted(DATA.get('h4', []), key=lambda c: str(c.get('dt', '')))
    h1 = sorted(DATA.get('h1', []), key=lambda c: str(c.get('dt', '')))
    h4_seq = [(c.get('close'), c.get('open')) for c in h4]
    h1_seq = [(c.get('close'), c.get('open')) for c in h1]
    h1_last = str(h1[-1].get('dt', ''))[:10] if h1 else ''
    h4_last = str(h4[-1].get('dt', ''))[:10] if h4 else ''
    return jsonify({
        'daily': _trend_of(daily_seq, 5),       # last 5 daily candles
        'h4':    _trend_of(h4_seq, 6),           # last 6 four-hour candles (~1 day)
        'h1':    _trend_of(h1_seq, 8),           # last 8 one-hour candles
        'daily_last': pdays[-1] if pdays else '', 'h4_last': h4_last, 'h1_last': h1_last,
        'h1_stale': bool(h1_last and h1_last < today_str),   # sheet's 1H tab lagging?
        'h4_stale': bool(h4_last and h4_last < today_str),
    })

@app.route('/api/telegram-test')
def telegram_test():
    """Send a test Telegram message — visit /api/telegram-test to check your setup."""
    if not notify.configured():
        return jsonify({'ok': False, 'info': 'Not configured. Put your bot token in telegram_config.json.'})
    ok, info = notify.send('✅ Naser Gold test — your Telegram alerts are working.')
    return jsonify({'ok': ok, 'info': info, 'chat_id': notify.discover_chat_id()})

@app.route('/api/telegram-decision')
def telegram_decision():
    """Force-send the current Decision-Day alert (ignores the once-per-day guard)."""
    ok, info = check_decision_telegram(force=True)
    return jsonify({'ok': ok, 'info': info})

@app.route('/api/dashboard')
def dashboard():
    from datetime import timedelta
    today_str = datetime.today().strftime('%Y-%m-%d')
    today_day = build_day(today_str)

    # Last 5 completed TRADING days (skip weekends/holidays)
    recent = []
    for i in range(1, 12):
        d = (datetime.today() - timedelta(days=i)).strftime('%Y-%m-%d')
        day = build_day(d)
        if day.get('close') and not day.get('market_closed'):
            recent.append(day)
        if len(recent) == 5: break

    # Next 7 TRADING days forecast (skip weekends/holidays)
    upcoming = []
    for i in range(1, 16):
        d = (datetime.today() + timedelta(days=i)).strftime('%Y-%m-%d')
        day = build_day(d)
        if day.get('sign') and not day.get('market_closed'):
            upcoming.append(day)
        if len(upcoming) == 7: break

    # End-of-day DECISION DAY alert: did the most recent completed day close small (±10)?
    decision_alert = None
    if recent:
        last = recent[0]                       # most recent completed trading day
        if last.get('decision_day'):
            # the IMMEDIATE next trading day after the decision day (may be today)
            nd = _first_trading_day_after(last['date'], today_str)
            nday = build_day(nd) if nd else None
            decision_alert = {
                'date': last['date'],
                'change': last.get('decision_change'),
                'next_date': nd,
                'next_signal': nday.get('signal') if nday else None,
                'threshold': DECISION_MAX,
            }

    return jsonify({
        'today': today_day,
        'recent': recent,
        'upcoming': upcoming,
        'decision_alert': decision_alert,
    })

# ── TELEGRAM DECISION-DAY ALERT (end of day) ──────────────────────────────────
def _tg_sent_load():
    try:
        with open(TG_SENT_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _tg_sent_save(obj):
    try:
        with open(TG_SENT_FILE, 'w', encoding='utf-8') as f:
            json.dump(obj, f)
    except Exception as e:
        print("Telegram-sent save skipped:", e)

def _decision_telegram_message(dd, nday):
    ch = dd.get('decision_change') or 0
    L = ['⚠️ <b>DECISION DAY</b> — %s' % dd['date'],
         'Closed %s$%.2f (within ±$%g) — market undecided, next day is the breakout.'
         % ('+' if ch >= 0 else '-', abs(ch), DECISION_MAX)]
    if nday and nday.get('decision_dir'):
        p = nday.get('plan4h') or {}
        L += ['', 'Next day <b>%s</b> → <b>%s</b> (trend resumes after the pause)' % (nday['date'], nday['decision_dir'])]
        if p.get('zone_low') is not None and p.get('zone_high') is not None:
            L.append('Entry zone: $%.2f–$%.2f' % (p['zone_low'], p['zone_high']))
        if p.get('stop') is not None:
            L.append('Stop: $%.2f' % p['stop'])
        if p.get('target') is not None:
            L.append('Target: $%.2f' % p['target'])
    return '\n'.join(L)

def check_decision_telegram(force=False):
    """If the most recent COMPLETED trading day is a Decision Day and we have not yet
       alerted for it, send a Telegram message (once per date)."""
    if not notify.configured():
        return False, 'telegram not configured'
    days = [d for d in sorted(DATA['prices']) if DATA['prices'][d].get('change') is not None]
    if not days:
        return False, 'no price data'
    last = days[-1]
    if not _is_decision_day(last):
        return False, 'last day (%s) is not a decision day' % last
    sent = _tg_sent_load()
    if not force and sent.get('last') == last:
        return False, 'already alerted for %s' % last
    today = datetime.today().strftime('%Y-%m-%d')
    nd = _first_trading_day_after(last, today)
    msg = _decision_telegram_message(build_day(last), build_day(nd) if nd else None)
    ok, info = notify.send(msg)
    if ok:
        _tg_sent_save({'last': last})
        print("Telegram decision alert sent for", last)
    else:
        print("Telegram send failed:", info)
    return ok, info

import time as _time
def _auto_refresh_loop(interval=300):
    """Re-pull the Google Sheet + USD news every few minutes so data stays live."""
    while True:
        _time.sleep(interval)
        try:
            load_data_safe()
        except Exception as e:
            print("Auto-refresh (sheet) error:", e)
        try:
            news.refresh(timeout=15)
        except Exception as e:
            print("Auto-refresh (news) error:", e)
        try:
            check_decision_telegram()
        except Exception as e:
            print("Decision Telegram check error:", e)

def _startup_news_refresh():
    try:
        touched = news.refresh(timeout=15)
        print("USD news: %d days this week (cache: %d days total)" % (touched, len(news._CACHE)))
    except Exception as e:
        print("Startup news refresh skipped:", e)

_INITED = False
def init_app():
    """Load data + start background refresh. Runs once, whether launched by
    `python app.py` (local) or by gunicorn/a WSGI server (online host)."""
    global _INITED
    if _INITED:
        return
    _INITED = True
    import threading
    print("Loading live data from Google Sheet...")
    load_data_safe()
    news.load_cache()
    threading.Thread(target=_startup_news_refresh, daemon=True).start()
    threading.Thread(target=_auto_refresh_loop, daemon=True).start()
    try:
        check_decision_telegram()      # fire on startup too, if today's close already qualifies
    except Exception as e:
        print("Startup Telegram check skipped:", e)

# Initialise on import so production servers (gunicorn) also load data.
init_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))   # cloud hosts inject PORT
    print("App ready -> http://localhost:%d" % port)
    app.run(host='0.0.0.0', debug=False, port=port, use_reloader=False)

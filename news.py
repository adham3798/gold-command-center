# -*- coding: utf-8 -*-
"""
USD high-impact news from the Forex Factory weekly calendar feed.

The free FF feed only serves the CURRENT week, so we cache each week's USD
high-impact events into news_cache.json and merge on every refresh. Coverage
therefore grows over time and past weeks stay saved.
"""
import os
import json
import requests as req

FF_URL     = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'news_cache.json')

# in-memory cache: { 'YYYY-MM-DD': [ {time,title,impact}, ... ] }
_CACHE = {}


def load_cache():
    global _CACHE
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding='utf-8') as f:
                _CACHE = json.load(f)
        except Exception:
            _CACHE = {}
    return _CACHE


def _save_cache():
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_CACHE, f, indent=2)
    except Exception:
        pass


def refresh(timeout=12, impact_levels=('High',)):
    """Fetch this week's FF calendar, merge USD events of given impact into cache.
    Returns number of (date) days touched."""
    r = req.get(FF_URL, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}, timeout=timeout)
    data = r.json()
    if not _CACHE:
        load_cache()
    touched = set()
    week = {}                                  # rebuild this week's USD-high days fresh
    for ev in data:
        if ev.get('country') != 'USD':
            continue
        if impact_levels and ev.get('impact') not in impact_levels:
            continue
        ds = str(ev.get('date', ''))           # e.g. 2026-06-01T10:00:00-04:00
        if 'T' not in ds:
            continue
        day, rest = ds.split('T', 1)
        time_str = rest[:5]                     # HH:MM (ET)
        week.setdefault(day, []).append({
            'time': time_str,
            'title': ev.get('title', ''),
            'impact': ev.get('impact', ''),
        })
    # merge: overwrite each day we have fresh data for (keeps other cached weeks)
    for day, evs in week.items():
        _CACHE[day] = evs
        touched.add(day)
    _save_cache()
    return len(touched)


def get_for(date_str):
    """Return list of USD high-impact events for a date (empty if none / unknown)."""
    return _CACHE.get(date_str, [])


def has_news(date_str):
    return len(_CACHE.get(date_str, [])) > 0

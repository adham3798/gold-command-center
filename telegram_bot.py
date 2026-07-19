"""
GOLD COMMAND CENTER — Interactive Telegram Bot
==============================================
Self-contained Flask integration for the Gold dashboard.

What it does
------------
- Two-way chat: ask anything ("what's the bias today?", "should I wait?",
  "where are my levels?") and get an AI answer grounded in the LIVE dashboard
  data (/api/rulebook, /api/live-price, /api/trends).
- Logs your trades / market notes to trades.json (the feedback loop file).
- Captures your weekly outlook to weekly_thoughts.json and feeds it back to
  the AI all week.
- Sends proactive reminders (session opens, news blackout, weekly check-in,
  guardrail lock) via the /telegram/tick endpoint, pinged by a scheduler.

Design notes
------------
- Stdlib only (urllib) — no extra dependencies to install on Render.
- Owner-only: the bot ignores anyone whose chat id != TELEGRAM_CHAT_ID.
- Webhook is processed on a background thread with an immediate 200 ACK, so a
  single gunicorn worker never deadlocks calling its own /api endpoints, and
  Telegram never retries while the LLM is thinking / Render is cold-starting.
- All secrets come from environment variables. Nothing is hard-coded.

Required environment variables (set in the Render dashboard)
------------------------------------------------------------
  TELEGRAM_BOT_TOKEN   token from @BotFather
  TELEGRAM_CHAT_ID     your own chat id (the bot replies only to this id)
  ANTHROPIC_API_KEY    key from console.anthropic.com
Optional:
  BOT_WEBHOOK_SECRET   path secret for the webhook URL (default "hook")
  TICK_KEY             query-string key protecting /telegram/tick (default "tick")
  BASE_URL             public base url (default https://gold-command-center-production.up.railway.app)
  BOT_MODEL            Claude model (default "claude-sonnet-4-6"; use
                       "claude-haiku-4-5-20251001" for cheaper/faster)
  BOT_TZ               timezone for reminders (default "Asia/Dubai")
"""

import os
import json
import time
import csv
import io
import re
import threading
import urllib.request
import urllib.error
import urllib.parse
import datetime as _dt

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

from flask import request, jsonify

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
TG_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER_CHAT = str(os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
AI_KEY     = os.environ.get("ANTHROPIC_API_KEY", "")
HOOK       = os.environ.get("BOT_WEBHOOK_SECRET", "hook")
TICK_KEY   = os.environ.get("TICK_KEY", "tick")
BASE_URL   = os.environ.get("BASE_URL", "https://web-production-44c32.up.railway.app").rstrip("/")
MODEL      = os.environ.get("BOT_MODEL", "claude-sonnet-4-6")
TZNAME     = os.environ.get("BOT_TZ", "Asia/Dubai")

DATA_DIR        = os.environ.get("BOT_DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
TRADES_FILE     = os.path.join(DATA_DIR, "trades.json")
WEEKLY_FILE     = os.path.join(DATA_DIR, "weekly_thoughts.json")
HISTORY_FILE    = os.path.join(DATA_DIR, "bot_history.json")
REMINDER_FILE   = os.path.join(DATA_DIR, "reminder_state.json")
ARCHIVE_FILE    = os.path.join(DATA_DIR, "chat_archive.jsonl")   # append-only, never trimmed
LESSONS_FILE    = os.path.join(DATA_DIR, "lessons.json")         # standing notes the AI always applies

# How many prior turns to feed the model each reply. With the durable /data volume
# this can be large; raise BOT_MAX_HISTORY in the env to give it a longer memory.
MAX_HISTORY = int(os.environ.get("BOT_MAX_HISTORY", "60"))         # recent turns fed to model
MAX_TRADES_CONTEXT = int(os.environ.get("BOT_MAX_TRADES", "25"))   # recent trades fed to AI
MAX_TOKENS = int(os.environ.get("BOT_MAX_TOKENS", "2000"))         # let answers be complete

# ---- Live proactive alerts (driven by /telegram/tick) ----
# These make the bot push updates on its own. The tick can be pinged at any
# frequency (UptimeRobot 5-min recommended); the logic is idempotent and only
# sends when a real condition is met.
ALERT_MOVE_USD    = float(os.environ.get("ALERT_MOVE_USD", "30"))   # $ move since last report that triggers a MOVE alert (raised 10->30 to cut noise)
HEARTBEAT_EVERY_H = int(os.environ.get("HEARTBEAT_EVERY_H", "0"))   # send a heartbeat every N hours (1 = hourly, 0 = off) — off by default to stop hourly spam
LIVE_ALERTS_ON    = os.environ.get("LIVE_ALERTS_ON", "1") not in ("0", "false", "False", "")
QUIET_START_H     = int(os.environ.get("QUIET_START_H", "23"))      # quiet window start hour (local Dubai) — no live pushes 23:00->07:00
QUIET_END_H       = int(os.environ.get("QUIET_END_H", "7"))         # quiet window end hour (local Dubai)

# Gold's standard 4H candle closes are 01/05/09/13/17/21 GMT, which in Asia/Dubai (GMT+4)
# = 05:00, 09:00, 13:00, 17:00, 21:00, 01:00 -> local hours 1,5,9,13,17,21. These are the
# hours (in BOT_TZ) at which the 🕓 4H-close update is sent. Override via FOUR_H_CLOSE_HOURS.
try:
    FOUR_H_CLOSE_HOURS = sorted({int(x) % 24 for x in
                                 os.environ.get("FOUR_H_CLOSE_HOURS", "1,5,9,13,17,21").split(",")
                                 if x.strip() != ""})
except Exception:
    FOUR_H_CLOSE_HOURS = [1, 5, 9, 13, 17, 21]

# Internal self-ticker: because the Railway service never sleeps, the bot can drive its
# own tick loop from a background thread — no external pinger (UptimeRobot/cron) required.
INTERNAL_TICK         = os.environ.get("INTERNAL_TICK", "1") not in ("0", "false", "False", "")
INTERNAL_TICK_SECONDS = max(60, int(os.environ.get("INTERNAL_TICK_SECONDS", "300")))  # default every 5 min

# ---- Gold & Astro Weekly Tracker (Google Sheet) — Section 3 & 4 alerts ----
# Reads the weekly tracker sheet (public "anyone with link -> viewer") via the same gviz
# CSV method the dashboard already uses. Section 3 = planetary transits, Section 4 =
# economic calendar. Fires a heads-up before each timed event, a daily agenda, and a
# Monday week-ahead summary.
# Daily OHLC memory — reads the "daily gold" tab of the price sheet and keeps a durable
# record of each day's Open/High/Low/Close so the bot always "has" the daily candle.
OHLC_SHEET_ID     = os.environ.get("OHLC_SHEET_ID", "12ynlr46bvHSJLnLGs5Z1SrhhlCj6_w7qO6YHMDBY7gs")
OHLC_GID          = os.environ.get("OHLC_GID", "415704171")
OHLC_ON           = os.environ.get("OHLC_ON", "1") not in ("0", "false", "False", "")
OHLC_PUSH_HOUR    = int(os.environ.get("OHLC_PUSH_HOUR", "7"))   # local hour to save + send the daily OHLC
OHLC_CONTEXT_DAYS = int(os.environ.get("OHLC_CONTEXT_DAYS", "15"))
OHLC_FILE         = os.path.join(DATA_DIR, "ohlc_history.json")

# News RESULTS — when an economic event's ACTUAL prints, read gold impact (ForexFactory /
# FairEconomy weekly JSON feed, same source app.py's news.py already uses).
NEWS_FEED_URL   = os.environ.get("NEWS_FEED_URL", "https://nfs.faireconomy.media/ff_calendar_thisweek.json")
NEWS_RESULTS_ON = os.environ.get("NEWS_RESULTS_ON", "1") not in ("0", "false", "False", "")
NEWS_COUNTRIES  = set(x.strip() for x in os.environ.get("NEWS_COUNTRIES", "USD").split(",") if x.strip())
NEWS_IMPACTS    = set(x.strip() for x in os.environ.get("NEWS_IMPACTS", "High,Medium").split(",") if x.strip())
NEWS_REFRESH_SEC = int(os.environ.get("NEWS_REFRESH_SEC", "300"))

TRACKER_SHEET_ID = os.environ.get("TRACKER_SHEET_ID", "13WdYpiBW9gJxJyN5mlq8oYM4M9XR0tMFz3ZFm9RXwjs")
TRACKER_TAB      = os.environ.get("TRACKER_TAB", "").strip()   # blank = auto-detect current week
SHEET_ALERTS_ON  = os.environ.get("SHEET_ALERTS_ON", "1") not in ("0", "false", "False", "")
CAL_LEAD_MIN     = int(os.environ.get("CAL_LEAD_MIN", "15"))   # minutes before each event to ping
CAL_AGENDA_HOUR  = int(os.environ.get("CAL_AGENDA_HOUR", "7")) # local hour for the daily agenda
CAL_WEEKLY_HOUR  = int(os.environ.get("CAL_WEEKLY_HOUR", "3")) # Monday local hour for week-ahead
CAL_REFRESH_SEC  = int(os.environ.get("CAL_REFRESH_SEC", "3600"))  # re-pull sheet at most this often
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# --------------------------------------------------------------------------
# Tiny JSON store helpers (best-effort; Render free disk is ephemeral)
# --------------------------------------------------------------------------
def _load(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, data):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, path)
    except Exception:
        pass


def _append_archive(role, content):
    """Append every message to a permanent, never-trimmed transcript (JSONL)."""
    try:
        with open(ARCHIVE_FILE, "a") as f:
            f.write(json.dumps({"ts": _now().isoformat(),
                                "role": role, "content": content}, default=str) + "\n")
    except Exception:
        pass


def _now():
    if ZoneInfo:
        try:
            return _dt.datetime.now(ZoneInfo(TZNAME))
        except Exception:
            pass
    return _dt.datetime.utcnow()


# --------------------------------------------------------------------------
# HTTP helpers (stdlib)
# --------------------------------------------------------------------------
def _http_json(url, data=None, headers=None, timeout=30):
    headers = headers or {}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=headers,
                                 method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _split_for_telegram(text, limit=3800):
    """Break a long answer into Telegram-sized parts on clean line/word boundaries."""
    text = (text or " ")
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)          # prefer a line break
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)        # else a space
        if cut <= 0:
            cut = limit                            # else hard cut
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text.strip():
        parts.append(text)
    return parts or [" "]


def tg_send(text, chat_id=None):
    """Send a Telegram message, auto-splitting long ones into numbered parts so the
    full answer always comes through without the user asking again."""
    if not TG_TOKEN:
        return
    chat_id = chat_id or OWNER_CHAT
    if not chat_id:
        return
    url = "https://api.telegram.org/bot%s/sendMessage" % TG_TOKEN
    parts = _split_for_telegram(text)
    total = len(parts)
    for idx, chunk in enumerate(parts, 1):
        body = chunk if total == 1 else ("(%d/%d)\n%s" % (idx, total, chunk))
        try:
            _http_json(url, {"chat_id": chat_id, "text": body or " ",
                             "disable_web_page_preview": True}, timeout=20)
        except Exception:
            pass


# --------------------------------------------------------------------------
# Live dashboard context
# --------------------------------------------------------------------------
def fetch_context():
    ctx = {}
    for key, path in (("rulebook", "/api/rulebook"),
                      ("price", "/api/live-price"),
                      ("trends", "/api/trends"),
                      ("structure", "/api/structure"),
                      ("silver", "/api/silver")):
        try:
            ctx[key] = _http_json(BASE_URL + path, timeout=20)
        except Exception as e:
            ctx[key] = {"error": str(e)}
    # /api/dashboard is large (10+ days) — keep only today's object + session header
    try:
        dash = _http_json(BASE_URL + "/api/dashboard", timeout=25)
        ctx["today"] = dash.get("today", {}) or {}
        ctx["session_plan"] = dash.get("session", {}) or {}
    except Exception as e:
        ctx["today"] = {"error": str(e)}
        ctx["session_plan"] = {}
    return ctx


def context_summary(ctx):
    """Compact human-readable snapshot for the AI system prompt."""
    rb = ctx.get("rulebook", {}) or {}
    pr = ctx.get("price", {}) or {}
    tr = ctx.get("trends", {}) or {}
    td = ctx.get("today", {}) or {}
    sv = ctx.get("silver", {}) or {}
    st = ctx.get("structure", {}) or {}
    lc = pr.get("last_close", {}) or {}   # previous completed day = PDH/PDL/PDC
    lvl = rb.get("level", {}) or {}
    gate = rb.get("gate", {}) or {}
    verd = rb.get("verdict", {}) or {}
    sess = rb.get("session", {}) or {}
    news = rb.get("news", {}) or {}
    guard = rb.get("guardrails", {}) or {}
    astro = rb.get("astro", {}) or {}
    lines = [
        "LIVE GOLD (XAU/USD) SNAPSHOT — %s" % _now().strftime("%Y-%m-%d %H:%M %Z"),
        "Spot price: %s (change %s / %s%%)" % (
            pr.get("price"), pr.get("change"), pr.get("change_pct")),
        "Market: %s" % pr.get("market_state"),
        "Daily bias/signal: %s %s  (confidence %s%%)" % (
            rb.get("signal"), rb.get("bias"), rb.get("confidence")),
        "Verdict: %s — %s" % (verd.get("state"), verd.get("reason")),
        "Confluence gate: %s/%s grade %s" % (
            gate.get("score"), gate.get("max"), gate.get("grade")),
        "Session: %s (grade %s, allowed=%s)" % (
            sess.get("name"), sess.get("grade"), sess.get("allowed")),
        "Nearest level: %s @ %s (dist %s / %s%%, at_level=%s)" % (
            lvl.get("nearest"), lvl.get("price"), lvl.get("dist"),
            lvl.get("dist_pct"), lvl.get("at_level")),
        "Prev day (PDH/PDL/PDC): %s / %s / %s" % (
            lc.get("high"), lc.get("low"), lc.get("close")),
        "News: blackout=%s, next=%s, today_count=%s" % (
            news.get("blackout"), news.get("next"), news.get("today_count")),
        "Guardrails: locked=%s, trades=%s, wins=%s, losses=%s, day_R=%s, reason=%s" % (
            guard.get("locked"), guard.get("trades"), guard.get("wins"),
            guard.get("losses"), guard.get("day_r"), guard.get("reason")),
        "Astro: %s, day#%s, power=%s, watch=%s" % (
            astro.get("phase"), astro.get("day_number"),
            astro.get("power"), astro.get("watch")),
    ]

    # ---- Multi-timeframe trend (from /api/trends) ----
    def _tf(o):
        o = o or {}
        return "%s (last %s, %s/%s bars bull, net %s)" % (
            o.get("dir"), o.get("last"), o.get("bull"), o.get("bars"), o.get("net"))
    rev = tr.get("reversal", {}) or {}
    if tr:
        lines += [
            "",
            "MULTI-TIMEFRAME TREND:",
            "  Daily: %s" % _tf(tr.get("daily")),
            "  H4:    %s%s" % (_tf(tr.get("h4")), " [STALE]" if tr.get("h4_stale") else ""),
            "  H1:    %s%s" % (_tf(tr.get("h1")), " [STALE]" if tr.get("h1_stale") else ""),
            "  Reversal state: %s — %s" % (rev.get("label"), rev.get("detail")),
        ]

    # ---- Market structure (HH/HL vs LH/LL, from /api/structure) ----
    def _st(o):
        o = o or {}
        return "%s — %s" % (o.get("label") or "n/a", o.get("detail") or "")
    if st and not st.get("error"):
        lines += [
            "",
            "MARKET STRUCTURE (swing highs/lows):",
            "  Daily: %s" % _st(st.get("daily")),
            "  H4:    %s" % _st(st.get("h4")),
            "  H1:    %s" % _st(st.get("h1")),
            "  Alignment: %s" % st.get("alignment"),
        ]

    # ---- Today's model + 4H plan + news (from /api/dashboard 'today') ----
    if td and not td.get("error"):
        p4 = td.get("plan4h", {}) or {}
        news_list = td.get("usd_news") or []
        news_txt = "none scheduled" if not news_list else "; ".join(
            (str(n) if not isinstance(n, dict)
             else "%s %s (%s)" % (n.get("time", ""), n.get("title", n.get("event", "")),
                                  n.get("impact", ""))).strip()
            for n in news_list)
        lines += [
            "",
            "TODAY'S MODEL (astro+MTF engine):",
            "  Signal %s | dir %s | trend_regime %s | mtf_label %s" % (
                td.get("signal"), td.get("dir"), td.get("trend_regime"), td.get("mtf_label")),
            "  Expected move %s / range %s | confidence %s%% | with_trend=%s" % (
                td.get("expected_move"), td.get("expected_range"),
                td.get("confidence"), td.get("with_trend")),
            "  wait_4h=%s%s" % (
                td.get("wait_4h"),
                (" — " + td.get("wait_4h_msg", "")) if td.get("wait_4h") else ""),
            "  4H PLAN: %s %s | entry %s (%s) | stop %s | target %s" % (
                p4.get("dir"), (p4.get("advice") or "").split(" — ")[0],
                p4.get("entry"), p4.get("entry_label"),
                p4.get("stop"), p4.get("target")),
            "  4H advice: %s" % p4.get("advice"),
            "  USD news today (%s): %s" % (td.get("usd_news_count", 0), news_txt),
        ]

    # ---- Silver cross-check ----
    if sv and not sv.get("error"):
        lines.append("")
        lines.append("Silver cross-check: regime=%s, corr=%s (%s)" % (
            sv.get("regime") or sv.get("verdict"), sv.get("corr") or sv.get("correlation"),
            sv.get("note", "")))

    # ---- Today's tracker events (Section 3 transits + Section 4 econ) ----
    try:
        cal = get_calendar(_now())
        todays = [e for e in (cal["astro"] + cal["econ"]) if _is_today(e["date"], _now())]
        todays.sort(key=_time_key)
        if todays:
            lines.append("")
            lines.append("TODAY'S TRACKER (Sec 3 & 4) — %s:" % (cal.get("tab") or ""))
            for e in todays:
                lines.append("  " + _fmt_event(e))
    except Exception:
        pass

    return "\n".join(lines)


# --------------------------------------------------------------------------
# AI
# --------------------------------------------------------------------------
SYSTEM_PROMPT = """You are GoldOS, the trading copilot inside Adham's Gold Command Center.
You are an expert in XAU/USD intraday and swing trading.
Adham trades on the higher timeframes only (spot / 1H / 4H / daily). Do NOT
recommend 5-minute or 15-minute scalps — that low-timeframe noise was removed on
purpose because it cost money. Keep every read on the 1H/4H/daily structure.

Rules of engagement:
- Ground EVERY answer in the LIVE SNAPSHOT and the trading rules below. Quote the
  actual numbers (price, levels, gate score, verdict) instead of being vague.
- Respect the no-trade gate: if verdict is WAIT or STAND DOWN, say so plainly and
  explain what would need to change to take a trade.
- Honor guardrails: if locked, the answer is STAND DOWN regardless of setup.
- During a news blackout, no entries.
- Be concise and direct. Lead with the answer, then the reason. No fluff.
- Give the COMPLETE answer in one turn. Never ask "should I continue?", never stop
  halfway, never tell Adham to ask again. Long replies are delivered automatically in
  multiple parts, so just write the full picture — don't truncate or hold anything back.
- Never make Adham repeat himself. You have durable memory of the whole conversation,
  his trade journal, his weekly outlook and his standing lessons (all below when present).
  If he already told you something, use it instead of asking again.
- You give information and structured reasoning, NOT licensed financial advice;
  the final decision and risk is always Adham's.

For TREND questions, lead with the MARKET STRUCTURE block (swing highs/lows) — this is
the real read: HH+HL = uptrend, LH+LL = downtrend, HH+LL = broadening/volatile, LH+HL =
contracting/coiling. Combine it with the MULTI-TIMEFRAME TREND direction + reversal state.
State the alignment plainly (e.g. "Daily LH+LL downtrend, but H4 and H1 now HH+HL —
structure turning up, reversal building"), then what it means for entries. Honor the
wait_4h flag: if the daily signal needs the 4-hour to confirm and it hasn't, say wait. If
a timeframe is marked STALE or structure says insufficient bars, note the data is missing
rather than guessing.

Trading framework (the rulebook this dashboard implements):
- Confluence gate scored 0-8 -> grade A (>=6), B (4-5), C (<4). Only A-grade
  setups are full size; B is reduced size or skip; C is no trade.
- Inputs: price at a ranked pivot level, directional daily bias, active session
  clear of news, multi-timeframe alignment, astro confluence (bonus).
- Risk 0.5% per trade, target R=2. Day stop at -3R; lock after 3 losses or 5 trades.
- Sessions: London-NY overlap is the A-grade window.

If the user logs a trade or shares a weekly view, acknowledge briefly and tell them
it's saved. Use their stored WEEKLY OUTLOOK as standing context for the week.

WEEKLY GOLD & ASTRO TRACKER: You are given the current week's tracker sheet below (under
"THIS WEEK'S GOLD & ASTRO TRACKER"). It is Adham's own weekly database and updates every
week (a new tab is added each week; you always get the current one). It contains the daily
snapshot, position-sizing guide, moon phases, planetary positions, the key planetary
transits (Section 3) and the economic calendar (Section 4) — all in Dubai time. When Adham
asks about astrology, moon phase, planetary transits/positions, critical degrees, economic
events, or "what's on today/this week", ANSWER FROM THIS TRACKER — quote the specific dates,
Dubai times, aspects and events. Combine it with the live price/trend snapshot for a full
read. If the tracker is missing or a detail isn't in it, say so rather than inventing.

MEMORY & LEARNING: You are given STANDING LESSONS and a RECENT TRADE JOURNAL below when
available. Treat the STANDING LESSONS as hard rules Adham has taught you — always apply
them and mention when one is relevant. Use the TRADE JOURNAL to learn from what has and
hasn't worked: reference past trades, point out repeating mistakes or patterns, and adapt
your guidance accordingly. The goal is to get sharper over time, not give generic answers."""


def ask_ai(question, ctx, history, weekly):
    if not AI_KEY:
        return ("AI key not set yet. Add ANTHROPIC_API_KEY in Render -> Environment, "
                "then redeploy. Meanwhile you can use /today, /levels, /log and /week.")
    snap = context_summary(ctx)
    weekly_txt = ""
    if weekly:
        last = weekly[-1]
        weekly_txt = "\n\nADHAM'S CURRENT WEEKLY OUTLOOK (saved %s):\n%s" % (
            last.get("ts", "?"), last.get("text", ""))

    # Standing lessons the AI must always apply (added via /learn)
    lessons = _load(LESSONS_FILE, [])
    lessons_txt = ""
    if isinstance(lessons, list) and lessons:
        lines = ["\n\n=== STANDING LESSONS (always apply these) ==="]
        for i, ls in enumerate(lessons, 1):
            lines.append("%d. %s" % (i, ls.get("text", ls) if isinstance(ls, dict) else ls))
        lessons_txt = "\n".join(lines)

    # Recent trade journal so the AI learns from past trades
    trades = _load(TRADES_FILE, [])
    trades_txt = ""
    if isinstance(trades, list) and trades:
        recent = trades[-MAX_TRADES_CONTEXT:]
        lines = ["\n\n=== RECENT TRADE JOURNAL (%d of %d entries) ===" % (
            len(recent), len(trades))]
        for t in recent:
            if isinstance(t, dict):
                lines.append("- %s: %s" % (t.get("ts", "?"), t.get("note", "")))
            else:
                lines.append("- %s" % t)
        trades_txt = "\n".join(lines)

    # This week's Gold & Astro Tracker sheet = the bot's weekly "database" (auto-follows
    # whichever weekly tab is current). Grounds astro / transit / news / econ answers.
    tracker_txt = ""
    try:
        tracker_txt = ("\n\n=== THIS WEEK'S GOLD & ASTRO TRACKER (live from your sheet) ===\n"
                       + tracker_context_text(_now()))
    except Exception:
        tracker_txt = ""

    # Durable daily OHLC memory (the "daily gold" sheet).
    ohlc_txt = ""
    try:
        ohlc_txt = "\n\n=== DAILY OHLC MEMORY ===\n" + ohlc_context_text(_now())
    except Exception:
        ohlc_txt = ""

    # Recent news results (actual vs forecast) from ForexFactory.
    news_txt = ""
    try:
        nt = news_context_text(_now())
        if nt:
            news_txt = "\n\n=== " + nt
    except Exception:
        news_txt = ""

    sys = (SYSTEM_PROMPT + "\n\n=== LIVE SNAPSHOT ===\n" + snap
           + weekly_txt + lessons_txt + trades_txt + tracker_txt + ohlc_txt + news_txt)

    messages = []
    for turn in history[-MAX_HISTORY:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": question})

    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": sys,
        "messages": messages,
    }
    headers = {
        "x-api-key": AI_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    try:
        resp = _http_json("https://api.anthropic.com/v1/messages",
                          data=payload, headers=headers, timeout=60)
        parts = resp.get("content", [])
        text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        return text.strip() or "(no answer)"
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:
            detail = ""
        return "AI error %s. %s" % (e.code, detail)
    except Exception as e:
        return "AI error: %s" % e


# --------------------------------------------------------------------------
# Command handlers
# --------------------------------------------------------------------------
HELP = """GoldOS bot — what I can do:

Just type a question and I'll answer from the live dashboard, e.g.
  "what's the bias today?"  /  "should I take a long here?"  /  "where are my levels?"

Commands:
  /today    quick live snapshot (bias, verdict, gate, price)
  /trend    Daily/H4/H1 trend + market structure (HH/HL vs LH/LL) + 4H plan
  /levels   today's pivots + day high/low
  /log ...  log a trade or note  (e.g. /log long 4120, +1.5R, news spike)
  /week ... save your weekly outlook  (referenced all week)
  /weekshow show your current weekly outlook
  /learn ... teach me a standing rule I apply forever (e.g. /learn skip Asia session)
  /lessons  show every standing rule you've taught me
  /events   today's Section 3 (transits) + Section 4 (economic) events
  /calendar this week's tracker (add "next" for next week: /calendar next)
  /ohlc     latest daily gold OHLC + last 7 days (saved in memory)
  /news     this week's USD news: actual vs forecast + gold read
  /help     this message

I also watch the market for you and push alerts on my own:
  ⏱ hourly heartbeat (price, H1/H4 trend, nearest level)
  🕓 a fuller update at each 4H candle close (structure + 4H plan)
  📈 a MOVE alert whenever gold jumps more than $%d since the last report
  🎯 a LEVEL alert the moment price reaches a support/resistance pivot
  ⏰ a heads-up ~%d min before every Section 3 transit & Section 4 econ event
  🗓️ a daily agenda each morning + a week-ahead summary every Monday
  🗞️ a RESULT alert when a news actual prints (actual vs forecast → gold read)
  📊 the daily gold OHLC each morning (saved in memory)
(plus morning brief, London-NY overlap, news blackout & guardrail lock).""" % (
    int(ALERT_MOVE_USD), CAL_LEAD_MIN) + """

I remember our full history, your trade journal, and your lessons — all saved
durably, so I keep learning from them."""


def cmd_today(ctx):
    return context_summary(ctx)


def cmd_levels(ctx):
    rb = ctx.get("rulebook", {}) or {}
    pr = ctx.get("price", {}) or {}
    lvl = rb.get("level", {}) or {}
    lc = pr.get("last_close", {}) or {}
    return ("LEVELS\n"
            "Spot: %s\n"
            "Nearest: %s @ %s (dist %s / %s%%)\n"
            "PDH %s | PDL %s | PDC %s" % (
                pr.get("price"),
                lvl.get("nearest"), lvl.get("price"), lvl.get("dist"),
                lvl.get("dist_pct"),
                lc.get("high"), lc.get("low"), lc.get("close")))


def cmd_trend(ctx):
    tr = ctx.get("trends", {}) or {}
    td = ctx.get("today", {}) or {}
    st = ctx.get("structure", {}) or {}
    rev = tr.get("reversal", {}) or {}
    p4 = td.get("plan4h", {}) or {}

    def _tf(o):
        o = o or {}
        return "%s (last %s, %s/%s bars bull)" % (
            o.get("dir"), o.get("last"), o.get("bull"), o.get("bars"))

    def _st(o):
        o = o or {}
        return "%s — %s" % (o.get("label") or "n/a", o.get("detail") or "")

    struct_block = ""
    if st and not st.get("error"):
        struct_block = ("\nSTRUCTURE (swing highs/lows)\n"
                        "Daily: %s\nH4:    %s\nH1:    %s\nAlignment: %s\n" % (
                            _st(st.get("daily")), _st(st.get("h4")),
                            _st(st.get("h1")), st.get("alignment")))

    return ("MULTI-TIMEFRAME TREND\n"
            "Daily: %s\nH4:    %s\nH1:    %s\n"
            "State: %s — %s\n%s\n"
            "4H plan: %s entry %s, stop %s, target %s\n%s" % (
                _tf(tr.get("daily")), _tf(tr.get("h4")), _tf(tr.get("h1")),
                rev.get("label"), rev.get("detail"), struct_block,
                p4.get("dir"), p4.get("entry"), p4.get("stop"), p4.get("target"),
                p4.get("advice", "")))


def cmd_log(text):
    trades = _load(TRADES_FILE, [])
    if not isinstance(trades, list):
        trades = []
    entry = {"ts": _now().isoformat(), "note": text}
    trades.append(entry)
    _save(TRADES_FILE, trades)
    return "Logged ✓ (%d entries today's file). %s" % (len(trades), text)


def cmd_week(text):
    weekly = _load(WEEKLY_FILE, [])
    if not isinstance(weekly, list):
        weekly = []
    weekly.append({"ts": _now().isoformat(), "text": text})
    _save(WEEKLY_FILE, weekly)
    return "Weekly outlook saved ✓ — I'll factor this into answers all week."


def cmd_weekshow():
    weekly = _load(WEEKLY_FILE, [])
    if not weekly:
        return "No weekly outlook saved yet. Use /week <your view>."
    last = weekly[-1]
    return "Current weekly outlook (saved %s):\n\n%s" % (
        last.get("ts"), last.get("text"))


def cmd_learn(text):
    lessons = _load(LESSONS_FILE, [])
    if not isinstance(lessons, list):
        lessons = []
    lessons.append({"ts": _now().isoformat(), "text": text})
    _save(LESSONS_FILE, lessons)
    return ("Lesson saved ✓ (%d total). I'll apply this to every read from now on:\n\"%s\""
            % (len(lessons), text))


def cmd_lessons():
    lessons = _load(LESSONS_FILE, [])
    if not isinstance(lessons, list) or not lessons:
        return ("No standing lessons yet. Teach me one with /learn <rule>, e.g.\n"
                "/learn don't trade the first 15 min after a red-folder news event.")
    out = ["STANDING LESSONS (applied to every answer):"]
    for i, ls in enumerate(lessons, 1):
        out.append("%d. %s" % (i, ls.get("text", "") if isinstance(ls, dict) else ls))
    return "\n".join(out)


# --------------------------------------------------------------------------
# Message router (runs on a background thread)
# --------------------------------------------------------------------------
def handle_message(chat_id, text):
    text = (text or "").strip()
    if not text:
        return

    low = text.lower()
    if low in ("/start", "start"):
        tg_send("GoldOS online ✅\nYour chat id is: %s\n\n%s" % (chat_id, HELP), chat_id)
        return
    if low in ("/help", "help"):
        tg_send(HELP, chat_id)
        return

    if low.startswith("/log"):
        tg_send(cmd_log(text[4:].strip() or "(empty)"), chat_id)
        return
    if low.startswith("/week") and not low.startswith("/weekshow"):
        body = text[5:].strip()
        tg_send(cmd_week(body) if body else "Add your view: /week <text>", chat_id)
        return
    if low.startswith("/weekshow"):
        tg_send(cmd_weekshow(), chat_id)
        return
    if low.startswith("/learn"):
        body = text[6:].strip()
        tg_send(cmd_learn(body) if body else "Teach me a rule: /learn <lesson>", chat_id)
        return
    if low.startswith("/lessons"):
        tg_send(cmd_lessons(), chat_id)
        return
    if low.startswith("/events") or low.startswith("/today-events"):
        tg_send(daily_agenda_text(get_calendar(_now(), force=True), _now()), chat_id)
        return
    if low.startswith("/calendar") or low.startswith("/week-events") or low.startswith("/astro"):
        want_next = "next" in low
        tab = _week_tab(_now(), 1) if want_next else None
        tg_send(weekly_summary_text(get_calendar(_now(), force=True, tab=tab), _now()), chat_id)
        return
    if low.startswith("/ohlc") or low.startswith("/daily"):
        tg_send(cmd_ohlc(_now()), chat_id)
        return
    if low.startswith("/news"):
        tg_send(cmd_news(_now()), chat_id)
        return

    # Everything below needs live context
    ctx = fetch_context()

    if low.startswith("/today"):
        tg_send(cmd_today(ctx), chat_id)
        return
    if low.startswith("/levels"):
        tg_send(cmd_levels(ctx), chat_id)
        return
    if low.startswith("/trend"):
        tg_send(cmd_trend(ctx), chat_id)
        return

    # Free-form question -> AI
    history = _load(HISTORY_FILE, [])
    if not isinstance(history, list):
        history = []
    weekly = _load(WEEKLY_FILE, [])
    answer = ask_ai(text, ctx, history, weekly)
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": answer})
    _save(HISTORY_FILE, history[-(MAX_HISTORY * 2):])
    # Permanent, never-trimmed record of every exchange (stored on the /data volume)
    _append_archive("user", text)
    _append_archive("assistant", answer)
    tg_send(answer, chat_id)


# --------------------------------------------------------------------------
# Gold & Astro Weekly Tracker — Section 3 (transits) & Section 4 (econ calendar)
# --------------------------------------------------------------------------
_cal_cache = {}   # tab name -> {ts, tab, astro, econ, rows}


def _week_tab(now, offset=0):
    """Tab name for the current week (offset=0) or another week, 'Week Jun29-Jul3' style."""
    monday = now.date() - _dt.timedelta(days=now.weekday()) + _dt.timedelta(days=7 * offset)
    friday = monday + _dt.timedelta(days=4)
    fmt = lambda d: "%s%d" % (d.strftime("%b"), d.day)
    return "Week %s-%s" % (fmt(monday), fmt(friday))


def _current_week_tab(now):
    return _week_tab(now, 0)


def _gviz_csv(sheet_name=None, gid=None, sheet_id=None):
    sid = sheet_id or TRACKER_SHEET_ID
    url = "https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv" % sid
    if sheet_name:
        url += "&sheet=" + urllib.parse.quote(sheet_name)
    if gid is not None:
        url += "&gid=%s" % gid
    url += "&cb=%d" % int(time.time() // 60)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (GoldOS bot)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", "replace")


# --------------------------------------------------------------------------
# Daily OHLC memory (the "daily gold" tab)
# --------------------------------------------------------------------------
def _num(x):
    try:
        return round(float(str(x).replace(",", "").strip()), 2)
    except Exception:
        return None


def _fetch_ohlc_rows():
    """Pull the daily OHLC tab and parse to [{date,open,high,low,close,change,dir,vol}]."""
    text = _gviz_csv(gid=OHLC_GID, sheet_id=OHLC_SHEET_ID)
    rows = []
    for r in csv.reader(io.StringIO(text)):
        if not r:
            continue
        d = (r[0] or "").strip()
        if not re.match(r"\d{4}-\d{2}-\d{2}", d):    # skip header / junk
            continue
        vol = ""
        for cell in r:
            if isinstance(cell, str) and cell.strip().endswith("%"):
                vol = cell.strip()
        rows.append({
            "date": d[:10],
            "open": _num(r[1]) if len(r) > 1 else None,
            "high": _num(r[2]) if len(r) > 2 else None,
            "low":  _num(r[3]) if len(r) > 3 else None,
            "close": _num(r[4]) if len(r) > 4 else None,
            "change": _num(r[6]) if len(r) > 6 else None,
            "dir":  (r[7].strip() if len(r) > 7 else ""),
            "vol":  vol,
        })
    rows.sort(key=lambda x: x["date"])
    return rows


def update_ohlc_memory(now):
    """Refresh the durable OHLC history file from the sheet. Returns the row list."""
    rows = _fetch_ohlc_rows()
    if rows:
        _save(OHLC_FILE, rows)          # the sheet is the full history -> this IS the memory
    return rows


def _latest_completed_ohlc(rows, now):
    today = now.strftime("%Y-%m-%d")
    past = [r for r in rows if r.get("date", "") <= today]
    return past[-1] if past else (rows[-1] if rows else None)


def _fmt_ohlc_day(r):
    return ("📊 Daily Gold OHLC — %s\n"
            "Open %s | High %s | Low %s | Close %s\n"
            "Change %s (%s) | Vol %s" % (
                r.get("date"), r.get("open"), r.get("high"), r.get("low"),
                r.get("close"), r.get("change"), r.get("dir"), r.get("vol")))


def ohlc_context_text(now, days=None):
    """Compact recent-OHLC block for the AI, read from the durable memory file."""
    rows = _load(OHLC_FILE, [])
    if not rows:
        try:
            rows = update_ohlc_memory(now)
        except Exception:
            rows = []
    if not rows:
        return "(daily OHLC memory not available yet)"
    days = days or OHLC_CONTEXT_DAYS
    today = now.strftime("%Y-%m-%d")
    past = [r for r in rows if r.get("date", "") <= today][-days:]
    out = ["DAILY GOLD OHLC — last %d days (from your 'daily gold' sheet, saved in memory):" % len(past)]
    for r in past:
        out.append("%s  O %s H %s L %s C %s  chg %s (%s)  vol %s" % (
            r.get("date"), r.get("open"), r.get("high"), r.get("low"),
            r.get("close"), r.get("change"), r.get("dir"), r.get("vol")))
    return "\n".join(out)


def cmd_ohlc(now):
    rows = _load(OHLC_FILE, [])
    if not rows:
        try:
            rows = update_ohlc_memory(now)
        except Exception as e:
            return "Couldn't read the daily OHLC sheet right now (%s)." % e
    last = _latest_completed_ohlc(rows, now)
    if not last:
        return "No daily OHLC rows found in the sheet yet."
    tail = [r for r in rows if r.get("date", "") <= now.strftime("%Y-%m-%d")][-7:]
    lines = [_fmt_ohlc_day(last), "", "Last 7 days:"]
    for r in tail:
        lines.append("%s  O %s H %s L %s C %s  (%s)" % (
            r.get("date"), r.get("open"), r.get("high"),
            r.get("low"), r.get("close"), r.get("dir")))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# News RESULTS — actual vs forecast -> gold impact (ForexFactory / FairEconomy feed)
# --------------------------------------------------------------------------
_news_cache = {"ts": 0.0, "events": []}


def _fetch_news_feed():
    nowt = time.time()
    if _news_cache["events"] and (nowt - _news_cache["ts"]) < NEWS_REFRESH_SEC:
        return _news_cache["events"]
    data = _http_json(NEWS_FEED_URL, headers={"User-Agent": "Mozilla/5.0 (GoldOS bot)"}, timeout=15)
    evs = data if isinstance(data, list) else []
    _news_cache.update({"ts": nowt, "events": evs})
    return evs


def _news_num(s):
    """Parse FF values like '3.2%', '250K', '-78.5B', '54.2' into a float (or None)."""
    if s is None:
        return None
    t = str(s).strip().replace(",", "").replace("%", "").replace("$", "")
    if t == "":
        return None
    mult = 1.0
    if t[-1:] in "KkMmBbTt":
        mult = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}[t[-1].lower()]
        t = t[:-1]
    try:
        return float(t) * mult
    except Exception:
        return None


def _news_gold_read(title, actual, forecast, previous):
    """Return (verdict, reason) for gold from an actual vs forecast surprise."""
    a = _news_num(actual)
    base = _news_num(forecast)
    ref = "forecast"
    if base is None:
        base = _news_num(previous)
        ref = "previous"
    if a is None or base is None:
        return ("", "")
    t = (title or "").lower()
    # Metrics where a HIGHER number means a WEAKER economy (so higher = bullish gold).
    inverse = any(k in t for k in ("unemployment rate", "jobless", "unemployment claims",
                                   "initial claims", "continuing claims"))
    diff = a - base
    scale = abs(base) if base else 1.0
    if scale and abs(diff) / scale < 0.002:
        return ("Neutral →", "Actual in line with %s (%s vs %s) — limited gold impact." % (ref, actual, forecast or previous))
    stronger_usd = (diff > 0) != inverse       # stronger-than-expected USD data?
    if stronger_usd:
        return ("Bearish gold ↓",
                "Stronger-than-expected USD data (actual %s vs %s %s) → firmer dollar, typically pressures gold." % (actual, ref, forecast or previous))
    return ("Bullish gold ↑",
            "Weaker-than-expected USD data (actual %s vs %s %s) → softer dollar, typically supports gold." % (actual, ref, forecast or previous))


def _ev_dubai(ev):
    ds = str(ev.get("date", ""))
    try:
        d = _dt.datetime.fromisoformat(ds)
        if ZoneInfo:
            d = d.astimezone(ZoneInfo(TZNAME))
        return d
    except Exception:
        return None


def run_news_alerts(state, now, sent):
    """When a watched event's ACTUAL prints, send a gold-impact read (once per event)."""
    if not NEWS_RESULTS_ON:
        return
    try:
        events = _fetch_news_feed()
    except Exception:
        return
    for ev in events:
        if NEWS_COUNTRIES and ev.get("country") not in NEWS_COUNTRIES:
            continue
        if NEWS_IMPACTS and ev.get("impact") not in NEWS_IMPACTS:
            continue
        actual = ev.get("actual", "")
        if actual in (None, ""):
            continue                            # not released yet
        date = str(ev.get("date", ""))[:10]
        key = "live.newsres:%s|%s" % (date, ev.get("title", ""))
        if state.get(key):
            continue
        state[key] = True
        verdict, reason = _news_gold_read(ev.get("title", ""), actual,
                                          ev.get("forecast", ""), ev.get("previous", ""))
        msg = ("🗞️ RESULT — %s (%s)\nActual %s | Forecast %s | Prev %s" % (
            ev.get("title"), ev.get("impact"), actual,
            ev.get("forecast") or "—", ev.get("previous") or "—"))
        if verdict:
            msg += "\n→ %s %s" % (verdict, reason)
        tg_send(msg)
        sent.append("news_result")


def cmd_news(now):
    try:
        events = _fetch_news_feed()
    except Exception as e:
        return "Couldn't fetch the news feed right now (%s)." % e
    watch = [e for e in events
             if (not NEWS_COUNTRIES or e.get("country") in NEWS_COUNTRIES)
             and (not NEWS_IMPACTS or e.get("impact") in NEWS_IMPACTS)]
    if not watch:
        return "No USD High/Medium events in this week's calendar feed."
    watch.sort(key=lambda e: str(e.get("date", "")))
    out = ["🗞️ THIS WEEK — %s (%s), Dubai time:" % (
        "/".join(sorted(NEWS_COUNTRIES)) or "all", "/".join(sorted(NEWS_IMPACTS)) or "all")]
    for e in watch[:25]:
        d = _ev_dubai(e)
        when = d.strftime("%a %d %H:%M") if d else str(e.get("date", ""))[:16]
        act = e.get("actual", "")
        if act:
            verdict, _ = _news_gold_read(e.get("title", ""), act, e.get("forecast", ""), e.get("previous", ""))
            tag = "✅ %s (fc %s) %s" % (act, e.get("forecast") or "—", verdict)
        else:
            tag = "⏳ pending (fc %s)" % (e.get("forecast") or "—")
        out.append("%s  %s [%s] — %s" % (when, e.get("title"), e.get("impact"), tag))
    return "\n".join(out)


def news_context_text(now, limit=8):
    """Recent RELEASED results for the AI context."""
    try:
        events = _fetch_news_feed()
    except Exception:
        return ""
    done = [e for e in events
            if e.get("actual") not in (None, "")
            and (not NEWS_COUNTRIES or e.get("country") in NEWS_COUNTRIES)
            and (not NEWS_IMPACTS or e.get("impact") in NEWS_IMPACTS)]
    if not done:
        return ""
    done.sort(key=lambda e: str(e.get("date", "")))
    lines = ["RECENT NEWS RESULTS (actual vs forecast, ForexFactory):"]
    for e in done[-limit:]:
        verdict, _ = _news_gold_read(e.get("title", ""), e.get("actual", ""),
                                     e.get("forecast", ""), e.get("previous", ""))
        lines.append("%s: actual %s vs fc %s (prev %s) -> %s" % (
            e.get("title"), e.get("actual"), e.get("forecast") or "—",
            e.get("previous") or "—", verdict or "n/a"))
    return "\n".join(lines)


def _cell(r, i):
    return (r[i].strip() if len(r) > i and r[i] is not None else "")


def _parse_events(csv_text):
    """Split the sheet into Section 3 (astro) and Section 4 (econ) event rows."""
    astro, econ = [], []
    mode = None
    for r in csv.reader(io.StringIO(csv_text)):
        a, b, c, d, e = (_cell(r, 0), _cell(r, 1), _cell(r, 2), _cell(r, 3), _cell(r, 4))
        ua = a.upper()
        if ua.startswith("SECTION 3"):
            mode = "astro"; continue
        if ua.startswith("SECTION 4"):
            mode = "econ"; continue
        if ua.startswith("SECTION "):
            mode = None; continue
        if mode is None:
            continue
        if a.lower() == "date" or b.lower().startswith("time"):
            continue                      # column-header row
        if a.startswith("---"):
            continue                      # day separator
        if not c:
            continue                      # nothing meaningful
        if mode == "astro":
            astro.append({"kind": "astro", "date": a, "time": b, "title": c,
                          "meta": " · ".join(x for x in (d, e) if x)})
        else:
            econ.append({"kind": "econ", "date": a, "time": b, "title": c,
                         "cur": d, "impact": e})
    return astro, econ


def _event_dt(date_label, time_label, now):
    """Build a Dubai-aware datetime from 'Jun 30 (Tue)' + '3:56' (24h). None if untimed."""
    if not date_label or not time_label:
        return None
    tl = time_label.strip()
    if ":" not in tl:
        return None                       # 'Ongoing', 'All week', blank
    md = re.match(r"([A-Za-z]{3,})\s+(\d{1,2})", date_label)
    if not md:
        return None
    mon = md.group(1)[:3].title()
    if mon not in _MONTHS:
        return None
    month, day = _MONTHS.index(mon) + 1, int(md.group(2))
    try:
        hh, mm = (int(x) for x in tl.split(":")[:2])
    except Exception:
        return None
    tz = ZoneInfo(TZNAME) if ZoneInfo else None
    try:
        d = _dt.datetime(now.year, month, day, hh, mm, tzinfo=tz)
    except Exception:
        return None
    if (d - now).days < -180:             # year rollover (Dec sheet read in Jan)
        try:
            d = d.replace(year=now.year + 1)
        except Exception:
            pass
    return d


def get_calendar(now, force=False, tab=None):
    """Return {tab, astro[], econ[], rows[]} for a week tab (default: current week),
    cached per tab and refreshed from the sheet at most hourly."""
    tab = tab or TRACKER_TAB or _current_week_tab(now)
    cur = _cal_cache.get(tab)
    if cur and not force and (time.time() - cur.get("ts", 0)) < CAL_REFRESH_SEC:
        return cur
    text = None
    try:
        text = _gviz_csv(sheet_name=tab)
    except Exception:
        text = None
    if text is None and not _cal_cache:
        try:
            text = _gviz_csv(gid=0)       # very first load fallback: first tab
        except Exception:
            text = None
    if text is None:
        return cur or {"ts": 0, "tab": tab, "astro": [], "econ": [], "rows": []}
    rows = list(csv.reader(io.StringIO(text)))
    astro, econ = _parse_events(text)
    entry = {"ts": time.time(), "tab": tab, "astro": astro, "econ": econ, "rows": rows}
    _cal_cache[tab] = entry
    return entry


def _render_tab(cal, max_chars=6000):
    rows = cal.get("rows") or []
    if not rows:
        return ""
    out = ["WEEKLY TRACKER TAB: %s" % (cal.get("tab") or "?")]
    for r in rows:
        cells = [(c or "").strip() for c in r]
        while cells and cells[-1] == "":
            cells.pop()
        if not any(cells):
            continue
        out.append(" | ".join(cells))
    txt = "\n".join(out)
    if len(txt) > max_chars:
        txt = txt[:max_chars] + "\n…(truncated)"
    return txt


def tracker_context_text(now, max_chars=6000):
    """Render the current-week tab (and next week's tab when it exists) as readable lines
    so the AI can answer any question from it — snapshot, moon phases, planetary positions,
    transits, econ. Follows whatever tab is current and looks ahead to next week too."""
    cur = _render_tab(get_calendar(now), max_chars=max_chars)
    if not cur:
        cur = "(current-week tracker sheet not available right now)"
    nxt_cal = get_calendar(now, tab=_week_tab(now, 1))
    nxt = _render_tab(nxt_cal, max_chars=3500)
    if nxt:
        return cur + "\n\n---- NEXT WEEK (%s) ----\n" % nxt_cal.get("tab") + nxt
    return cur


def _fmt_astro(ev):
    tail = " (%s)" % ev["meta"] if ev.get("meta") else ""
    return "🔭 %s %s — %s%s" % (ev["date"], ev["time"], ev["title"], tail)


def _fmt_econ(ev):
    cur = (" [%s]" % ev["cur"]) if ev.get("cur") else ""
    imp = (" %s" % ev["impact"]) if ev.get("impact") else ""
    return "📅 %s %s — %s%s%s" % (ev["date"], ev["time"], ev["title"], cur, imp)


def _fmt_event(ev):
    return _fmt_astro(ev) if ev["kind"] == "astro" else _fmt_econ(ev)


def _is_today(date_label, now):
    m = re.match(r"([A-Za-z]{3,})\s+(\d{1,2})", date_label or "")
    if not m:
        return False
    return m.group(1)[:3].title() == now.strftime("%b") and int(m.group(2)) == now.day


def _time_key(ev):
    tl = ev.get("time", "")
    if ":" in tl:
        try:
            hh, mm = (int(x) for x in tl.split(":")[:2])
            return hh * 60 + mm
        except Exception:
            pass
    return 24 * 60 + 1                     # untimed -> sort last


def daily_agenda_text(cal, now):
    evs = [e for e in (cal["astro"] + cal["econ"]) if _is_today(e["date"], now)]
    evs.sort(key=_time_key)
    head = "🗓️ TODAY %s — Astro & Econ (Sec 3 & 4)" % now.strftime("%a %b %d")
    if not evs:
        return head + ":\n  (no timed transits or economic events today)"
    return "\n".join([head + ":"] + ["  " + _fmt_event(e) for e in evs])


def weekly_summary_text(cal, now):
    lines = ["🗓️ WEEK AHEAD — %s (Dubai time)" % (cal.get("tab") or "this week"),
             "", "🔭 SECTION 3 — Planetary transits:"]
    lines += ["  " + _fmt_astro(e) for e in cal["astro"]] or ["  (none listed)"]
    lines += ["", "📅 SECTION 4 — Economic calendar:"]
    lines += ["  " + _fmt_econ(e) for e in cal["econ"]] or ["  (none listed)"]
    return "\n".join(lines)


def run_calendar_alerts(state, now, sent):
    """Sheet-driven pings: 15-min-before each event, daily agenda, weekly summary."""
    if not SHEET_ALERTS_ON:
        return
    cal = get_calendar(now)
    today = now.strftime("%Y-%m-%d")

    # Monday week-ahead summary (03:00 Dubai by default)
    if now.weekday() == 0 and now.hour == CAL_WEEKLY_HOUR and _reminder_due(state, "cal_weekly"):
        tg_send(weekly_summary_text(get_calendar(now, force=True), now))
        sent.append("cal_weekly")

    # Daily agenda (07:00 by default)
    if now.hour == CAL_AGENDA_HOUR and _reminder_due(state, "cal_agenda"):
        tg_send(daily_agenda_text(cal, now))
        sent.append("cal_agenda")

    # Heads-up before each timed event
    for ev in (cal["astro"] + cal["econ"]):
        d = _event_dt(ev.get("date"), ev.get("time"), now)
        if not d:
            continue
        lead_min = (d - now).total_seconds() / 60.0
        if 0 < lead_min <= CAL_LEAD_MIN:
            key = "%s:evt:%s|%s|%s|%s" % (today, ev["kind"], ev["date"], ev["time"], ev["title"][:30])
            if not state.get(key):
                state[key] = True
                tg_send("⏰ In ~%d min:\n%s" % (max(1, int(round(lead_min))), _fmt_event(ev)))
                sent.append("cal_event")


# --------------------------------------------------------------------------
# Reminders + live proactive alerts (driven by /telegram/tick)
# --------------------------------------------------------------------------
def _reminder_due(state, key):
    """Fire each reminder at most once per local day-slot."""
    today = _now().strftime("%Y-%m-%d")
    slot = "%s:%s" % (today, key)
    if state.get(slot):
        return False
    state[slot] = True
    return True


def _to_float(x):
    """Parse a price-ish value ('4,069.30', '$4069', 4069.3) into a float, or None."""
    if x is None:
        return None
    try:
        return float(str(x).replace(",", "").replace("$", "").strip())
    except Exception:
        return None


def _in_quiet_hours(hh):
    """True if local hour hh is inside the optional quiet window (no live pushes)."""
    if QUIET_START_H < 0 or QUIET_END_H < 0:
        return False
    if QUIET_START_H == QUIET_END_H:
        return False
    if QUIET_START_H < QUIET_END_H:
        return QUIET_START_H <= hh < QUIET_END_H
    # window wraps past midnight (e.g. 23 -> 6)
    return hh >= QUIET_START_H or hh < QUIET_END_H


def _live_line(ctx):
    """One compact live snapshot line used by heartbeats / move alerts."""
    pr = ctx.get("price", {}) or {}
    rb = ctx.get("rulebook", {}) or {}
    tr = ctx.get("trends", {}) or {}
    lvl = rb.get("level", {}) or {}
    verd = rb.get("verdict", {}) or {}
    h1 = tr.get("h1") or {}
    h4 = tr.get("h4") or {}
    h1s = " ⚠STALE" if tr.get("h1_stale") else ""
    h4s = " ⚠STALE" if tr.get("h4_stale") else ""
    return (
        "Spot %s (%s / %s%%) · %s\n"
        "H4 %s%s · H1 %s%s\n"
        "Nearest %s @ %s (%s away, %s%%)\n"
        "Verdict: %s" % (
            pr.get("price"), pr.get("change"), pr.get("change_pct"), pr.get("market_state"),
            h4.get("dir"), h4s, h1.get("dir"), h1s,
            lvl.get("nearest"), lvl.get("price"), lvl.get("dist"), lvl.get("dist_pct"),
            verd.get("state")))


def _four_h_block(ctx):
    """Extra structure + 4H plan lines for the 4-hour close update."""
    td = ctx.get("today", {}) or {}
    st = ctx.get("structure", {}) or {}
    p4 = td.get("plan4h", {}) or {}
    bits = []
    if st and not st.get("error") and st.get("alignment"):
        bits.append("Structure: %s" % st.get("alignment"))
    if p4:
        bits.append("4H plan: %s entry %s, stop %s, target %s" % (
            p4.get("dir"), p4.get("entry"), p4.get("stop"), p4.get("target")))
        if p4.get("advice"):
            bits.append(p4.get("advice"))
    return ("\n" + "\n".join(bits)) if bits else ""


def run_live_alerts(ctx, state, now, sent):
    """Movement-, level- and candle-driven pushes. Idempotent via live.* keys in
    state (these survive the daily prune). Safe to call at any tick frequency."""
    if not LIVE_ALERTS_ON:
        return
    hh = now.hour
    if _in_quiet_hours(hh):
        return

    rb = ctx.get("rulebook", {}) or {}
    pr = ctx.get("price", {}) or {}
    tr = ctx.get("trends", {}) or {}
    lvl = rb.get("level", {}) or {}
    verd = rb.get("verdict", {}) or {}

    price_now = _to_float(pr.get("price"))
    market = (pr.get("market_state") or "").lower()
    market_closed = "clos" in market  # skip pushes when the market is clearly closed

    # ---- 1) Support/Resistance hit ----------------------------------------
    at_level = bool(lvl.get("at_level"))
    level_key = "%s@%s" % (lvl.get("nearest"), lvl.get("price"))
    if at_level and price_now is not None and not market_closed:
        if state.get("live.level_key") != level_key:
            tg_send("🎯 PRICE AT LEVEL — %s @ %s\n"
                    "Spot %s (%s away, %s%%). Verdict: %s.\n"
                    "Watch for reaction / rejection here." % (
                        lvl.get("nearest"), lvl.get("price"), pr.get("price"),
                        lvl.get("dist"), lvl.get("dist_pct"), verd.get("state")))
            state["live.level_key"] = level_key
            sent.append("level_hit")
    elif not at_level and state.get("live.level_key"):
        # left the level — re-arm so the next touch alerts again
        state.pop("live.level_key", None)

    # ---- 2) Movement-triggered --------------------------------------------
    if price_now is not None and not market_closed:
        last_price = _to_float(state.get("live.last_alert_price"))
        if last_price is None:
            state["live.last_alert_price"] = price_now
        elif abs(price_now - last_price) >= ALERT_MOVE_USD:
            arrow = "▲ up" if price_now > last_price else "▼ down"
            h1 = tr.get("h1") or {}
            h4 = tr.get("h4") or {}
            tg_send("📈 MOVE %s $%.2f → now %s (%s / %s%%)\n"
                    "H4 %s · H1 %s · Nearest %s @ %s · Verdict: %s" % (
                        arrow, abs(price_now - last_price), pr.get("price"),
                        pr.get("change"), pr.get("change_pct"),
                        h4.get("dir"), h1.get("dir"),
                        lvl.get("nearest"), lvl.get("price"), verd.get("state")))
            state["live.last_alert_price"] = price_now
            sent.append("move")

    # ---- 3) 4H candle close (gold's real closes: 1/5/9/13/17/21 Dubai) ----
    block4 = "%s:4h%d" % (now.strftime("%Y-%m-%d"), hh)
    posted_4h = False
    if hh in FOUR_H_CLOSE_HOURS and state.get("live.last_4h") != block4 and not market_closed:
        tg_send("🕓 4H update — %s\n%s%s" % (
            now.strftime("%H:%M %Z"), _live_line(ctx), _four_h_block(ctx)))
        state["live.last_4h"] = block4
        sent.append("h4_close")
        posted_4h = True

    # ---- 4) Hourly heartbeat (1H candle close) ----------------------------
    hour_key = now.strftime("%Y-%m-%d:%H")
    if (HEARTBEAT_EVERY_H > 0 and hh % HEARTBEAT_EVERY_H == 0
            and state.get("live.last_hour") != hour_key and not market_closed):
        if not posted_4h:  # the 4H update already covers this hour — don't double-post
            tg_send("⏱ %s\n%s" % (now.strftime("%H:%M %Z"), _live_line(ctx)))
            sent.append("heartbeat")
        state["live.last_hour"] = hour_key


def run_tick():
    """Check time + live state and send any due reminders/alerts. Idempotent."""
    state = _load(REMINDER_FILE, {})
    if not isinstance(state, dict):
        state = {}
    # prune old daily slots, but KEEP the persistent live.* tracking keys.
    # Also drop news-result markers older than 14 days so state doesn't grow forever.
    today = _now().strftime("%Y-%m-%d")
    _cutoff = (_now() - _dt.timedelta(days=14)).strftime("%Y-%m-%d")

    def _keep(k):
        if k.startswith("live.newsres:"):
            d = k[len("live.newsres:"):][:10]
            return d >= _cutoff
        return k.startswith(today) or k.startswith("live.")
    state = {k: v for k, v in state.items() if _keep(k)}

    now = _now()
    hh = now.hour
    sent = []

    ctx = fetch_context()
    rb = ctx.get("rulebook", {}) or {}
    news = rb.get("news", {}) or {}
    guard = rb.get("guardrails", {}) or {}
    verd = rb.get("verdict", {}) or {}

    # ---- Live proactive alerts (movement / level / hourly / 4H) ----
    run_live_alerts(ctx, state, now, sent)

    # ---- Weekly tracker sheet alerts (Section 3 transits + Section 4 econ) ----
    try:
        run_calendar_alerts(state, now, sent)
    except Exception:
        pass

    # ---- Daily OHLC: save to memory + send once per day ----
    if OHLC_ON and now.hour == OHLC_PUSH_HOUR and _reminder_due(state, "ohlc_daily"):
        try:
            rows = update_ohlc_memory(now)
            r = _latest_completed_ohlc(rows, now)
            if r:
                tg_send(_fmt_ohlc_day(r) + "\n(saved to memory ✓)")
                sent.append("ohlc_daily")
        except Exception:
            pass

    # ---- News RESULTS: alert with gold impact when an actual prints ----
    try:
        run_news_alerts(state, now, sent)
    except Exception:
        pass

    # 1) Weekly check-in — Sunday evening (Dubai week starts Sunday)
    if now.weekday() == 6 and hh >= 18 and _reminder_due(state, "weekly_checkin"):
        tg_send("🗓️ Weekly check-in: send me your outlook for the week with "
                "/week <your view>. I'll use it as context all week.")
        sent.append("weekly_checkin")

    # 2) Morning brief nudge — local 07:00-08:00
    if hh == 7 and _reminder_due(state, "morning_brief"):
        tg_send("☀️ Good morning. Today's setup:\n\n" + context_summary(ctx))
        sent.append("morning_brief")

    # 3) London-NY overlap open nudge — local ~16:00
    if hh == 16 and _reminder_due(state, "overlap_open"):
        tg_send("⚔ London-NY overlap window is opening — the A-grade session. "
                "Verdict right now: %s. Ask me for a read." % verd.get("state"))
        sent.append("overlap_open")

    # 4) News blackout alert — fire whenever blackout flips on
    if news.get("blackout") and _reminder_due(state, "news_blackout"):
        tg_send("📰 NEWS BLACKOUT active — no new entries until it clears. "
                "Next event: %s" % news.get("next"))
        sent.append("news_blackout")

    # 5) Guardrail lock alert
    if guard.get("locked") and _reminder_due(state, "guard_lock"):
        tg_send("🛑 Guardrail LOCK hit — STAND DOWN for the rest of the day. "
                "Reason: %s (day R %s)." % (guard.get("reason"), guard.get("day_r")))
        sent.append("guard_lock")

    _save(REMINDER_FILE, state)
    return sent


# --------------------------------------------------------------------------
# Internal self-ticker (Railway never sleeps -> no external pinger needed)
# --------------------------------------------------------------------------
def _internal_ticker():
    """Background loop that calls run_tick() on a fixed interval. Runs forever in a
    daemon thread inside the (single) gunicorn worker. Idempotent dedupe in run_tick
    means it's safe even if an external pinger also hits /telegram/tick."""
    time.sleep(20)  # let the app finish booting before the first self-tick
    while True:
        try:
            run_tick()
        except Exception:
            pass
        time.sleep(INTERNAL_TICK_SECONDS)


def start_internal_ticker(app):
    """Start the self-ticker exactly once per process."""
    if not INTERNAL_TICK:
        return
    if getattr(app, "_gold_ticker_started", False):
        return
    app._gold_ticker_started = True
    threading.Thread(target=_internal_ticker, daemon=True).start()


# --------------------------------------------------------------------------
# Registration — call register_telegram_bot(app) from app.py
# --------------------------------------------------------------------------
def register_telegram_bot(app):
    @app.route("/telegram/webhook/<secret>", methods=["POST"])
    def _tg_webhook(secret):
        if secret != HOOK:
            return ("forbidden", 403)
        try:
            update = request.get_json(force=True, silent=True) or {}
        except Exception:
            update = {}
        msg = update.get("message") or update.get("edited_message") or {}
        chat = (msg.get("chat") or {})
        chat_id = str(chat.get("id", ""))
        text = msg.get("text", "")
        # Owner-only: ignore everyone else (but let them learn nothing)
        if OWNER_CHAT and chat_id and chat_id != OWNER_CHAT:
            return jsonify(ok=True)
        if chat_id and text:
            threading.Thread(target=handle_message,
                             args=(chat_id, text), daemon=True).start()
        return jsonify(ok=True)

    @app.route("/telegram/tick", methods=["GET", "POST"])
    def _tg_tick():
        if request.args.get("key", "") != TICK_KEY:
            return ("forbidden", 403)
        sent = run_tick()
        return jsonify(ok=True, sent=sent, time=_now().isoformat())

    @app.route("/telegram/health", methods=["GET"])
    def _tg_health():
        return jsonify(
            ok=True,
            has_token=bool(TG_TOKEN),
            has_owner=bool(OWNER_CHAT),
            has_ai_key=bool(AI_KEY),
            model=MODEL,
            base_url=BASE_URL,
            tz=TZNAME,
            internal_tick=INTERNAL_TICK,
            internal_tick_seconds=INTERNAL_TICK_SECONDS,
        )

    # Start the self-ticker so the bot drives its own hourly/4H/movement/level alerts
    # without any external pinger (Railway keeps the process alive 24/7).
    start_internal_ticker(app)

    return app

"""
GOLD COMMAND CENTER — Interactive Telegram Bot
==============================================
Self-contained Flask integration for the Gold dashboard.

What it does
------------
- Two-way chat: ask anything ("what's the bias today?", "should I wait?",
  "where are my levels?") and get an AI answer grounded in the LIVE dashboard
  data (/api/rulebook, /api/scalp, /api/live-price).
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
  BASE_URL             public base url (default https://gold-command-center.onrender.com)
  BOT_MODEL            Claude model (default "claude-sonnet-4-6"; use
                       "claude-haiku-4-5-20251001" for cheaper/faster)
  BOT_TZ               timezone for reminders (default "Asia/Dubai")
"""

import os
import json
import time
import threading
import urllib.request
import urllib.error
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
BASE_URL   = os.environ.get("BASE_URL", "https://gold-command-center.onrender.com").rstrip("/")
MODEL      = os.environ.get("BOT_MODEL", "claude-sonnet-4-6")
TZNAME     = os.environ.get("BOT_TZ", "Asia/Dubai")

DATA_DIR        = os.environ.get("BOT_DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
TRADES_FILE     = os.path.join(DATA_DIR, "trades.json")
WEEKLY_FILE     = os.path.join(DATA_DIR, "weekly_thoughts.json")
HISTORY_FILE    = os.path.join(DATA_DIR, "bot_history.json")
REMINDER_FILE   = os.path.join(DATA_DIR, "reminder_state.json")

MAX_HISTORY = 12  # how many prior turns to feed the model


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


def tg_send(text, chat_id=None):
    """Send a Telegram message (plain text, chunked to 4096)."""
    if not TG_TOKEN:
        return
    chat_id = chat_id or OWNER_CHAT
    if not chat_id:
        return
    url = "https://api.telegram.org/bot%s/sendMessage" % TG_TOKEN
    for i in range(0, len(text) or 1, 3900):
        chunk = text[i:i + 3900] or " "
        try:
            _http_json(url, {"chat_id": chat_id, "text": chunk,
                             "disable_web_page_preview": True}, timeout=20)
        except Exception:
            pass


# --------------------------------------------------------------------------
# Live dashboard context
# --------------------------------------------------------------------------
def fetch_context():
    ctx = {}
    for key, path in (("rulebook", "/api/rulebook"),
                      ("scalp", "/api/scalp"),
                      ("price", "/api/live-price"),
                      ("trends", "/api/trends"),
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
    sc = ctx.get("scalp", {}) or {}
    pr = ctx.get("price", {}) or {}
    tr = ctx.get("trends", {}) or {}
    td = ctx.get("today", {}) or {}
    sv = ctx.get("silver", {}) or {}
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
        "Day levels: PDH %s / PDL %s / PDC %s" % (
            sc.get("pdh"), sc.get("pdl"), sc.get("pdc")),
        "Scalp feed: VWAP %s, EMA21 %s, RSI %s, ATR5 %s, OR %s-%s (source %s)" % (
            sc.get("vwap"), sc.get("ema21"), sc.get("rsi"), sc.get("atr5"),
            sc.get("orl"), sc.get("orh"), sc.get("source")),
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

    return "\n".join(lines)


# --------------------------------------------------------------------------
# AI
# --------------------------------------------------------------------------
SYSTEM_PROMPT = """You are GoldOS, the trading copilot inside Adham's Gold Command Center.
You are an expert in XAU/USD scalping, intraday and swing trading.

Rules of engagement:
- Ground EVERY answer in the LIVE SNAPSHOT and the trading rules below. Quote the
  actual numbers (price, levels, gate score, verdict) instead of being vague.
- Respect the no-trade gate: if verdict is WAIT or STAND DOWN, say so plainly and
  explain what would need to change to take a trade.
- Honor guardrails: if locked, the answer is STAND DOWN regardless of setup.
- During a news blackout, no entries.
- Be concise and direct. Lead with the answer, then the reason. No fluff.
- You give information and structured reasoning, NOT licensed financial advice;
  the final decision and risk is always Adham's.

For TREND questions, use the MULTI-TIMEFRAME TREND block (Daily / H4 / H1 direction +
the reversal-state readout) plus the 5m/15m scalp feed when present. State the alignment
plainly (e.g. "Daily down, H4 down, H1 up — pullback, no reversal confirmed yet"), then
what it means for entries. Honor the wait_4h flag: if the daily signal needs the 4-hour to
confirm and it hasn't, say wait. If a timeframe is marked STALE or the 5m/15m feed is null,
note the data is missing rather than guessing.

Trading framework (the rulebook this dashboard implements):
- Confluence gate scored 0-8 -> grade A (>=6), B (4-5), C (<4). Only A-grade
  setups are full size; B is reduced size or skip; C is no trade.
- Inputs: price at a ranked pivot level, directional daily bias, active session
  clear of news, multi-timeframe alignment, astro confluence (bonus).
- Risk 0.5% per trade, target R=2. Day stop at -3R; lock after 3 losses or 5 trades.
- Sessions: London-NY overlap is the A-grade window.

If the user logs a trade or shares a weekly view, acknowledge briefly and tell them
it's saved. Use their stored WEEKLY OUTLOOK as standing context for the week."""


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
    sys = SYSTEM_PROMPT + "\n\n=== LIVE SNAPSHOT ===\n" + snap + weekly_txt

    messages = []
    for turn in history[-MAX_HISTORY:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": question})

    payload = {
        "model": MODEL,
        "max_tokens": 700,
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
  /trend    multi-timeframe trend (Daily/H4/H1) + reversal state + 4H plan
  /levels   today's pivots + day high/low
  /log ...  log a trade or note  (e.g. /log long 4120, +1.5R, news spike)
  /week ... save your weekly outlook  (referenced all week)
  /weekshow show your current weekly outlook
  /help     this message"""


def cmd_today(ctx):
    return context_summary(ctx)


def cmd_levels(ctx):
    rb = ctx.get("rulebook", {}) or {}
    sc = ctx.get("scalp", {}) or {}
    lvl = rb.get("level", {}) or {}
    return ("LEVELS\n"
            "Nearest: %s @ %s (dist %s / %s%%)\n"
            "PDH %s | PDL %s | PDC %s\n"
            "OR %s-%s | VWAP %s | EMA21 %s" % (
                lvl.get("nearest"), lvl.get("price"), lvl.get("dist"),
                lvl.get("dist_pct"), sc.get("pdh"), sc.get("pdl"),
                sc.get("pdc"), sc.get("orl"), sc.get("orh"),
                sc.get("vwap"), sc.get("ema21")))


def cmd_trend(ctx):
    tr = ctx.get("trends", {}) or {}
    td = ctx.get("today", {}) or {}
    rev = tr.get("reversal", {}) or {}
    p4 = td.get("plan4h", {}) or {}

    def _tf(o):
        o = o or {}
        return "%s (last %s, %s/%s bars bull)" % (
            o.get("dir"), o.get("last"), o.get("bull"), o.get("bars"))
    return ("MULTI-TIMEFRAME TREND\n"
            "Daily: %s\nH4:    %s\nH1:    %s\n"
            "State: %s — %s\n\n"
            "4H plan: %s entry %s, stop %s, target %s\n%s" % (
                _tf(tr.get("daily")), _tf(tr.get("h4")), _tf(tr.get("h1")),
                rev.get("label"), rev.get("detail"),
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
    tg_send(answer, chat_id)


# --------------------------------------------------------------------------
# Reminders (driven by /telegram/tick)
# --------------------------------------------------------------------------
def _reminder_due(state, key):
    """Fire each reminder at most once per local day-slot."""
    today = _now().strftime("%Y-%m-%d")
    slot = "%s:%s" % (today, key)
    if state.get(slot):
        return False
    state[slot] = True
    return True


def run_tick():
    """Check time + live state and send any due reminders. Idempotent per slot."""
    state = _load(REMINDER_FILE, {})
    # prune old slots
    today = _now().strftime("%Y-%m-%d")
    state = {k: v for k, v in state.items() if k.startswith(today)}

    now = _now()
    hh = now.hour
    sent = []

    ctx = fetch_context()
    rb = ctx.get("rulebook", {}) or {}
    news = rb.get("news", {}) or {}
    guard = rb.get("guardrails", {}) or {}
    verd = rb.get("verdict", {}) or {}

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
        )

    return app

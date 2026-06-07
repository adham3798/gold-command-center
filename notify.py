# -*- coding: utf-8 -*-
"""Telegram notifier for the Decision-Day end-of-day alert.

Config (either one works):
  1) telegram_config.json next to this file:
        { "bot_token": "123456:ABC...", "chat_id": "" }
     Leave chat_id empty and just message your bot once — it is auto-discovered.
  2) Environment variables TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.

Nothing here ever raises into the app: if it is not configured it simply no-ops.
"""
import os, json
import requests as req

_HERE = os.path.dirname(os.path.abspath(__file__))
CFG   = os.path.join(_HERE, 'telegram_config.json')

def _config():
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat  = os.environ.get('TELEGRAM_CHAT_ID')
    if (not token or not chat) and os.path.exists(CFG):
        try:
            with open(CFG, encoding='utf-8') as f:
                c = json.load(f)
            token = token or c.get('bot_token')
            chat  = chat  or c.get('chat_id')
        except Exception:
            pass
    token = (str(token).strip() or None) if token else None
    chat  = (str(chat).strip()  or None) if chat  else None
    return token, chat

def configured():
    token, _ = _config()
    return bool(token)

def discover_chat_id():
    """Find the chat id from the most recent message sent TO the bot."""
    token, _ = _config()
    if not token:
        return None
    try:
        r = req.get('https://api.telegram.org/bot%s/getUpdates' % token, timeout=10).json()
        for u in reversed(r.get('result', [])):
            m = u.get('message') or u.get('channel_post') or {}
            cid = (m.get('chat') or {}).get('id')
            if cid:
                return cid
    except Exception:
        pass
    return None

def send(text):
    """Send a Telegram message. Returns (ok: bool, info: str)."""
    token, chat = _config()
    if not token:
        return False, 'no bot token configured (telegram_config.json)'
    if not chat:
        chat = discover_chat_id()
        if not chat:
            return False, 'no chat id — open your bot in Telegram and send it any message first'
    try:
        r = req.post('https://api.telegram.org/bot%s/sendMessage' % token,
                     json={'chat_id': chat, 'text': text, 'parse_mode': 'HTML',
                           'disable_web_page_preview': True}, timeout=10).json()
        return (bool(r.get('ok')), 'sent' if r.get('ok') else r.get('description', 'failed'))
    except Exception as e:
        return False, str(e)

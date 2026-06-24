"""
wire_telegram_bot.py — idempotent installer for the Gold Telegram bot.

Run this once from the repo root (same folder as app.py) after copying
telegram_bot.py in next to it:

    python3 wire_telegram_bot.py

It appends a small, guarded registration block to app.py that imports and
registers the bot. Running it again does nothing (it detects the marker).
Matches the pattern of wire_scalp_api.py / wire_rulebook_api.py.
"""

import os
import sys

APP = "app.py"
MARKER = "GOLD TELEGRAM BOT (idempotent)"

BLOCK = '''

# === %s ===
try:
    from telegram_bot import register_telegram_bot
    register_telegram_bot(app)
    print("[telegram_bot] registered: /telegram/webhook, /telegram/tick, /telegram/health")
except Exception as _tg_e:  # never crash the app if the bot fails to load
    import logging
    logging.exception("telegram bot init failed: %%s", _tg_e)
# === END GOLD TELEGRAM BOT ===
''' % MARKER


def main():
    if not os.path.exists(APP):
        print("ERROR: %s not found. Run this from the repo root (next to app.py)." % APP)
        sys.exit(1)
    if not os.path.exists("telegram_bot.py"):
        print("ERROR: telegram_bot.py not found. Copy it next to app.py first.")
        sys.exit(1)

    with open(APP, "r") as f:
        src = f.read()

    if MARKER in src:
        print("Already wired — no change made. ✓")
        return

    # Make a backup once.
    bak = APP + ".bak_telegram"
    if not os.path.exists(bak):
        with open(bak, "w") as f:
            f.write(src)
        print("Backup written: %s" % bak)

    with open(APP, "a") as f:
        f.write(BLOCK)
    print("Wired telegram_bot into app.py ✓")
    print("Next: commit + push, set env vars in Render, then register the webhook.")
    print("See GOLD_BOT_SETUP.md.")


if __name__ == "__main__":
    main()

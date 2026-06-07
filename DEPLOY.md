# Deploying GOLD COMMAND CENTER online

This is a **Python (Flask)** app, so it needs a host that runs Python.
**GitHub Pages will NOT work** (it only serves static files — it can't run the engine/APIs).

Recommended free host: **Render.com** (full internet access for the gold-api / Forex Factory / Google Sheets calls).

---

## Files used for deploy (already in this folder)
- `app.py`, `engine.py`, `news.py`        — the backend
- `templates/`, `adham.html`              — the pages
- `requirements.txt`                       — Python packages
- `Procfile` / `render.yaml`               — how the host starts the app
- `trades.json`, `news_cache.json`         — data (optional)

Not needed online: the local `.xlsx` (Windows-only fallback) and `START_APP.bat`.

---

## Option A — Render (recommended)

1. Put this folder in a GitHub repo (e.g. a new repo `gold-command-center`):
   - On github.com → **New repository** → upload all files in this folder
     (or push with git).
2. Go to **https://render.com** → sign in with GitHub → **New → Web Service**.
3. Pick your repo. Render auto-detects Python and reads `render.yaml`/`Procfile`:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app --workers 1 --timeout 120`
   - Plan: **Free**
4. Click **Create Web Service**. First build takes ~2-3 min.
5. You get a public URL like `https://gold-command-center.onrender.com`.
   - `/`        → the combined command center (tabs)
   - `/gold`    → moon calendar / predictions
   - `/adham`   → ADHAM intraday

That's it — it auto-redeploys whenever you push to the repo.

### Notes for the free tier
- The service **sleeps after ~15 min idle**; the first hit then takes ~30-60s to wake.
- Disk is **ephemeral**: trades you add online and the news cache reset on each
  redeploy/restart. (The Google-Sheet data always reloads fresh, so prices/forecast are fine.)
- For always-on + persistent disk, upgrade to Render's paid tier (~$7/mo) or use Railway/Fly.io.

---

## Option B — PythonAnywhere
Beginner-friendly, but the **free tier blocks outbound internet** except a whitelist,
so gold-api.com and Forex Factory calls may fail. Use a paid PythonAnywhere plan if you
go this route, or prefer Render.

---

## Keep the ADHAM static page on GitHub Pages too (optional)
Your `adham-system` repo already serves `index.html` on GitHub Pages. That still works
standalone. The combined app also serves it at `/adham`, so you don't need both — but
there's no harm in keeping the GitHub Pages copy as a lightweight backup.

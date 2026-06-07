# GOLD COMMAND CENTER — static site (no server needed)

This folder is the **fully client-side** version. It runs the entire gold engine
in the browser and reads your Google Sheet live (via a CORS proxy), so it can be
hosted free on **GitHub Pages / Cloudflare Pages / Netlify** — exactly like the
ADHAM page. No Python, no server, always-on, works on phone.

## Files
- `index.html`    — the shell (tabs: Moon Calendar + ADHAM)
- `gold.html`     — GoldOS dashboard (engine runs in-browser)
- `goldengine.js` — the JS engine (port of the Python engine + data layer)
- `adham.html`    — the ADHAM intraday dashboard

Data source: the same Google Sheet (`gold_price`, `MOON_REAL`, `H1_DATA`,
`H4_DATA`, `WEEKLY_FORECAST`, libraries). Live spot price from gold-api.com.
USD news from Forex Factory. Trades are saved in the browser (localStorage).

Engine features (identical to the local Python build): astro+transit+day-number
scoring, sheet-forecast override, movable 2-day pullback, 3·7·9 important dates,
9-cycle end/turn, TP1(50%) win/loss, market-closed (weekends+holidays), and the
**Nature-Cycle model** (second opinion, ~52% backtested) shown alongside each signal.

## Deploy to GitHub Pages
1. Put these 4 files in a public repo (root), e.g. reuse `adham-system` or a new repo.
   - If reusing `adham-system`: your old ADHAM `index.html` is already here as `adham.html`;
     just add `index.html` (shell), `gold.html`, `goldengine.js`.
2. Repo → **Settings → Pages** → Source: **Deploy from a branch** → `main` / `/root` → Save.
3. After ~1 min your site is live at:
   `https://<username>.github.io/<repo>/`  → opens the command center.

## Notes
- First load fetches the sheet through a public CORS proxy (allorigins) — takes a few
  seconds. If a proxy is down it falls back to the next one automatically.
- Everything updates whenever you update the Google Sheet (just reload the page).
- To run locally: `python -m http.server 8000 --directory site` then open
  `http://localhost:8000/`.

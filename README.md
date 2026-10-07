# Lendable

NYC condo and co-op building assistant for real estate professionals.

- `index.html` — the app (financing activity, DOB flags, Fannie Mae project standards, Lendable AI).
- `buildings-db.json` — city building records (MapPLUTO) used for building facts and search.
- `api/dob.js` — DOB/HPD lookup on Vercel using free NYC Open Data: open DOB and ECB violations, facade (FISP) status, HPD vacate orders. Call `/api/dob?bbl=1000237501` or `/api/dob?address=1 Wall Street&borough=Manhattan`.

- `api/ask.js` — Lendable AI on Vercel (Claude Sonnet 5.5 with prompt caching). Needs env var `ANTHROPIC_API_KEY`; set a monthly spend limit in console.anthropic.com.

## Deploy
1. Import this repo in Vercel (Add New → Project). No build settings needed.
2. Optional: add env var `NYC_APP_TOKEN` (free from data.cityofnewyork.us → Developer Settings) for higher rate limits.

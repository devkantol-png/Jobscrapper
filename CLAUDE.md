# Job Scraper — Context Handoff

## What this project does
A daily job scraper that pulls Founder's Office / Chief of Staff / Growth Manager / Strategy roles from Naukri and LinkedIn (Gurgaon + Mumbai), stores them in Upstash KV, and serves them via a filtered front-end hosted on Vercel.

---

## Current State

### Working
- `jobs.html` — full front-end with filters (city, category, source, recency), "Applied" tracker, expiry hiding. Has 55 jobs from March 13 **baked in as embedded fallback** — shows these instantly if live API returns nothing.
- `api/scrape.py` — scrapes Naukri via Jina Reader (`r.jina.ai`) + LinkedIn via Jina Search (`s.jina.ai`). Both free, no API key needed. Replaced Firecrawl (credits ran out).
- `api/jobs.py` — reads from Upstash KV and returns JSON to the front-end.
- `scraper.py` — local standalone scraper (runs independently, not Vercel).
- `vercel.json` — cron at 04:30 UTC (10:00 AM IST), redirect `/` → `jobs.html`. No `functions` block (was causing build errors).

### Broken / Stuck
- **Vercel deployment is failing.** Every deployment errors with:
  > `The pattern "api/scrape.py" defined in functions doesn't match any Serverless Functions inside the api directory.`
  This occurs even with the `functions` key removed — Vercel Hobby plan appears to no longer auto-detect Python files as serverless functions.
- The site currently has **no live production deployment** serving traffic.

### Not implemented
- No notification/alert when new jobs appear
- No pagination on the front-end (works fine at current job volumes)

---

## Last Session Summary (March 24, 2026)

**What we did:**
1. Replaced Firecrawl (paid, credits exhausted) with Jina AI reader/search (free, no key needed) in `api/scrape.py`
2. Added embedded fallback jobs to `jobs.html` — front-end now shows March 13 data immediately rather than a blank page
3. Fixed front-end boot logic: shows embedded jobs right away, upgrades to live API data silently in background
4. Fixed recency filter, expiry calculation, city filter, "Applied" tracker persistence
5. Debugged Vercel deployments — found and fixed two blocking issues:
   - Git committer identity mismatch (fixed: set email to `245829157+devkantol-png@users.noreply.github.com`)
   - `vercel.json` `functions` block: tried `{}` (invalid — needs at least one property), tried `{ "maxDuration": 10 }` (build error persists), tried removing the block entirely (same error)
6. All code pushed to both remotes (origin + vercel)

**Decisions made:**
- Went with Jina over other free scrapers (ScrapingBee, ZenRows) because it requires zero API key and has a search endpoint that mimics Firecrawl's search API
- Kept Python for the API rather than rewriting to JS — but this is now the blocker

---

## Exact Next Steps

**The one thing to fix:** Vercel won't run Python on Hobby plan.

**Option A — Rewrite API to Node.js (recommended, ~30 min):**
- Rename `api/scrape.py` → `api/scrape.js`, `api/jobs.py` → `api/jobs.js`
- Replace `urllib.request` calls with `fetch()` (built-in Node 18+)
- Replace `BaseHTTPRequestHandler` with Vercel's default JS handler format: `export default function handler(req, res) { ... }`
- `requirements.txt` → `package.json` (can be minimal, no dependencies needed)
- Upstash KV REST API calls are identical — just swap to `fetch`

**Option B — Upgrade Vercel to Pro ($20/mo):** Python works on Pro. No code changes needed.

**Option C — Split hosting:** Keep `jobs.html` on Vercel (static, works fine), move `api/scrape.py` + `api/jobs.py` to Railway or Render free tier.

---

## Environment / Config Notes

**Vercel environment variables needed (set in Vercel dashboard → Settings → Environment Variables):**
- `KV_REST_API_URL` — Upstash Redis REST URL
- `KV_REST_API_TOKEN` — Upstash Redis REST token

**No API keys needed for scraping** — Jina Reader and Jina Search are free with no auth.

**Git remotes:**
- `origin` → `https://github.com/devkantol-png/Jobscrapper.git` (main repo)
- `vercel` → `https://github.com/devkantol-png/jobscrapperdev.git` (Vercel-connected repo)
- Both are in sync as of this session.

**Git identity (important for Vercel deployments):**
- Must use: `devkantol@users.noreply.github.com` was the OLD email — now fixed to `245829157+devkantol-png@users.noreply.github.com`
- Set locally: `git config user.email "245829157+devkantol-png@users.noreply.github.com"`

**Local scraper (`scraper.py`):**
- Runs independently on your machine (not Vercel)
- Uses `requests` + BeautifulSoup directly — no Jina, no Firecrawl
- Has its own Firecrawl key reference — may need updating if you want to run it locally

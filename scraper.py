#!/usr/bin/env python3
"""
Daily Job Scraper — Founder's Office, Chief of Staff, Growth, Strategy
Runs at 10am daily via cron, scrapes LinkedIn + Naukri, writes jobs.html
"""

import requests
import json
import re
import os
import sys
from datetime import datetime, timedelta

# ── Config ─────────────────────────────────────────────────────────────────
FIRECRAWL_API_KEY = "fc-24085ca9f4194d70abeefe9e6606fcd0"
OUTPUT_FILE       = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.html")
LOG_FILE          = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scraper.log")

LINKEDIN_SEARCHES = [
    {"query": "founder office jobs Gurgaon India",          "category": "founders", "city": "gurgaon"},
    {"query": "founder office jobs Mumbai India",           "category": "founders", "city": "mumbai"},
    {"query": "chief of staff jobs Gurgaon India",          "category": "cos",      "city": "gurgaon"},
    {"query": "chief of staff jobs Mumbai India",           "category": "cos",      "city": "mumbai"},
    {"query": "growth manager D2C startup Gurgaon India",   "category": "growth",   "city": "gurgaon"},
    {"query": "growth manager D2C startup Mumbai India",    "category": "growth",   "city": "mumbai"},
    {"query": "strategy operations startup Gurgaon India",  "category": "strategy", "city": "gurgaon"},
    {"query": "strategy operations startup Mumbai India",   "category": "strategy", "city": "mumbai"},
]

NAUKRI_SEARCHES = [
    {"url": "https://www.naukri.com/founder-office-jobs-in-gurgaon",  "category": "founders", "city": "gurgaon"},
    {"url": "https://www.naukri.com/founder-office-jobs-in-mumbai",   "category": "founders", "city": "mumbai"},
    {"url": "https://www.naukri.com/chief-of-staff-jobs-in-gurgaon",  "category": "cos",      "city": "gurgaon"},
    {"url": "https://www.naukri.com/chief-of-staff-jobs-in-mumbai",   "category": "cos",      "city": "mumbai"},
]


# ── Logging ────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# ── LinkedIn Scraper (via Firecrawl search API) ─────────────────────────────
def scrape_linkedin(search):
    """Use Firecrawl's native search API to find LinkedIn job listings."""
    query = f'site:linkedin.com/jobs {search["query"]}'
    try:
        resp = requests.post(
            "https://api.firecrawl.dev/v1/search",
            headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}", "Content-Type": "application/json"},
            json={"query": query, "limit": 10, "lang": "en", "country": "in"},
            timeout=30,
        )
        data = resp.json()
        if not data.get("success"):
            log(f"  LinkedIn search error ({search['city']}): {data.get('error','')}")
            return []
        results = data.get("data", [])
    except Exception as e:
        log(f"  LinkedIn search fetch error: {e}")
        return []

    jobs       = []
    city_label = search["city"].capitalize() + ", India"
    city_key   = search["city"].lower()
    city_aliases = {
        "gurgaon": ["gurgaon", "gurugram", "delhi ncr", "delhi", "ncr"],
        "mumbai":  ["mumbai", "bombay", "navi mumbai", "thane"],
    }
    ok_cities    = city_aliases.get(city_key, [city_key])
    other_cities = ["bangalore", "bengaluru", "hyderabad", "pune", "chennai",
                    "kolkata", "ahmedabad", "noida", "faridabad", "chandigarh"]
    li_pat     = re.compile(r'https://(?:www\.|in\.)?linkedin\.com/jobs/view/', re.IGNORECASE)
    seen_urls  = set()

    for result in results:
        job_url = result.get("url", "")
        if not li_pat.search(job_url) or job_url in seen_urls:
            continue
        seen_urls.add(job_url)

        raw_title = result.get("title", "")
        desc      = result.get("description", "")
        combined  = (raw_title + " " + desc).lower()

        # Skip if clearly belongs to another city
        if not any(c in combined for c in ok_cities):
            if any(c in combined for c in other_cities):
                continue

        # LinkedIn titles come in 3 formats:
        # 1) "Company hiring Role [in Location]"
        # 2) "Role at Company | LinkedIn"
        # 3) "Role - Part - Company - LinkedIn"
        hire_m = re.search(
            r'^(.+?)\s+(?:is\s+)?hiring\s+(.+?)(?:\s+in\s+[\w\s,]+)?$',
            raw_title, re.IGNORECASE
        )
        at_m = re.search(
            r'^(.+?)\s+at\s+(.+?)(?:\s*\|\s*LinkedIn.*)?$',
            raw_title, re.IGNORECASE
        )
        if hire_m:
            company = clean(hire_m.group(1))
            role    = clean(hire_m.group(2))
        elif at_m:
            role    = clean(at_m.group(1))
            company = clean(at_m.group(2).split('|')[0].strip())
        else:
            clean_t = re.sub(r'\s*[-|]\s*LinkedIn.*$', '', raw_title, flags=re.IGNORECASE).strip()
            parts   = [p.strip() for p in re.split(r'\s*[-–]\s*', clean_t) if p.strip()]
            if len(parts) >= 2:
                role    = clean(parts[0])
                company = clean(parts[-1])
            else:
                role    = clean(clean_t)
                company = ""

        posted_m  = re.search(r'(\d+\s+(?:day|week|hour|month)s?\s+ago)', desc, re.IGNORECASE)
        posted    = posted_m.group(1) if posted_m else "Today"
        exp_date, days_left = calc_expiry(posted)

        # Skip expired postings
        if days_left == 0:
            continue

        jobs.append({
            "role":       role,
            "company":    company,
            "location":   city_label,
            "city":       city_key,
            "category":   search["category"],
            "posted":     posted,
            "url":        job_url,
            "salary":     None,
            "exp":        "Not specified",
            "tags":       infer_tags(role, company, search["category"]),
            "fresh":      "day" in posted or "hour" in posted or posted == "Today",
            "expires_on": exp_date,
            "days_left":  days_left,
            "source":     "linkedin",
        })

    log(f"  LinkedIn: {len(jobs)} jobs — {search['query'][:40]}")
    return jobs


# ── Naukri Scraper (via Firecrawl) ─────────────────────────────────────────
def scrape_naukri(search):
    try:
        resp = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={
                "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "url": search["url"],
                "formats": ["markdown"],
                "onlyMainContent": True,
                "waitFor": 2000,
            },
            timeout=30,
        )
        data = resp.json()
        if not data.get("success"):
            log(f"  Naukri Firecrawl error: {data.get('error')}")
            return []
        md = data["data"].get("markdown", "")
    except Exception as e:
        log(f"  Naukri fetch error: {e}")
        return []

    jobs = []
    # Parse markdown job listings — pattern: ## [Title](url)
    link_pat  = re.compile(r'##\s+\[([^\]]+)\]\(([^)]+)\)', re.MULTILINE)
    # Look for salary patterns like "20-35 Lacs PA" or "25-45 LPA"
    salary_pat= re.compile(r'(\d[\d.]*[-–]\d[\d.]*\s*(?:Lac[s]?|LPA|lpa|L PA)\s*(?:PA)?)', re.IGNORECASE)
    # Exp patterns like "2-5 Yrs"
    exp_pat   = re.compile(r'(\d+[-–]\d+\s*Yrs?)', re.IGNORECASE)

    # Split into blocks per job
    blocks = re.split(r'\n(?=##\s+\[)', md)
    for block in blocks:
        lm = link_pat.search(block)
        if not lm:
            continue
        title = clean(lm.group(1))
        url   = lm.group(2)

        # Skip if title looks like navigation / non-job
        skip_words = ["login", "register", "naukri", "buy online", "employer"]
        if any(sw in title.lower() for sw in skip_words):
            continue

        salary = salary_pat.search(block)
        exp    = exp_pat.search(block)

        # Company: usually on a line after the title
        company_match = re.search(r'\n\[([^\]]+)\]\(https://www\.naukri\.com/[^)]*-jobs-careers', block)
        company = clean(company_match.group(1)) if company_match else ""

        # Try to find posted time
        posted_match = re.search(r'(\d+\s+(?:day|week|hour|month)s?\s+ago)', block, re.IGNORECASE)
        posted = posted_match.group(1) if posted_match else "Today"

        exp_date, days_left = calc_expiry(posted)
        jobs.append({
            "role":       title,
            "company":    company,
            "location":   search["city"].capitalize() + ", India",
            "city":       search["city"],
            "category":   search["category"],
            "posted":     posted,
            "url":        url if url.startswith("http") else "https://www.naukri.com" + url,
            "salary":     clean(salary.group(1)) if salary else None,
            "exp":        clean(exp.group(1)) if exp else "Not specified",
            "tags":       infer_tags(title, company, search["category"]),
            "fresh":      "day" in posted or "hour" in posted,
            "expires_on": exp_date,
            "days_left":  days_left,
            "source":     "naukri",
        })

    log(f"  Naukri: {len(jobs)} jobs — {search['url'].split('/')[-1]}")
    return jobs


# ── Helpers ─────────────────────────────────────────────────────────────────
def clean(s):
    return re.sub(r'\s+', ' ', s or "").strip()

def calc_expiry(posted_str):
    """
    Jobs on Naukri/LinkedIn typically expire 30 days after posting.
    Parse the relative posted string → calculate expiry date → days remaining.
    Returns (expiry_date_str, days_remaining)
    """
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    s = (posted_str or "").lower().strip()

    # Parse how many days ago it was posted
    days_ago = 0
    if "today" in s or s == "":
        days_ago = 0
    elif m := re.search(r'(\d+)\s*hour', s):
        days_ago = 0
    elif m := re.search(r'(\d+)\s*minute', s):
        days_ago = 0
    elif m := re.search(r'(\d+)\s*day', s):
        days_ago = int(m.group(1))
    elif m := re.search(r'(\d+)\s*week', s):
        days_ago = int(m.group(1)) * 7
    elif m := re.search(r'(\d+)\s*month', s):
        days_ago = int(m.group(1)) * 30
    elif "yesterday" in s:
        days_ago = 1

    posted_date  = today - timedelta(days=days_ago)
    expiry_date  = posted_date + timedelta(days=30)   # 30-day standard TTL
    days_left    = (expiry_date - today).days

    return expiry_date.strftime("%d %b %Y"), max(days_left, 0)

def infer_tags(role, company, category):
    tags = []
    text = (role + " " + company).lower()
    if any(w in text for w in ["d2c", "direct to consumer", "dtc", "brand", "consumer"]):
        tags.append("d2c")
    if any(w in text for w in ["growth", "expand", "scale"]):
        tags.append("growth")
    if any(w in text for w in ["strategy", "consulting", "advisory"]):
        tags.append("strategy")
    # Company size heuristics
    big = ["mckinsey","bcg","bain","pwc","deloitte","accenture","mongodb","google","microsoft",
           "amazon","flipkart","swiggy","zomato","dlf","healthkart","noise","barclays","bank"]
    if any(b in text for b in big):
        tags.append("mnc")
    else:
        tags.append("startup")
    return list(set(tags))

def dedupe(jobs):
    seen = set()
    out  = []
    for j in jobs:
        key = (j["role"].lower()[:40], j["company"].lower()[:20])
        if key not in seen:
            seen.add(key)
            out.append(j)
    return out


# ── HTML Generator ──────────────────────────────────────────────────────────
def generate_html(jobs, scraped_at):
    fresh_count = sum(1 for j in jobs if j.get("fresh"))
    jobs_json   = json.dumps(jobs, ensure_ascii=False, indent=2)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Job Board — Founder's Office · CoS · Growth · Strategy</title>
  <style>
    :root{{--bg:#0f1117;--surface:#1a1d27;--surface2:#22263a;--border:#2e3248;--accent:#6c63ff;--accent2:#00d4aa;--accent3:#ff6b6b;--accent4:#ffa94d;--text:#e8eaf6;--muted:#8b92b8;--tag-bg:#1e2235;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    body{{background:var(--bg);color:var(--text);font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;min-height:100vh;}}
    header{{background:linear-gradient(135deg,#1a1d27 0%,#12142a 100%);border-bottom:1px solid var(--border);padding:24px 40px;position:sticky;top:0;z-index:100;}}
    .header-inner{{max-width:1300px;margin:0 auto;display:flex;align-items:center;gap:20px;flex-wrap:wrap;}}
    .logo{{font-size:22px;font-weight:700;letter-spacing:-0.5px;}}.logo span{{color:var(--accent);}}
    .stats-bar{{display:flex;gap:24px;margin-left:auto;}}
    .stat{{text-align:center;}}.stat-n{{font-size:22px;font-weight:700;color:var(--accent2);}}.stat-l{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;}}
    .hero{{background:linear-gradient(135deg,#1a1d27 0%,#0d0f1e 60%,#12142a 100%);padding:50px 40px 40px;border-bottom:1px solid var(--border);}}
    .hero-inner{{max-width:1300px;margin:0 auto;}}
    .hero h1{{font-size:36px;font-weight:800;letter-spacing:-1px;line-height:1.2;}}.hero h1 em{{font-style:normal;color:var(--accent);}}
    .hero p{{color:var(--muted);margin-top:10px;font-size:14px;}}
    .pills{{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px;}}
    .pill{{background:var(--surface2);border:1px solid var(--border);border-radius:20px;padding:5px 14px;font-size:13px;}}
    .filters-bar{{background:var(--surface);border-bottom:1px solid var(--border);padding:16px 40px;position:sticky;top:73px;z-index:90;}}
    .filters-inner{{max-width:1300px;margin:0 auto;display:flex;gap:10px;align-items:center;flex-wrap:wrap;}}
    .search-box{{flex:1;min-width:200px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:9px 14px;color:var(--text);font-size:14px;outline:none;transition:border-color .2s;}}.search-box:focus{{border-color:var(--accent);}}
    .filter-btn{{padding:8px 15px;border-radius:8px;border:1px solid var(--border);background:var(--surface2);color:var(--muted);font-size:13px;cursor:pointer;transition:all .2s;white-space:nowrap;}}
    .filter-btn:hover,.filter-btn.active{{background:var(--accent);border-color:var(--accent);color:#fff;}}
    .results-count{{margin-left:auto;color:var(--muted);font-size:13px;white-space:nowrap;}}
    .grid-wrap{{max-width:1300px;margin:0 auto;padding:28px 40px 60px;}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;}}
    .card{{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:22px 24px;transition:all .2s;text-decoration:none;display:flex;flex-direction:column;gap:12px;position:relative;overflow:hidden;color:var(--text);}}
    .card::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;border-radius:14px 14px 0 0;}}
    .card.founders::before{{background:var(--accent);}}.card.cos::before{{background:var(--accent2);}}.card.growth::before{{background:var(--accent4);}}.card.strategy::before{{background:var(--accent3);}}
    .card:hover{{border-color:var(--accent);transform:translateY(-2px);box-shadow:0 8px 32px rgba(108,99,255,.15);}}
    .card-top{{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;}}
    .company-logo{{width:40px;height:40px;border-radius:10px;background:var(--surface2);border:1px solid var(--border);display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;}}
    .card-meta{{flex:1;min-width:0;}}.card-role{{font-size:15px;font-weight:600;line-height:1.35;margin-bottom:3px;}}.card-company{{font-size:13px;color:var(--muted);}}
    .badge-new{{background:rgba(0,212,170,.15);color:var(--accent2);border:1px solid rgba(0,212,170,.3);border-radius:6px;padding:3px 8px;font-size:11px;font-weight:600;white-space:nowrap;flex-shrink:0;}}
    .badge-hot{{background:rgba(255,107,107,.15);color:var(--accent3);border:1px solid rgba(255,107,107,.3);border-radius:6px;padding:3px 8px;font-size:11px;font-weight:600;white-space:nowrap;flex-shrink:0;}}
    .card-info{{display:flex;flex-wrap:wrap;gap:8px;}}
    .chip{{display:flex;align-items:center;gap:5px;font-size:12px;color:var(--muted);background:var(--tag-bg);border-radius:6px;padding:4px 10px;}}
    .dot{{width:6px;height:6px;border-radius:50%;background:var(--accent);flex-shrink:0;}}.dot.g{{background:var(--accent2);}}.dot.o{{background:var(--accent4);}}
    .card-tags{{display:flex;flex-wrap:wrap;gap:6px;}}
    .tag{{font-size:11px;border-radius:5px;padding:3px 8px;font-weight:500;}}
    .tag.d2c{{background:rgba(255,169,77,.15);color:var(--accent4);}}.tag.startup{{background:rgba(108,99,255,.15);color:var(--accent);}}.tag.mnc{{background:rgba(255,107,107,.1);color:var(--accent3);}}.tag.growth{{background:rgba(255,169,77,.12);color:var(--accent4);}}.tag.strategy{{background:rgba(255,107,107,.1);color:#ff9f9f;}}
    .card-footer{{display:flex;align-items:center;justify-content:space-between;margin-top:auto;padding-top:8px;border-top:1px solid var(--border);}}
    .posted-time{{font-size:12px;color:var(--muted);}}
    .apply-btn{{background:var(--accent);color:#fff;border:none;border-radius:7px;padding:7px 16px;font-size:13px;font-weight:600;cursor:pointer;text-decoration:none;}}
    .empty{{text-align:center;padding:80px 20px;color:var(--muted);grid-column:1/-1;}}.empty h3{{font-size:20px;margin-bottom:8px;color:var(--text);}}
    .source-badge{{font-size:10px;background:var(--surface2);border:1px solid var(--border);border-radius:4px;padding:2px 6px;color:var(--muted);}}
    ::-webkit-scrollbar{{width:6px;}}::-webkit-scrollbar-track{{background:var(--bg);}}::-webkit-scrollbar-thumb{{background:var(--border);border-radius:3px;}}
    @media(max-width:768px){{header,.hero,.filters-bar,.grid-wrap{{padding-left:20px;padding-right:20px;}}.hero h1{{font-size:24px;}}.stats-bar{{display:none;}}}}
  </style>
</head>
<body>
<header>
  <div class="header-inner">
    <div class="logo">job<span>hunt</span>.ai</div>
    <div class="stats-bar">
      <div class="stat"><div class="stat-n" id="total-count">{len(jobs)}</div><div class="stat-l">Total Roles</div></div>
      <div class="stat"><div class="stat-n">2</div><div class="stat-l">Cities</div></div>
      <div class="stat"><div class="stat-n">25–45</div><div class="stat-l">LPA Target</div></div>
      <div class="stat"><div class="stat-n">{fresh_count}</div><div class="stat-l">Fresh &lt;48h</div></div>
    </div>
  </div>
</header>

<div class="hero">
  <div class="hero-inner">
    <h1>Open Roles in <em>Founder's Office</em>, Chief of Staff,<br/>Growth &amp; Strategy</h1>
    <p>Auto-scraped from LinkedIn &amp; Naukri · Last updated: {scraped_at} · Gurgaon &amp; Mumbai</p>
    <div class="pills">
      <div class="pill">📍 Gurgaon &amp; Mumbai</div>
      <div class="pill">💰 25–45 LPA</div>
      <div class="pill">📅 4.5 Years Experience</div>
      <div class="pill">🏢 Any Stage · Prefer Established</div>
      <div class="pill">🛒 D2C Preferred</div>
    </div>
  </div>
</div>

<div class="filters-bar">
  <div class="filters-inner">
    <input class="search-box" type="text" placeholder="Search role, company..." id="search" oninput="filterJobs()"/>
    <button class="filter-btn active" onclick="setFilter('all',this)">All</button>
    <button class="filter-btn" onclick="setFilter('founders',this)">Founder's Office</button>
    <button class="filter-btn" onclick="setFilter('cos',this)">Chief of Staff</button>
    <button class="filter-btn" onclick="setFilter('growth',this)">Growth</button>
    <button class="filter-btn" onclick="setFilter('strategy',this)">Strategy</button>
    <button class="filter-btn" onclick="setFilter('gurgaon',this)">Gurgaon</button>
    <button class="filter-btn" onclick="setFilter('mumbai',this)">Mumbai</button>
    <button class="filter-btn" onclick="setFilter('d2c',this)">D2C</button>
    <span class="results-count" id="results-count">{len(jobs)} roles</span>
  </div>
</div>

<div class="grid-wrap"><div class="grid" id="job-grid"></div></div>

<script>
const JOBS = {jobs_json};
let activeFilter = 'all';

function setFilter(f, btn) {{
  activeFilter = f;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  filterJobs();
}}

function filterJobs() {{
  const q = document.getElementById('search').value.toLowerCase();
  const grid = document.getElementById('job-grid');
  grid.innerHTML = '';

  const filtered = JOBS.filter(j => {{
    const mf = activeFilter === 'all'
      || j.category === activeFilter
      || (activeFilter === 'gurgaon' && j.city === 'gurgaon')
      || (activeFilter === 'mumbai'  && j.city === 'mumbai')
      || (activeFilter === 'd2c'     && j.tags && j.tags.includes('d2c'));
    const ms = !q
      || j.role.toLowerCase().includes(q)
      || (j.company || '').toLowerCase().includes(q)
      || (j.location || '').toLowerCase().includes(q);
    return mf && ms;
  }});

  document.getElementById('results-count').textContent = filtered.length + ' role' + (filtered.length !== 1 ? 's' : '');

  if (!filtered.length) {{
    grid.innerHTML = '<div class="empty"><h3>No roles found</h3><p>Try adjusting your search or filters.</p></div>';
    return;
  }}

  filtered.sort((a, b) => (b.fresh ? 1 : 0) - (a.fresh ? 1 : 0));

  const cm = {{
    founders: {{ label: "Founder's Office", color: 'var(--accent)',  border: '#6c63ff' }},
    cos:      {{ label: 'Chief of Staff',   color: 'var(--accent2)', border: '#00d4aa' }},
    growth:   {{ label: 'Growth',           color: 'var(--accent4)', border: '#ffa94d' }},
    strategy: {{ label: 'Strategy',         color: 'var(--accent3)', border: '#ff6b6b' }},
  }};
  const tl = {{ d2c: '🛒 D2C', startup: '🚀 Startup', mnc: '🏢 MNC', growth: '📈 Growth', strategy: '🧩 Strategy' }};
  const emoji = {{ founders: '🎯', cos: '🤝', growth: '📈', strategy: '♟️' }};

  filtered.forEach(j => {{
    const m = cm[j.category] || cm.founders;
    const badge = j.posted && (j.posted.includes('hour') || j.posted.includes('minute'))
      ? '<span class="badge-hot">🔥 HOT</span>'
      : j.fresh ? '<span class="badge-new">NEW</span>' : '';
    const salaryChip = j.salary
      ? `<div class="chip"><span class="dot g"></span>${{j.salary}}</div>` : '';
    const tags = (j.tags || []).map(t => `<span class="tag ${{t}}">${{tl[t] || t}}</span>`).join('');
    const src  = j.source === 'naukri'
      ? '<span class="source-badge">Naukri</span>' : '<span class="source-badge">LinkedIn</span>';

    grid.innerHTML += `
      <a class="card ${{j.category}}" href="${{j.url}}" target="_blank" rel="noopener noreferrer">
        <div class="card-top">
          <div class="company-logo">${{emoji[j.category] || '💼'}}</div>
          <div class="card-meta">
            <div class="card-role">${{j.role}}</div>
            <div class="card-company">${{j.company || 'Company'}}</div>
          </div>
          ${{badge}}
        </div>
        <div class="card-info">
          <div class="chip"><span class="dot"></span>${{j.location}}</div>
          <div class="chip"><span class="dot o"></span>${{j.exp}}</div>
          ${{salaryChip}}
          <div class="chip" style="color:${{m.color}}">${{m.label}}</div>
          ${{src}}
        </div>
        <div class="card-tags">${{tags}}</div>
        <div class="card-footer">
          <span class="posted-time">⏱ ${{j.posted}}</span>
          <span class="apply-btn">Apply →</span>
        </div>
      </a>`;
  }});
}}

filterJobs();
</script>
</body>
</html>"""


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    scraped_at = datetime.now().strftime("%d %b %Y, %I:%M %p")
    log(f"=== Scraper started at {scraped_at} ===")

    all_jobs = []

    log("Scraping LinkedIn...")
    for s in LINKEDIN_SEARCHES:
        jobs = scrape_linkedin(s)
        all_jobs.extend(jobs)

    log("Scraping Naukri via Firecrawl...")
    for s in NAUKRI_SEARCHES:
        jobs = scrape_naukri(s)
        all_jobs.extend(jobs)

    log(f"Total before dedup: {len(all_jobs)}")
    all_jobs = dedupe(all_jobs)
    log(f"Total after dedup:  {len(all_jobs)}")

    html = generate_html(all_jobs, scraped_at)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    log(f"jobs.html written — {len(all_jobs)} roles — {OUTPUT_FILE}")
    log("=== Done ===\n")
    return len(all_jobs)


if __name__ == "__main__":
    count = main()
    sys.exit(0 if count > 0 else 1)

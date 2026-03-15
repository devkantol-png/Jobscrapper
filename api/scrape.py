"""
Vercel Serverless Function — GET /api/scrape
Called by Vercel Cron at 04:30 UTC (10:00 AM IST) every day.
Scrapes Naukri via Firecrawl, stores JSON in Upstash KV, returns summary.
"""

from http.server import BaseHTTPRequestHandler
import json
import os
import re
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "fc-24085ca9f4194d70abeefe9e6606fcd0")
KV_REST_API_URL   = os.environ.get("KV_REST_API_URL", "")
KV_REST_API_TOKEN = os.environ.get("KV_REST_API_TOKEN", "")

NAUKRI_SEARCHES = [
    {"url": "https://www.naukri.com/founder-office-jobs-in-gurgaon",  "category": "founders", "city": "gurgaon"},
    {"url": "https://www.naukri.com/founder-office-jobs-in-mumbai",   "category": "founders", "city": "mumbai"},
    {"url": "https://www.naukri.com/chief-of-staff-jobs-in-gurgaon",  "category": "cos",      "city": "gurgaon"},
    {"url": "https://www.naukri.com/chief-of-staff-jobs-in-mumbai",   "category": "cos",      "city": "mumbai"},
    {"url": "https://www.naukri.com/growth-manager-jobs-in-gurgaon",  "category": "growth",   "city": "gurgaon"},
    {"url": "https://www.naukri.com/growth-manager-jobs-in-mumbai",   "category": "growth",   "city": "mumbai"},
]

LINKEDIN_SEARCHES = [
    {"query": "founder office jobs Gurgaon India",         "category": "founders", "city": "gurgaon"},
    {"query": "founder office jobs Mumbai India",          "category": "founders", "city": "mumbai"},
    {"query": "chief of staff jobs Gurgaon India",         "category": "cos",      "city": "gurgaon"},
    {"query": "chief of staff jobs Mumbai India",          "category": "cos",      "city": "mumbai"},
    {"query": "growth manager D2C startup Gurgaon India",  "category": "growth",   "city": "gurgaon"},
    {"query": "growth manager D2C startup Mumbai India",   "category": "growth",   "city": "mumbai"},
    {"query": "strategy operations startup Gurgaon India", "category": "strategy", "city": "gurgaon"},
    {"query": "strategy operations startup Mumbai India",  "category": "strategy", "city": "mumbai"},
]

def clean(s):
    return re.sub(r'\s+', ' ', s or "").strip()

def calc_expiry(posted_str):
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    s = (posted_str or "").lower().strip()
    days_ago = 0
    if m := re.search(r'(\d+)\s*day',    s): days_ago = int(m.group(1))
    elif m := re.search(r'(\d+)\s*week', s): days_ago = int(m.group(1)) * 7
    elif m := re.search(r'(\d+)\s*month',s): days_ago = int(m.group(1)) * 30
    elif "yesterday" in s: days_ago = 1
    expiry    = today - timedelta(days=days_ago) + timedelta(days=30)
    days_left = max((expiry - today).days, 0)
    return expiry.strftime("%d %b %Y"), days_left

def infer_tags(role, company, category):
    text = (role + " " + company).lower()
    tags = []
    if any(w in text for w in ["d2c","brand","consumer","dtc"]): tags.append("d2c")
    if any(w in text for w in ["growth","scale"]): tags.append("growth")
    if any(w in text for w in ["strategy","consulting","advisory"]): tags.append("strategy")
    big = ["mckinsey","bcg","pwc","deloitte","accenture","mongodb","google","microsoft",
           "amazon","flipkart","swiggy","zomato","dlf","healthkart","noise","barclays"]
    tags.append("mnc" if any(b in text for b in big) else "startup")
    return list(set(tags))

def firecrawl_scrape(url):
    payload = json.dumps({
        "url": url, "formats": ["markdown"],
        "onlyMainContent": True, "waitFor": 2000
    }).encode()
    req = urllib.request.Request(
        "https://api.firecrawl.dev/v1/scrape", data=payload,
        headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}", "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"success": False, "error": str(e)}

def parse_linkedin(search):
    """Search Google for site:linkedin.com/jobs and parse results via Firecrawl."""
    q   = urllib.parse.quote(f'site:linkedin.com/jobs {search["query"]}')
    url = f"https://www.google.com/search?q={q}&num=20&hl=en&gl=in"
    data = firecrawl_scrape(url)
    if not data.get("success"):
        return []
    md = data.get("data", {}).get("markdown", "")
    jobs = []
    city_label = search["city"].capitalize() + ", India"
    direct_pat   = re.compile(r'\[([^\]]{5,120})\]\((https://(?:www\.|in\.)?linkedin\.com/jobs/view/[^\s\)]+)\)')
    redirect_pat = re.compile(r'\[([^\]]{5,120})\]\(/url\?[^)]*q=(https?://(?:www\.|in\.)?linkedin\.com/jobs/view/[^&\s\)]+)')
    seen_urls = set()
    for pat in (direct_pat, redirect_pat):
        for m in pat.finditer(md):
            title   = clean(m.group(1))
            job_url = m.group(2) if pat is direct_pat else urllib.parse.unquote(m.group(2))
            if not title or job_url in seen_urls:
                continue
            if any(s in job_url.lower() or s in title.lower() for s in ["login","sign in","join","linkedin.com/company","linkedin.com/in/"]):
                continue
            seen_urls.add(job_url)
            snippet   = md[m.end():m.end()+200]
            company_m = re.search(r'[·\|]\s*([A-Za-z][^\n·\|]{2,50}?)\s*[·\|]', snippet)
            company   = clean(company_m.group(1)) if company_m else ""
            posted_m  = re.search(r'(\d+\s+(?:day|week|hour|month)s?\s+ago)', snippet, re.IGNORECASE)
            posted    = posted_m.group(1) if posted_m else "Today"
            exp_date, days_left = calc_expiry(posted)
            jobs.append({
                "role": title, "company": company, "location": city_label,
                "city": search["city"], "category": search["category"],
                "posted": posted, "url": job_url, "salary": None,
                "exp": "Not specified", "tags": infer_tags(title, company, search["category"]),
                "fresh": "day" in posted or "hour" in posted or posted == "Today",
                "expires_on": exp_date, "days_left": days_left, "source": "linkedin",
            })
    return jobs


def parse_naukri(search):
    data = firecrawl_scrape(search["url"])
    if not data.get("success"):
        return []
    md = data.get("data", {}).get("markdown", "")
    jobs = []
    link_pat   = re.compile(r'##\s+\[([^\]]+)\]\(([^)]+)\)', re.MULTILINE)
    salary_pat = re.compile(r'(\d[\d.]*[-–]\d[\d.]*\s*(?:Lacs?|LPA)\s*(?:PA)?)', re.IGNORECASE)
    exp_pat    = re.compile(r'(\d+[-–]\d+\s*Yrs?)', re.IGNORECASE)
    blocks = re.split(r'\n(?=##\s+\[)', md)
    for block in blocks:
        lm = link_pat.search(block)
        if not lm: continue
        title = clean(lm.group(1))
        url   = lm.group(2)
        if any(w in title.lower() for w in ["login","register","naukri","buy online","employer"]): continue
        salary    = salary_pat.search(block)
        exp       = exp_pat.search(block)
        company_m = re.search(r'\n\[([^\]]+)\]\(https://www\.naukri\.com/[^)]*-jobs-careers', block)
        company   = clean(company_m.group(1)) if company_m else ""
        posted_m  = re.search(r'(\d+\s+(?:day|week|hour|month)s?\s+ago)', block, re.IGNORECASE)
        posted    = posted_m.group(1) if posted_m else "Today"
        exp_date, days_left = calc_expiry(posted)
        jobs.append({
            "role": title, "company": company,
            "location": search["city"].capitalize() + ", India",
            "city": search["city"], "category": search["category"],
            "posted": posted,
            "url": url if url.startswith("http") else "https://www.naukri.com" + url,
            "salary": clean(salary.group(1)) if salary else None,
            "exp": clean(exp.group(1)) if exp else "Not specified",
            "tags": infer_tags(title, company, search["category"]),
            "fresh": "day" in posted or "hour" in posted or "today" in posted.lower(),
            "expires_on": exp_date, "days_left": days_left, "source": "naukri",
        })
    return jobs

def dedupe(jobs):
    seen, out = set(), []
    for j in jobs:
        key = (j["role"].lower()[:40], j["company"].lower()[:20])
        if key not in seen:
            seen.add(key)
            out.append(j)
    return out

def kv_set(key, value):
    if not KV_REST_API_URL or not KV_REST_API_TOKEN:
        return False
    data = json.dumps(value).encode()
    req  = urllib.request.Request(
        f"{KV_REST_API_URL}/set/{urllib.parse.quote(key)}",
        data=data,
        headers={"Authorization": f"Bearer {KV_REST_API_TOKEN}", "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        scraped_at = datetime.utcnow().strftime("%d %b %Y, %I:%M %p UTC")
        all_jobs = []
        for s in LINKEDIN_SEARCHES:
            all_jobs.extend(parse_linkedin(s))
        for s in NAUKRI_SEARCHES:
            all_jobs.extend(parse_naukri(s))
        all_jobs = dedupe(all_jobs)
        payload  = {"scraped_at": scraped_at, "count": len(all_jobs), "jobs": all_jobs}
        kv_set("jobs_data", payload)
        body = json.dumps({"ok": True, "scraped_at": scraped_at, "count": len(all_jobs)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.do_GET()

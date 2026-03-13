"""
Vercel Serverless Function — GET /api/jobs
Returns the latest scraped jobs JSON from Vercel KV.
Frontend fetches this on load instead of using hardcoded data.
"""

import json
import os
import urllib.request

KV_REST_API_URL   = os.environ.get("KV_REST_API_URL", "")
KV_REST_API_TOKEN = os.environ.get("KV_REST_API_TOKEN", "")


def kv_get(key):
    if not KV_REST_API_URL or not KV_REST_API_TOKEN:
        return None
    url = f"{KV_REST_API_URL}/get/{key}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {KV_REST_API_TOKEN}"},
        method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            return body.get("result")
    except Exception:
        return None


def handler(request, response):
    data = kv_get("jobs_data")

    response.headers["Content-Type"]                = "application/json"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Cache-Control"]               = "s-maxage=3600, stale-while-revalidate"

    if not data:
        response.status_code = 503
        response.write(json.dumps({"error": "No data yet. Trigger /api/scrape first."}))
        return

    response.status_code = 200
    response.write(json.dumps(data) if isinstance(data, str) else json.dumps(data))

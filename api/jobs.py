"""
Vercel Serverless Function — GET /api/jobs
Returns the latest scraped jobs JSON from Upstash KV.
"""

from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request

KV_REST_API_URL   = os.environ.get("KV_REST_API_URL", "")
KV_REST_API_TOKEN = os.environ.get("KV_REST_API_TOKEN", "")


def kv_get(key):
    if not KV_REST_API_URL or not KV_REST_API_TOKEN:
        return None
    req = urllib.request.Request(
        f"{KV_REST_API_URL}/get/{key}",
        headers={"Authorization": f"Bearer {KV_REST_API_TOKEN}"},
        method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            result = body.get("result")
            if isinstance(result, str):
                return json.loads(result)
            return result
    except Exception:
        return None


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = kv_get("jobs_data")
        self.send_response(200 if data else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "s-maxage=3600, stale-while-revalidate")
        self.end_headers()
        if not data:
            self.wfile.write(json.dumps({"error": "No data yet. Trigger /api/scrape first."}).encode())
        else:
            self.wfile.write(json.dumps(data).encode())

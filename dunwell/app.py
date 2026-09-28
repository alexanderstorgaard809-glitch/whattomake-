#!/usr/bin/env python3
"""Dunwell: få betaling fra kunder i EU og UK.

Lokalt:  python app.py      og åbn http://localhost:8000
Online:  se README (Render). Sæt HOST=0.0.0.0 og miljøvariablerne OPENROUTER_API_KEY, OPERATOR_NAME, CONTACT_EMAIL.

Privatliv: uploadede filer og sagsdata behandles kun i hukommelsen under forespørgslen og gemmes aldrig.
Der logges kun metode, sti og statuskode (ingen IP-adresser, ingen indhold).
"""

import json
import os
import sys
import threading
import time
import traceback
import webbrowser
from collections import defaultdict, deque
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import ai
import claims

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
EXAMPLES = ROOT / "examples"
MAX_BODY = 12 * 1024 * 1024  # ca. 8 MB filer efter base64
LAST_UPDATED = "28 September 2026"

PAGES = {"/": "landing.html", "/app": "app.html", "/privacy": "privacy.html", "/terms": "terms.html"}
ASSETS = {"/site.css": ("site.css", "text/css; charset=utf-8")}
EXAMPLE_TYPES = {".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    # Alt ligger på egen server: ingen eksterne scripts, fonte eller trackere.
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                               "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
}


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


# ---------------- Begrænsning af misbrug ----------------

class RateLimiter:
    """Simpel grænse i hukommelsen: X AI-kald pr. IP pr. time og et samlet dagligt loft.
    IP-adresser holdes kun i hukommelsen i op til en time og skrives aldrig til disk eller log."""

    def __init__(self, per_ip_per_hour, per_day):
        self.per_ip, self.per_day = per_ip_per_hour, per_day
        self.hits = defaultdict(deque)
        self.day, self.day_count = date.today(), 0
        self.lock = threading.Lock()

    def allow(self, ip):
        now = time.time()
        with self.lock:
            if date.today() != self.day:
                self.day, self.day_count = date.today(), 0
            q = self.hits[ip]
            while q and now - q[0] > 3600:
                q.popleft()
            if not q:
                self.hits.pop(ip, None)
                q = self.hits[ip]
            if self.day_count >= self.per_day:
                return "The demo has reached its daily limit. Please try again tomorrow."
            if len(q) >= self.per_ip:
                return "You've reached the demo limit for this hour. Please try again later."
            q.append(now)
            self.day_count += 1
            return None


_limits = config().get("demo_limits", {})
LIMITER = RateLimiter(_limits.get("ai_calls_per_ip_per_hour", 10), _limits.get("ai_calls_per_day", 200))


# ---------------- API ----------------

def _calc(claim, payload, cfg):
    """Beregning i koden. `rate_override` er kun sat, hvis brugeren selv har rettet renten på siden."""
    return claims.calculate(claim, cfg["rates"], rate_override=payload.get("rate_override"))


def _llm(cfg):
    return ai.OpenRouter(cfg["models"], privacy=cfg.get("privacy"))


def analyze(payload):
    cfg = config()
    llm = _llm(cfg)
    claim = ai.extract_claim(llm, payload.get("files", [])[:6], (payload.get("notes") or "")[:4000])
    claim["disputed"] = bool((claim.get("dispute_signals") or "").strip())
    return {"claim": claim, "calc": _calc(claim, {}, cfg),
            "language": claims.default_language(claim["debtor"].get("country")),
            "cost": round(llm.total_cost, 4)}


def letter(payload):
    cfg = config()
    claim = payload["claim"]
    calc = _calc(claim, payload, cfg)  # altid genberegnet i koden, aldrig af AI
    deadline = (date.today() + timedelta(days=calc["deadline_days"])).isoformat()
    llm = _llm(cfg)
    result = ai.write_letter(llm, claim, calc, payload.get("language") or "en", deadline,
                             (payload.get("note") or "")[:500])
    return {"letter": result, "calc": calc, "deadline": deadline, "cost": round(llm.total_cost, 4)}


def recalc(payload):
    return {"calc": _calc(payload["claim"], payload, config())}


def meta(_payload=None):
    rates = config()["rates"]
    return {"countries": {k: v[0] for k, v in sorted(claims.COUNTRIES.items(), key=lambda kv: kv[1][0])},
            "languages": claims.LANGUAGES, "rate_notes": {k: v["note"] for k, v in rates.items()}}


ROUTES = {"/api/analyze": analyze, "/api/letter": letter, "/api/recalc": recalc, "/api/meta": meta}
AI_ROUTES = {"/api/analyze", "/api/letter"}


def render_page(name):
    html = (STATIC / name).read_text(encoding="utf-8")
    values = {
        "OPERATOR_NAME": os.environ.get("OPERATOR_NAME", "[Your name or company]"),
        "CONTACT_EMAIL": os.environ.get("CONTACT_EMAIL", "[your@email]"),
        "OPERATOR_ADDRESS": os.environ.get("OPERATOR_ADDRESS", "[Your address]"),
        "OPERATOR_COUNTRY": os.environ.get("OPERATOR_COUNTRY", "[your country]"),
        "LAST_UPDATED": LAST_UPDATED,
    }
    for k, v in values.items():
        html = html.replace("{{" + k + "}}", v)
    return html.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "Dunwell"
    sys_version = ""

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            return self._send(200, b"ok", "text/plain")
        if path == "/api/meta":
            return self._json(200, meta())
        if path in PAGES:
            return self._send(200, render_page(PAGES[path]), "text/html; charset=utf-8")
        if path in ASSETS:
            name, ctype = ASSETS[path]
            return self._send(200, (STATIC / name).read_bytes(), ctype, cache=True)
        if path.startswith("/examples/"):
            name = path[len("/examples/"):]
            f = EXAMPLES / name
            if "/" not in name and f.suffix in EXAMPLE_TYPES and f.is_file():
                return self._send(200, f.read_bytes(), EXAMPLE_TYPES[f.suffix], cache=True)
        self._send(404, b"Not found", "text/plain")

    def do_POST(self):
        handler = ROUTES.get(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if not handler:
            return self._json(404, {"error": "Not found"})
        if length > MAX_BODY:
            return self._json(413, {"error": "The files are too large (max about 8 MB in total)."})
        if self.path in AI_ROUTES:
            blocked = LIMITER.allow(self._client_ip())
            if blocked:
                return self._json(429, {"error": blocked})
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            self._json(200, handler(payload))
        except ai.AIError as e:
            sys.stderr.write(f"  AI error: {e}\n")
            self._json(502, {"error": "The AI service could not process this right now. Please try again."
                             if os.environ.get("PUBLIC") else str(e)})
        except Exception as e:
            traceback.print_exc()  # kun serverens log, ingen brugerdata
            self._json(500, {"error": "Something went wrong." if os.environ.get("PUBLIC")
                             else f"{type(e).__name__}: {e}"})

    def _client_ip(self):
        fwd = self.headers.get("X-Forwarded-For")
        # Render's proxy tilføjer den rigtige klient-IP til sidst; tidligere værdier kan være forfalsket.
        return fwd.split(",")[-1].strip() if fwd else self.client_address[0]

    def _send(self, status, body, ctype, cache=False):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600" if cache else "no-store")
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, data):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def log_message(self, fmt, *args):
        # Standardloggen indeholder IP-adressen; vi logger kun metode, sti og status.
        if args and isinstance(args[0], str):
            sys.stderr.write(f"  {args[0].split(' HTTP')[0]} -> {args[1] if len(args) > 1 else ''}\n")


def main():
    load_env()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 8000))
    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://localhost:{port}"
    print(f"Dunwell kører på {url}  (stop med Ctrl+C)", flush=True)
    if host == "127.0.0.1":
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStoppet.")


if __name__ == "__main__":
    main()

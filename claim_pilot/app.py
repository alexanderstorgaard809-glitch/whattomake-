#!/usr/bin/env python3
"""Claim Pilot: få betaling fra kunder i andre EU-lande.

Start:  python app.py      og åbn http://localhost:8000 i browseren.
"""

import json
import os
import sys
import webbrowser
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import ai
import claims

ROOT = Path(__file__).parent
MAX_BODY = 25 * 1024 * 1024  # 25 MB (filer sendes som base64)


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def analyze(payload):
    cfg = config()
    llm = ai.OpenRouter(cfg["models"])
    claim = ai.extract_claim(llm, payload.get("files", []), payload.get("notes", ""))
    claim["disputed"] = bool((claim.get("dispute_signals") or "").strip())
    rate = cfg["late_payment_rate_percent"]
    calc = claims.calculate(claim, rate)
    return {"claim": claim, "calc": calc, "rate_percent": rate,
            "language": claims.default_language(claim["debtor"].get("country")),
            "cost": round(llm.total_cost, 4)}


def letter(payload):
    cfg = config()
    claim, rate = payload["claim"], float(payload.get("rate_percent") or cfg["late_payment_rate_percent"])
    calc = claims.calculate(claim, rate)  # altid genberegnet i koden, aldrig af AI
    deadline = (date.today() + timedelta(days=int(cfg.get("payment_deadline_days", 14)))).isoformat()
    llm = ai.OpenRouter(cfg["models"])
    result = ai.write_letter(llm, claim, calc, payload.get("language") or "en", deadline, payload.get("note", ""))
    return {"letter": result, "calc": calc, "deadline": deadline, "cost": round(llm.total_cost, 4)}


def recalc(payload):
    rate = float(payload.get("rate_percent") or config()["late_payment_rate_percent"])
    return {"calc": claims.calculate(payload["claim"], rate)}


def meta(_payload=None):
    return {"countries": {k: v[0] for k, v in claims.EU_COUNTRIES.items()}, "languages": claims.LANGUAGES,
            "rate_percent": config()["late_payment_rate_percent"], "rate_note": config().get("rate_note", "")}


ROUTES = {"/api/analyze": analyze, "/api/letter": letter, "/api/recalc": recalc, "/api/meta": meta}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/meta":
            return self._json(200, meta())
        if self.path in ("/", "/index.html"):
            body = (ROOT / "static" / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        self._json(404, {"error": "Not found"})

    def do_POST(self):
        handler = ROUTES.get(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if not handler:
            return self._json(404, {"error": "Not found"})
        if length > MAX_BODY:
            return self._json(413, {"error": "Filerne er for store (max 25 MB i alt)."})
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            self._json(200, handler(payload))
        except ai.AIError as e:
            self._json(502, {"error": str(e)})
        except Exception as e:  # vis fejlen i browseren i stedet for at crashe
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def _json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("  " + (fmt % args) + "\n")


def main():
    load_env()
    port = int(os.environ.get("PORT", 8000))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://localhost:{port}"
    print(f"Claim Pilot kører på {url}  (stop med Ctrl+C)")
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

"""Henter udbud fra TED (Tenders Electronic Daily) via det officielle, gratis Search API v3.

API-spec: https://api.ted.europa.eu/api-v3.yaml  (ingen API-nøgle nødvendig til søgning)
Grænser: max 250 udbud pr. side, max 10.000 felter pr. side, ca. 1 kald pr. sekund.
"""

import json
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
PAGE_SIZE = 250

FIELDS = [
    "publication-number",
    "publication-date",
    "notice-type",
    "notice-title",
    "description-proc",
    "buyer-name",
    "buyer-country",
    "classification-cpv",
    "deadline-receipt-tender-date-lot",
    "estimated-value-proc",
    "estimated-value-cur-proc",
    "estimated-value-lot",
    "estimated-value-cur-lot",
    "procedure-type",
    "links",
]

# Foretrukne sprog når en tekst findes på flere sprog (ISO 639-2, som TED bruger).
PREFERRED_LANGS = ["eng", "dan", "deu", "fra", "nld", "swe", "nor"]


class TedError(Exception):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}  # TED's fejl-JSON, fx {"error": {"type": ..., "fieldValue": ...}}


def build_query(cpv_codes, days_back, notice_types=None):
    since = (date.today() - timedelta(days=days_back)).strftime("%Y%m%d")
    parts = [
        f"publication-date>={since}",
        f"classification-cpv IN ({' '.join(cpv_codes)})",
    ]
    if notice_types:
        parts.append(f"notice-type IN ({' '.join(notice_types)})")
    return " AND ".join(parts) + " SORT BY publication-date DESC"


def _post(body):
    req = urllib.request.Request(
        SEARCH_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:1000]
        try:
            details = json.loads(detail)
        except ValueError:
            details = {}
        raise TedError(f"TED svarede {e.code}: {detail}", details) from e
    except urllib.error.URLError as e:
        raise TedError(f"Kunne ikke forbinde til TED ({e.reason}). Tjek din internetforbindelse.") from e


def search(query, scope="ACTIVE", max_notices=5000, log=print):
    notices, page = [], 1
    while True:
        data = _post({
            "query": query,
            "fields": FIELDS,
            "limit": PAGE_SIZE,
            "page": page,
            "scope": scope,
            "paginationMode": "PAGE_NUMBER",
            "onlyLatestVersions": True,
        })
        batch = data.get("notices", [])
        notices.extend(batch)
        total = data.get("totalNoticeCount", len(notices))
        log(f"  side {page}: {len(batch)} udbud (i alt {len(notices)} af {total})")
        if not batch or len(notices) >= min(total, max_notices):
            return notices[:max_notices]
        page += 1
        time.sleep(1.1)  # TED tillader ca. 1 kald pr. sekund


def fetch(cpv_codes, days_back, notice_types, scope="ACTIVE", log=print):
    """Henter udbud. Hvis TED afviser en CPV-kode eller udbudstype, fjernes den, og der prøves igen."""
    cpv_codes, notice_types = list(cpv_codes), list(notice_types or [])
    for _ in range(len(cpv_codes) + len(notice_types) + 1):
        try:
            raw = search(build_query(cpv_codes, days_back, notice_types), scope, log=log)
            break
        except TedError as e:
            err = (e.details or {}).get("error") or {}
            field, value = err.get("fieldName"), err.get("fieldValue")
            if err.get("type") != "QUERY_UNSUPPORTED_FIELD_VALUE":
                raise
            if field == "classification-cpv" and value in cpv_codes:
                cpv_codes.remove(value)
                log(f"  TED kender ikke CPV-koden {value}, springer den over (fjern den gerne fra config.json)")
            elif field == "notice-type" and value in notice_types:
                notice_types.remove(value)
                log(f"  TED kender ikke udbudstypen {value}, springer den over")
            else:
                raise
    tenders = [normalize(n) for n in raw]
    if notice_types:
        tenders = [t for t in tenders if not t["notice_type"] or t["notice_type"] in notice_types]
    return tenders


# ---------- Normalisering af TED's rå felter til et simpelt format ----------

def pick_text(value):
    """TED returnerer tekster som {"eng": "..."} eller {"eng": ["..."]}. Vælg bedste sprog."""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " / ".join(pick_text(v) for v in value if v)
    if isinstance(value, dict):
        for lang in PREFERRED_LANGS + list(value.keys()):
            if value.get(lang):
                return pick_text(value[lang])
    return str(value)


def pick_first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def pick_link(links, pub_no):
    for kind in ("html", "htmlDirect", "pdf"):
        options = (links or {}).get(kind) or {}
        for lang in ("ENG", "eng", "EN", "en"):
            if options.get(lang):
                return options[lang]
        if options:
            return next(iter(options.values()))
    return f"https://ted.europa.eu/en/notice/-/detail/{pub_no}"


def estimated_value(n):
    value, cur = n.get("estimated-value-proc"), n.get("estimated-value-cur-proc")
    if value is None:
        lots = n.get("estimated-value-lot") or []
        lots = [v for v in lots if isinstance(v, (int, float))]
        if lots:
            value = sum(lots)
            cur = pick_first(n.get("estimated-value-cur-lot"))
    return value, pick_first(cur)


def normalize(n):
    pub_no = n.get("publication-number", "")
    deadlines = sorted(d for d in (n.get("deadline-receipt-tender-date-lot") or []) if d)
    value, currency = estimated_value(n)
    return {
        "id": pub_no,
        "published": (pick_first(n.get("publication-date")) or "")[:10],
        "notice_type": n.get("notice-type") or "",
        "title": pick_text(n.get("notice-title")),
        "description": pick_text(n.get("description-proc")),
        "buyer": pick_text(n.get("buyer-name")),
        "country": pick_first(n.get("buyer-country")) or "",
        "cpv": n.get("classification-cpv") or [],
        "deadline": deadlines[0][:10] if deadlines else "",
        "value": value,
        "currency": currency or "",
        "procedure": n.get("procedure-type") or "",
        "url": pick_link(n.get("links"), pub_no),
    }

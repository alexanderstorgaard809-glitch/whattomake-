"""De to AI-trin.

Trin 1 (summarize): Hvert udbud oversættes og opsummeres på engelsk ÉN gang og gemmes,
                    så det ikke skal betales igen for hver kunde.
Trin 2 (match):     For hver kundeprofil scores de opsummerede udbud 0-100 med en kort begrundelse.
"""

from ted import format_value

SUMMARY_BATCH = 10
MATCH_BATCH = 40

SUMMARY_SYSTEM = """You analyse EU public procurement notices from TED for small IT agencies.
Notices can be in any of the 24 EU languages. For each notice, return an English summary.
Be factual and concise. Never invent facts that are not in the notice."""

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title_en": {"type": "string", "description": "Short English title"},
                    "summary_en": {"type": "string", "description": "2-3 sentences: what the buyer wants"},
                    "work_type": {
                        "type": "string",
                        "enum": ["custom software", "website", "mobile app", "IT consulting",
                                 "software licences", "hosting/operations", "IT support",
                                 "data/AI", "hardware", "other"],
                    },
                    "keywords": {"type": "array", "items": {"type": "string"},
                                 "description": "Max 6 technologies or domains mentioned"},
                    "small_company_friendly": {
                        "type": "boolean",
                        "description": "False if the notice clearly requires a large supplier (huge turnover, many staff, big framework)",
                    },
                },
                "required": ["id", "title_en", "summary_en", "work_type", "keywords", "small_company_friendly"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

MATCH_SYSTEM = """You help a small company find public tenders worth bidding on.
Score how well each tender fits the company profile from 0 to 100. Use the full scale and
differentiate between tenders - do not give the same score to everything:
95-100 = service, technologies AND size all match; the company could clearly win this.
80-94  = core service matches, but technology, size or scope is less certain.
60-79  = relevant, worth a look.
30-59  = partially related.
0-29   = not relevant.
Lower the score if the tender is clearly too big for the company, is a large framework
agreement, or needs skills it lacks. Consider estimated value versus company size.
Write the reason ENTIRELY in the requested language (never mix languages), max 25 words,
concrete: name what matches and any risk."""

MATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "score": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "score", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

LANG_NAMES = {"da": "Danish", "en": "English", "de": "German", "sv": "Swedish", "no": "Norwegian"}

# Max score når bureauet ikke kan skrive tilbud på et af de sprog, udbuddet tillader.
LANGUAGE_CAP = 40


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _tender_text(t):
    desc = t["description"][:2500]
    value = format_value(t)
    return (f"ID: {t['id']}\nTitle: {t['title']}\nBuyer: {t['buyer']} ({t['country']})\n"
            f"CPV: {', '.join(t['cpv'][:6])}\nEstimated value: {value}\nDescription: {desc}")


def summarize(tenders, llm, cache, log=print):
    """Tilføjer 'ai'-felt til hvert udbud. `cache` er en dict id -> resumé, som opdateres."""
    todo = [t for t in tenders if t["id"] not in cache]
    log(f"  {len(tenders) - len(todo)} udbud er allerede opsummeret, {len(todo)} nye")
    for i, batch in enumerate(_chunks(todo, SUMMARY_BATCH), 1):
        user = "Summarise these notices:\n\n" + "\n\n---\n\n".join(_tender_text(t) for t in batch)
        result = llm.json_call(SUMMARY_SYSTEM, user, "tender_summaries", SUMMARY_SCHEMA)
        by_id = {item["id"]: item for item in result.get("items", [])}
        for t in batch:
            if t["id"] in by_id:
                cache[t["id"]] = by_id[t["id"]]
        log(f"  batch {i}: {len(by_id)}/{len(batch)} opsummeret (pris indtil nu: ${llm.total_cost:.4f})")
    for t in tenders:
        t["ai"] = cache.get(t["id"])
    return tenders


def language_ok(t, profile):
    """True hvis bureauet kan byde på et af udbuddets sprog (eller hvis vi ikke ved det)."""
    theirs, ours = set(t.get("languages") or []), {x.upper() for x in profile.get("languages") or []}
    return not theirs or not ours or bool(theirs & ours)


def match(tenders, profile, llm, log=print):
    """Returnerer liste af (udbud, score, begrundelse) sorteret efter score."""
    candidates = [t for t in tenders if t.get("ai")]
    lang = LANG_NAMES.get(profile.get("report_language", "en"), "English")
    profile_text = (f"Company: {profile['name']}\nDescription: {profile['description']}\n"
                    f"Services: {', '.join(profile.get('services', []))}\n"
                    f"Technologies: {', '.join(profile.get('technologies', []))}\n"
                    f"Size: {profile.get('size', 'unknown')}\n"
                    f"Languages they can write bids in: {', '.join(profile.get('languages', [])) or 'unknown'}\n"
                    f"Countries they can work in: {', '.join(profile.get('countries', ['any']))}\n"
                    f"Not interested in: {', '.join(profile.get('exclude', [])) or 'nothing specified'}")
    scored = {}
    for i, batch in enumerate(_chunks(candidates, MATCH_BATCH), 1):
        lines = []
        for t in batch:
            a = t["ai"]
            flag = "" if a["small_company_friendly"] else " [likely needs a large supplier]"
            langs = ", ".join(t.get("languages") or []) or "unknown"
            lines.append(f"- {t['id']} | {t['country']} | bid language: {langs} | value: {format_value(t)} | "
                         f"{a['work_type']} | {a['title_en']}: {a['summary_en']} "
                         f"Keywords: {', '.join(a['keywords'])}{flag}")
        user = (f"COMPANY PROFILE\n{profile_text}\n\nWrite reasons in {lang}.\n\n"
                f"TENDERS\n" + "\n".join(lines))
        result = llm.json_call(MATCH_SYSTEM, user, "tender_scores", MATCH_SCHEMA)
        for item in result.get("items", []):
            scored[item["id"]] = item
        log(f"  batch {i}: {len(batch)} udbud scoret (pris indtil nu: ${llm.total_cost:.4f})")
    results = []
    for t in candidates:
        if t["id"] not in scored:
            continue
        score = int(scored[t["id"]]["score"])
        if not language_ok(t, profile):
            score = min(score, LANGUAGE_CAP)
        results.append((t, score, scored[t["id"]]["reason"]))
    return sorted(results, key=lambda r: r[1], reverse=True)

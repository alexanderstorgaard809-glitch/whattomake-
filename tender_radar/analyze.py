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
    profile_text = _profile_text(profile)
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


# ---------------- Trin 3: grundig vurdering med stærkere model ----------------

RERANK_BATCH = 8

RERANK_SYSTEM = """You are an experienced bid manager advising a small company on which public tenders to bid for.
You get the company profile and the ORIGINAL tender text (any EU language) plus an English summary.
Read the original text carefully and judge realistically, like a sceptical expert:

1. purchase_type: is the buyer paying for custom development work, or buying a ready-made
   product/licence/SaaS, operations/support, consulting/staffing, hardware, or a mix?
2. conflicts_with_exclusions: true if a substantial part of the tender is something the company
   says it is NOT interested in (e.g. hardware, ERP, on-site support).
3. too_big: true if the value, duration, turnover requirements or scope are clearly beyond the
   company's size (e.g. huge multi-year frameworks, large references required).
4. score 0-100 using the full scale, and differentiate:
   95-100 only if service, technologies, sector AND size all fit and the company could realistically win;
   80-94 strong fit with one uncertainty; 60-79 relevant but clear risks; below 60 not worth it.
   A shared sector (e.g. education) alone is NOT a match - the work itself must fit.
5. reason: ENTIRELY in the requested language, max 30 words: what fits and the main risk."""

PURCHASE_TYPES = ["custom development", "ready-made product or licence", "operations or support",
                  "consulting or staffing", "hardware", "mixed"]

RERANK_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "purchase_type": {"type": "string", "enum": PURCHASE_TYPES},
                    "conflicts_with_exclusions": {"type": "boolean"},
                    "too_big": {"type": "boolean"},
                    "score": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "purchase_type", "conflicts_with_exclusions", "too_big", "score", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

# Hårde lofter, så AI'en ikke kan "overtale" sig selv til en høj score.
CAP_EXCLUDED = 25
CAP_PRODUCT = 50   # køb af færdigt produkt, når bureauet ikke sælger egne produkter
CAP_TOO_BIG = 55


def apply_caps(score, item, t, profile):
    """Returnerer (score efter lofter, liste af årsager til at scoren blev sænket)."""
    caps = []
    if item["conflicts_with_exclusions"]:
        caps.append(("ikke interesseret-listen", CAP_EXCLUDED))
    if item["purchase_type"] in ("ready-made product or licence", "hardware") and not profile.get("sells_products"):
        caps.append(("køb af færdigt produkt/hardware", CAP_PRODUCT))
    if item["too_big"]:
        caps.append(("for stor opgave", CAP_TOO_BIG))
    if not language_ok(t, profile):
        caps.append(("tilbudssprog", LANGUAGE_CAP))
    reasons = [name for name, cap in caps if score > cap]
    for _, cap in caps:
        score = min(score, cap)
    return score, reasons


def _norm_id(value):
    return str(value or "").replace("ID:", "").strip()


def _profile_text(profile):
    return (f"Company: {profile['name']}\nDescription: {profile['description']}\n"
            f"Services: {', '.join(profile.get('services', []))}\n"
            f"Technologies: {', '.join(profile.get('technologies', []))}\n"
            f"Size: {profile.get('size', 'unknown')}\n"
            f"Sells its own software products: {'yes' if profile.get('sells_products') else 'no'}\n"
            f"Languages they can write bids in: {', '.join(profile.get('languages', [])) or 'unknown'}\n"
            f"NOT interested in: {', '.join(profile.get('exclude', [])) or 'nothing specified'}")


def rerank(first_pass, profile, llm, min_first_score=50, max_items=80, log=print, debug=None):
    """Genvurderer de bedste udbud fra første runde med en stærkere model og hele udbudsteksten.

    Returnerer (udbud, score, begrundelse) for de genvurderede udbud; udbud['purchase_type'] sættes.
    Hvis `debug` er en liste, tilføjes den rå vurdering af hvert udbud til den.
    """
    todo = [t for t, score, _ in first_pass if score >= min_first_score][:max_items]
    first_scores = {t["id"]: score for t, score, _ in first_pass}
    lang = LANG_NAMES.get(profile.get("report_language", "en"), "English")
    log(f"  grundig vurdering af de {len(todo)} mest lovende med {llm.models[0]} ...")
    results, missing, cap_counts = [], 0, {}
    for i, batch in enumerate(_chunks(todo, RERANK_BATCH), 1):
        blocks = []
        for t in batch:
            a = t["ai"]
            langs = ", ".join(t.get("languages") or []) or "unknown"
            blocks.append(f"{_tender_text(t)}\nBid languages: {langs}\n"
                          f"Procedure: {t.get('procedure') or 'unknown'}\n"
                          f"English summary: {a['title_en']}. {a['summary_en']}")
        user = (f"COMPANY PROFILE\n{_profile_text(profile)}\n\nWrite reasons in {lang}.\n"
                "Return exactly one item per tender, using the tender's ID exactly as given.\n\n"
                "TENDERS\n\n" + "\n\n---\n\n".join(blocks))
        result = llm.json_call(RERANK_SYSTEM, user, "tender_assessment", RERANK_SCHEMA)
        items = result.get("items", [])
        by_id = {_norm_id(item.get("id")): item for item in items}
        # Reserve: hvis modellen har ændret ID'erne, men svaret har samme længde, bruges rækkefølgen.
        by_pos = items if len(items) == len(batch) else []
        matched = 0
        for pos, t in enumerate(batch):
            item = by_id.get(t["id"]) or (by_pos[pos] if by_pos else None)
            if not item:
                missing += 1
                continue
            matched += 1
            score, reasons = apply_caps(int(item["score"]), item, t, profile)
            for r in reasons:
                cap_counts[r] = cap_counts.get(r, 0) + 1
            if debug is not None:
                debug.append({"id": t["id"], "title": t["ai"]["title_en"], "country": t["country"],
                              "first_pass_score": first_scores.get(t["id"]), "ai_score": item["score"],
                              "final_score": score, "lowered_by": reasons, **{k: item[k] for k in
                              ("purchase_type", "conflicts_with_exclusions", "too_big", "reason")}})
            results.append((dict(t, purchase_type=item["purchase_type"]), score, item["reason"]))
        log(f"  batch {i}: {matched}/{len(batch)} vurderet (pris indtil nu: ${llm.total_cost:.4f})")
    if missing:
        log(f"  ADVARSEL: {missing} udbud fik intet svar fra modellen")
    if cap_counts:
        log("  sænket af lofter: " + ", ".join(f"{k}: {v}" for k, v in cap_counts.items()))
    return sorted(results, key=lambda r: r[1], reverse=True)

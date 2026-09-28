#!/usr/bin/env python3
"""Tender Radar: find relevante offentlige EU-udbud til IT-bureauer.

Brug:
  python radar.py run                      # hent + opsummer + lav rapporter for alle profiler
  python radar.py fetch                    # hent kun udbud fra TED (gratis, ingen AI)
  python radar.py summarize                # AI-opsummer nye udbud (gemmes, betales kun én gang)
  python radar.py report [profil.json]     # lav rapport(er) for én eller alle profiler
  python radar.py profile --url https://bureau.dk --name "Bureau ApS"   # lav profil ud fra hjemmeside
"""

import argparse
import html
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import analyze
import llm as llm_mod
import report
import ted

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUTPUT = ROOT / "output"
PROFILES = ROOT / "profiles"
TENDERS_FILE = DATA / "tenders.json"
SUMMARIES_FILE = DATA / "summaries.json"


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def config():
    return load_json(ROOT / "config.json", {})


def make_llm(cfg):
    return llm_mod.OpenRouter(cfg["models"])


# ---------------- kommandoer ----------------

def cmd_fetch(args):
    cfg = config()
    days = args.days or cfg["days_back"]
    print(f"Henter IT-udbud fra TED for de seneste {days} dage ...")
    tenders = ted.fetch(cfg["cpv_codes"], days, cfg.get("notice_types"), cfg.get("scope", "ACTIVE"))
    save_json(TENDERS_FILE, {"days": days, "tenders": tenders})
    countries = {}
    for t in tenders:
        countries[t["country"]] = countries.get(t["country"], 0) + 1
    top = ", ".join(f"{c}: {n}" for c, n in sorted(countries.items(), key=lambda x: -x[1])[:8])
    print(f"Færdig: {len(tenders)} udbud gemt i {TENDERS_FILE.relative_to(ROOT)}")
    print(f"Flest fra: {top}")


def cmd_summarize(args):
    cfg = config()
    data = load_json(TENDERS_FILE, None)
    if not data:
        sys.exit("Ingen udbud hentet endnu. Kør først: python radar.py fetch")
    cache = load_json(SUMMARIES_FILE, {})
    llm = make_llm(cfg)
    print(f"Opsummerer udbud med {cfg['models'][0]} ...")
    try:
        analyze.summarize(data["tenders"], llm, cache)
    finally:
        save_json(SUMMARIES_FILE, cache)  # gem det der er nået, også ved fejl
    print(f"Færdig. {llm.calls} AI-kald, pris: ${llm.total_cost:.4f}")


def profile_paths(arg):
    if arg:
        return [Path(arg)]
    return sorted(p for p in PROFILES.glob("*.json"))


def cmd_report(args):
    cfg = config()
    data = load_json(TENDERS_FILE, None)
    cache = load_json(SUMMARIES_FILE, {})
    if not data or not cache:
        sys.exit("Mangler data. Kør først: python radar.py fetch && python radar.py summarize")
    tenders = data["tenders"]
    for t in tenders:
        t["ai"] = cache.get(t["id"])
    llm = make_llm(cfg)
    OUTPUT.mkdir(exist_ok=True)
    for path in profile_paths(args.profile):
        profile = load_json(path, None)
        print(f"\nMatcher udbud til {profile['name']} ...")
        allowed = set(profile.get("countries") or [])
        pool = [t for t in tenders if not allowed or t["country"] in allowed]
        scored = analyze.match(pool, profile, llm)
        min_score = profile.get("min_score", cfg["min_score"])
        hits = [r for r in scored if r[1] >= min_score][: cfg["max_results_per_report"]]
        page, md = report.build(profile, hits, total=len(pool), days=data["days"])
        (OUTPUT / f"{path.stem}.html").write_text(page, encoding="utf-8")
        (OUTPUT / f"{path.stem}.md").write_text(md, encoding="utf-8")
        print(f"  {len(hits)} udbud med score >= {min_score} -> output/{path.stem}.html")
        for t, score, reason in hits[:5]:
            print(f"   {score:3d}%  {t['country']}  {t['ai']['title_en'][:70]}")
    print(f"\nPris for matching: ${llm.total_cost:.4f}")


def cmd_run(args):
    cmd_fetch(args)
    cmd_summarize(args)
    args.profile = None
    cmd_report(args)


PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "services": {"type": "array", "items": {"type": "string"}},
        "technologies": {"type": "array", "items": {"type": "string"}},
        "size": {"type": "string"},
        "exclude": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["description", "services", "technologies", "size", "exclude"],
    "additionalProperties": False,
}


def fetch_site_text(url, limit=12000):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (TenderRadar)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    raw = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def cmd_profile(args):
    cfg = config()
    text = args.text or fetch_site_text(args.url)
    llm = make_llm(cfg)
    result = llm.json_call(
        "You write short, factual company profiles used to match public tenders. "
        "Only use facts from the provided website text. Write in English.",
        f"Company name: {args.name}\nWebsite text:\n{text}",
        "company_profile", PROFILE_SCHEMA,
    )
    profile = {"name": args.name, "website": args.url or "", "report_language": args.lang,
               "countries": args.countries.split(",") if args.countries else [], **result}
    slug = re.sub(r"[^a-z0-9]+", "-", args.name.lower()).strip("-")
    path = PROFILES / f"{slug}.json"
    save_json(path, profile)
    print(f"Profil gemt i {path.relative_to(ROOT)} (pris ${llm.total_cost:.4f}). Tjek og ret den gerne.")


def main():
    load_env()
    p = argparse.ArgumentParser(description="Find relevante offentlige EU-udbud til IT-bureauer.")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("run", "fetch"):
        s = sub.add_parser(name)
        s.add_argument("--days", type=int, help="Antal dage tilbage (standard: fra config.json)")
    sub.add_parser("summarize")
    s = sub.add_parser("report")
    s.add_argument("profile", nargs="?", help="Sti til én profil (standard: alle i profiles/)")
    s = sub.add_parser("profile")
    s.add_argument("--name", required=True)
    s.add_argument("--url", help="Bureauets hjemmeside")
    s.add_argument("--text", help="Alternativt: indsæt beskrivelse som tekst")
    s.add_argument("--lang", default="da", help="Sprog i rapporten: da eller en")
    s.add_argument("--countries", help="Fx DNK,SWE,NOR,DEU (tom = hele EU)")
    args = p.parse_args()
    if args.cmd == "profile" and not (args.url or args.text):
        p.error("profile kræver --url eller --text")
    {"run": cmd_run, "fetch": cmd_fetch, "summarize": cmd_summarize,
     "report": cmd_report, "profile": cmd_profile}[args.cmd](args)


if __name__ == "__main__":
    try:
        main()
    except (ted.TedError, llm_mod.LLMError) as e:
        sys.exit(f"Fejl: {e}")

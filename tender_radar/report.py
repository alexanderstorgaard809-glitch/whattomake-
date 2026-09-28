"""Laver en mail-klar rapport (HTML + ren tekst) for én kundeprofil."""

import html
from datetime import date

from ted import format_value

COUNTRIES = {
    "DNK": "Danmark", "SWE": "Sverige", "NOR": "Norge", "FIN": "Finland", "DEU": "Tyskland",
    "NLD": "Holland", "BEL": "Belgien", "FRA": "Frankrig", "IRL": "Irland", "POL": "Polen",
    "ESP": "Spanien", "ITA": "Italien", "AUT": "Østrig", "EST": "Estland", "LVA": "Letland",
    "LTU": "Litauen", "CZE": "Tjekkiet", "PRT": "Portugal", "LUX": "Luxembourg", "ISL": "Island",
}

TEXT = {
    "da": {
        "heading": "{n} relevante offentlige udbud til {name}",
        "intro": "Vi har gennemgået {total} nye IT-udbud i EU fra de seneste {days} dage og fundet dem, der passer bedst til jer.",
        "buyer": "Køber", "deadline": "Tilbudsfrist", "request": "Frist for ansøgning", "value": "Anslået værdi",
        "fit": "Match", "lang": "Tilbudssprog",
        "unknown": "ikke oplyst", "open": "Se udbuddet på TED",
        "footer": "Genereret {today} ud fra offentlige data fra TED (ted.europa.eu). Tjek altid det originale udbudsmateriale.",
        "none": "Ingen udbud over tærsklen i denne periode.",
    },
    "en": {
        "heading": "{n} relevant public tenders for {name}",
        "intro": "We reviewed {total} new IT tenders across the EU from the last {days} days and picked the best fits for you.",
        "buyer": "Buyer", "deadline": "Deadline", "request": "Application deadline", "value": "Estimated value",
        "fit": "Match", "lang": "Bid language",
        "unknown": "not stated", "open": "View tender on TED",
        "footer": "Generated {today} from public TED data (ted.europa.eu). Always check the original tender documents.",
        "none": "No tenders above the threshold in this period.",
    },
}


LANGUAGES = {
    "da": {"DAN": "dansk", "ENG": "engelsk", "DEU": "tysk", "SWE": "svensk", "NOR": "norsk", "FIN": "finsk",
           "NLD": "hollandsk", "FRA": "fransk", "POL": "polsk", "SPA": "spansk", "ITA": "italiensk",
           "CES": "tjekkisk", "EST": "estisk", "LIT": "litauisk", "LAV": "lettisk", "POR": "portugisisk"},
    "en": {"DAN": "Danish", "ENG": "English", "DEU": "German", "SWE": "Swedish", "NOR": "Norwegian",
           "FIN": "Finnish", "NLD": "Dutch", "FRA": "French", "POL": "Polish", "SPA": "Spanish"},
}


def _langs(t, tx, lang):
    names = LANGUAGES.get(lang, {})
    return ", ".join(names.get(c, c) for c in t.get("languages") or []) or tx["unknown"]


def _deadline_label(t, tx):
    return tx["request"] if t.get("deadline_kind") == "request" else tx["deadline"]


def _buyer(t, limit=80):
    b = t["buyer"]
    return b if len(b) <= limit else b[:limit].rsplit(" ", 1)[0] + " …"


def _value(t, tx):
    return format_value(t, tx["unknown"])


def build(profile, results, total, days):
    lang = profile.get("report_language", "en")
    tx = TEXT.get(lang, TEXT["en"])
    country_name = (lambda c: COUNTRIES.get(c, c)) if lang == "da" else (lambda c: c)
    heading = tx["heading"].format(n=len(results), name=profile["name"])
    intro = tx["intro"].format(total=total, days=days)
    footer = tx["footer"].format(today=date.today().isoformat())

    # --- ren tekst / markdown ---
    md = [f"# {heading}", "", intro, ""]
    for i, (t, score, reason) in enumerate(results, 1):
        a = t["ai"]
        md += [
            f"## {i}. {a['title_en']} ({tx['fit']}: {score}%)",
            f"- **{tx['buyer']}:** {_buyer(t)} ({country_name(t['country'])})",
            f"- **{_deadline_label(t, tx)}:** {t['deadline'] or tx['unknown']}",
            f"- **{tx['lang']}:** {_langs(t, tx, lang)}",
            f"- **{tx['value']}:** {_value(t, tx)}",
            f"- {a['summary_en']}",
            f"- *{reason}*",
            f"- {t['url']}",
            "",
        ]
    if not results:
        md.append(tx["none"])
    md += ["---", footer]

    # --- HTML (kan kopieres direkte ind i en mail) ---
    e = html.escape
    cards = []
    for i, (t, score, reason) in enumerate(results, 1):
        a = t["ai"]
        color = "#1a7f37" if score >= 80 else "#9a6700"
        cards.append(f"""
<div style="border:1px solid #d0d7de;border-radius:8px;padding:16px;margin:0 0 14px">
  <div style="font-size:13px;color:{color};font-weight:bold">{tx['fit']}: {score}%</div>
  <div style="font-size:17px;font-weight:bold;margin:4px 0 8px">{i}. {e(a['title_en'])}</div>
  <div style="font-size:14px;color:#57606a;margin-bottom:8px">
    <b>{tx['buyer']}:</b> {e(_buyer(t))} ({e(country_name(t['country']))}) &nbsp;·&nbsp;
    <b>{e(_deadline_label(t, tx))}:</b> {e(t['deadline'] or tx['unknown'])} &nbsp;·&nbsp;
    <b>{tx['lang']}:</b> {e(_langs(t, tx, lang))} &nbsp;·&nbsp;
    <b>{tx['value']}:</b> {e(_value(t, tx))}
  </div>
  <div style="font-size:14px;margin-bottom:8px">{e(a['summary_en'])}</div>
  <div style="font-size:14px;font-style:italic;color:#24292f;margin-bottom:10px">{e(reason)}</div>
  <a href="{e(t['url'])}" style="font-size:14px;color:#0969da">{tx['open']} →</a>
</div>""")
    body = "".join(cards) or f"<p>{tx['none']}</p>"
    page = f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(heading)}</title></head>
<body style="margin:0;background:#f6f8fa;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#24292f">
<div style="max-width:680px;margin:0 auto;padding:24px 16px;background:#ffffff">
  <h1 style="font-size:22px;margin:0 0 8px">{e(heading)}</h1>
  <p style="font-size:15px;color:#57606a;margin:0 0 20px">{e(intro)}</p>
  {body}
  <p style="font-size:12px;color:#8c959f;margin-top:24px">{e(footer)}</p>
</div></body></html>"""
    return page, "\n".join(md)

"""AI-trin via OpenRouter: (1) læs faktura/korrespondance, (2) skriv rykkerbrev.

AI'en beregner aldrig beløb. Alle tal kommer fra claims.py og sendes ind i brev-prompten.
"""

import base64
import json
import os
import time
from datetime import date
import urllib.error
import urllib.request

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class AIError(Exception):
    pass


class OpenRouter:
    def __init__(self, models):
        self.models = models
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise AIError("Mangler OPENROUTER_API_KEY. Læg den i filen .env (se .env.example).")
        self.total_cost = 0.0

    def json_call(self, system, content, schema_name, schema, retries=3):
        body = {
            "models": self.models,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
            "temperature": 0.2,
            "usage": {"include": True},
        }
        last = None
        for attempt in range(retries):
            try:
                data = self._post(body)
                self.total_cost += float((data.get("usage") or {}).get("cost") or 0)
                return _parse_json(data["choices"][0]["message"]["content"])
            except (AIError, KeyError, IndexError, ValueError) as e:
                last = e
                time.sleep(2 * (attempt + 1))
        raise AIError(f"AI-kaldet fejlede: {last}")

    def _post(self, body):
        req = urllib.request.Request(API_URL, data=json.dumps(body).encode("utf-8"), method="POST", headers={
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
            "X-Title": "Claim Pilot"})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise AIError(f"OpenRouter svarede {e.code}: {e.read().decode('utf-8', 'replace')[:400]}") from e
        except urllib.error.URLError as e:
            raise AIError(f"Kunne ikke forbinde til OpenRouter ({e.reason})") from e
        if "error" in data:
            raise AIError(f"OpenRouter-fejl: {data['error']}")
        return data


def _parse_json(text):
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Intet JSON i svaret: {text[:200]}")
    return json.loads(text[start:end + 1])


# ---------------- 1. Udtræk af kravet ----------------

_PARTY = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "address": {"type": "string"},
        "country": {"type": "string", "description": "ISO 3166-1 alpha-2 code, e.g. DE. Empty if unknown"},
        "vat_id": {"type": "string"},
        "email": {"type": "string"},
        "contact_person": {"type": "string", "description": "Name of the person acting for this party, empty if unknown"},
        "is_business": {"type": "boolean"},
    },
    "required": ["name", "address", "country", "vat_id", "email", "contact_person", "is_business"],
    "additionalProperties": False,
}

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "creditor": _PARTY,
        "debtor": _PARTY,
        "creditor_bank": {"type": "string", "description": "IBAN/BIC or payment details on the invoice, empty if none"},
        "invoices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "string"},
                    "issue_date": {"type": "string", "description": "YYYY-MM-DD or empty"},
                    "due_date": {"type": "string", "description": "YYYY-MM-DD or empty if not stated"},
                    "amount": {"type": "number", "description": "Total amount due incl. VAT"},
                    "currency": {"type": "string", "description": "ISO 4217, e.g. EUR"},
                    "description": {"type": "string"},
                },
                "required": ["number", "issue_date", "due_date", "amount", "currency", "description"],
                "additionalProperties": False,
            },
        },
        "work_summary": {"type": "string", "description": "One sentence: what was delivered"},
        "dispute_signals": {"type": "string",
                            "description": "Any sign the debtor contests the work or amount, quoted briefly. Empty if none"},
        "creditor_response_to_dispute": {"type": "string",
                                         "description": "How the creditor answered the complaint (e.g. fix delivered, date), empty if none"},
        "reminders_sent": {"type": "string", "description": "Earlier reminders mentioned in the material, empty if none"},
        "missing_info": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["creditor", "debtor", "creditor_bank", "invoices", "work_summary", "dispute_signals",
                 "creditor_response_to_dispute", "reminders_sent", "missing_info"],
    "additionalProperties": False,
}

EXTRACT_SYSTEM = """You extract facts from invoices and email threads for a cross-border unpaid invoice claim.
The creditor is the party that issued the invoice and is owed money; the debtor is the customer.
Documents may be in any language. Only use facts that are in the material; leave fields empty if unknown.
Never guess dates or amounts. is_business is true for companies and self-employed traders acting professionally."""


def extract_claim(llm, files, notes):
    content = [{"type": "text", "text": "Extract the claim from the attached documents."
                + (f"\n\nExtra information from the creditor:\n{notes}" if notes else "")}]
    for f in files:
        data_url, name = f["data_url"], f.get("name") or "document"
        if data_url.startswith("data:image/"):
            content.append({"type": "image_url", "image_url": {"url": data_url}})
        elif data_url.startswith("data:text/"):
            text = base64.b64decode(data_url.split(",", 1)[1]).decode("utf-8", "replace")
            content.append({"type": "text", "text": f"--- {name} ---\n{text[:40000]}"})
        else:
            content.append({"type": "file", "file": {"filename": name, "file_data": data_url}})
    return llm.json_call(EXTRACT_SYSTEM, content, "claim", EXTRACT_SCHEMA)


# ---------------- 2. Rykkerbrev ----------------

LETTER_SCHEMA = {
    "type": "object",
    "properties": {
        "subject_local": {"type": "string"},
        "letter_local": {"type": "string"},
        "subject_en": {"type": "string"},
        "letter_en": {"type": "string"},
    },
    "required": ["subject_local", "letter_local", "subject_en", "letter_en"],
    "additionalProperties": False,
}

LETTER_SYSTEM = """You write formal final payment demand letters (letters before action) between businesses in the EU.
Tone: firm, professional, polite, factual. No threats beyond the legal steps given. Plain text, no markdown.
Use ONLY the facts provided. Amounts are given pre-formatted per language: copy them exactly as written,
never reformat or recalculate them. Copy dates and invoice numbers exactly.

Layout (use line breaks and blank lines like a real business letter):
  sender block (name, address, VAT ID, email) / recipient block / place and date / subject line /
  salutation / short paragraphs / an itemised amount overview, one item per line (principal, interest,
  fixed compensation, total) / deadline and bank details on separate lines / consequence / closing /
  signature: the creditor's contact person (if known) on one line and the company name below.

If the facts contain a dispute raised by the debtor, address it in its own short paragraph: acknowledge it
factually, state the creditor's response (e.g. that the issue was fixed and when) and conclude that the
amount is due. Never admit fault and never invent details.

LANGUAGE RULES (important):
- Every sentence of the letter must be in the requested language. Facts may be given in English or another
  language: translate them, including the work description and the next step. Never copy English phrases
  into a non-English letter. Names, addresses, IBAN and invoice numbers stay unchanged.
- Write dates in the usual long format of the letter's language (e.g. "28 septembre 2026", "28. September 2026",
  "28 September 2026"), keeping exactly the same day, month and year as in the facts.

Write the letter natively in the requested language (not a word-for-word translation), then an English version
with the same content. Use '[...]' placeholders for anything missing, e.g. bank details."""


def write_letter(llm, claim, calc, language, deadline, sender_note=""):
    from claims import LANGUAGES, format_money, format_percent
    cur = calc["currency"] if calc["currency"] != "MIXED" else ""
    money = lambda v, c=cur: format_money(v, c, language)
    facts = {
        "creditor": claim["creditor"], "debtor": claim["debtor"],
        "creditor_bank": claim.get("creditor_bank") or "[bank details]",
        "work_summary": claim.get("work_summary", ""),
        "reminders_sent": claim.get("reminders_sent", ""),
        "invoices": [{"number": l["number"], "issue_date": l["issue_date"], "due_date": l["due_date"],
                      "amount": money(l["amount"], l["currency"]), "days_overdue": l["days_late"]}
                     for l in calc["lines"]],
        "principal": money(calc["principal"]),
        "statutory_interest_to_date": money(calc["interest"]),
        "interest_rate_per_year": format_percent(calc["rate_percent"], language),
        "daily_interest": money(calc["daily_interest"]),
        "fixed_compensation": money(calc["compensation_eur"], "EUR"),
        "total_amount_due": money(calc["principal"] + calc["interest"] + calc["compensation_eur"])
                            if cur == "EUR" else f"{money(calc['principal'] + calc['interest'])} + "
                            f"{money(calc['compensation_eur'], 'EUR')}",
        "b2b": calc["b2b"],
        "dispute_raised_by_debtor": claim.get("dispute_signals", "") if claim.get("disputed") else "",
        "creditor_response_to_dispute": claim.get("creditor_response_to_dispute", "") if claim.get("disputed") else "",
        "letter_date": date.today().isoformat(),
        "payment_deadline": deadline,
        "next_step_if_unpaid": _next_step(calc, bool(claim.get("disputed"))),
    }
    legal = ("Cite Directive 2011/7/EU on combating late payment (statutory interest and the EUR 40 fixed "
             "compensation per invoice under Article 6)." if calc["b2b"] else
             "Do not claim Directive 2011/7/EU interest or the EUR 40 compensation (not B2B).")
    user = (f"Write the letter in {LANGUAGES.get(language, 'English')}.\n{legal}\n"
            + (f"Additional instruction from the creditor: {sender_note}\n" if sender_note else "")
            + f"FACTS (JSON):\n{json.dumps(facts, ensure_ascii=False, indent=1)}")
    result = llm.json_call(LETTER_SYSTEM, user, "demand_letter", LETTER_SCHEMA)
    if language != "en":
        leaked = untranslated(result.get("letter_local", ""), [facts["next_step_if_unpaid"], facts["work_summary"]])
        if leaked:  # én ny chance med en tydelig besked om, hvad der ikke blev oversat
            retry = user + ("\n\nYour previous draft copied these English phrases into the "
                            f"{LANGUAGES.get(language)} letter. Translate them: " + " | ".join(leaked))
            result = llm.json_call(LETTER_SYSTEM, retry, "demand_letter", LETTER_SCHEMA)
    return result


def untranslated(letter, english_phrases, window=6):
    """Finder engelske sætningsstykker (6 ord i træk), der er kopieret uoversat ind i brevet."""
    low, found = letter.lower(), []
    for phrase in english_phrases:
        words = (phrase or "").split()
        for i in range(0, max(len(words) - window + 1, 0)):
            chunk = " ".join(words[i:i + window]).lower()
            if chunk in low:
                found.append(" ".join(words))
                break
    return found


def _next_step(calc, disputed=False):
    p = calc["procedures"]
    if disputed:
        # Et betalingspåbud kan afvises med en simpel indsigelse, så nævn det ikke ved en tvist.
        if p["small_claims"]:
            return ("start the European Small Claims Procedure (Regulation (EC) No 861/2007) at the competent "
                    "court, without further notice")
        return "initiate legal proceedings at the competent court to recover the debt, without further notice"
    if p["small_claims"]:
        return ("apply for a European Payment Order (Regulation (EC) No 1896/2006) or start the European Small "
                "Claims Procedure (Regulation (EC) No 861/2007) at the competent court, without further notice")
    if p["payment_order"]:
        return ("apply for a European Payment Order (Regulation (EC) No 1896/2006) at the competent court, "
                "without further notice")
    return "take legal steps to recover the debt, without further notice"

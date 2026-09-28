"""Deterministiske regler og beregninger. Ingen AI her: tal og juridiske tærskler skal være præcise.

Kilder:
- Direktiv 2011/7/EU om bekæmpelse af forsinket betaling (B2B): rente = referencerente + mindst 8 %-point,
  40 EUR fast kompensation pr. forsinket betaling, 30 dages betalingsfrist hvis intet er aftalt.
- Forordning (EF) nr. 1896/2006: europæisk betalingspåbud (ubestridte krav, ingen beløbsgrænse).
- Forordning (EF) nr. 861/2007: europæisk småkravsprocedure (krav op til 5.000 EUR).
- Danmark deltager ikke i de to procedurer.
"""

from datetime import date, timedelta

EU_COUNTRIES = {
    "AT": ("Austria", "de"), "BE": ("Belgium", "fr"), "BG": ("Bulgaria", "bg"), "HR": ("Croatia", "hr"),
    "CY": ("Cyprus", "el"), "CZ": ("Czechia", "cs"), "DK": ("Denmark", "da"), "EE": ("Estonia", "et"),
    "FI": ("Finland", "fi"), "FR": ("France", "fr"), "DE": ("Germany", "de"), "GR": ("Greece", "el"),
    "HU": ("Hungary", "hu"), "IE": ("Ireland", "en"), "IT": ("Italy", "it"), "LV": ("Latvia", "lv"),
    "LT": ("Lithuania", "lt"), "LU": ("Luxembourg", "fr"), "MT": ("Malta", "en"), "NL": ("Netherlands", "nl"),
    "PL": ("Poland", "pl"), "PT": ("Portugal", "pt"), "RO": ("Romania", "ro"), "SK": ("Slovakia", "sk"),
    "SI": ("Slovenia", "sl"), "ES": ("Spain", "es"), "SE": ("Sweden", "sv"),
}

LANGUAGES = {
    "bg": "Bulgarian", "cs": "Czech", "da": "Danish", "de": "German", "el": "Greek", "en": "English",
    "es": "Spanish", "et": "Estonian", "fi": "Finnish", "fr": "French", "hr": "Croatian", "hu": "Hungarian",
    "it": "Italian", "lt": "Lithuanian", "lv": "Latvian", "nl": "Dutch", "pl": "Polish", "pt": "Portuguese",
    "ro": "Romanian", "sk": "Slovak", "sl": "Slovenian", "sv": "Swedish",
}

SMALL_CLAIMS_LIMIT_EUR = 5000
FLAT_COMPENSATION_EUR = 40
DEFAULT_PAYMENT_TERM_DAYS = 30
NON_PARTICIPATING = {"DK"}  # Danmark bruger ikke betalingspåbud/småkravsproceduren


def parse_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def invoice_due_date(inv):
    """Forfaldsdato: den angivne, ellers fakturadato + 30 dage (direktivets standard)."""
    due = parse_date(inv.get("due_date"))
    if due:
        return due, False
    issued = parse_date(inv.get("issue_date"))
    if issued:
        return issued + timedelta(days=DEFAULT_PAYMENT_TERM_DAYS), True
    return None, False


def calculate(claim, rate_percent, today=None):
    """Beregner renter, kompensation og hvilke procedurer der kan bruges."""
    today = today or date.today()
    creditor, debtor = claim.get("creditor", {}), claim.get("debtor", {})
    c_country, d_country = (creditor.get("country") or "").upper(), (debtor.get("country") or "").upper()
    b2b = bool(creditor.get("is_business")) and bool(debtor.get("is_business"))

    lines, warnings = [], []
    for inv in claim.get("invoices", []):
        amount = float(inv.get("amount") or 0)
        due, assumed = invoice_due_date(inv)
        days_late = max((today - due).days, 0) if due else 0
        interest = round(amount * rate_percent / 100 * days_late / 365, 2) if b2b else 0.0
        comp = FLAT_COMPENSATION_EUR if (b2b and days_late > 0) else 0
        if assumed:
            warnings.append(f"Invoice {inv.get('number') or '?'}: no due date found, assumed "
                            f"{DEFAULT_PAYMENT_TERM_DAYS} days after issue date ({due}).")
        if not due:
            warnings.append(f"Invoice {inv.get('number') or '?'}: no dates found, interest not calculated.")
        lines.append({
            "number": inv.get("number") or "",
            "issue_date": inv.get("issue_date") or "",
            "due_date": due.isoformat() if due else "",
            "due_date_assumed": assumed,
            "amount": round(amount, 2),
            "currency": (inv.get("currency") or "EUR").upper(),
            "days_late": days_late,
            "interest": interest,
            "compensation_eur": comp,
        })

    currencies = {l["currency"] for l in lines}
    currency = currencies.pop() if len(currencies) == 1 else "MIXED"
    principal = round(sum(l["amount"] for l in lines), 2)
    interest = round(sum(l["interest"] for l in lines), 2)
    compensation = sum(l["compensation_eur"] for l in lines)
    daily_interest = round(sum(l["amount"] for l in lines if l["days_late"] > 0) * rate_percent / 100 / 365, 2) if b2b else 0.0

    if currency == "MIXED":
        warnings.append("Invoices use different currencies; totals are not comparable.")
    if not b2b:
        warnings.append("Not clearly business-to-business: the Late Payment Directive (statutory interest and "
                        "EUR 40 compensation) only covers B2B. National consumer rules apply instead.")
    if not any(l["days_late"] > 0 for l in lines):
        warnings.append("No invoice is overdue yet.")

    procedures = procedure_options(c_country, d_country, principal, currency, bool(claim.get("disputed")))
    return {
        "rate_percent": rate_percent,
        "b2b": b2b,
        "lines": lines,
        "currency": currency,
        "principal": principal,
        "interest": interest,
        "daily_interest": daily_interest,
        "compensation_eur": compensation,
        "total_claim": round(principal + interest, 2),
        "procedures": procedures,
        "warnings": warnings,
    }


def procedure_options(c_country, d_country, principal, currency, disputed=False):
    """Hvilke EU-procedurer kan kreditor bruge? Returnerer anbefaling og forklaring."""
    out = {"cross_border": False, "payment_order": False, "small_claims": False, "notes": []}
    if c_country not in EU_COUNTRIES or d_country not in EU_COUNTRIES:
        out["notes"].append("Both parties must be in the EU for the EU procedures.")
        return out
    if c_country == d_country:
        out["notes"].append("Both parties are in the same country: use that country's national procedure.")
        return out
    out["cross_border"] = True
    if {c_country, d_country} & NON_PARTICIPATING:
        out["notes"].append("Denmark does not take part in the European payment order or small claims "
                            "procedure. A national procedure or a debt collection agency is needed.")
        return out
    out["payment_order"] = True
    out["notes"].append("European Payment Order (Reg. 1896/2006): for uncontested claims, no amount limit, "
                        "written procedure, no lawyer required.")
    if currency == "EUR" and principal <= SMALL_CLAIMS_LIMIT_EUR:
        out["small_claims"] = True
        out["notes"].append("European Small Claims Procedure (Reg. 861/2007): available because the claim "
                            f"is at most EUR {SMALL_CLAIMS_LIMIT_EUR:,}. Also works if the debtor disputes it.")
    elif currency != "EUR":
        out["notes"].append("Small claims limit is in EUR: convert the amount to check eligibility.")
    if disputed:
        out["notes"].append("The client disputes the claim: a payment order ends if the client files an objection "
                            "and becomes ordinary proceedings. " + ("Small claims is the better route."
                            if out["small_claims"] else "Expect ordinary court proceedings; consider a lawyer."))
    out["notes"].append(f"Competent court: normally in the debtor's country ({EU_COUNTRIES[d_country][0]}). "
                        "Find the exact court with the court-finder on e-justice.europa.eu.")
    return out


def default_language(country):
    return EU_COUNTRIES.get((country or "").upper(), (None, "en"))[1]


# Beløbsformat pr. sprog: (tusindtalsseparator, decimaltegn, valuta før beløbet?)
_MONEY = {"en": (",", ".", True), "fr": ("\u202f", ",", False), "de": (".", ",", False), "es": (".", ",", False),
          "it": (".", ",", False), "nl": (".", ",", True), "pt": (".", ",", False), "da": (".", ",", False),
          "sv": ("\u00a0", ",", False), "fi": ("\u00a0", ",", False), "pl": ("\u00a0", ",", False),
          "cs": ("\u00a0", ",", False), "sk": ("\u00a0", ",", False)}
_SYMBOL = {"EUR": "€"}


def format_money(amount, currency, language="en"):
    """Fx 7800 EUR -> 'EUR 7,800.00' (en), '7.800,00 €' (de), '7 800,00 €' (fr)."""
    thousands, decimal, before = _MONEY.get(language, (".", ",", False))
    text = f"{float(amount):,.2f}".replace(",", "\x00").replace(".", decimal).replace("\x00", thousands)
    if not currency:
        return text
    if language == "en":
        return f"{currency} {text}"
    symbol = _SYMBOL.get(currency, currency)
    return f"{symbol} {text}" if before else f"{text} {symbol}"


def format_percent(value, language="en"):
    """Fx 10.4 -> '10.4 %' (en) eller '10,4 %' (fr/de/...)."""
    decimal = _MONEY.get(language, (".", ",", False))[1]
    return f"{float(value):g}".replace(".", decimal) + " %"

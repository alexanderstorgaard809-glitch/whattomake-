"""Deterministiske regler og beregninger. Ingen AI her: tal og juridiske tærskler skal være præcise.

Hvilke regler gælder? Uden andet lovvalg i kontrakten gælder loven i leverandørens land for en
tjenesteydelse (Rom I, art. 4(1)(b)). Derfor vælges regelsættet ud fra KREDITORS land:

EU (direktiv 2011/7/EU, B2B):
- rente = ECB-referencerente + mindst 8 %-point, 40 EUR fast kompensation pr. forsinket betaling
- 30 dages betalingsfrist, hvis intet er aftalt
- Forordning 1896/2006: europæisk betalingspåbud (ubestridte krav, ingen beløbsgrænse)
- Forordning 861/2007: europæisk småkravsprocedure (op til 5.000 EUR). Danmark deltager ikke i de to.

UK (Late Payment of Commercial Debts (Interest) Act 1998, B2B):
- rente = Bank of England base rate + 8 %-point. Base rate pr. 31/12 gælder for fakturaer, der forfalder
  i 1. halvår, pr. 30/6 for 2. halvår, og satsen er fast for den faktura.
- fast kompensation pr. faktura: £40 (under £1.000), £70 (£1.000-9.999,99), £100 (£10.000+)
- Retssag i England & Wales: Money Claim Online (op til £100.000), small claims track op til £10.000.
- Pre-Action Protocol for Debt Claims, når skyldneren er en enkeltmandsvirksomhed eller privatperson:
  30 dages svarfrist og standardiseret informationsark + svarformular vedlagt brevet.
- Efter Brexit kan EU's procedurer ikke bruges, når den ene part er i UK.
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
UK = "GB"
COUNTRIES = {**EU_COUNTRIES, UK: ("United Kingdom", "en")}

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
UK_MCOL_LIMIT_GBP = 100_000
UK_SMALL_CLAIMS_LIMIT_GBP = 10_000
UK_PROTOCOL_DAYS = 30
DEFAULT_DEADLINE_DAYS = 14
INDIVIDUAL_TYPES = {"sole_trader", "individual"}


def parse_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def invoice_due_date(inv):
    """Forfaldsdato: den angivne, ellers fakturadato + 30 dage (lovens standard i både EU og UK)."""
    due = parse_date(inv.get("due_date"))
    if due:
        return due, False
    issued = parse_date(inv.get("issue_date"))
    if issued:
        return issued + timedelta(days=DEFAULT_PAYMENT_TERM_DAYS), True
    return None, False


def regime_for(creditor_country):
    c = (creditor_country or "").upper()
    if c == UK:
        return "UK"
    if c in EU_COUNTRIES:
        return "EU"
    return None


def half_year(d):
    return f"{d.year}-H{1 if d.month <= 6 else 2}"


def uk_compensation(amount):
    if amount < 1000:
        return 40
    if amount < 10000:
        return 70
    return 100


def statutory_rate(regime, due, rates, warnings):
    """Årlig lovbestemt rente i procent for en faktura med forfaldsdato `due`."""
    if regime == "EU":
        return float(rates["EU"]["percent"])
    uk = rates["UK"]
    base_rates = uk["base_rates"]
    key = half_year(due) if due else None
    if key in base_rates:
        return base_rates[key] + uk["margin"]
    latest = sorted(base_rates)[-1]
    warnings.append(f"No Bank of England reference rate stored for {key or 'this invoice'}; used {latest} "
                    f"({base_rates[latest]}% + {uk['margin']}%). Check the rate on gov.uk.")
    return base_rates[latest] + uk["margin"]


def calculate(claim, rates, today=None, rate_override=None):
    """Beregner renter, kompensation, frist og hvilke procedurer der kan bruges."""
    today = today or date.today()
    creditor, debtor = claim.get("creditor", {}), claim.get("debtor", {})
    c_country, d_country = (creditor.get("country") or "").upper(), (debtor.get("country") or "").upper()
    b2b = bool(creditor.get("is_business")) and bool(debtor.get("is_business"))
    regime = regime_for(c_country)
    comp_currency = "GBP" if regime == "UK" else "EUR"

    lines, warnings = [], []
    for inv in claim.get("invoices", []):
        amount = float(inv.get("amount") or 0)
        due, assumed = invoice_due_date(inv)
        days_late = max((today - due).days, 0) if due else 0
        applies = b2b and regime is not None and days_late > 0
        rate = (float(rate_override) if rate_override not in (None, "") else
                statutory_rate(regime, due, rates, warnings)) if applies else 0.0
        interest = round(amount * rate / 100 * days_late / 365, 2) if applies else 0.0
        if not applies:
            comp = 0
        elif regime == "UK":
            comp = uk_compensation(amount)
        else:
            comp = FLAT_COMPENSATION_EUR
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
            "currency": (inv.get("currency") or ("GBP" if regime == "UK" else "EUR")).upper(),
            "days_late": days_late,
            "rate_percent": rate,
            "interest": interest,
            "compensation": comp,
        })

    currencies = {l["currency"] for l in lines}
    currency = currencies.pop() if len(currencies) == 1 else "MIXED"
    principal = round(sum(l["amount"] for l in lines), 2)
    interest = round(sum(l["interest"] for l in lines), 2)
    compensation = sum(l["compensation"] for l in lines)
    daily_interest = round(sum(l["amount"] * l["rate_percent"] / 100 / 365 for l in lines), 2)
    rates_used = sorted({l["rate_percent"] for l in lines if l["rate_percent"]})

    if currency == "MIXED":
        warnings.append("Invoices use different currencies; totals are not comparable.")
    if regime is None:
        warnings.append("Your country is not supported yet (EU and UK only): no statutory interest calculated.")
    elif not b2b:
        warnings.append("Not clearly business-to-business: statutory late-payment interest and the fixed "
                        "compensation only apply between businesses. Consumer rules apply instead.")
    if regime == "UK" and currency not in ("GBP", "MIXED"):
        warnings.append(f"Invoice is in {currency}: the UK fixed compensation (£40/£70/£100) is in GBP.")
    if not any(l["days_late"] > 0 for l in lines):
        warnings.append("No invoice is overdue yet.")

    debtor_type = debtor.get("entity_type") or ("company" if debtor.get("is_business") else "individual")
    procedures = procedure_options(c_country, d_country, principal, currency,
                                   bool(claim.get("disputed")), debtor_type)
    return {
        "regime": regime,
        "law": {"EU": "Directive 2011/7/EU on combating late payment",
                "UK": "Late Payment of Commercial Debts (Interest) Act 1998"}.get(regime, ""),
        "rate_percent": rates_used[-1] if rates_used else 0.0,
        "rates_used": rates_used,
        "b2b": b2b,
        "lines": lines,
        "currency": currency,
        "principal": principal,
        "interest": interest,
        "daily_interest": daily_interest,
        "compensation": compensation,
        "compensation_currency": comp_currency,
        "total_claim": round(principal + interest, 2),
        "deadline_days": procedures.pop("deadline_days"),
        "procedures": procedures,
        "warnings": warnings,
    }


def procedure_options(c_country, d_country, principal, currency, disputed=False, debtor_type="company"):
    """Hvilke skridt kan kreditor tage? Returnerer en liste af muligheder og forklaringer."""
    out = {"cross_border": c_country != d_country, "payment_order": False, "small_claims": False,
           "uk_claim": False, "uk_protocol": False, "options": [], "notes": [],
           "deadline_days": DEFAULT_DEADLINE_DAYS}

    def option(name, available):
        out["options"].append({"name": name, "available": available})

    if d_country == UK:
        out["uk_claim"] = True
        protocol = debtor_type in INDIVIDUAL_TYPES
        out["uk_protocol"] = protocol
        gbp = currency == "GBP"
        option("Letter before claim", True)
        option("Money Claim Online (England & Wales)", gbp and principal <= UK_MCOL_LIMIT_GBP)
        option("Small claims track (up to £10,000)", gbp and principal <= UK_SMALL_CLAIMS_LIMIT_GBP)
        if protocol:
            out["deadline_days"] = UK_PROTOCOL_DAYS
            out["notes"].append("The client is a sole trader or individual, so the Pre-Action Protocol for Debt "
                                "Claims applies: give 30 days to respond and enclose the Information Sheet and "
                                "Reply Form from the protocol (available on justice.gov.uk).")
        else:
            out["notes"].append("For a company, a letter before claim with a reasonable deadline (14 days is "
                                "typical) is expected before going to court. Skipping it can cost you in court.")
        out["notes"].append("Money Claim Online is the government's online service for claims up to £100,000. "
                            "Claims up to £10,000 normally go to the small claims track, where you rarely need a "
                            "lawyer. Scotland and Northern Ireland have their own procedures.")
        if c_country != UK:
            out["notes"].append("The EU's cross-border procedures don't cover the UK since Brexit: the claim is "
                                "made in the UK courts.")
        if not gbp:
            out["notes"].append("Convert the amount to GBP to check the court limits.")
        return out

    option("Final demand letter", True)
    if c_country not in COUNTRIES or d_country not in EU_COUNTRIES:
        out["notes"].append("The EU procedures need both parties in the EU.")
        return out
    if c_country == UK:
        out["notes"].append("As a UK business you can't use the EU's cross-border procedures since Brexit. "
                            f"Use the national procedure in {EU_COUNTRIES[d_country][0]}.")
        return out
    if c_country == d_country:
        out["notes"].append("Both parties are in the same country: use that country's national procedure.")
        return out
    if {c_country, d_country} & NON_PARTICIPATING:
        out["notes"].append("Denmark does not take part in the European payment order or small claims "
                            "procedure. A national procedure or a debt collection agency is needed.")
        return out
    out["payment_order"] = True
    out["small_claims"] = currency == "EUR" and principal <= SMALL_CLAIMS_LIMIT_EUR
    option("European Payment Order", True)
    option("European Small Claims Procedure (up to €5,000)", out["small_claims"])
    out["notes"].append("European Payment Order (Reg. 1896/2006): for uncontested claims, no amount limit, "
                        "written procedure, no lawyer required.")
    if out["small_claims"]:
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
    return COUNTRIES.get((country or "").upper(), (None, "en"))[1]


# Beløbsformat pr. sprog: (tusindtalsseparator, decimaltegn, valuta før beløbet?)
_MONEY = {"en": (",", ".", True), "fr": (" ", ",", False), "de": (".", ",", False), "es": (".", ",", False),
          "it": (".", ",", False), "nl": (".", ",", True), "pt": (".", ",", False), "da": (".", ",", False),
          "sv": (" ", ",", False), "fi": (" ", ",", False), "pl": (" ", ",", False),
          "cs": (" ", ",", False), "sk": (" ", ",", False)}
_SYMBOL = {"EUR": "€", "GBP": "£"}


def format_money(amount, currency, language="en"):
    """Fx 7800 EUR -> 'EUR 7,800.00' (en), '7.800,00 €' (de), '7 800,00 €' (fr); 2000 GBP -> '£2,000.00'."""
    thousands, decimal, before = _MONEY.get(language, (".", ",", False))
    text = f"{float(amount):,.2f}".replace(",", "\x00").replace(".", decimal).replace("\x00", thousands)
    if not currency:
        return text
    if language == "en":
        return f"£{text}" if currency == "GBP" else f"{currency} {text}"
    symbol = _SYMBOL.get(currency, currency)
    return f"{symbol} {text}" if before else f"{text} {symbol}"


def format_percent(value, language="en"):
    """Fx 10.4 -> '10.4 %' (en) eller '10,4 %' (fr/de/...)."""
    decimal = _MONEY.get(language, (".", ",", False))[1]
    return f"{float(value):g}".replace(".", decimal) + " %"

"""Test af de deterministiske beregninger. Kør: python -m unittest discover tests"""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import claims  # noqa: E402

TODAY = date(2026, 9, 28)
RATES = {"EU": {"percent": 10.4}, "UK": {"margin": 8, "base_rates": {"2026-H1": 3.75, "2026-H2": 3.75}}}


def claim(c="ES", d="DE", b2b=True, invoices=None):
    return {
        "creditor": {"name": "Ana Freelance", "country": c, "is_business": b2b},
        "debtor": {"name": "Kunde GmbH", "country": d, "is_business": True},
        "invoices": invoices if invoices is not None else [
            {"number": "2026-014", "issue_date": "2026-06-01", "due_date": "2026-07-01", "amount": 3650.0, "currency": "EUR"}],
    }


class CalcTests(unittest.TestCase):
    def test_interest_and_compensation(self):
        r = claims.calculate(claim(), RATES, today=TODAY)
        line = r["lines"][0]
        self.assertEqual(line["days_late"], 89)
        self.assertEqual(line["interest"], round(3650 * 0.104 * 89 / 365, 2))  # 92.56
        self.assertEqual(r["compensation"], 40)
        self.assertEqual(r["total_claim"], round(3650 + line["interest"], 2))
        self.assertTrue(r["procedures"]["payment_order"])
        self.assertTrue(r["procedures"]["small_claims"])

    def test_default_30_day_term(self):
        inv = [{"number": "7", "issue_date": "2026-08-01", "due_date": "", "amount": 1000, "currency": "EUR"}]
        r = claims.calculate(claim(invoices=inv), RATES, today=TODAY)
        self.assertEqual(r["lines"][0]["due_date"], "2026-08-31")
        self.assertTrue(r["lines"][0]["due_date_assumed"])
        self.assertTrue(any("assumed" in w for w in r["warnings"]))

    def test_compensation_per_invoice(self):
        inv = [{"number": str(i), "issue_date": "2026-05-01", "due_date": "2026-06-01", "amount": 500, "currency": "EUR"}
               for i in range(3)]
        self.assertEqual(claims.calculate(claim(invoices=inv), RATES, today=TODAY)["compensation"], 120)

    def test_small_claims_limit(self):
        inv = [{"number": "1", "issue_date": "2026-05-01", "due_date": "2026-06-01", "amount": 5000.01, "currency": "EUR"}]
        p = claims.calculate(claim(invoices=inv), RATES, today=TODAY)["procedures"]
        self.assertTrue(p["payment_order"])
        self.assertFalse(p["small_claims"])

    def test_not_b2b(self):
        r = claims.calculate(claim(b2b=False), RATES, today=TODAY)
        self.assertEqual((r["interest"], r["compensation"]), (0.0, 0))
        self.assertTrue(any("business-to-business" in w for w in r["warnings"]))

    def test_same_country_and_denmark(self):
        self.assertFalse(claims.calculate(claim(d="ES"), RATES, today=TODAY)["procedures"]["cross_border"])
        p = claims.calculate(claim(d="DK"), RATES, today=TODAY)["procedures"]
        self.assertTrue(p["cross_border"])
        self.assertFalse(p["payment_order"])

    def test_not_overdue(self):
        inv = [{"number": "1", "issue_date": "2026-09-20", "due_date": "2026-10-20", "amount": 100, "currency": "EUR"}]
        r = claims.calculate(claim(invoices=inv), RATES, today=TODAY)
        self.assertEqual((r["interest"], r["compensation"]), (0.0, 0))

    def test_uk_regime(self):
        inv = [{"number": "A1", "issue_date": "2026-05-01", "due_date": "2026-06-01", "amount": 1200, "currency": "GBP"},
               {"number": "A2", "issue_date": "2026-07-01", "due_date": "2026-07-31", "amount": 800, "currency": "GBP"}]
        c = claim(c="GB", d="GB", invoices=inv)
        c["debtor"]["entity_type"] = "company"
        r = claims.calculate(c, RATES, today=TODAY)
        self.assertEqual(r["regime"], "UK")
        self.assertEqual([l["rate_percent"] for l in r["lines"]], [11.75, 11.75])
        self.assertEqual([l["compensation"] for l in r["lines"]], [70, 40])  # £70 for £1k-10k, £40 under £1k
        self.assertEqual(r["compensation_currency"], "GBP")
        self.assertEqual(r["lines"][0]["interest"], round(1200 * 0.1175 * 119 / 365, 2))
        p = r["procedures"]
        self.assertTrue(p["uk_claim"])
        self.assertFalse(p["uk_protocol"])
        self.assertEqual(r["deadline_days"], 14)
        self.assertEqual([o["available"] for o in p["options"]], [True, True, True])

    def test_uk_sole_trader_protocol(self):
        c = claim(c="GB", d="GB", invoices=[{"number": "1", "issue_date": "2026-05-01", "due_date": "2026-06-01",
                                               "amount": 2000, "currency": "GBP"}])
        c["debtor"]["entity_type"] = "sole_trader"
        r = claims.calculate(c, RATES, today=TODAY)
        self.assertTrue(r["procedures"]["uk_protocol"])
        self.assertEqual(r["deadline_days"], 30)

    def test_uk_rate_missing_half_year(self):
        c = claim(c="GB", d="GB", invoices=[{"number": "1", "issue_date": "2025-01-01", "due_date": "2025-02-01",
                                               "amount": 500, "currency": "GBP"}])
        r = claims.calculate(c, RATES, today=TODAY)
        self.assertEqual(r["lines"][0]["rate_percent"], 11.75)
        self.assertTrue(any("2025-H1" in w for w in r["warnings"]))

    def test_brexit_cases(self):
        eu_to_uk = claims.calculate(claim(c="ES", d="GB"), RATES, today=TODAY)
        self.assertEqual(eu_to_uk["regime"], "EU")          # kreditors lov: EU-rente og 40 EUR
        self.assertEqual(eu_to_uk["compensation"], 40)
        self.assertTrue(eu_to_uk["procedures"]["uk_claim"])  # men sagen føres ved britiske domstole
        self.assertTrue(any("Brexit" in n for n in eu_to_uk["procedures"]["notes"]))
        uk_to_eu = claims.calculate(claim(c="GB", d="DE"), RATES, today=TODAY)
        self.assertEqual(uk_to_eu["regime"], "UK")
        self.assertFalse(uk_to_eu["procedures"]["payment_order"])

    def test_rate_override(self):
        r = claims.calculate(claim(), RATES, today=TODAY, rate_override="12")
        self.assertEqual(r["lines"][0]["rate_percent"], 12.0)

    def test_money_format(self):
        self.assertEqual(claims.format_money(7800, "EUR", "en"), "EUR 7,800.00")
        self.assertEqual(claims.format_money(7800, "EUR", "de"), "7.800,00 €")
        self.assertEqual(claims.format_money(7800, "EUR", "fr"), "7\u202f800,00 €")
        self.assertEqual(claims.format_money(8142.26, "EUR", "nl"), "€ 8.142,26")
        self.assertEqual(claims.format_money(1234.5, "SEK", "sv"), "1\u00a0234,50 SEK")
        self.assertEqual(claims.format_money(2000, "GBP", "en"), "£2,000.00")

    def test_percent_format(self):
        self.assertEqual(claims.format_percent(10.4, "fr"), "10,4 %")
        self.assertEqual(claims.format_percent(10.4, "en"), "10.4 %")

    def test_disputed_claim(self):
        c = dict(claim(), disputed=True)
        p = claims.calculate(c, RATES, today=TODAY)["procedures"]
        self.assertTrue(any("disputes" in n for n in p["notes"]))
        import ai
        self.assertIn("Small Claims", ai._next_step({"procedures": p}, disputed=True))
        big = {"payment_order": True, "small_claims": False, "uk_claim": False}
        self.assertNotIn("Payment Order", ai._next_step({"procedures": big}, disputed=True))
        self.assertIn("Payment Order", ai._next_step({"procedures": big}, disputed=False))

    def test_untranslated_detection(self):
        import ai
        step = "initiate legal proceedings at the competent court to recover the debt, without further notice"
        bad = "nous prendrons les dispositions afin de initiate legal proceedings at the competent court to recover"
        good = "nous engagerons une procédure judiciaire devant la juridiction compétente"
        self.assertEqual(ai.untranslated(bad, [step]), [step])
        self.assertEqual(ai.untranslated(good, [step, ""]), [])

    def test_language_defaults(self):
        self.assertEqual(claims.default_language("de"), "de")
        self.assertEqual(claims.default_language("IE"), "en")
        self.assertEqual(claims.default_language("XX"), "en")


if __name__ == "__main__":
    unittest.main()

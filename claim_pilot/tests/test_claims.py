"""Test af de deterministiske beregninger. Kør: python -m unittest discover tests"""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import claims  # noqa: E402

TODAY = date(2026, 9, 28)


def claim(c="ES", d="DE", b2b=True, invoices=None):
    return {
        "creditor": {"name": "Ana Freelance", "country": c, "is_business": b2b},
        "debtor": {"name": "Kunde GmbH", "country": d, "is_business": True},
        "invoices": invoices if invoices is not None else [
            {"number": "2026-014", "issue_date": "2026-06-01", "due_date": "2026-07-01", "amount": 3650.0, "currency": "EUR"}],
    }


class CalcTests(unittest.TestCase):
    def test_interest_and_compensation(self):
        r = claims.calculate(claim(), 10.4, today=TODAY)
        line = r["lines"][0]
        self.assertEqual(line["days_late"], 89)
        self.assertEqual(line["interest"], round(3650 * 0.104 * 89 / 365, 2))  # 92.56
        self.assertEqual(r["compensation_eur"], 40)
        self.assertEqual(r["total_claim"], round(3650 + line["interest"], 2))
        self.assertTrue(r["procedures"]["payment_order"])
        self.assertTrue(r["procedures"]["small_claims"])

    def test_default_30_day_term(self):
        inv = [{"number": "7", "issue_date": "2026-08-01", "due_date": "", "amount": 1000, "currency": "EUR"}]
        r = claims.calculate(claim(invoices=inv), 10.4, today=TODAY)
        self.assertEqual(r["lines"][0]["due_date"], "2026-08-31")
        self.assertTrue(r["lines"][0]["due_date_assumed"])
        self.assertTrue(any("assumed" in w for w in r["warnings"]))

    def test_compensation_per_invoice(self):
        inv = [{"number": str(i), "issue_date": "2026-05-01", "due_date": "2026-06-01", "amount": 500, "currency": "EUR"}
               for i in range(3)]
        self.assertEqual(claims.calculate(claim(invoices=inv), 10.4, today=TODAY)["compensation_eur"], 120)

    def test_small_claims_limit(self):
        inv = [{"number": "1", "issue_date": "2026-05-01", "due_date": "2026-06-01", "amount": 5000.01, "currency": "EUR"}]
        p = claims.calculate(claim(invoices=inv), 10.4, today=TODAY)["procedures"]
        self.assertTrue(p["payment_order"])
        self.assertFalse(p["small_claims"])

    def test_not_b2b(self):
        r = claims.calculate(claim(b2b=False), 10.4, today=TODAY)
        self.assertEqual((r["interest"], r["compensation_eur"]), (0.0, 0))
        self.assertTrue(any("B2B" in w for w in r["warnings"]))

    def test_same_country_and_denmark(self):
        self.assertFalse(claims.calculate(claim(d="ES"), 10.4, today=TODAY)["procedures"]["cross_border"])
        p = claims.calculate(claim(d="DK"), 10.4, today=TODAY)["procedures"]
        self.assertTrue(p["cross_border"])
        self.assertFalse(p["payment_order"])

    def test_not_overdue(self):
        inv = [{"number": "1", "issue_date": "2026-09-20", "due_date": "2026-10-20", "amount": 100, "currency": "EUR"}]
        r = claims.calculate(claim(invoices=inv), 10.4, today=TODAY)
        self.assertEqual((r["interest"], r["compensation_eur"]), (0.0, 0))

    def test_language_defaults(self):
        self.assertEqual(claims.default_language("de"), "de")
        self.assertEqual(claims.default_language("IE"), "en")
        self.assertEqual(claims.default_language("XX"), "en")


if __name__ == "__main__":
    unittest.main()

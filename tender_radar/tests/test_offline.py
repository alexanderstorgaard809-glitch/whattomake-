"""Offline-test af koden (ingen netværk). Testdata er opdigtet og formet efter TED's API-spec.

Kør: python -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analyze  # noqa: E402
import report  # noqa: E402
import ted  # noqa: E402

RAW = {
    "publication-number": "123456-2026",
    "publication-date": ["2026-09-20+02:00"],
    "notice-type": "cn-standard",
    "notice-title": {"nld": "Nieuwe website gemeente", "eng": "New municipal website"},
    "description-proc": {"nld": "De gemeente zoekt een bureau voor een toegankelijke website."},
    "buyer-name": {"nld": ["Gemeente Voorbeeld"]},
    "buyer-country": ["NLD"],
    "classification-cpv": ["72413000"],
    "deadline-receipt-tender-date-lot": ["2026-11-14+01:00", "2026-11-10+01:00"],
    "estimated-value-lot": [100000.0, 50000.0],
    "estimated-value-cur-lot": ["EUR", "EUR"],
    "links": {"html": {"ENG": "https://ted.europa.eu/en/notice/-/detail/123456-2026"}},
}


class FakeLLM:
    total_cost = 0.0

    def json_call(self, system, user, name, schema):
        ids = [line.split("ID: ")[1] for line in user.splitlines() if line.startswith("ID: ")]
        if name == "tender_summaries":
            return {"items": [{"id": i, "title_en": "New municipal website", "summary_en": "Accessible website.",
                               "work_type": "website", "keywords": ["WCAG"], "small_company_friendly": True}
                              for i in ids]}
        ids = [line.split(" | ")[0][2:] for line in user.splitlines() if line.startswith("- ")]
        return {"items": [{"id": i, "score": 88, "reason": "Passer til jeres webarbejde."} for i in ids]}


class FakeStrongLLM:
    total_cost = 0.0
    models = ["fake-strong"]

    def __init__(self, **item):
        self.item = item

    def json_call(self, system, user, name, schema):
        ids = [line.split("ID: ")[1] for line in user.splitlines() if line.startswith("ID: ")]
        base = {"purchase_type": "custom development", "conflicts_with_exclusions": False,
                "too_big": False, "score": 92, "reason": "God match."}
        return {"items": [dict(base, id=i, **self.item) for i in ids]}


class OfflineTests(unittest.TestCase):
    def test_normalize(self):
        t = ted.normalize(RAW)
        self.assertEqual(t["title"], "New municipal website")
        self.assertEqual(t["buyer"], "Gemeente Voorbeeld")
        self.assertEqual(t["country"], "NLD")
        self.assertEqual(t["deadline"], "2026-11-10")
        self.assertEqual((t["value"], t["currency"]), (150000.0, "EUR"))
        self.assertEqual(t["published"], "2026-09-20")

    def test_values_as_text(self):
        t = ted.normalize(dict(RAW, **{"estimated-value-proc": "250000", "estimated-value-cur-proc": "EUR"}))
        self.assertEqual(t["value"], 250000.0)
        t2 = ted.normalize(dict(RAW, **{"estimated-value-lot": ["100000", "50000.5"]}))
        self.assertEqual(t2["value"], 150000.5)
        # gamle data i tenders.json kan have tekst-værdier
        self.assertEqual(ted.format_value({"value": "1200000", "currency": "DKK"}), "1.200.000 DKK")
        self.assertEqual(ted.format_value({"value": "n/a"}), "unknown")

    def test_deadline_fallback_and_languages(self):
        raw = dict(RAW, **{"deadline-receipt-tender-date-lot": [],
                           "deadline-receipt-request-date-lot": ["2026-10-20+02:00"],
                           "submission-language": ["DEU", "ENG", "DEU"]})
        t = ted.normalize(raw)
        self.assertEqual((t["deadline"], t["deadline_kind"]), ("2026-10-20", "request"))
        self.assertEqual(t["languages"], ["DEU", "ENG"])

    def test_language_cap(self):
        t = dict(ted.normalize(RAW), languages=["DEU"])
        self.assertFalse(analyze.language_ok(t, {"languages": ["DAN", "ENG"]}))
        self.assertTrue(analyze.language_ok(t, {"languages": ["dan", "deu"]}))
        self.assertTrue(analyze.language_ok(dict(t, languages=[]), {"languages": ["DAN"]}))
        tenders = [t]
        analyze.summarize(tenders, FakeLLM(), {}, log=lambda *_: None)
        profile = {"name": "X", "description": "web", "languages": ["DAN", "ENG"]}
        results = analyze.match(tenders, profile, FakeLLM(), log=lambda *_: None)
        self.assertEqual(results[0][1], analyze.LANGUAGE_CAP)

    def test_rerank_caps(self):
        t = ted.normalize(RAW)
        analyze.summarize([t], FakeLLM(), {}, log=lambda *_: None)
        profile = {"name": "X", "description": "web", "languages": ["ENG"]}
        first = [(t, 70, "x"), (dict(t, id="low"), 30, "y")]
        cases = [({}, 92), ({"conflicts_with_exclusions": True}, analyze.CAP_EXCLUDED),
                 ({"purchase_type": "ready-made product or licence"}, analyze.CAP_PRODUCT),
                 ({"too_big": True}, analyze.CAP_TOO_BIG)]
        for item, expected in cases:
            out = analyze.rerank(first, profile, FakeStrongLLM(**item), min_first_score=50, log=lambda *_: None)
            self.assertEqual(len(out), 1)  # udbud under 50 i første runde genvurderes ikke
            self.assertEqual(out[0][1], expected, item)
        # modellen ændrer ID'et, men svarer i samme rækkefølge
        class RenamingLLM(FakeStrongLLM):
            def json_call(self, *a):
                res = super().json_call(*a)
                for it in res["items"]:
                    it["id"] = "notice " + it["id"]
                return res
        debug = []
        out = analyze.rerank(first, profile, RenamingLLM(), log=lambda *_: None, debug=debug)
        self.assertEqual(out[0][1], 92)
        self.assertEqual(debug[0]["final_score"], 92)
        out = analyze.rerank(first, dict(profile, sells_products=True),
                             FakeStrongLLM(purchase_type="ready-made product or licence"), log=lambda *_: None)
        self.assertEqual(out[0][1], 92)
        page, md = report.build(dict(profile, report_language="da"), out, total=1, days=30)
        self.assertIn("køb af færdigt produkt/licens", md)

    def test_query(self):
        q = ted.build_query(["72000000", "48000000"], 30, ["cn-standard"])
        self.assertIn("classification-cpv IN (72000000 48000000)", q)
        self.assertIn("notice-type IN (cn-standard)", q)

    def test_fetch_drops_unsupported_values(self):
        calls = []

        def unsupported(field, value):
            return ted.TedError("400", {"error": {"type": "QUERY_UNSUPPORTED_FIELD_VALUE",
                                                  "fieldName": field, "fieldValue": value}})

        def fake_search(query, scope, log):
            calls.append(query)
            if "72212800" in query:
                raise unsupported("classification-cpv", "72212800")
            if "cn-bogus" in query:
                raise unsupported("notice-type", "cn-bogus")
            return [RAW, dict(RAW, **{"publication-number": "2", "notice-type": "can-standard"})]

        with mock.patch.object(ted, "search", side_effect=fake_search):
            out = ted.fetch(["72000000", "72212800"], 30, ["cn-standard", "cn-bogus"], log=lambda *_: None)
        self.assertEqual(len(calls), 3)
        self.assertIn("classification-cpv IN (72000000)", calls[-1])
        self.assertIn("notice-type IN (cn-standard)", calls[-1])
        self.assertEqual([t["id"] for t in out], ["123456-2026"])

    def test_fetch_raises_other_errors(self):
        err = ted.TedError("400", {"error": {"type": "QUERY_SYNTAX_ERROR"}})
        with mock.patch.object(ted, "search", side_effect=err):
            with self.assertRaises(ted.TedError):
                ted.fetch(["72000000"], 30, [], log=lambda *_: None)

    def test_pipeline_and_report(self):
        tenders = [ted.normalize(RAW)]
        cache = {}
        analyze.summarize(tenders, FakeLLM(), cache, log=lambda *_: None)
        self.assertIn("123456-2026", cache)
        profile = {"name": "Test ApS", "description": "web", "report_language": "da"}
        results = analyze.match(tenders, profile, FakeLLM(), log=lambda *_: None)
        self.assertEqual(results[0][1], 88)
        page, md = report.build(profile, results, total=1, days=30)
        self.assertIn("Holland", page)
        self.assertIn("150.000 EUR", md)
        self.assertIn("https://ted.europa.eu/en/notice/-/detail/123456-2026", page)
        long_buyer = dict(results[0][0], buyer="Ministerium " * 20, languages=["DEU"], deadline_kind="request")
        page, md = report.build(profile, [(long_buyer, 90, "x")], total=1, days=30)
        self.assertIn("Frist for ansøgning", md)
        self.assertIn("Tilbudssprog:** tysk", md)
        self.assertIn(" …", md)


if __name__ == "__main__":
    unittest.main()

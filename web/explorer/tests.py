"""Saved-portfolio persistence: CRUD, validation, sharing.

None of these hit the network — only the analyze flow fetches prices, and
that is not exercised here. `/p/<uuid>` renders the page, which normally
asks FRED for the risk-free rate, so that call is patched out.
"""

import json
import uuid
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from explorer.models import Holding, SavedPortfolio

CONFIG = {
    "name": "Dividend core",
    "weights": {"AAPL": 50, "MSFT": 30, "JNJ": 20},
    "method": "robust",
    "years": 15,
    "risk_free_rate": 0.043,
}


class PortfolioApiTests(TestCase):
    def post(self, body, expect=None):
        res = self.client.post(
            "/api/portfolios", data=json.dumps(body), content_type="application/json"
        )
        if expect is not None:
            self.assertEqual(res.status_code, expect, res.content)
        return res

    # ---------------------------------------------------------- round trip

    def test_save_list_read_delete(self):
        res = self.post(CONFIG, expect=201)
        created = res.json()
        pid = created["id"]
        self.assertEqual(created["name"], "Dividend core")
        self.assertTrue(created["url"].endswith(f"/p/{pid}"))
        self.assertEqual(SavedPortfolio.objects.count(), 1)
        self.assertEqual(Holding.objects.count(), 3)

        listing = self.client.get("/api/portfolios").json()
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]["id"], pid)
        self.assertEqual(listing[0]["tickers"], ["AAPL", "MSFT", "JNJ"])
        self.assertEqual(listing[0]["method"], "robust")
        self.assertIn("updated_at", listing[0])

        detail = self.client.get(f"/api/portfolios/{pid}").json()
        self.assertEqual(detail["tickers"], ["AAPL", "MSFT", "JNJ"])
        self.assertEqual(detail["method"], "robust")
        self.assertEqual(detail["years"], 15)
        self.assertAlmostEqual(detail["risk_free_rate"], 0.043)
        # weights come back as fractions of 1, in the order given
        self.assertAlmostEqual(detail["weights"]["AAPL"], 0.5)
        self.assertAlmostEqual(detail["weights"]["MSFT"], 0.3)
        self.assertAlmostEqual(detail["weights"]["JNJ"], 0.2)
        self.assertAlmostEqual(sum(detail["weights"].values()), 1.0)

        res = self.client.delete(f"/api/portfolios/{pid}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(SavedPortfolio.objects.count(), 0)
        self.assertEqual(Holding.objects.count(), 0)  # cascade
        self.assertEqual(self.client.get("/api/portfolios").json(), [])

    def test_update_replaces_holdings_and_keeps_id(self):
        pid = self.post(CONFIG, expect=201).json()["id"]
        updated = dict(
            CONFIG,
            id=pid,
            name="Renamed",
            weights={"SPY": 1, "BND": 1},
            method="normal",
            years=5,
        )
        res = self.post(updated, expect=200)
        self.assertEqual(res.json()["id"], pid)
        self.assertEqual(SavedPortfolio.objects.count(), 1)

        detail = self.client.get(f"/api/portfolios/{pid}").json()
        self.assertEqual(detail["name"], "Renamed")
        self.assertEqual(detail["tickers"], ["SPY", "BND"])
        self.assertEqual(detail["method"], "normal")
        self.assertEqual(detail["years"], 5)
        self.assertAlmostEqual(detail["weights"]["SPY"], 0.5)
        self.assertEqual(Holding.objects.count(), 2)  # old rows gone

    def test_list_is_newest_first(self):
        first = self.post(dict(CONFIG, name="first"), expect=201).json()["id"]
        second = self.post(dict(CONFIG, name="second"), expect=201).json()["id"]
        ids = [row["id"] for row in self.client.get("/api/portfolios").json()]
        self.assertEqual(ids, [second, first])

    def test_config_round_trips_through_the_model(self):
        pid = self.post(CONFIG, expect=201).json()["id"]
        config = SavedPortfolio.objects.get(pk=pid).to_config()
        self.assertEqual(
            set(config),
            {"tickers", "weights", "method", "years", "risk_free_rate"},
        )
        self.assertEqual(config["tickers"], list(config["weights"]))

    # ---------------------------------------------------------- validation

    def test_rejects_bad_ticker(self):
        res = self.post(dict(CONFIG, weights={"not a ticker!": 1}), expect=400)
        self.assertIn("ticker", res.json()["error"])
        self.assertEqual(SavedPortfolio.objects.count(), 0)

    def test_rejects_too_many_assets(self):
        weights = {f"T{i}": 1 for i in range(16)}
        res = self.post(dict(CONFIG, weights=weights), expect=400)
        self.assertIn("15 assets", res.json()["error"])
        self.assertEqual(SavedPortfolio.objects.count(), 0)

    def test_rejects_bad_risk_free_rate(self):
        res = self.post(dict(CONFIG, risk_free_rate=0.9), expect=400)
        self.assertIn("Risk-free rate", res.json()["error"])
        res = self.post(dict(CONFIG, risk_free_rate="high"), expect=400)
        self.assertIn("numbers", res.json()["error"])
        self.assertEqual(SavedPortfolio.objects.count(), 0)

    def test_rejects_bad_years_and_method(self):
        self.assertIn("Lookback", self.post(dict(CONFIG, years=99), 400).json()["error"])
        self.assertIn("method", self.post(dict(CONFIG, method="magic"), 400).json()["error"])

    def test_rejects_missing_name_and_weights(self):
        body = dict(CONFIG)
        body.pop("name")
        self.assertIn("name", self.post(body, 400).json()["error"])
        self.assertIn("weights", self.post(dict(CONFIG, weights={}), 400).json()["error"])
        self.assertIn("weights", self.post(dict(CONFIG, weights={"AAPL": -1}), 400).json()["error"])
        self.assertIn("zero", self.post(dict(CONFIG, weights={"AAPL": 0}), 400).json()["error"])

    def test_rejects_overlong_name(self):
        res = self.post(dict(CONFIG, name="x" * 81), expect=400)
        self.assertIn("80 characters", res.json()["error"])

    def test_rejects_non_json_body(self):
        res = self.client.post(
            "/api/portfolios", data="not json", content_type="application/json"
        )
        self.assertEqual(res.status_code, 400)

    # ------------------------------------------------------------ missing

    def test_unknown_uuid_is_404(self):
        missing = uuid.uuid4()
        self.assertEqual(self.client.get(f"/api/portfolios/{missing}").status_code, 404)
        self.assertEqual(
            self.client.delete(f"/api/portfolios/{missing}").status_code, 404
        )
        self.assertEqual(self.post(dict(CONFIG, id=str(missing))).status_code, 404)

    def test_malformed_uuid_does_not_route(self):
        self.assertEqual(self.client.get("/api/portfolios/nope").status_code, 404)

    def test_method_not_allowed(self):
        self.assertEqual(self.client.delete("/api/portfolios").status_code, 405)
        self.assertEqual(self.client.post(f"/api/portfolios/{uuid.uuid4()}").status_code, 405)


class SharedPageTests(TestCase):
    def setUp(self):
        self.portfolio = SavedPortfolio.objects.create(
            name="Shared mix", method="normal", years=5, risk_free_rate=0.05
        )
        self.portfolio.set_holdings({"SPY": 60, "BND": 40})
        # the page prefills the risk-free field from FRED; no network in tests
        patcher = patch("explorer.views.risk_free_rate", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_shared_page_embeds_the_preset(self):
        url = reverse("shared_portfolio", args=[self.portfolio.id])
        self.assertEqual(url, f"/p/{self.portfolio.id}")
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertIn('id="preset"', html)

        start = html.index('id="preset"')
        payload = json.loads(html[html.index(">", start) + 1 : html.index("</script>", start)])
        self.assertEqual(payload["id"], str(self.portfolio.id))
        self.assertEqual(payload["name"], "Shared mix")
        self.assertEqual(payload["tickers"], ["SPY", "BND"])
        self.assertAlmostEqual(payload["weights"]["SPY"], 0.6)
        self.assertEqual(payload["method"], "normal")
        self.assertEqual(payload["years"], 5)
        self.assertAlmostEqual(payload["risk_free_rate"], 0.05)

    def test_plain_page_has_no_preset(self):
        html = self.client.get("/").content.decode()
        self.assertNotIn('id="preset"', html)

    def test_unknown_shared_page_is_404(self):
        res = self.client.get(f"/p/{uuid.uuid4()}")
        self.assertEqual(res.status_code, 404)

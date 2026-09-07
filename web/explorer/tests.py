"""Saved-portfolio persistence: CRUD, validation, sharing.

None of these hit the network — only the analyze flow fetches prices, and
that is not exercised here. `/p/<uuid>` renders the page, which normally
asks FRED for the risk-free rate, so that call is patched out.
"""

import json
import re
import smtplib
import uuid
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from explorer.models import DraftPortfolio, Holding, SavedPortfolio


def make_user(name="rt"):
    return User.objects.create_user(name, password="x-not-secret-x")

CONFIG = {
    "name": "Dividend core",
    "weights": {"AAPL": 50, "MSFT": 30, "JNJ": 20},
    "method": "robust",
    "years": 15,
    "risk_free_rate": 0.043,
}


class PortfolioApiTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

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
        self.user = make_user()
        self.client.force_login(self.user)
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


class AuthTests(TestCase):
    """Everything requires a login; saved lists are per-user; links are
    readable (not editable) across the team."""

    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")

    def save_as(self, user, name):
        self.client.force_login(user)
        res = self.client.post(
            "/api/portfolios",
            data=json.dumps({"name": name, "weights": {"AAPL": 1},
                             "method": "robust", "years": 10,
                             "risk_free_rate": 0.04}),
            content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)
        return res.json()["id"]

    def test_anonymous_can_explore(self):
        """Explore is open: Build and Optimize render for a stranger."""
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            for path in ("/", "/optimize"):
                self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_anonymous_api_gets_json_401(self):
        """...but a user's own data still needs a login, as JSON."""
        for call in (
            lambda: self.client.get("/api/portfolios"),
            lambda: self.client.get("/api/draft"),
            lambda: self.client.put("/api/draft", data="{}",
                                    content_type="application/json"),
            lambda: self.client.get("/api/account"),
        ):
            res = call()
            self.assertEqual(res.status_code, 401)
            self.assertIn("error", res.json())

    def test_login_page_renders_anonymously(self):
        res = self.client.get("/login")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Sign in")

    def test_saved_list_is_scoped_to_the_owner(self):
        self.save_as(self.alice, "Alice mix")
        self.save_as(self.bob, "Bob mix")
        self.client.force_login(self.alice)
        rows = self.client.get("/api/portfolios").json()
        self.assertEqual([r["name"] for r in rows], ["Alice mix"])

    def test_share_link_readable_but_not_editable_across_users(self):
        pid = self.save_as(self.alice, "Alice mix")
        self.client.force_login(self.bob)
        # read: fine (that is the sharing model)
        self.assertEqual(self.client.get(f"/api/portfolios/{pid}").status_code, 200)
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            self.assertEqual(self.client.get(f"/p/{pid}").status_code, 200)
        # overwrite: 403 with a hint to save-as-new
        res = self.client.post(
            "/api/portfolios",
            data=json.dumps({"id": pid, "name": "Steal", "weights": {"AAPL": 1},
                             "method": "robust", "years": 10,
                             "risk_free_rate": 0.04}),
            content_type="application/json")
        self.assertEqual(res.status_code, 403)
        # delete: 403, row survives
        self.assertEqual(
            self.client.delete(f"/api/portfolios/{pid}").status_code, 403)
        self.assertTrue(SavedPortfolio.objects.filter(pk=pid).exists())

    def test_legacy_ownerless_rows_stay_visible_and_are_claimed_on_edit(self):
        legacy = SavedPortfolio.objects.create(name="Old row", method="robust",
                                               years=10, risk_free_rate=0.04)
        legacy.set_holdings({"AAPL": 1})
        self.client.force_login(self.bob)
        rows = self.client.get("/api/portfolios").json()
        self.assertIn("Old row", [r["name"] for r in rows])
        res = self.client.post(
            "/api/portfolios",
            data=json.dumps({"id": str(legacy.id), "name": "Old row",
                             "weights": {"AAPL": 1}, "method": "robust",
                             "years": 10, "risk_free_rate": 0.04}),
            content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        legacy.refresh_from_db()
        self.assertEqual(legacy.owner, self.bob)


class ForecastApiTests(TestCase):
    """/api/forecast — boundary only; prices are synthetic (no network)."""

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    @staticmethod
    def fake_prices(tickers, years=10, **kw):
        import numpy as np
        import pandas as pd
        rng = np.random.default_rng(3)
        idx = pd.bdate_range("2020-01-01", periods=756)
        data = 100 * np.cumprod(
            1 + 0.0004 + 0.01 * rng.standard_normal((756, len(tickers))), axis=0)
        return pd.DataFrame(data, index=idx, columns=list(tickers))

    def forecast(self, body):
        with patch("explorer.views.fetch_prices", side_effect=self.fake_prices):
            return self.client.post(
                "/api/forecast", data=json.dumps(body),
                content_type="application/json")

    def test_happy_path_payload_shape(self):
        res = self.forecast({"tickers": ["AAA", "BBB"], "years": 3,
                             "method": "robust", "risk_free_rate": 0.04,
                             "weights": {"AAA": 70, "BBB": 30},
                             "horizon_years": 2})
        self.assertEqual(res.status_code, 200, res.content)
        d = res.json()
        self.assertEqual(d["model"], "constant-rate")
        self.assertEqual(d["t"][0], 0)
        self.assertEqual(d["median"][0], 1)
        self.assertAlmostEqual(d["t"][-1], 2.0)
        self.assertEqual([b["level"] for b in d["bands"]], [65, 95])
        self.assertEqual(len(d["bands_est"][0]["lo"]), len(d["t"]))
        # outer (estimate-error) band contains the path-only band
        self.assertLessEqual(d["bands_est"][1]["lo"][-1], d["bands"][1]["lo"][-1])

    def test_rejects_bad_horizon(self):
        for bad in (0, 31, "soon"):
            res = self.forecast({"tickers": ["AAA"], "horizon_years": bad})
            self.assertEqual(res.status_code, 400, bad)

    def test_bootstrap_model_selected_and_validated(self):
        res = self.forecast({"tickers": ["AAA", "BBB"],
                             "horizon_years": 2, "model": "bootstrap"})
        self.assertEqual(res.status_code, 200, res.content)
        d = res.json()
        self.assertEqual(d["model"], "block-bootstrap")
        self.assertEqual(d["block"], 21)
        self.assertIn("guarded", d)
        # bands still nested and JSON-clean
        self.assertLessEqual(d["bands"][0]["hi"][-1], d["bands"][1]["hi"][-1])
        res = self.forecast({"tickers": ["AAA"], "model": "oracle"})
        self.assertEqual(res.status_code, 400)

    def test_anchor_modes_reach_the_model(self):
        hist = self.forecast({"tickers": ["AAA", "BBB"], "horizon_years": 2})
        self.assertEqual(hist.status_code, 200, hist.content)
        h = hist.json()
        self.assertEqual(h["anchor"]["mode"], "historical")
        self.assertIsNone(h["anchor"]["value"])

        mkt = self.forecast({"tickers": ["AAA", "BBB"], "horizon_years": 2,
                             "anchor": "market"}).json()
        self.assertEqual(mkt["anchor"]["mode"], "market")
        self.assertEqual(mkt["anchor"]["value"], 0.08)
        self.assertEqual(mkt["anchor"]["prior_sd"], 0.03)
        # the anchor moved the centre and sharpened the estimate, and the
        # payload still says what history alone claimed
        self.assertNotEqual(mkt["mu_annual"], h["mu_annual"])
        self.assertLess(mkt["mu_se_annual"], h["mu_se_annual"])
        self.assertEqual(mkt["anchor"]["mu_historical"], h["mu_annual"])

        cus = self.forecast({"tickers": ["AAA"], "horizon_years": 2,
                             "anchor": "custom", "anchor_value": 0.06}).json()
        self.assertEqual(cus["anchor"]["value"], 0.06)

    def test_cash_sleeve_reaches_the_model(self):
        """`cash_weight` forecasts the complete portfolio — the engine
        option the account page's hypothetical needs (bridge 2). A cash
        sleeve must damp both the centre and the spread, and the payload
        has to report the sleeve it actually used."""
        risky = self.forecast({"tickers": ["AAA", "BBB"], "horizon_years": 2,
                               "risk_free_rate": 0.04}).json()
        mixed = self.forecast({"tickers": ["AAA", "BBB"], "horizon_years": 2,
                               "risk_free_rate": 0.04,
                               "cash_weight": 0.5}).json()
        self.assertEqual(risky["cash_weight"], 0.0)
        self.assertEqual(mixed["cash_weight"], 0.5)
        self.assertEqual(mixed["risk_free_rate"], 0.04)
        self.assertLess(mixed["sigma_annual"], risky["sigma_annual"])
        # ...and the all-risky payload is untouched by the new parameter
        self.assertEqual(risky["risk_free_rate"], 0.0)

    def test_rejects_bad_cash_weight(self):
        for bad in (-0.1, 1.5, "half"):
            res = self.forecast({"tickers": ["AAA"], "horizon_years": 2,
                                 "cash_weight": bad})
            self.assertEqual(res.status_code, 400, bad)

    def test_rejects_bad_anchor(self):
        for body in ({"anchor": "vibes"},
                     {"anchor": "custom"},                   # no value
                     {"anchor": "custom", "anchor_value": "eight"},
                     {"anchor": "custom", "anchor_value": 8},   # 800%/yr
                     {"anchor": "custom", "anchor_value": -0.5}):
            res = self.forecast({"tickers": ["AAA"], **body})
            self.assertEqual(res.status_code, 400, body)
            self.assertIn("error", res.json())      # a message, not a traceback

    def test_anchored_bootstrap_is_floored_under_the_same_anchor(self):
        d = self.forecast({"tickers": ["AAA", "BBB"], "horizon_years": 2,
                           "model": "bootstrap", "anchor": "market"}).json()
        self.assertEqual(d["model"], "block-bootstrap")
        self.assertEqual(d["anchor"]["mode"], "market")
        # bands still nested around the anchored centre
        self.assertLessEqual(d["bands_est"][1]["lo"][-1], d["bands"][1]["lo"][-1])
        self.assertLessEqual(d["bands"][1]["lo"][-1], d["median"][-1])

    def test_is_public(self):
        """No login: it computes from public price data and holds no user
        state. A bad body still gets the ordinary 400, not a 401."""
        self.client.logout()
        res = self.client.post("/api/forecast", data="{}",
                               content_type="application/json")
        self.assertEqual(res.status_code, 400)
        res = self.forecast({"tickers": ["AAA", "BBB"], "years": 3,
                             "method": "robust", "risk_free_rate": 0.04,
                             "horizon_years": 2})
        self.assertEqual(res.status_code, 200, res.content)


class AccountTests(TestCase):
    """Account ledger APIs — engine math is pinned in tests/test_accounting;
    here we test the boundary: validation, derivation, ownership."""

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        import numpy as np
        import pandas as pd
        idx = pd.bdate_range("2026-01-05", periods=4)
        self.closes = {"AAA": pd.DataFrame({"AAA": [50.0, 50.0, 60.0, 60.0]},
                                           index=idx)["AAA"]}
        self.closes["BBB"] = pd.DataFrame({"BBB": [10.0] * 4}, index=idx)["BBB"]

    def patched(self):
        import pandas as pd
        tests = self

        def fake_history(tickers, start):
            return pd.DataFrame({t: tests.closes[t] for t in sorted(tickers)})
        return patch("explorer.account._close_history",
                     side_effect=fake_history)

    def post_event(self, body, expect=200):
        with self.patched():
            res = self.client.post("/api/account/events",
                                   data=json.dumps(body),
                                   content_type="application/json")
        self.assertEqual(res.status_code, expect, res.content)
        return res.json()

    def test_state_derives_from_ledger(self):
        self.post_event({"kind": "deposit", "date": "2026-01-05",
                         "amount": 1000})
        self.post_event({"kind": "buy", "ticker": "AAA", "date": "2026-01-06",
                         "shares": 10, "price": 50})
        d = self.post_event({"kind": "deposit", "date": "2026-01-08",
                             "amount": 1100})
        self.assertEqual(d["total_value"], 2200.0)
        self.assertEqual(d["net_contributions"], 2100.0)
        self.assertEqual(d["gain"], 100.0)
        self.assertAlmostEqual(d["twr"], 0.10, places=6)   # deposit != return
        pos = {p["ticker"]: p for p in d["positions"]}
        self.assertEqual(pos["AAA"]["shares"], 10)
        self.assertEqual(pos["AAA"]["value"], 600.0)
        self.assertEqual(len(d["series"]["dates"]), 4)

    def test_price_defaults_to_that_days_close(self):
        self.post_event({"kind": "deposit", "date": "2026-01-05",
                         "amount": 1000})
        d = self.post_event({"kind": "buy", "ticker": "AAA",
                             "date": "2026-01-07", "shares": 2})
        buy = [e for e in d["events"] if e["kind"] == "buy"][0]
        self.assertEqual(buy["price"], 60.0)

    def test_guards_cash_shares_and_kind(self):
        self.post_event({"kind": "buy", "ticker": "AAA", "shares": 1,
                         "date": "2026-01-06", "price": 50}, expect=400)
        self.post_event({"kind": "deposit", "amount": 100,
                         "date": "2026-01-05"})
        self.post_event({"kind": "sell", "ticker": "AAA", "shares": 1,
                         "date": "2026-01-06", "price": 50}, expect=400)
        self.post_event({"kind": "bribe", "amount": 5}, expect=400)
        self.post_event({"kind": "deposit", "amount": -3}, expect=400)
        self.post_event({"kind": "deposit", "amount": 10,
                         "date": "2199-01-01"}, expect=400)

    def test_forces_are_allowed_and_book_contributions(self):
        d = self.post_event({"kind": "set_shares", "ticker": "AAA",
                             "date": "2026-01-05", "shares": 10, "price": 50})
        self.assertEqual(d["net_contributions"], 500.0)
        self.assertEqual(d["total_value"], 600.0)   # valued at last close 60

    def test_target_and_plan_round_trip(self):
        self.post_event({"kind": "deposit", "date": "2026-01-05",
                         "amount": 1000})
        with self.patched():
            res = self.client.post(
                "/api/account/target",
                data=json.dumps({"weights": {"AAA": 0.6, "BBB": 0.3}}),
                content_type="application/json")
            self.assertEqual(res.status_code, 200, res.content)
            self.assertAlmostEqual(res.json()["target_cash_weight"], 0.1)
            plan = self.client.get("/api/account/plan").json()
        rows = {r["ticker"]: r for r in plan["rows"]}
        self.assertEqual(rows["AAA"]["trade_shares"], 10)   # 600/60
        self.assertEqual(rows["BBB"]["trade_shares"], 30)   # 300/10
        self.assertEqual(plan["cash_after"], 100.0)
        with self.patched():
            res = self.client.post(
                "/api/account/plan/confirm",
                data=json.dumps({"trades": [
                    {"ticker": "AAA", "shares": 10, "price": 60},
                    {"ticker": "BBB", "shares": 30, "price": 10},
                ], "date": "2026-01-08"}),
                content_type="application/json")
        d = res.json()
        self.assertEqual(res.status_code, 200, res.content)
        pos = {p["ticker"]: p for p in d["positions"]}
        self.assertEqual(pos["AAA"]["shares"], 10)
        self.assertEqual(d["cash"], 100.0)
        kinds = [e["kind"] for e in d["events"]]
        self.assertEqual(kinds.count("buy"), 2)

    def test_target_validation(self):
        for weights, code in (
            ({"AAA": 0.9, "BBB": 0.3}, 400),   # sums past 1
            ({"AAA": -0.1}, 400),
            ({"$$$": 0.5}, 400),
            ("nope", 400),
        ):
            res = self.client.post("/api/account/target",
                                   data=json.dumps({"weights": weights}),
                                   content_type="application/json")
            self.assertEqual(res.status_code, code, weights)

    def test_delete_event_and_ownership(self):
        d = self.post_event({"kind": "deposit", "date": "2026-01-05",
                             "amount": 100})
        eid = d["events"][0]["id"]
        other = make_user("intruder")
        self.client.force_login(other)
        with self.patched():
            res = self.client.delete(f"/api/account/events/{eid}")
        self.assertEqual(res.status_code, 404)   # not their ledger
        with self.patched():
            other_state = self.client.get("/api/account").json()
        self.assertEqual(other_state["events"], [])   # accounts are private
        self.client.force_login(self.user)
        with self.patched():
            res = self.client.delete(f"/api/account/events/{eid}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["events"], [])

    def test_pages_render_the_anchor_control_from_engine_constants(self):
        """Both forecast cards get the control, and the long-run number in
        the copy comes from the engine — an empty {{ }} here would be a
        silently blank label. Optimize only renders its card when there is
        something to optimize, so give this user a draft first (fix 1)."""
        draft = DraftPortfolio.objects.create(owner=self.user)
        draft.set_assets([("AAA", 1.0)])
        draft.save()
        with patch("explorer.views.risk_free_rate",
                   return_value={"rate": 0.04, "as_of": "2026-09-01"}):
            build = self.client.get("/optimize").content.decode()
        account = self.client.get("/account").content.decode()
        for html, ids in ((build, ("fanchor", "fanchorvalue")),
                          (account, ("af-anchor", "af-anchorvalue"))):
            for element_id in ids:
                self.assertIn(f'id="{element_id}"', html)
            self.assertIn("Return to normal (8%/yr)", html)
            self.assertIn('max="30"', html)
            self.assertIn('min="-20"', html)
            # the control lives behind a disclosure now; it must still be
            # on the page unconditionally, not swapped for a third model
            self.assertIn("Advanced", html)
            self.assertNotIn("of 3", html)

    def test_anonymous_gets_401_and_page_redirects(self):
        self.client.logout()
        self.assertEqual(self.client.get("/api/account").status_code, 401)
        res = self.client.get("/account")
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.url.startswith("/login"))


class ContributionTests(TestCase):
    """DCA schedule + contribution routing + whole-account forecast."""

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        import pandas as pd
        idx = pd.bdate_range("2026-01-05", periods=4)
        self.closes = {
            "AAA": pd.DataFrame({"AAA": [100.0] * 4}, index=idx)["AAA"],
            "BBB": pd.DataFrame({"BBB": [50.0] * 4}, index=idx)["BBB"],
        }

    def patched(self):
        import pandas as pd
        tests = self

        def fake_history(tickers, start):
            return pd.DataFrame({t: tests.closes[t] for t in sorted(tickers)})
        return patch("explorer.account._close_history",
                     side_effect=fake_history)

    def api(self, method, url, body=None, expect=200):
        with self.patched():
            kwargs = {"content_type": "application/json"}
            if body is not None:
                kwargs["data"] = json.dumps(body)
            res = getattr(self.client, method)(url, **kwargs)
        self.assertEqual(res.status_code, expect, res.content)
        return res.json()

    def seed(self):
        self.api("post", "/api/account/events",
                 {"kind": "deposit", "date": "2026-01-05", "amount": 350})
        self.api("post", "/api/account/target",
                 {"weights": {"AAA": 0.5, "BBB": 0.5}})

    def test_schedule_save_due_flag_and_reminder_context(self):
        d = self.api("post", "/api/account/schedule",
                     {"amount": 200, "cadence": "monthly",
                      "next_due": "2026-01-01"})
        self.assertTrue(d["schedule"]["due"])       # past due date
        # the base template shows the dot on any page
        with self.patched(), \
             patch("explorer.views.risk_free_rate", side_effect=OSError):
            page = self.client.get("/").content.decode()
        self.assertIn("duedot", page)
        # future due date -> not due, no dot
        d = self.api("post", "/api/account/schedule",
                     {"amount": 200, "cadence": "monthly",
                      "next_due": "2099-01-01"})
        self.assertFalse(d["schedule"]["due"])
        self.api("post", "/api/account/schedule",
                 {"amount": -5, "cadence": "monthly"}, expect=400)
        self.api("post", "/api/account/schedule",
                 {"amount": 5, "cadence": "sometimes"}, expect=400)

    def test_contribution_plan_matches_hand_case(self):
        self.seed()
        plan = self.api("get", "/api/account/contribution?amount=350")
        rows = {r["ticker"]: r for r in plan["rows"]}
        # engine hand case: $350 to 50/50 at 100/50 -> A2 + B3... but
        # here $350 idle cash ALSO deploys: budget 700 -> A3+B7? No:
        # deposit was 350 and the plan amount is another 350 -> total
        # 700, targets 350/350: A3 (300) + B7 (350)?? A deficit 350 ->
        # 3 shares (300), B -> 7 shares (350), spend 650 <= 700. Hand:
        self.assertEqual(rows["AAA"]["buy_shares"], 3)
        self.assertEqual(rows["BBB"]["buy_shares"], 7)
        self.assertEqual(plan["spent"], 650.0)
        self.assertEqual(plan["cash_after"], 50.0)
        # buys only
        self.assertTrue(all(r["buy_shares"] >= 0 for r in plan["rows"]))

    def test_confirm_writes_ledger_and_advances_schedule(self):
        self.seed()
        self.api("post", "/api/account/schedule",
                 {"amount": 350, "cadence": "monthly",
                  "next_due": "2026-01-31"})
        d = self.api("post", "/api/account/contribution/confirm",
                     {"amount": 350, "date": "2026-02-15",
                      "trades": [{"ticker": "AAA", "shares": 3, "price": 100},
                                 {"ticker": "BBB", "shares": 7, "price": 50}]})
        kinds = [e["kind"] for e in d["events"]]
        self.assertEqual(kinds.count("deposit"), 2)
        self.assertEqual(kinds.count("buy"), 2)
        # advanced from the DUE date, not the confirm date: Jan 31 ->
        # Feb 28 (clamped), which is > Feb 15, so it stops there.
        # (The `due` flag compares against the real today, so it is
        # asserted with far dates in the schedule test instead.)
        self.assertEqual(d["schedule"]["next_due"], "2026-02-28")
        self.assertEqual(d["cash"], 50.0)

    def test_confirm_rejects_sells_and_overspend(self):
        self.seed()
        self.api("post", "/api/account/contribution/confirm",
                 {"amount": 100,
                  "trades": [{"ticker": "AAA", "shares": -1, "price": 100}]},
                 expect=400)
        self.api("post", "/api/account/contribution/confirm",
                 {"amount": 100,
                  "trades": [{"ticker": "AAA", "shares": 50, "price": 100}]},
                 expect=400)

    def test_account_forecast_complete_portfolio(self):
        self.seed()
        self.api("post", "/api/account/events",
                 {"kind": "buy", "ticker": "AAA", "date": "2026-01-06",
                  "shares": 2, "price": 100})
        import numpy as np
        import pandas as pd

        def fake_prices(tickers, years=10, **kw):
            rng = np.random.default_rng(9)
            idx = pd.bdate_range("2020-01-01", periods=756)
            data = 100 * np.cumprod(
                1 + 0.0004 + 0.01 * rng.standard_normal((756, len(tickers))),
                axis=0)
            return pd.DataFrame(data, index=idx, columns=list(tickers))

        with self.patched(), \
             patch("explorer.account.fetch_prices", side_effect=fake_prices), \
             patch("explorer.account.risk_free_rate",
                   return_value={"rate": 0.04}):
            res = self.client.post(
                "/api/account/forecast",
                data=json.dumps({"horizon_years": 2}),
                content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        f = res.json()
        # $350 in, $200 in AAA -> cash weight 150/350
        self.assertAlmostEqual(f["cash_weight"], 150 / 350, places=6)
        self.assertEqual(f["risk_free_rate"], 0.04)
        self.assertEqual(f["start_value"], 350.0)
        self.assertEqual(f["median"][0], 1)

    def test_account_forecast_anchor(self):
        """The anchor reaches the account endpoint, and on a part-cash
        account it enters as a claim about the risky sleeve only."""
        self.seed()
        self.api("post", "/api/account/events",
                 {"kind": "buy", "ticker": "AAA", "date": "2026-01-06",
                  "shares": 2, "price": 100})
        import numpy as np
        import pandas as pd

        def fake_prices(tickers, years=10, **kw):
            rng = np.random.default_rng(9)
            idx = pd.bdate_range("2020-01-01", periods=756)
            data = 100 * np.cumprod(
                1 + 0.0004 + 0.01 * rng.standard_normal((756, len(tickers))),
                axis=0)
            return pd.DataFrame(data, index=idx, columns=list(tickers))

        def project(body):
            with self.patched(), \
                 patch("explorer.account.fetch_prices", side_effect=fake_prices), \
                 patch("explorer.account.risk_free_rate",
                       return_value={"rate": 0.04}):
                return self.client.post(
                    "/api/account/forecast", data=json.dumps(body),
                    content_type="application/json")

        res = project({"horizon_years": 2, "anchor": "market"})
        self.assertEqual(res.status_code, 200, res.content)
        f = res.json()
        cw = 150 / 350
        self.assertEqual(f["anchor"]["mode"], "market")
        self.assertEqual(f["anchor"]["value"], 0.08)
        self.assertAlmostEqual(f["anchor"]["effective"],
                               (1 - cw) * 0.08 + cw * 0.04, places=6)
        self.assertAlmostEqual(f["anchor"]["prior_sd_effective"],
                               (1 - cw) * 0.03, places=6)
        base = project({"horizon_years": 2}).json()
        self.assertEqual(f["anchor"]["mu_historical"], base["mu_annual"])
        self.assertLess(f["mu_se_annual"], base["mu_se_annual"])

        res = project({"horizon_years": 2, "anchor": "custom",
                       "anchor_value": 0.99})
        self.assertEqual(res.status_code, 400)
        self.assertIn("error", res.json())

    def test_account_forecast_needs_holdings(self):
        self.api("post", "/api/account/events",
                 {"kind": "deposit", "date": "2026-01-05", "amount": 100})
        with self.patched():
            res = self.client.post("/api/account/forecast", data="{}",
                                   content_type="application/json")
        self.assertEqual(res.status_code, 400)


# ----------------------------------------------------------- Build / Optimize
# feature/home-builder: the Build home page, its draft, and the rename of
# the old index page to Optimize. Kept in its own classes per
# docs/handoffs/home-builder.md's conflict watchlist.


class PageTests(TestCase):
    """`/` (Build) and `/optimize` render; login still lands on Build."""

    def setUp(self):
        self.user = make_user()

    def test_build_page_renders_for_a_logged_in_user(self):
        self.client.force_login(self.user)
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Explore")

    def test_optimize_page_renders_for_a_logged_in_user(self):
        self.client.force_login(self.user)
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            res = self.client.get("/optimize")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Optimize")

    def test_optimize_refuses_to_invent_a_portfolio(self):
        """Fix 1: a user with no draft and no holdings gets a signpost back
        to Build — not a toolbar, a chart and seven example assets they
        never chose."""
        self.client.force_login(self.user)
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            res = self.client.get("/optimize")
        html = res.content.decode()
        self.assertIn('id="optimize-empty"', html)
        self.assertIn("Nothing to optimize yet", html)
        for absent in ('id="addform"', 'id="analyze"', 'id="chart"',
                       'id="method"', "app.js"):
            self.assertNotIn(absent, html)

    def test_optimize_renders_the_workbench_once_a_draft_exists(self):
        """...and the moment there is something to optimize, the page is
        exactly what it always was."""
        self.client.force_login(self.user)
        draft = DraftPortfolio.objects.create(owner=self.user)
        draft.set_assets([("AAA", 0.6), ("BBB", 0.4)])
        draft.save()
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            html = self.client.get("/optimize").content.decode()
        self.assertNotIn('id="optimize-empty"', html)
        for present in ('id="addform"', 'id="analyze"', 'id="chart"',
                        'id="sourcepick"', "app.js"):
            self.assertIn(present, html)

    def test_optimize_opens_for_a_funded_account_with_no_draft(self):
        """Holdings are a source too (fix 2) — someone who funded an
        account elsewhere still has something to optimize."""
        from explorer.models import Account, AccountEvent
        self.client.force_login(self.user)
        account = Account.objects.create(owner=self.user)
        AccountEvent.objects.create(account=account, date="2026-01-05",
                                    kind="deposit", amount=1000)
        AccountEvent.objects.create(account=account, date="2026-01-06",
                                    kind="buy", ticker="AAA", shares=5,
                                    price=100)
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            html = self.client.get("/optimize").content.decode()
        self.assertNotIn('id="optimize-empty"', html)
        self.assertIn('id="analyze"', html)

    def test_no_phantom_third_forecast_model_is_served(self):
        """Fix 5: the numbered model labels sent the owner hunting for a
        third model twice. The numbering must be gone from the templates
        *and* the served JS — this deliberately checks the bytes we serve,
        comments included, so it can't creep back in as a stale label."""
        self.client.force_login(self.user)
        draft = DraftPortfolio.objects.create(owner=self.user)
        draft.set_assets([("AAA", 1.0)])
        draft.save()
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            pages = [self.client.get("/optimize").content.decode(),
                     self.client.get("/account").content.decode()]
        from django.contrib.staticfiles import finders
        for name in ("explorer/app.js", "explorer/account.js"):
            with open(finders.find(name)) as fh:
                pages.append(fh.read())
        for text in pages:
            self.assertNotIn("of 3", text)
            self.assertNotIn("model 1", text)
            self.assertNotIn("model 2", text)

    def test_optimize_renders_for_anonymous_visitors(self):
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            res = self.client.get("/optimize")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Optimize")

    def test_login_redirect_lands_on_build(self):
        res = self.client.post(
            "/login", {"username": self.user.username, "password": "x-not-secret-x"})
        self.assertRedirects(res, "/")


class ExploreFirstNavTests(TestCase):
    """feature/explore-first: Explore | My portfolio nav, the journey
    stepper, and the empty-draft start chooser for holders of real
    positions. docs/handoffs/explore-first.md's conflict watchlist claims
    the same files as PageTests above."""

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def draft(self, weights=(("AAA", 1.0),)):
        d = DraftPortfolio.objects.create(owner=self.user)
        d.set_assets(list(weights))
        d.save()
        return d

    def test_nav_is_explore_and_my_portfolio(self):
        html = self.client.get("/").content.decode()
        self.assertIn('class="active">Explore</a>', html)
        self.assertIn(">My portfolio<", html)
        self.assertNotIn(">Build<", html)
        self.assertNotIn(">Optimize<", html)

    def test_nav_marks_explore_active_on_optimize_too(self):
        self.draft()
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            html = self.client.get("/optimize").content.decode()
        self.assertIn('class="active">Explore</a>', html)

    def test_nav_marks_my_portfolio_active_on_account_page(self):
        html = self.client.get("/account").content.decode()
        self.assertIn('class="active">My portfolio', html)

    def test_account_page_title_and_h1_are_my_portfolio(self):
        html = self.client.get("/account").content.decode()
        self.assertIn("Condor Funds — My portfolio</title>", html)
        self.assertIn("<h1>My portfolio</h1>", html)

    def test_stepper_present_on_explore_pages_absent_on_account(self):
        self.draft()
        home_html = self.client.get("/").content.decode()
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            optimize_html = self.client.get("/optimize").content.decode()
        account_html = self.client.get("/account").content.decode()
        self.assertIn('class="stepper"', home_html)
        self.assertIn('class="stepper"', optimize_html)
        self.assertNotIn('class="stepper"', account_html)

    def test_stepper_present_even_when_optimize_has_nothing_to_show(self):
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            html = self.client.get("/optimize").content.decode()
        self.assertIn('id="optimize-empty"', html)
        self.assertIn('class="stepper"', html)

    def test_stepper_highlights_the_current_step_and_links_work(self):
        self.draft()
        home_html = self.client.get("/").content.decode()
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            optimize_html = self.client.get("/optimize").content.decode()
        self.assertIn('class="step current"', home_html)
        self.assertIn('href="/"', home_html)
        self.assertIn('href="/optimize"', home_html)
        self.assertIn('class="step current"', optimize_html)

    def test_no_start_chooser_without_real_holdings(self):
        html = self.client.get("/").content.decode()
        self.assertIn(
            '<script id="has_real" type="application/json">false</script>', html)
        self.assertIn('id="starterchooser" hidden', html)

    def test_start_chooser_appears_for_a_holdings_owner_with_empty_draft(self):
        from explorer.models import Account, AccountEvent
        account = Account.objects.create(owner=self.user)
        AccountEvent.objects.create(account=account, date="2026-01-05",
                                    kind="deposit", amount=1000)
        AccountEvent.objects.create(account=account, date="2026-01-06",
                                    kind="buy", ticker="AAA", shares=5,
                                    price=100)
        html = self.client.get("/").content.decode()
        self.assertIn(
            '<script id="has_real" type="application/json">true</script>', html)
        self.assertIn('id="loadreal"', html)

    def test_no_start_chooser_once_a_draft_exists_even_with_real_holdings(self):
        from explorer.models import Account, AccountEvent
        account = Account.objects.create(owner=self.user)
        AccountEvent.objects.create(account=account, date="2026-01-05",
                                    kind="deposit", amount=1000)
        AccountEvent.objects.create(account=account, date="2026-01-06",
                                    kind="buy", ticker="AAA", shares=5,
                                    price=100)
        self.draft([("BBB", 1.0)])
        html = self.client.get("/").content.decode()
        # has_real is still true (the chooser's JS gates on an empty draft,
        # not on this flag alone), but a draft-holder never gets invented one
        self.assertIn(
            '<script id="has_real" type="application/json">true</script>', html)


class DraftApiTests(TestCase):
    """`/api/draft` — the Build page's single stored mix."""

    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.client.force_login(self.alice)

    def put(self, assets, expect=None):
        res = self.client.put(
            "/api/draft", data=json.dumps({"assets": assets}),
            content_type="application/json")
        if expect is not None:
            self.assertEqual(res.status_code, expect, res.content)
        return res

    def test_empty_draft_created_lazily(self):
        res = self.client.get("/api/draft")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["assets"], [])
        from explorer.models import DraftPortfolio
        self.assertEqual(DraftPortfolio.objects.filter(owner=self.alice).count(), 1)

    def test_put_normalizes_weights_and_round_trips(self):
        res = self.put([{"symbol": "aapl", "weight": 3}, {"symbol": "msft", "weight": 1}],
                       expect=200)
        assets = res.json()["assets"]
        self.assertEqual([a["symbol"] for a in assets], ["AAPL", "MSFT"])
        self.assertAlmostEqual(assets[0]["weight"], 0.75)
        self.assertAlmostEqual(assets[1]["weight"], 0.25)
        self.assertAlmostEqual(sum(a["weight"] for a in assets), 1.0)

        get = self.client.get("/api/draft").json()
        self.assertEqual(get["assets"], assets)

    def test_rejects_bad_ticker_duplicate_and_too_many(self):
        self.put([{"symbol": "not a ticker!", "weight": 1}], expect=400)
        self.put([{"symbol": "AAPL", "weight": 1}, {"symbol": "AAPL", "weight": 1}],
                expect=400)
        self.put([{"symbol": f"T{i}", "weight": 1} for i in range(16)], expect=400)

    def test_rejects_empty_and_all_zero_weights(self):
        self.put([], expect=400)
        self.put([{"symbol": "AAPL", "weight": 0}], expect=400)

    def test_draft_is_scoped_per_owner(self):
        self.put([{"symbol": "AAPL", "weight": 1}], expect=200)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get("/api/draft").json()["assets"], [])
        self.put([{"symbol": "SPY", "weight": 1}], expect=200)
        self.client.force_login(self.alice)
        alice_assets = self.client.get("/api/draft").json()["assets"]
        self.assertEqual([a["symbol"] for a in alice_assets], ["AAPL"])

    def test_anonymous_gets_401(self):
        self.client.logout()
        self.assertEqual(self.client.get("/api/draft").status_code, 401)
        self.assertEqual(self.put([{"symbol": "AAPL", "weight": 1}]).status_code, 401)


class AssetInfoApiTests(TestCase):
    """`/api/asset` — plain facts for one Build-page row, no traceback on a
    data miss. Prices are synthetic (no network); name lookup reads the
    real bundled tickers.json."""

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    @staticmethod
    def fake_store(closes):
        import pandas as pd

        class FakeStore:
            def get(self, ticker, start=None, **kw):
                if ticker not in closes:
                    from condor import DataFetchError
                    raise DataFetchError(f"no data for {ticker}")
                return pd.DataFrame({"close": closes[ticker]})
        return patch("explorer.views.PriceStore", return_value=FakeStore())

    def test_happy_path_with_known_name(self):
        import datetime as dt
        import pandas as pd
        idx = pd.bdate_range(end=dt.date.today(), periods=400)
        s = pd.Series(100.0, index=idx, dtype=float)
        s.iloc[-1] = 112.0
        with self.fake_store({"AAPL": s}):
            res = self.client.get("/api/asset?symbol=aapl")
        self.assertEqual(res.status_code, 200)
        d = res.json()
        series = d.pop("series")
        self.assertEqual(d, {
            "ok": True, "symbol": "AAPL", "name": "Apple Inc.",
            "last_close": 112.0, "as_of": str(idx[-1].date()),
            "year_return": round(0.12, 6), "month_return": round(0.12, 6),
        })
        # ~60 evenly-downsampled points; first and last are real endpoints,
        # never interpolated — a shape for a sparkline, not a data export.
        self.assertLessEqual(len(series["dates"]), 62)
        self.assertEqual(len(series["dates"]), len(series["closes"]))
        self.assertEqual(series["dates"][0], str(idx[0].date()))
        self.assertEqual(series["dates"][-1], str(idx[-1].date()))
        self.assertEqual(series["closes"][0], 100.0)
        self.assertEqual(series["closes"][-1], 112.0)

    def test_short_history_is_not_downsampled_and_short_returns_are_none(self):
        import datetime as dt
        import pandas as pd
        idx = pd.bdate_range(end=dt.date.today(), periods=10)
        s = pd.Series(50.0, index=idx, dtype=float)
        with self.fake_store({"NEWCO": s}):
            d = self.client.get("/api/asset?symbol=NEWCO").json()
        self.assertIsNone(d["year_return"])
        self.assertIsNone(d["month_return"])
        self.assertEqual(len(d["series"]["dates"]), len(idx))
        self.assertEqual(d["series"]["dates"][0], str(idx[0].date()))
        self.assertEqual(d["series"]["dates"][-1], str(idx[-1].date()))

    def test_downsample_keeps_recent_history_dense(self):
        """A naive uniform downsample over ~400 days spaces points ~7 days
        apart, which would make a client-side "last 30 days" slice nearly
        blank. The recent tail must stay close to daily resolution."""
        import datetime as dt
        import pandas as pd
        idx = pd.bdate_range(end=dt.date.today(), periods=400)
        s = pd.Series(range(len(idx)), index=idx, dtype=float)
        with self.fake_store({"DENSE": s}):
            d = self.client.get("/api/asset?symbol=DENSE").json()
        dates = d["series"]["dates"]
        cutoff = str((idx[-1] - pd.Timedelta(days=35)).date())
        recent = [x for x in dates if x >= cutoff]
        self.assertGreaterEqual(len(recent), 20)
        self.assertLessEqual(len(dates), 62)
        self.assertEqual(dates[0], str(idx[0].date()))
        self.assertEqual(dates[-1], str(idx[-1].date()))

    def test_no_data_degrades_gracefully(self):
        with self.fake_store({}):
            res = self.client.get("/api/asset?symbol=ZZZZ")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": False, "symbol": "ZZZZ", "name": None})

    def test_rejects_bad_symbol(self):
        res = self.client.get("/api/asset?symbol=not a ticker!")
        self.assertEqual(res.status_code, 400)

    def test_anonymous_is_served(self):
        """Public: plain facts about a public ticker, no user state."""
        import datetime as dt

        import pandas as pd
        self.client.logout()
        idx = pd.bdate_range(end=dt.date.today(), periods=400)
        with self.fake_store({"AAPL": pd.Series(100.0, index=idx, dtype=float)}):
            res = self.client.get("/api/asset?symbol=AAPL")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])


class LearnPageTests(TestCase):
    """feature/learn-page: `/learn` is the one public page — sessions from
    the channel, the plain-words glossary, the why-card — and the in-app
    "Learn →" links that point into it. The auth boundary is the risk here,
    so it is tested from both sides."""

    def setUp(self):
        self.user = make_user()

    def learn_html(self):
        res = self.client.get("/learn")
        self.assertEqual(res.status_code, 200)
        return res.content.decode()

    # ------------------------------------------------------------ public

    def test_learn_renders_for_anonymous_visitors(self):
        html = self.learn_html()
        for present in ("Sessions", "What is a portfolio?", "Plain words",
                        "Why Condor exists", "Prefer reading? Full transcript"):
            self.assertIn(present, html)

    def test_learn_renders_the_same_for_a_logged_in_user(self):
        anon = self.learn_html()
        self.client.force_login(self.user)
        self.assertIn("Plain words", self.learn_html())
        self.assertIn("Sessions", anon)

    def test_base_template_survives_anonymous_users(self):
        """The nav, the contribution-due dot and the user box all render
        off `request.user`. Links to the private pages still show — they
        just redirect at the door — and the user box now carries the way
        in rather than nothing at all."""
        html = self.learn_html()
        self.assertIn('href="/"', html)
        self.assertIn('href="/account"', html)
        self.assertIn('class="userbox"', html)
        self.assertIn('href="/login?next=/learn"', html)
        self.assertNotIn("Log out", html)
        self.assertNotIn("duedot", html)

    def test_my_portfolio_still_requires_a_login(self):
        """Explore opened up; the account world did not."""
        for path in ("/account",):
            res = self.client.get(path)
            self.assertEqual(res.status_code, 302, path)
            self.assertTrue(res.url.startswith("/login"), path)

    # ------------------------------------------------------------- embeds

    def test_no_youtube_player_before_the_click(self):
        """Facade only: the initial HTML carries a thumbnail and a button,
        no iframe and not even a player URL to fetch."""
        html = self.learn_html()
        self.assertNotIn("youtube-nocookie", html)
        self.assertNotIn("<iframe", html)
        self.assertNotIn("youtube.com/embed", html)
        self.assertIn("i.ytimg.com/vi/dyjYgHEM1og/hqdefault.jpg", html)
        self.assertIn('data-video="dyjYgHEM1og"', html)
        self.assertIn('data-video="jT6muQRTAeI"', html)
        self.assertIn('class="facadebtn"', html)
        self.assertIn("Plays from YouTube", html)

    def test_the_player_is_built_by_the_click_handler_only(self):
        """The nocookie URL lives in the script, so it is fetched when a
        visitor asks for it and never on page load."""
        from django.contrib.staticfiles import finders
        with open(finders.find("explorer/learn.js")) as fh:
            js = fh.read()
        self.assertIn("https://www.youtube-nocookie.com/embed/", js)
        self.assertIn("addEventListener", js)
        # site-wide Referrer-Policy is same-origin, which the YouTube player
        # rejects with Error 153; the iframe has to relax it for itself
        self.assertIn("strict-origin-when-cross-origin", js)
        self.assertIn('src="/static/explorer/learn.js"', self.learn_html())

    def test_facade_images_have_alt_text(self):
        """The brand logo is decorative (alt=""); a thumbnail is content —
        it is the only picture of what the session is."""
        thumbs = re.findall(r"<img[^>]*i\.ytimg\.com[^>]*>", self.learn_html())
        self.assertEqual(len(thumbs), 2)
        for img in thumbs:
            self.assertIn("alt=", img)
            self.assertNotIn('alt=""', img)

    # ----------------------------------------------------------- glossary

    def test_all_thirteen_glossary_anchors_are_present(self):
        from explorer.learn import GLOSSARY
        expected = ["portfolio", "weight", "diversification", "expected-return",
                    "dispersion", "robust", "frontier", "cal", "index", "bond",
                    "whole-shares", "bands", "anchor"]
        self.assertEqual([e["id"] for e in GLOSSARY], expected)
        html = self.learn_html()
        for gid in expected:
            self.assertIn(f'class="glossentry" id="{gid}"', html)

    def test_in_the_app_lines_link_into_the_app(self):
        html = self.learn_html()
        self.assertIn("In the app:", html)
        self.assertIn('href="/optimize#forecastcard"', html)
        self.assertIn('href="/account"', html)

    def test_session_covers_chips_point_at_real_anchors(self):
        html = self.learn_html()
        chips = re.findall(r'class="termchip" href="#([\w-]+)"', html)
        self.assertEqual(chips, ["portfolio", "weight", "diversification",
                                 "index", "bond"])
        for chip in chips:
            self.assertIn(f'id="{chip}"', html)

    # --------------------------------------------------------- in-app links

    def test_every_in_app_learn_link_resolves_to_an_anchor(self):
        """The glossary ids are API. Walk the pages that carry a "Learn →"
        link and prove each fragment exists on `/learn` — a renamed id has
        to break here, not in a user's face."""
        learn = self.learn_html()
        self.client.force_login(self.user)
        draft = DraftPortfolio.objects.create(owner=self.user)
        draft.set_assets([("AAA", 1.0)])
        draft.save()
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            pages = {"/": self.client.get("/").content.decode(),
                     "/optimize": self.client.get("/optimize").content.decode()}
        self.client.logout()
        pages["/login"] = self.client.get("/login").content.decode()

        found = set()
        for path, html in pages.items():
            for href in re.findall(r'href="(/learn[^"]*)"', html):
                found.add(href)
                fragment = href.partition("#")[2]
                if fragment:
                    self.assertIn(f'id="{fragment}"', learn,
                                  f"{path} links to /learn#{fragment}")
        self.assertEqual(found, {"/learn", "/learn#robust", "/learn#anchor",
                                 "/learn#bands", "/learn#frontier"})

    def test_the_five_in_app_link_sites(self):
        self.client.force_login(self.user)
        draft = DraftPortfolio.objects.create(owner=self.user)
        draft.set_assets([("AAA", 1.0)])
        draft.save()
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            optimize = self.client.get("/optimize").content.decode()
        home = self.client.get("/").content.decode()
        for fragment in ("#robust", "#anchor", "#bands", "#frontier"):
            self.assertIn(f'class="learnlink" href="/learn{fragment}"', optimize)
        self.assertIn("New here? Watch the 3-minute session on portfolios", home)

    def test_login_page_offers_learn_to_people_without_an_account(self):
        html = self.client.get("/login").content.decode()
        self.assertIn("New to investing?", html)
        self.assertIn('href="/learn"', html)

    # ---------------------------------------------------------------- nav

    def test_nav_learn_is_a_link_and_active_on_the_learn_page(self):
        self.assertIn('class="active">Learn</a>', self.learn_html())
        self.client.force_login(self.user)
        home = self.client.get("/").content.decode()
        self.assertIn('href="/learn"', home)
        self.assertNotIn('<span class="soon" title="Coming soon">Learn</span>', home)

    def test_learn_carries_no_worldchip_and_no_chart_payload(self):
        """Learn belongs to neither world, and has nothing to plot."""
        html = self.learn_html()
        self.assertNotIn("worldchip", html)
        self.assertNotIn("stepper", html)
        self.assertNotIn("plotly", html)


class AnonymousExploreTests(TestCase):
    """feature/anon-explore: the whole Explore journey without an account.

    The funnel is Learn -> play on Explore -> sign in at the moment you
    want a mix to be real. What did *not* move is the identity boundary:
    anything that reads or writes a user's own data still needs a login,
    and the tests below say so one route at a time."""

    def setUp(self):
        self.user = make_user()

    def analyze(self, body):
        with patch("explorer.views.fetch_prices",
                   side_effect=ForecastApiTests.fake_prices):
            return self.client.post("/api/analyze", data=json.dumps(body),
                                    content_type="application/json")

    def forecast(self, body):
        with patch("explorer.views.fetch_prices",
                   side_effect=ForecastApiTests.fake_prices):
            return self.client.post("/api/forecast", data=json.dumps(body),
                                    content_type="application/json")

    # ------------------------------------------------------------ public

    def test_explore_pages_render_without_an_account(self):
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            for path in ("/", "/optimize", "/learn"):
                self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_share_links_are_readable_by_people_without_accounts(self):
        """The viral loop: a link is *meant* to be sent to a stranger, and
        the uuid is the capability that carries the permission."""
        saved = SavedPortfolio.objects.create(owner=self.user, name="Sent to a friend",
                                              method="robust", years=10,
                                              risk_free_rate=0.04)
        saved.set_holdings({"AAPL": 0.6, "MSFT": 0.4})
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            res = self.client.get(f"/p/{saved.id}")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Sent to a friend")

    def test_analyze_and_forecast_round_trip_with_no_login(self):
        mix = {"tickers": ["AAA", "BBB"], "years": 3, "method": "robust",
               "risk_free_rate": 0.04, "weights": {"AAA": 60, "BBB": 40}}
        res = self.analyze(mix)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIn("frontier", res.json())
        res = self.forecast({**mix, "horizon_years": 2})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIn("median", res.json())

    def test_public_pages_hand_out_a_csrf_cookie(self):
        """An anonymous visitor's first act is a fetch() POST to analyze,
        which needs a token — so every public Explore page must mint one."""
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            for path in ("/", "/optimize"):
                res = self.client.get(path)
                self.assertIn("csrftoken", res.cookies, path)

    # ----------------------------------------------------------- private

    def test_a_users_own_data_still_needs_a_login(self):
        """Explicit regression list: every route that reads or writes
        something belonging to a person stays shut to anonymous callers."""
        json_routes = [
            ("get", "/api/draft"),
            ("put", "/api/draft"),
            ("get", "/api/portfolios"),
            ("post", "/api/portfolios"),
            ("get", "/api/account"),
            ("post", "/api/account/events"),
            ("post", "/api/account/target"),
            ("get", "/api/account/plan"),
            ("post", "/api/account/plan/confirm"),
            ("post", "/api/account/schedule"),
            ("get", "/api/account/contribution"),
            ("post", "/api/account/contribution/confirm"),
            ("get", "/api/account/forecast"),
        ]
        for method, path in json_routes:
            call = getattr(self.client, method)
            res = (call(path) if method == "get" else
                   call(path, data="{}", content_type="application/json"))
            self.assertEqual(res.status_code, 401, path)
            self.assertIn("error", res.json(), path)

        res = self.client.get("/account")
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.url.startswith("/login"))

    def test_a_saved_portfolio_of_someone_elses_is_still_theirs(self):
        """Reading a share link is public; the collection behind it is not."""
        saved = SavedPortfolio.objects.create(owner=self.user, name="Mine",
                                              method="robust", years=10,
                                              risk_free_rate=0.04)
        saved.set_holdings({"AAPL": 1})
        self.assertEqual(self.client.get(f"/api/portfolios/{saved.id}").status_code, 401)
        self.assertEqual(self.client.delete(f"/api/portfolios/{saved.id}").status_code, 401)
        self.assertTrue(SavedPortfolio.objects.filter(pk=saved.id).exists())


class SignInBoundaryTests(TestCase):
    """The identity moments as a visitor without an account meets them:
    visible and aspirational, never a dead end, and never a control that
    would fail if pressed."""

    def setUp(self):
        self.user = make_user()

    def optimize_html(self):
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            return self.client.get("/optimize").content.decode()

    def test_userbox_offers_the_way_in(self):
        html = self.client.get("/learn").content.decode()
        self.assertIn('href="/login?next=/learn"', html)
        self.assertIn("Sign in", html)

    def test_build_swaps_the_account_card_for_an_invitation(self):
        html = self.client.get("/").content.decode()
        self.assertIn("Have an account?", html)
        self.assertIn("or just keep exploring", html)
        self.assertNotIn("Go to My portfolio", html)
        self.assertNotIn('id="acct-tiles"', html)

    def test_the_point_card_asks_for_a_sign_in_instead_of_a_target(self):
        html = self.optimize_html()
        self.assertIn("Sign in to make it real", html)
        self.assertIn('href="/login?next=/optimize"', html)
        self.assertNotIn('id="settarget"', html)
        self.assertNotIn('id="settargetconfirm"', html)
        # adopting a point into your own draft needs no account at all
        self.assertIn('id="adoptpoint"', html)

    def test_signing_in_returns_you_to_the_page_you_were_on(self):
        """Including its query string: someone who followed Build's
        "see the range" deep link and signed in from there should land
        back on the forecast they were looking at, not a bare /optimize."""
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            html = self.client.get(
                "/optimize?forecast=10000&years=5").content.decode()
        self.assertIn("next=/optimize%3Fforecast%3D10000%26years%3D5", html)

    def test_save_and_share_are_replaced_by_a_quiet_line(self):
        html = self.optimize_html()
        self.assertIn("to save &amp; share this mix", html)
        self.assertNotIn('id="save"', html)
        self.assertNotIn('id="saved"', html)

    def test_signed_in_visitors_see_exactly_what_they_always_did(self):
        self.client.force_login(self.user)
        draft = DraftPortfolio.objects.create(owner=self.user)
        draft.set_assets([("AAA", 1.0)])
        draft.save()
        html = self.optimize_html()
        for present in ('id="settarget"', 'id="settargetconfirm"',
                        'id="save"', 'id="saved"', "Make this my real portfolio"):
            self.assertIn(present, html)
        for absent in ("Sign in to make it real", "to save &amp; share this mix"):
            self.assertNotIn(absent, html)
        build = self.client.get("/").content.decode()
        self.assertIn("Go to My portfolio", build)
        self.assertNotIn("Have an account?", build)


class AnonymousDraftGateTests(TestCase):
    """Optimize refuses to invent a portfolio (fix 1) — but an anonymous
    visitor's draft lives in their browser, where the server cannot see
    it. Who decides, and how the page avoids a flash of the wrong half."""

    def setUp(self):
        self.user = make_user()

    def optimize_html(self):
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            return self.client.get("/optimize").content.decode()

    def test_anonymous_ships_both_halves_and_a_head_script_to_choose(self):
        html = self.optimize_html()
        self.assertIn('id="optimize-empty"', html)      # the signpost
        self.assertIn('id="workbench"', html)           # ...and the workbench
        self.assertIn("condor.draft.v1", html)          # the head script
        self.assertIn("nodraft", html)
        # the choice is made in <head>, before any of it can be painted
        self.assertLess(html.index("condor.draft.v1"), html.index("<body>"))

    def test_signed_in_with_nothing_is_unchanged_and_imports_instead(self):
        """No client gate for a signed-in visitor: the server still knows
        the whole answer. The one thing it cannot know — a draft carried
        in from an anonymous session — is imported, then the page reloads
        into the workbench (signpost.js)."""
        self.client.force_login(self.user)
        html = self.optimize_html()
        self.assertIn('id="optimize-empty"', html)
        self.assertNotIn('id="workbench"', html)
        self.assertNotIn("app.js", html)
        self.assertNotIn("nodraft", html)               # no client gate
        self.assertIn("signpost.js", html)

    def test_signed_in_with_a_draft_gets_the_workbench_only(self):
        self.client.force_login(self.user)
        draft = DraftPortfolio.objects.create(owner=self.user)
        draft.set_assets([("AAA", 1.0)])
        draft.save()
        html = self.optimize_html()
        self.assertNotIn('id="optimize-empty"', html)
        self.assertNotIn("nodraft", html)
        self.assertIn('id="workbench"', html)
        self.assertIn("app.js", html)

    def test_a_share_link_is_a_source_of_its_own(self):
        """A stranger following /p/<uuid> has something to optimize even
        with an empty browser — so no gate, no signpost."""
        saved = SavedPortfolio.objects.create(owner=self.user, name="Shared",
                                              method="robust", years=10,
                                              risk_free_rate=0.04)
        saved.set_holdings({"AAPL": 1})
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            html = self.client.get(f"/p/{saved.id}").content.decode()
        self.assertNotIn('id="optimize-empty"', html)
        self.assertNotIn("nodraft", html)
        self.assertIn("app.js", html)


class DraftStorageAdapterTests(TestCase):
    """One draft, two homes (draft.js). The server can only see half of
    this, so these check the half it can: that both Explore pages are
    wired to the adapter, tell it who the visitor is, and that neither
    page talks to /api/draft behind its back. The browser half is
    verified by hand (see the handoff doc)."""

    def setUp(self):
        self.user = make_user()

    @staticmethod
    def served(name):
        from django.contrib.staticfiles import finders
        with open(finders.find(name)) as fh:
            return fh.read()

    def test_both_pages_load_the_adapter_and_say_who_is_here(self):
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            pages = [self.client.get("/").content.decode(),
                     self.client.get("/optimize").content.decode()]
        for html in pages:
            self.assertIn("draft.js", html)
            self.assertIn('id="is_authenticated"', html)
        self.client.force_login(self.user)
        draft = DraftPortfolio.objects.create(owner=self.user)
        draft.set_assets([("AAA", 1.0)])
        draft.save()
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            authed = [self.client.get("/").content.decode(),
                      self.client.get("/optimize").content.decode()]
        for html in authed:
            self.assertIn(">true<", html)

    def test_no_page_writes_the_draft_api_behind_the_adapter(self):
        """Every read and write of the draft goes through draft.js — a
        direct fetch("/api/draft") in either page would silently do
        nothing for a visitor without an account."""
        for name in ("explorer/home.js", "explorer/app.js"):
            self.assertNotIn('"/api/draft"', self.served(name), name)
        adapter = self.served("explorer/draft.js")
        self.assertIn('"/api/draft"', adapter)
        self.assertIn("condor.draft.v1", adapter)

    def test_the_import_is_one_shot_and_the_account_wins(self):
        """The contract the browser half implements, asserted where it is
        written down: import once per load, and a non-empty account draft
        is never overwritten by the browser's copy."""
        adapter = self.served("explorer/draft.js")
        self.assertIn("if (importing) return importing", adapter)
        self.assertIn("clearLocal();                        // the account's draft wins",
                      adapter)

    def test_the_draft_api_still_round_trips_for_signed_in_visitors(self):
        """The import's server half: a straight PUT of the same payload
        shape the browser stores, into an empty account draft."""
        self.client.force_login(self.user)
        stored = {"assets": [{"symbol": "AAA", "weight": 0.6},
                             {"symbol": "BBB", "weight": 0.4}],
                  "updated_at": "2026-09-05T00:00:00.000Z"}
        self.assertEqual(self.client.get("/api/draft").json()["assets"], [])
        res = self.client.put("/api/draft", data=json.dumps(stored),
                              content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual([a["symbol"] for a in res.json()["assets"]], ["AAA", "BBB"])


@override_settings(RATELIMIT_ENABLE=True, CONDOR_RATE_LIMITS={
    "analyze": "2/m", "forecast": "2/m", "asset": "2/m", "login": "2/m",
    "signup": "2/m", "reset": "2/m"})
# django-ratelimit counts inside a wall-clock window, and a window that
# rolls over between two requests resets the count — a real 1-in-a-suite
# flake, not a real bug. Pin the window so these tests are about counting.
@patch("django_ratelimit.core._get_window", lambda value, period: 10 ** 9)
class RateLimitTests(TestCase):
    """Per-IP caps on the public compute endpoints (explorer.throttle).

    Explore is open to strangers, so nothing but these caps stands between
    one script and a $12/mo box's CPU and price-data quota. Limits are
    overridden down to 2/minute here; the production numbers live in
    settings.CONDOR_RATE_LIMITS."""

    def setUp(self):
        cache.clear()      # counters are cache state, shared across tests

    def tearDown(self):
        cache.clear()

    MIX = {"tickers": ["AAA", "BBB"], "years": 3, "method": "robust",
           "risk_free_rate": 0.04, "horizon_years": 2}

    def post(self, path, **extra):
        with patch("explorer.views.fetch_prices",
                   side_effect=ForecastApiTests.fake_prices):
            return self.client.post(path, data=json.dumps(self.MIX),
                                    content_type="application/json", **extra)

    def assert_limited(self, res):
        self.assertEqual(res.status_code, 429, res.content)
        self.assertIn("number crunching", res.json()["error"])

    # ------------------------------------------------------------ limits

    def test_analyze_is_capped(self):
        for _ in range(2):
            self.assertEqual(self.post("/api/analyze").status_code, 200)
        self.assert_limited(self.post("/api/analyze"))

    def test_forecast_is_capped(self):
        for _ in range(2):
            self.assertEqual(self.post("/api/forecast").status_code, 200)
        self.assert_limited(self.post("/api/forecast"))

    def test_requests_that_never_reach_the_view_cost_nothing(self):
        """The quota meters work. A GET to a POST-only endpoint earns a
        405 and does no work, so it must not spend anyone's budget."""
        for _ in range(5):
            self.assertEqual(self.client.get("/api/analyze").status_code, 405)
        for _ in range(2):
            self.assertEqual(self.post("/api/analyze").status_code, 200)
        self.assert_limited(self.post("/api/analyze"))

    def test_each_endpoint_has_its_own_bucket(self):
        """Burning through analyze must not lock someone out of forecast —
        they are different costs and different groups."""
        for _ in range(3):
            self.post("/api/analyze")
        self.assertEqual(self.post("/api/forecast").status_code, 200)

    def test_asset_info_is_capped(self):
        import datetime as dt

        import pandas as pd
        idx = pd.bdate_range(end=dt.date.today(), periods=400)
        store = AssetInfoApiTests.fake_store(
            {"AAPL": pd.Series(100.0, index=idx, dtype=float)})
        with store:
            for _ in range(2):
                self.assertEqual(
                    self.client.get("/api/asset?symbol=AAPL").status_code, 200)
            self.assert_limited(self.client.get("/api/asset?symbol=AAPL"))

    def test_the_login_form_is_capped(self):
        """Registration is closed, so an unlimited login form buys a
        stranger nothing but password guesses."""
        creds = {"username": "nobody", "password": "wrong"}
        for _ in range(2):
            self.assertEqual(self.client.post("/login", creds).status_code, 200)
        res = self.client.post("/login", creds)
        self.assertEqual(res.status_code, 429)
        self.assertContains(res, "Too many sign-in attempts", status_code=429)
        # reading the page is free — only attempts are counted
        self.assertEqual(self.client.get("/login").status_code, 200)

    # --------------------------------------------------------- the key fn

    def test_the_bucket_is_the_real_client_not_the_proxy(self):
        """On Fly every request's REMOTE_ADDR is the proxy. Keying on that
        would put the whole internet in one bucket, so one visitor's burst
        would throttle everybody — the bug this test exists to prevent."""
        for _ in range(3):
            self.post("/api/analyze", headers={"fly-client-ip": "203.0.113.7"})
        # a different visitor behind the same proxy is unaffected
        self.assertEqual(
            self.post("/api/analyze",
                      headers={"fly-client-ip": "203.0.113.9"}).status_code, 200)
        # ...and the one who burst through is still held
        self.assert_limited(
            self.post("/api/analyze", headers={"fly-client-ip": "203.0.113.7"}))

    def test_client_ip_prefers_fly_and_never_trusts_x_forwarded_for(self):
        from django.test import RequestFactory

        from explorer.throttle import client_ip
        rf = RequestFactory()

        req = rf.get("/", headers={"fly-client-ip": "203.0.113.7"},
                     REMOTE_ADDR="10.0.0.1")
        self.assertEqual(client_ip("g", req), "203.0.113.7")

        # X-Forwarded-For is client-suppliable: ignoring it is the point
        req = rf.get("/", headers={"x-forwarded-for": "9.9.9.9"},
                     REMOTE_ADDR="10.0.0.1")
        self.assertEqual(client_ip("g", req), "10.0.0.1")

        # off Fly (dev), REMOTE_ADDR is the real peer
        req = rf.get("/", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(client_ip("g", req), "127.0.0.1")

    def test_a_spoofed_forwarding_header_does_not_buy_a_fresh_bucket(self):
        for _ in range(3):
            self.post("/api/analyze")
        self.assert_limited(
            self.post("/api/analyze", headers={"x-forwarded-for": "9.9.9.9"}))

    def test_the_signup_form_is_capped(self):
        def body(n):  # distinct username/email so each call is its own signup
            return {
                "username": f"capped{n}", "email": f"capped{n}@example.com",
                "password1": "Correct-Horse-9", "password2": "Correct-Horse-9",
                "consent": "on", "website": "",
            }
        for n in range(2):
            self.assertEqual(self.client.post("/signup", body(n)).status_code, 200)
        res = self.client.post("/signup", body(99))
        self.assertEqual(res.status_code, 429)
        self.assertContains(res, "Too many signup attempts", status_code=429)
        # reading the page is free — only attempts are counted
        self.assertEqual(self.client.get("/signup").status_code, 200)

    def test_the_reset_form_is_capped(self):
        for _ in range(2):
            self.assertEqual(
                self.client.post("/password-reset/",
                                 {"email": "nobody@example.com"}).status_code, 302)
        res = self.client.post("/password-reset/", {"email": "nobody@example.com"})
        self.assertEqual(res.status_code, 429)
        self.assertEqual(self.client.get("/password-reset/").status_code, 200)


class SignupTests(TestCase):
    """Self-serve accounts: happy path, honeypot, consent, the inactive-user
    resend rule, case-insensitive email uniqueness, and send-failure
    rollback. `RATELIMIT_ENABLE` is off by default in tests (settings.py),
    so these post as often as a scenario needs."""

    VALID = {
        "username": "newuser", "email": "new@example.com",
        "password1": "Correct-Horse-42", "password2": "Correct-Horse-42",
        "consent": "on", "website": "",
    }

    @staticmethod
    def link_from(body):
        for line in body.splitlines():
            if line.startswith("http"):
                return line.strip()
        raise AssertionError(f"no link in email body: {body!r}")

    def test_happy_path_sends_one_email_and_activation_logs_in(self):
        res = self.client.post("/signup", self.VALID)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertContains(res, "new@example.com")
        user = User.objects.get(username="newuser")
        self.assertFalse(user.is_active)
        self.assertEqual(len(mail.outbox), 1)

        res = self.client.get(self.link_from(mail.outbox[0].body).replace(
            "http://testserver", ""), follow=True)
        self.assertRedirects(res, "/")
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(res.wsgi_request.user.is_authenticated)
        self.assertContains(res, "pretend money, go play")

    def test_garbage_token_shows_the_sorry_page_and_stays_inactive(self):
        self.client.post("/signup", self.VALID)
        user = User.objects.get(username="newuser")

        res = self.client.get("/activate/garbage/garbage-token")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "doesn't work")
        user.refresh_from_db()
        self.assertFalse(user.is_active)

        # well-formed uid, wrong token
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        res = self.client.get(f"/activate/{uid}/not-a-real-token")
        self.assertContains(res, "doesn't work")
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_used_link_cannot_be_replayed(self):
        self.client.post("/signup", self.VALID)
        link = self.link_from(mail.outbox[0].body).replace("http://testserver", "")
        self.client.get(link)  # first use: activates + logs in
        self.client.logout()
        res = self.client.get(link)  # replay
        self.assertContains(res, "doesn't work")

    def test_honeypot_pretends_success_and_creates_nothing(self):
        body = dict(self.VALID, website="http://spam.example")
        res = self.client.post("/signup", body)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, self.VALID["email"])
        self.assertFalse(User.objects.filter(username="newuser").exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_consent_is_required(self):
        body = {k: v for k, v in self.VALID.items() if k != "consent"}
        res = self.client.post("/signup", body)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(User.objects.filter(username="newuser").exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_email_uniqueness_is_case_insensitive_for_a_new_username(self):
        User.objects.create_user("existing", email="Taken@Example.com",
                                 password="x-not-secret-x", is_active=True)
        body = dict(self.VALID, username="different", email="taken@example.com")
        res = self.client.post("/signup", body)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "already registered")
        self.assertFalse(User.objects.filter(username="different").exists())

    def test_active_username_clash_is_a_form_error(self):
        User.objects.create_user("newuser", email="new@example.com",
                                 password="x-not-secret-x", is_active=True)
        res = self.client.post("/signup", self.VALID)
        self.assertContains(res, "already registered")
        self.assertEqual(len(mail.outbox), 0)

    def test_inactive_same_email_case_insensitive_retries_and_updates_password(self):
        self.client.post("/signup", self.VALID)
        user = User.objects.get(username="newuser")
        old_hash = user.password

        retry = dict(self.VALID, email=self.VALID["email"].upper(),
                    password1="Different-Horse-9", password2="Different-Horse-9")
        res = self.client.post("/signup", retry)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(User.objects.filter(username="newuser").count(), 1)
        user.refresh_from_db()
        self.assertNotEqual(user.password, old_hash)
        self.assertFalse(user.check_password(self.VALID["password1"]))
        self.assertTrue(user.check_password("Different-Horse-9"))
        self.assertEqual(len(mail.outbox), 2)

    def test_inactive_different_email_is_a_clash_not_a_retry(self):
        self.client.post("/signup", self.VALID)
        res = self.client.post(
            "/signup", dict(self.VALID, email="someoneelse@example.com"))
        self.assertContains(res, "already registered")
        self.assertEqual(len(mail.outbox), 1)  # only the first signup's

    def test_send_failure_creates_nothing(self):
        with patch("explorer.views.send_mail", side_effect=smtplib.SMTPException):
            res = self.client.post("/signup", self.VALID)
        self.assertEqual(res.status_code, 502)
        self.assertContains(res, "nothing was created", status_code=502)
        self.assertFalse(User.objects.filter(username="newuser").exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_send_failure_on_retry_leaves_old_password_working(self):
        self.client.post("/signup", self.VALID)
        user = User.objects.get(username="newuser")
        retry = dict(self.VALID, password1="Different-Horse-9",
                    password2="Different-Horse-9")
        with patch("explorer.views.send_mail", side_effect=smtplib.SMTPException):
            res = self.client.post("/signup", retry)
        self.assertEqual(res.status_code, 502)
        user.refresh_from_db()
        self.assertTrue(user.check_password(self.VALID["password1"]))
        self.assertFalse(user.check_password("Different-Horse-9"))


@override_settings(SIGNUPS_ENABLED=False)
class SignupsClosedTests(TestCase):
    """Prod-shaped settings with no SMTP configured: `/signup` refuses to
    mint accounts whose activation links would go to a log file."""

    def test_closed_page_and_no_creation(self):
        self.assertContains(self.client.get("/signup"), "closed")
        before = User.objects.count()
        self.client.post("/signup", SignupTests.VALID)
        self.assertEqual(User.objects.count(), before)
        self.assertEqual(len(mail.outbox), 0)

    def test_login_page_hides_the_invite(self):
        self.assertNotContains(self.client.get("/login"), "Create one")


class PasswordResetTests(TestCase):
    """Django's own four views, wired under /password-reset/…, with our
    templates. Don't-reveal-existence behaviour is Django's; not retested
    beyond confirming an unknown address still gets the same response."""

    def test_round_trip(self):
        User.objects.create_user("resetme", email="reset@example.com",
                                 password="Old-Horse-1", is_active=True)
        res = self.client.post("/password-reset/", {"email": "reset@example.com"})
        self.assertRedirects(res, "/password-reset/done/")
        self.assertEqual(len(mail.outbox), 1)

        link = re.search(r"http://testserver(\S+)", mail.outbox[0].body).group(1)
        res = self.client.get(link, follow=True)
        confirm_path = res.redirect_chain[-1][0]
        res = self.client.post(confirm_path, {
            "new_password1": "Brand-New-77", "new_password2": "Brand-New-77",
        }, follow=True)
        self.assertRedirects(res, "/password-reset/complete/")

        user = User.objects.get(username="resetme")
        self.assertFalse(user.check_password("Old-Horse-1"))
        self.assertTrue(user.check_password("Brand-New-77"))

    def test_unknown_email_does_not_reveal_existence(self):
        res = self.client.post("/password-reset/", {"email": "nobody@example.com"})
        self.assertRedirects(res, "/password-reset/done/")
        self.assertEqual(len(mail.outbox), 0)

    def test_login_page_always_shows_the_reset_link(self):
        self.assertContains(self.client.get("/login"), "Forgot password?")

    def test_garbage_confirm_link_shows_the_sorry_page(self):
        res = self.client.get("/password-reset/confirm/bad/bad-token/", follow=True)
        self.assertContains(res, "doesn't work")

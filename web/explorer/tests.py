"""Saved-portfolio persistence: CRUD, validation, sharing.

None of these hit the network — only the analyze flow fetches prices, and
that is not exercised here. `/p/<uuid>` renders the page, which normally
asks FRED for the risk-free rate, so that call is patched out.
"""

import json
import uuid
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

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

    def test_anonymous_page_redirects_to_login(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.url.startswith("/login"))

    def test_anonymous_api_gets_json_401(self):
        for call in (
            lambda: self.client.get("/api/portfolios"),
            lambda: self.client.post("/api/analyze", data="{}",
                                     content_type="application/json"),
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

    def test_requires_login(self):
        self.client.logout()
        res = self.client.post("/api/forecast", data="{}",
                               content_type="application/json")
        self.assertEqual(res.status_code, 401)


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

    def test_optimize_anonymous_redirects_to_login(self):
        res = self.client.get("/optimize")
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.url.startswith("/login"))

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

    def test_anonymous_gets_401(self):
        self.client.logout()
        self.assertEqual(self.client.get("/api/asset?symbol=AAPL").status_code, 401)

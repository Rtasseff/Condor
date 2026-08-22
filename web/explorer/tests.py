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

from explorer.models import Holding, SavedPortfolio


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

    def test_account_forecast_needs_holdings(self):
        self.api("post", "/api/account/events",
                 {"kind": "deposit", "date": "2026-01-05", "amount": 100})
        with self.patched():
            res = self.client.post("/api/account/forecast", data="{}",
                                   content_type="application/json")
        self.assertEqual(res.status_code, 400)

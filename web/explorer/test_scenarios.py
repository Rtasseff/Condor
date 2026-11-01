"""Scenarios and stability bands over HTTP.  No network: fetches are patched."""

import json
from unittest.mock import patch

from django.test import TestCase, override_settings

from explorer.tests import ForecastApiTests, fake_history

BODY = {"tickers": ["AAA", "BBB", "CCC"], "years": 3, "method": "normal",
        "risk_free_rate": 0.02}
SET = {
    "name": "Cautious",
    "prior": {"kind": "equilibrium", "reference": "AAA", "market_premium": None,
              "t0": 20, "views": []},
    "constraints": {"bounds": {"BBB": {"max": 0.4}}, "groups": []},
}


def call(client, url, body, history=fake_history):
    with patch("explorer.views.fetch_prices",
               side_effect=ForecastApiTests.fake_prices), \
         patch("explorer.views.risk_free_history", side_effect=history):
        return client.post(url, data=json.dumps(body),
                           content_type="application/json")


class ScenariosApiTests(TestCase):
    def analyze(self, extra=None):
        return call(self.client, "/api/analyze", {**BODY, **(extra or {})})

    def test_scenarios_added_and_existing_keys_unchanged(self):
        got = self.analyze().json()
        sc = got.pop("scenarios")
        self.assertEqual(sc["basis"], "fixed_weights_daily")
        names = [w["name"] for w in sc["portfolio"]]
        self.assertEqual(names, ["2008 financial crisis", "2018 Q4 selloff",
                                 "2020 Covid crash", "2022 inflation shock"])
        covid = sc["portfolio"][2]
        self.assertTrue(covid["covered"])      # fake data spans 2020-01..2022-10
        self.assertIsNotNone(covid["ret"])
        self.assertFalse(sc["portfolio"][0]["covered"])
        self.assertIsNone(sc["portfolio"][0]["ret"])
        self.assertEqual(len(sc["tangency"]), 4)
        self.assertNotIn("scenarios", got["frontier"][0])
        self.assertEqual(got["portfolio"]["weights"].keys(), {"AAA", "BBB", "CCC"})

    def test_custom_windows(self):
        w = [{"name": "Spring", "start": "2020-03-02", "end": "2020-06-30"}]
        sc = self.analyze({"scenario_windows": w}).json()["scenarios"]
        self.assertEqual([x["name"] for x in sc["portfolio"]], ["Spring"])

    def test_windows_reach_the_assumed_copy(self):
        w = [{"name": "Spring", "start": "2020-03-02", "end": "2020-06-30"}]
        got = self.analyze({"scenario_windows": w, "assumptions": SET}).json()
        self.assertEqual([x["name"] for x in got["assumed"]["scenarios"]["portfolio"]],
                         ["Spring"])

    def test_window_with_no_trading_days_is_flagged(self):
        w = [{"name": "Weekend", "start": "2020-03-07", "end": "2020-03-08"}]
        row = self.analyze({"scenario_windows": w}).json()["scenarios"]["portfolio"][0]
        self.assertFalse(row["covered"])
        self.assertEqual(row["reason"], "no_trading_days")

    def test_bad_windows_are_400(self):
        ok = {"name": "x", "start": "2020-03-02", "end": "2020-06-30"}
        bad = [
            "nope", [], [ok] * 6, [{**ok, "start": "2020-07-01"}],
            [{**ok, "start": "2020-06-30"}], [{**ok, "name": ""}],
            [{**ok, "end": "not a date"}], [{**ok, "end": None}], [5],
            [{**ok, "start": "0001-01-01"}],
        ]
        for w in bad:
            res = self.analyze({"scenario_windows": w})
            self.assertEqual(res.status_code, 400, (w, res.content))
            self.assertIn("error", res.json())
        self.assertEqual(self.analyze({"scenario_windows": [ok] * 5}).status_code, 200)


class StabilityApiTests(TestCase):
    def stab(self, extra=None, **kw):
        return call(self.client, "/api/stability", {**BODY, "n": 6, **(extra or {})}, **kw)

    def test_anonymous_works_and_shape(self):
        res = self.stab()
        self.assertEqual(res.status_code, 200, res.content)
        got = res.json()
        self.assertEqual((got["n"], got["block"], got["seed"]), (6, 21, 0))
        self.assertEqual(set(got["assets"]), {"AAA", "BBB", "CCC"})
        self.assertEqual(set(got["assets"]["AAA"]),
                         {"p10", "p50", "p90", "held_share"})
        self.assertEqual(res.json(), self.stab().json())   # reproducible

    def test_under_assumptions(self):
        res = self.stab({"assumptions": SET})
        self.assertEqual(res.status_code, 200, res.content)
        got = res.json()
        self.assertEqual(got["name"], "Cautious")
        if got["n_failed"] < got["n"]:
            self.assertLessEqual(got["assets"]["BBB"]["p90"], 0.4 + 1e-6)

    def test_n_cap_and_validation(self):
        for n in (0, 301, 1000, -1, "many", 2.5, True, None):
            res = self.stab({"n": n})
            self.assertEqual(res.status_code, 400, (n, res.content))
        self.assertEqual(self.stab({"n": 1}).status_code, 200)
        # default when omitted is 100: check without paying for it
        with patch("condor.AssetSet.stability",
                   return_value={"n": 100}) as st:
            call(self.client, "/api/stability", BODY)
            self.assertEqual(st.call_args.kwargs["n"], 100)
            call(self.client, "/api/stability", {**BODY, "n": 300})
            self.assertEqual(st.call_args.kwargs["n"], 300)

    def test_non_finite_n_is_400_not_a_crash(self):
        for raw in ("NaN", "Infinity", "-Infinity", "1e999"):
            with patch("explorer.views.fetch_prices",
                       side_effect=ForecastApiTests.fake_prices), \
                 patch("explorer.views.risk_free_history",
                       side_effect=fake_history):
                body = json.dumps({**BODY}).rstrip("}") + f', "n": {raw}}}'
                res = self.client.post("/api/stability", data=body,
                                       content_type="application/json")
            self.assertEqual(res.status_code, 400, (raw, res.content))
            self.assertIn("error", res.json())

    def test_infeasible_limits_say_so(self):
        bad = {**SET, "constraints": {"bounds": {
            "AAA": {"min": 0.7}, "BBB": {"min": 0.7}}, "groups": []}}
        res = self.stab({"assumptions": bad})
        self.assertEqual(res.status_code, 400, res.content)
        self.assertNotIn("risk-free", res.json()["error"])

    def test_bad_input(self):
        for patch_ in ({"tickers": []}, {"tickers": ["AAA"]},
                       {"tickers": ["no way!"]}, {"years": 99},
                       {"assumptions": {"name": ""}}):
            self.assertEqual(self.stab(patch_).status_code, 400, patch_)
        res = self.stab({"assumptions": SET}, history=lambda *a, **k: 1 / 0)
        self.assertEqual(res.status_code, 400)       # needs T-bill history

    def test_get_not_allowed_and_nothing_stored(self):
        self.assertEqual(self.client.get("/api/stability").status_code, 405)

    @override_settings(RATELIMIT_ENABLE=True,
                       CONDOR_RATE_LIMITS={"stability": "2/m"})
    def test_rate_limited(self):
        for _ in range(2):
            self.assertEqual(self.stab().status_code, 200)
        self.assertEqual(self.stab().status_code, 429)


class OptimizePageTests(TestCase):
    def test_new_cards_are_on_the_page(self):
        from explorer.tests import make_user
        from explorer.models import DraftPortfolio
        user = make_user("rt")
        self.client.force_login(user)
        draft = DraftPortfolio.objects.create(owner=user)
        draft.set_assets([("AAA", 1.0)])
        draft.save()
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            res = self.client.get("/optimize")
        self.assertContains(res, "How it would have done")
        self.assertContains(res, "How stable is the best mix?")
        self.assertContains(res, "Re-running the optimizer on reshuffled")

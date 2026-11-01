"""Assumptions mode over HTTP: saved sets (CRUD, owner scope) and
/api/analyze with an `assumptions` copy.  No network: fetches are patched."""

import copy
import json
from unittest.mock import patch

from django.test import TestCase

from explorer.models import AssumptionSet
from explorer.tests import ForecastApiTests, fake_history, make_user

SET = {
    "name": "Cautious",
    "prior": {"kind": "equilibrium", "reference": "VT", "market_premium": None,
              "t0": 20, "views": []},
    "constraints": {"bounds": {"AAA": {"max": 0.4}}, "groups": []},
}
BODY = {"tickers": ["AAA", "BBB", "CCC"], "years": 3, "method": "robust",
        "risk_free_rate": 0.04}


def post(client, url, body, method="post"):
    return getattr(client, method)(url, data=json.dumps(body),
                                   content_type="application/json")


class AssumptionCrudTests(TestCase):
    def setUp(self):
        self.rt = make_user("rt")
        self.bob = make_user("bob")
        self.client.force_login(self.rt)

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get("/api/assumptions").status_code, 401)
        self.assertEqual(post(self.client, "/api/assumptions", SET).status_code, 401)

    def test_create_list_get_update_delete(self):
        res = post(self.client, "/api/assumptions", SET)
        self.assertEqual(res.status_code, 201, res.content)
        pid = res.json()["id"]
        self.assertEqual(res.json()["assumptions"], SET)
        rows = self.client.get("/api/assumptions").json()
        self.assertEqual([r["name"] for r in rows], ["Cautious"])
        self.assertEqual(self.client.get(f"/api/assumptions/{pid}").json()
                         ["assumptions"], SET)
        new = copy.deepcopy(SET)
        new["name"] = "Bolder"
        new["constraints"]["bounds"]["AAA"]["max"] = 0.6
        res = post(self.client, f"/api/assumptions/{pid}", new, "put")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(AssumptionSet.objects.get(pk=pid).name, "Bolder")
        self.assertEqual(AssumptionSet.objects.get(pk=pid).payload, new)
        res = self.client.delete(f"/api/assumptions/{pid}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(AssumptionSet.objects.count(), 0)

    def test_validation_errors_name_the_field(self):
        bad = copy.deepcopy(SET)
        bad["constraints"]["bounds"]["AAA"]["max"] = 3
        res = post(self.client, "/api/assumptions", bad)
        self.assertEqual(res.status_code, 400)
        self.assertIn("bounds.AAA.max", res.json()["error"])
        self.assertEqual(AssumptionSet.objects.count(), 0)

    def test_owner_scoped_foreign_id_is_404(self):
        row = AssumptionSet.objects.create(owner=self.bob, name="Bob's",
                                           payload=SET)
        self.assertEqual(self.client.get("/api/assumptions").json(), [])
        for method, kw in (("get", {}), ("delete", {})):
            res = getattr(self.client, method)(f"/api/assumptions/{row.id}")
            self.assertEqual(res.status_code, 404)
        res = post(self.client, f"/api/assumptions/{row.id}", SET, "put")
        self.assertEqual(res.status_code, 404)
        unknown = self.client.get(
            "/api/assumptions/00000000-0000-0000-0000-000000000000")
        self.assertEqual(unknown.status_code, 404)
        self.assertTrue(AssumptionSet.objects.filter(pk=row.id).exists())

    def test_limit_of_50_sets(self):
        for i in range(50):
            AssumptionSet.objects.create(owner=self.rt, name=f"s{i}", payload=SET)
        res = post(self.client, "/api/assumptions", SET)
        self.assertEqual(res.status_code, 400)
        self.assertIn("50", res.json()["error"])
        # another user is unaffected
        self.client.force_login(self.bob)
        self.assertEqual(post(self.client, "/api/assumptions", SET).status_code, 201)


class AnalyzeAssumedTests(TestCase):
    def analyze(self, body, history=fake_history, fetch=None):
        fetch = fetch or ForecastApiTests.fake_prices
        with patch("explorer.views.fetch_prices", side_effect=fetch) as f, \
             patch("explorer.views.risk_free_history", side_effect=history):
            res = post(self.client, "/api/analyze", body)
        self.fetch = f
        return res

    def test_absent_unless_asked_and_history_unchanged(self):
        plain = self.analyze(BODY)
        self.assertEqual(plain.status_code, 200)
        self.assertNotIn("assumed", plain.json())
        asked = self.analyze({**BODY, "assumptions": SET})
        self.assertEqual(asked.status_code, 200, asked.content)
        got = asked.json()
        assumed = got.pop("assumed")
        self.assertEqual(got, plain.json())        # history is untouched
        self.assertNotIn("error", assumed)
        self.assertEqual(assumed["name"], "Cautious")
        self.assertEqual(assumed["assumptions"], SET)
        note = assumed["prior_note"]
        self.assertEqual(note["reference"], "VT")
        self.assertEqual(note["t0"], 20)
        self.assertAlmostEqual(note["t_years"], 2.89, delta=0.02)
        self.assertLess(note["t_effective"], note["t_years"])  # robust
        self.assertLessEqual(assumed["tangency"]["weights"].get("AAA", 0),
                             0.4 + 1e-6)
        self.assertEqual(set(assumed["gaps"]),
                         {"sharpe_gap", "return_gap", "risk_gap", "at_risk",
                          "at_return", "violations", "sharpe_gap_reason",
                          "return_gap_reason", "risk_gap_reason"})
        self.assertEqual(assumed["constraints"]["bounds"],
                         {"AAA": {"min": 0.0, "max": 0.4}})

    def test_anonymous_works_and_reference_fetched_separately(self):
        res = self.analyze({**BODY, "assumptions": SET})
        self.assertEqual(res.status_code, 200)
        calls = [c.args[0] for c in self.fetch.call_args_list]
        self.assertEqual(calls, [BODY["tickers"], ["VT"]])
        # the proxy must not shorten the analysis window
        self.assertEqual(res.json()["n_days"], res.json()["assumed"]["n_days"])

    def test_reference_in_tickers_is_not_fetched(self):
        s = copy.deepcopy(SET)
        s["prior"]["reference"] = "BBB"
        res = self.analyze({**BODY, "assumptions": s})
        self.assertNotIn("error", res.json()["assumed"])
        self.assertEqual(len(self.fetch.call_args_list), 1)

    def test_failures_become_assumed_error_history_intact(self):
        plain = self.analyze(BODY).json()
        cases = {
            "can't all hold": {"constraints": {"bounds": {
                "AAA": {"min": 0.6}, "BBB": {"min": 0.6}}}},
            "name": {"name": ""},
            "prior.t0": {"prior": {"t0": -1}},
        }
        for needle, patch_ in cases.items():
            res = self.analyze({**BODY, "assumptions": {**SET, **patch_}})
            self.assertEqual(res.status_code, 200)
            got = res.json()
            self.assertIn(needle, got["assumed"]["error"])
            self.assertEqual(list(got["assumed"]), ["error"])
            got.pop("assumed")
            self.assertEqual(got, plain)

    def test_premium_false_and_no_history_are_errors(self):
        res = self.analyze({**BODY, "premium": False, "assumptions": SET})
        self.assertIn("T-bill", res.json()["assumed"]["error"])
        self.assertTrue(res.json()["tickers"])

        def down(*a, **k):
            raise OSError("FRED down")
        res = self.analyze({**BODY, "assumptions": SET}, history=down)
        self.assertIn("T-bill", res.json()["assumed"]["error"])

    def test_optimizer_error_becomes_assumed_error(self):
        from pypfopt.exceptions import OptimizationError
        with patch("condor.model._constrained_tangency",
                   side_effect=OptimizationError("nope")):
            res = self.analyze({**BODY, "assumptions": SET})
        self.assertEqual(res.status_code, 200)
        self.assertIn("optimizer couldn't solve", res.json()["assumed"]["error"])
        self.assertIn("tangency", res.json())

    def test_short_window_with_a_view_works(self):
        s = copy.deepcopy(SET)
        s["prior"]["views"] = [{"ticker": "AAA", "ret": 0.09, "sd": 0.04}]
        s["prior"]["t0"] = 0
        res = self.analyze({**BODY, "assumptions": s})
        self.assertNotIn("error", res.json()["assumed"])

    def test_proxy_fetch_failure(self):
        from condor import DataFetchError

        def fetch(tickers, years=10, **kw):
            if tickers == ["VT"]:
                raise DataFetchError("no such ticker")
            return ForecastApiTests.fake_prices(tickers, years)
        res = self.analyze({**BODY, "assumptions": SET}, fetch=fetch)
        self.assertIn("market proxy VT", res.json()["assumed"]["error"])

    def test_history_only_kind_needs_no_proxy(self):
        s = copy.deepcopy(SET)
        s["prior"]["kind"] = "history"
        res = self.analyze({**BODY, "assumptions": s})
        self.assertNotIn("error", res.json()["assumed"])
        self.assertEqual(len(self.fetch.call_args_list), 1)

    def test_copy_semantics_saved_edit_does_not_move_a_response(self):
        user = make_user("rt")
        self.client.force_login(user)
        row = AssumptionSet.objects.create(owner=user, name="Cautious",
                                           payload=SET)
        first = self.analyze({**BODY, "assumptions": row.payload}).json()
        row.payload = {**SET, "constraints": {"bounds": {"AAA": {"max": 0.1}}}}
        row.save()
        again = self.analyze({**BODY, "assumptions": SET}).json()
        self.assertEqual(first["assumed"], again["assumed"])
        edited = self.analyze({**BODY, "assumptions": row.payload}).json()
        self.assertNotEqual(first["assumed"]["tangency"],
                            edited["assumed"]["tangency"])


class OptimizePageTests(TestCase):
    """The card is on the workbench, wired to its script; signed-out visitors
    get the editor and an invitation to sign in instead of the save controls."""

    def page(self, user=None):
        from explorer.models import DraftPortfolio
        if user:
            self.client.force_login(user)
            draft = DraftPortfolio.objects.create(owner=user)
            draft.set_assets([("AAA", 0.6), ("BBB", 0.4)])
            draft.save()
        with patch("explorer.views.risk_free_rate", side_effect=OSError):
            return self.client.get("/optimize").content.decode()

    def test_signed_in(self):
        html = self.page(make_user())
        for want in ("Under my assumptions", 'id="chart-assumed"',
                     'id="asmsave"', "explorer/assumptions.js",
                     "History alone mostly picks whatever won lately"):
            self.assertIn(want, html)
        self.assertLess(html.index("explorer/app.js"),
                        html.index("explorer/assumptions.js"))

    def test_signed_out_gets_editor_and_sign_in_invite(self):
        html = self.page()
        self.assertIn('id="asmcard"', html)
        self.assertNotIn('id="asmsave"', html)
        self.assertIn("to save your sets", html)

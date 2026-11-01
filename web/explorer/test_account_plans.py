"""ADR 0007: pay-in plans, rules and XIRR on mirror accounts. Fixture:
tests/fixtures/payin_sample_* (account broker_b, numbers in the brief)."""

import io
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from explorer.models import Account, AccountRule, PayInPlan

FIX = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
F = {k: str(FIX / f"payin_sample_{k}.csv")
     for k in ("ledger", "targets", "payin", "rules", "prices")}
TODAY = "2027-04-05"


def run(*args, **kw):
    out, err = io.StringIO(), io.StringIO()
    call_command(*args, stdout=out, stderr=err, **kw)
    return out.getvalue(), err.getvalue()


def do_import(user="rt", ledger=None, targets=F["targets"], payin=F["payin"],
              rules=F["rules"], today=TODAY):
    args = ["import_ledger", ledger or F["ledger"], "--user", user,
            "--replace", "--today", today]
    for flag, path in (("--targets", targets), ("--payin", payin),
                       ("--rules", rules)):
        if path:
            args += [flag, path]
    return run(*args)


def tmp(text):
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
    f.write(text)
    f.close()
    return f.name


class ImportPlanTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rt", password="pw")

    def test_five_fixture_files_import_together(self):
        out, _ = do_import()
        self.assertIn("pay-in 4 tranches", out)
        self.assertIn("rules 3", out)
        acc = Account.objects.get(label="broker_b")
        self.assertTrue(acc.mirror)
        self.assertEqual(acc.currency, "USD")
        self.assertEqual(
            sorted(acc.target_specs()),
            sorted([("LMP", 0.2, "lump", "lump"),
                    ("RES", 0.1, "reservoir", "reservoir"),
                    ("AAA", 0.3, "dca", "aaa"), ("BBB", 0.2, "dca", "bbb"),
                    ("CCC", 0.15, "dca", "sleeve"),
                    ("DDD", 0.05, "dca", "sleeve")]))
        plan = acc.payin
        self.assertEqual((plan.total, plan.dates), (
            1000.0, ["2027-01-04", "2027-02-01", "2027-03-01", "2027-04-05"]))
        r = acc.rules.get(rule_id="ccc_below_cost")
        self.assertEqual((r.rule, r.ticker, r.threshold, r.action,
                          r.tranches, r.targets),
                         ("below_avg_cost", "CCC", 20.0, "accelerate", 1,
                          "CCC DDD"))
        self.assertIsNone(acc.rules.get(rule_id="drift").tranches)

    def test_v1_three_column_targets_still_import(self):
        path = tmp("account,ticker,weight\nbroker_b,AAA,0.3\n")
        out, _ = do_import(targets=path, payin=None, rules=None)
        acc = Account.objects.get(label="broker_b")
        self.assertEqual(acc.target_specs(), [("AAA", 0.3, "", "aaa")])
        self.assertNotIn("pay-in", out)

    def test_reimport_replaces_and_no_rows_clears(self):
        do_import()
        do_import()
        self.assertEqual(PayInPlan.objects.count(), 1)
        self.assertEqual(AccountRule.objects.count(), 3)
        empty_p = tmp("account,total,date\n")
        empty_r = tmp("account,id,rule,ticker,threshold,action,tranches,target\n")
        do_import(payin=empty_p, rules=empty_r)
        self.assertEqual(PayInPlan.objects.count(), 0)
        self.assertEqual(AccountRule.objects.count(), 0)

    def test_omitting_the_flags_keeps_the_stored_plan(self):
        do_import()
        do_import(targets=None, payin=None, rules=None)
        self.assertEqual(PayInPlan.objects.count(), 1)
        self.assertEqual(AccountRule.objects.count(), 3)

    def _refused(self, text, **kw):
        n = (Account.objects.count(), PayInPlan.objects.count(),
             AccountRule.objects.count())
        with self.assertRaises(CommandError) as e:
            do_import(**kw)
        self.assertEqual(n, (Account.objects.count(),
                             PayInPlan.objects.count(),
                             AccountRule.objects.count()))
        self.assertIn(text, str(e.exception) + "")
        return e

    def test_payin_for_account_not_in_ledger(self):
        self._refused("pay-in for accounts not in the ledger", payin=tmp(
            "account,total,date\nnope,100,2027-01-04\n"))

    def test_rules_for_account_not_in_ledger(self):
        self._refused("rules for accounts not in the ledger", rules=tmp(
            "account,id,rule,ticker,threshold,action,tranches,target\n"
            "nope,d,drift,,5,alert,,\n"))

    def test_payin_needs_a_dca_target(self):
        self._refused("nothing written", targets=tmp(
            "account,ticker,weight,timing,line\nbroker_b,AAA,0.3,,\n"))

    def test_rule_target_must_be_a_dca_target(self):
        self._refused("nothing written", rules=tmp(
            "account,id,rule,ticker,threshold,action,tranches,target\n"
            "broker_b,x,below_avg_cost,CCC,20,accelerate,1,RES\n"))

    def test_second_reservoir_is_a_format_error(self):
        self._refused("nothing written", targets=tmp(
            "account,ticker,weight,timing,line\n"
            "broker_b,AAA,0.3,dca,\nbroker_b,RES,0.1,reservoir,\n"
            "broker_b,LMP,0.1,reservoir,\n"))

    def test_payin_judged_against_stored_targets_when_none_given(self):
        do_import(targets=None, payin=None, rules=None)   # no targets stored
        self._refused("nothing written", targets=None)


# ------------------------------------------------------------------ web

import datetime as dt                                  # noqa: E402
from unittest.mock import patch                        # noqa: E402

import pandas as pd                                    # noqa: E402

from condor import payin as eng_payin                  # noqa: E402
from explorer.models import AccountEvent               # noqa: E402

PX = pd.read_csv(F["prices"], parse_dates=["date"]).pivot(
    index="date", columns="ticker", values="close")
D1, T2, T3, T4 = "2027-01-04", "2027-02-01", "2027-03-01", "2027-04-05"


class PlanWebBase(TestCase):
    """Imports the fixture, then rewinds the mirror to a given day."""

    def setUp(self):
        self.user = User.objects.create_user("rt", password="pw")
        self.client.force_login(self.user)
        do_import()
        self.acc = Account.objects.get(label="broker_b")
        self.q = f"?account={self.acc.id}"
        self.extra = {}

    def at(self, day, before=False, deposit_only=False):
        """Clock and prices at `day`; the ledger as of that day (rows
        dated before it, when `before`)."""
        cut = AccountEvent.objects.filter(account=self.acc)
        (cut.filter(date__gte=day) if before else cut.filter(date__gt=day)
         ).delete()
        if deposit_only:
            cut.exclude(kind="deposit").delete()
        self.day = day
        return self

    def get(self, path, expect=200, **params):
        clock = dt.date.fromisoformat(self.day)
        px = PX.loc[:pd.Timestamp(self.day)]
        extra = self.extra

        def fake(tickers, start):
            return pd.DataFrame({t: extra[t] if t in extra
                                 else px[t].dropna() for t in tickers})
        qs = self.q + "".join(f"&{k}={v}" for k, v in params.items())
        with patch("explorer.account._today", return_value=clock), \
             patch("explorer.account._close_history", side_effect=fake):
            res = self.client.get(path + qs)
        self.assertEqual(res.status_code, expect, res.content)
        return res.json()


class PayloadTests(PlanWebBase):
    def test_t2_payload_keys_and_values(self):
        j = self.at(T2, before=True).get("/api/account")
        p = j["payin"]
        self.assertEqual((p["total"], p["n"], p["k_due"], p["next_date"],
                          p["complete"], p["reserve"]),
                         (1000, 4, 2, "2027-03-01", False, 100))
        self.assertEqual(p["budget"], 511.22)
        rows = {r["line"]: r for r in p["rows"]}
        self.assertEqual(rows["aaa"]["bought"], 80)
        self.assertEqual(rows["sleeve"]["tickers"], ["CCC", "DDD"])
        self.assertEqual(rows["sleeve"]["pct"], 25.0)
        self.assertEqual(rows["aaa"]["scheduled"], 150)
        self.assertIsNone(rows["reservoir"]["scheduled"])
        self.assertEqual(set(rows["aaa"]), {
            "line", "tickers", "timing", "plan", "bought", "pct",
            "scheduled"})
        # the panel is the engine's progress table
        want = eng_payin.progress(
            eng_payin.PayInPlan.build(
                1000, [dt.date.fromisoformat(d) for d in
                       ("2027-01-04", "2027-02-01", "2027-03-01",
                        "2027-04-05")],
                self.acc.target_specs()),
            {"LMP": 200, "AAA": 80, "BBB": 60, "CCC": 36, "DDD": 14,
             "RES": 610}, T2)
        for line, r in want.iterrows():
            self.assertAlmostEqual(rows[line]["pct"], r["pct"], 1)
        self.assertIsNone(j["xirr"])                 # 28 days
        self.assertNotIn("combined", j)
        self.assertTrue(all(k in j for k in (
            "twr", "positions", "series", "events", "schedule")))

    def test_rules_in_the_payload(self):
        j = self.at(T2, before=True).get("/api/account")
        rules = {r["id"]: r for r in j["rules"]}
        self.assertEqual(set(rules), {"idx_drawdown", "ccc_below_cost",
                                      "drift"})
        c = rules["ccc_below_cost"]
        self.assertTrue(c["fired"])
        self.assertEqual(c["measured"], 25.0)
        self.assertEqual(c["targets"], ["CCC", "DDD"])
        self.assertIn("CCC more than 20% below average cost", c["text"])
        i = rules["idx_drawdown"]
        self.assertEqual((i["measured"], i["fired"]), (6.0, False))
        d = rules["drift"]
        self.assertTrue(d["muted"] and not d["fired"])     # mid-pay-in

    def test_xirr_and_complete_after_the_last_tranche(self):
        j = self.at(T4).get("/api/account")
        self.assertTrue(j["payin"]["complete"])
        self.assertIsNone(j["payin"]["next_date"])
        self.assertEqual(j["total_value"], 1049.28)
        self.assertIsNotNone(j["xirr"])          # 91 days of history
        d = {r["id"]: r for r in j["rules"]}["drift"]
        self.assertFalse(d["muted"])
        self.assertFalse(d["fired"])

    def test_missing_index_leaves_the_rule_unmeasured(self):
        self.extra = {}
        self.at(T2, before=True)
        clock = dt.date(2027, 2, 1)
        px = PX.loc[:pd.Timestamp(T2)]

        def fake(tickers, start):
            return pd.DataFrame({t: px[t].dropna() for t in tickers
                                 if t != "^IDX"}) if "^IDX" not in tickers \
                else (_ for _ in ()).throw(KeyError("^IDX"))
        with patch("explorer.account._today", return_value=clock), \
             patch("explorer.account._close_history", side_effect=fake):
            j = self.client.get("/api/account" + self.q).json()
        i = {r["id"]: r for r in j["rules"]}["idx_drawdown"]
        self.assertIsNone(i["measured"])
        self.assertFalse(i["fired"])

    def test_account_without_plan_has_null_payin_and_no_rules(self):
        manual = Account.objects.create(owner=self.user, name="m")
        self.day = T2
        self.q = f"?account={manual.id}"
        j = self.get("/api/account")
        self.assertIsNone(j["payin"])
        self.assertEqual(j["rules"], [])
        self.assertIsNone(j["xirr"])
        self.assertNotIn("combined", j)


class TrancheEndpointTests(PlanWebBase):
    def test_day_one_lump_first_then_tranche_then_reservoir(self):
        j = self.at(D1, deposit_only=True).get("/api/account/tranche")
        self.assertEqual((j["through"], j["n"], j["applied_rules"]),
                         (1, 4, []))
        self.assertEqual((j["cash"], j["reserve"], j["budget"]),
                         (1000, 300, 700))
        o = j["orders"]
        self.assertEqual([x["ticker"] for x in o],
                         ["LMP", "AAA", "BBB", "CCC", "DDD"])
        self.assertEqual(o[0]["timing"], "lump")
        self.assertEqual([x["qty"] for x in o], [4, 2, 2, 3, 2])
        self.assertEqual([x["amount"] for x in o], [200, 80, 60, 36, 14])
        self.assertEqual(o[1]["timing"], "dca")
        self.assertEqual(j["reservoir_trade"], {
            "side": "BUY", "ticker": "RES", "qty": 61, "price": 10.0,
            "amount": 610.0})

    def test_t2_list_and_reservoir_sale(self):
        j = self.at(T2, before=True).get("/api/account/tranche")
        self.assertEqual(j["through"], 2)
        self.assertEqual(j["budget"], 511.22)
        self.assertEqual([x["qty"] for x in j["orders"]], [2, 1, 4, 2])
        self.assertEqual(sum(x["amount"] for x in j["orders"]), 165)
        self.assertEqual(j["reservoir_trade"]["side"], "SELL")
        self.assertEqual(j["reservoir_trade"]["qty"], 17)
        self.assertEqual(set(j["orders"][0]), {
            "ticker", "timing", "due", "qty", "price", "amount", "note"})

    def test_t2_with_rules_applied(self):
        j = self.at(T2, before=True).get("/api/account/tranche",
                                         apply_rules=1)
        self.assertEqual(j["applied_rules"], ["ccc_below_cost"])
        by = {x["ticker"]: x for x in j["orders"]}
        self.assertEqual((by["CCC"]["qty"], by["CCC"]["amount"]), (9, 81))
        self.assertEqual((by["DDD"]["qty"], by["DDD"]["amount"]), (3, 21))
        self.assertEqual(j["reservoir_trade"]["qty"], 22)

    def test_t3_drawdown_caps_trims_and_sells(self):
        j = self.at(T3, before=True).get("/api/account/tranche",
                                         apply_rules=1)
        self.assertEqual(j["applied_rules"], ["idx_drawdown"])
        self.assertEqual(j["through"], 4)
        self.assertEqual(j["budget"], 346.66)
        by = {x["ticker"]: x for x in j["orders"]}
        self.assertEqual([by[t]["qty"] for t in ("AAA", "BBB", "CCC", "DDD")],
                         [3, 2, 8, 3])
        self.assertIn("trimmed", by["BBB"]["note"])
        self.assertEqual(j["reservoir_trade"]["qty"], 32)
        plain = self.get("/api/account/tranche")
        self.assertEqual((plain["through"], plain["applied_rules"]),
                         (3, []))

    def test_explicit_through_and_validation(self):
        self.at(T2, before=True)
        self.assertEqual(self.get("/api/account/tranche", through=3)[
            "through"], 3)
        for bad in ("0", "5", "x"):
            r = self.get("/api/account/tranche", expect=400, through=bad)
            self.assertIn("through", r["error"])

    def test_t4_nothing_to_buy(self):
        j = self.at(T4).get("/api/account/tranche")
        self.assertEqual(j["through"], 4)
        self.assertEqual(sum(x["qty"] for x in j["orders"]), 0)
        self.assertEqual(j["budget"], 29.78)
        self.assertIsNone(j["reservoir_trade"])

    def test_list_equals_the_engine(self):
        j = self.at(T2, before=True).get("/api/account/tranche")
        plan = eng_payin.PayInPlan.build(
            1000, [dt.date.fromisoformat(d) for d in
                   ("2027-01-04", "2027-02-01", "2027-03-01", "2027-04-05")],
            self.acc.target_specs())
        bought = {"LMP": 200, "AAA": 80, "BBB": 60, "CCC": 36, "DDD": 14,
                  "RES": 610}
        want = eng_payin.tranche_orders(
            plan, bought, PX.loc[pd.Timestamp(T2)], 2, budget=511.22)
        self.assertEqual([x["qty"] for x in j["orders"]],
                         want["qty"].tolist())
        self.assertEqual([x["due"] for x in j["orders"]],
                         [round(v, 2) for v in want["due"]])

    def test_account_without_a_plan_is_a_400(self):
        PayInPlan.objects.all().delete()
        r = self.at(T2).get("/api/account/tranche", expect=400)
        self.assertIn("no pay-in plan", r["error"])

    def test_foreign_account_is_404(self):
        other = User.objects.create_user("x", password="pw")
        self.client.force_login(other)
        self.day = T2
        self.get("/api/account/tranche", expect=404)

    def test_mirror_stays_read_only(self):
        self.at(T2)
        before = (AccountEvent.objects.count(), PayInPlan.objects.count(),
                  AccountRule.objects.count())
        for method, url, body in [
                ("post", "/api/account/events", {"kind": "deposit",
                                                  "amount": 5}),
                ("post", "/api/account/target", {"weights": {"AAA": 0.5}}),
                ("post", "/api/account/schedule", {"amount": 5}),
                ("post", "/api/account/tranche", {}),
                ("delete", "/api/account/tranche", None)]:
            kw = {"content_type": "application/json"}
            if body is not None:
                kw["data"] = __import__("json").dumps(body)
            res = getattr(self.client, method)(url + self.q, **kw)
            self.assertIn(res.status_code, (403, 405), url)
        self.assertEqual(before, (AccountEvent.objects.count(),
                                  PayInPlan.objects.count(),
                                  AccountRule.objects.count()))


class CombinedTests(PlanWebBase):
    def setUp(self):
        super().setUp()
        eur = Account.objects.create(owner=self.user, label="tesoro",
                                     name="tesoro", currency="EUR",
                                     mirror=True)
        AccountEvent.objects.create(account=eur, date="2027-01-04",
                                    kind="deposit", amount=800)
        self.at(T4)

    def test_both_totals_and_the_fx_rate(self):
        fx = pd.Series([1.2, 1.25], index=pd.to_datetime(
            ["2027-04-02", "2027-04-05"]))
        self.extra = {"EURUSD=X": fx}
        c = self.get("/api/account")["combined"]
        self.assertEqual(c["USD"], round(1049.28 + 800 * 1.25, 2))
        self.assertEqual(c["EUR"], round(800 + 1049.28 / 1.25, 2))
        self.assertEqual(c["fx"], {"pair": "EURUSD", "rate": 1.25,
                                   "as_of": "2027-04-05"})

    def test_fx_failure_omits_the_key_and_keeps_the_page(self):
        j = self.get("/api/account")       # no EURUSD=X in the fake: KeyError
        self.assertNotIn("combined", j)
        self.assertIn("payin", j)

    def test_single_currency_has_no_combined(self):
        Account.objects.filter(label="tesoro").delete()
        self.extra = {"EURUSD=X": pd.Series([1.25], index=pd.to_datetime(
            [T4]))}
        self.assertNotIn("combined", self.get("/api/account"))


class PageTests(PlanWebBase):
    def test_page_has_the_panels_and_exact_strings(self):
        res = self.client.get("/account" + self.q)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        for needle in ('id="payin"', 'id="rules"', 'id="a-xirr"',
                       'id="a-combined"', "Money-weighted",
                       "Cancel last month’s unfilled orders before placing "
                       "these — this list already includes what they "
                       "didn’t buy.",
                       "Advice only — place trades at your broker and "
                       "record them in your ledger."):
            self.assertIn(needle, html)

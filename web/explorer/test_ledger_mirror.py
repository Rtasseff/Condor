"""ADR 0005: ledger import/export commands, mirror accounts, and the web
layer's handling of them. Numbers are the synthetic fixture's (AAA/BBB
are invented tickers, so price fetches are patched)."""

import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from condor import accounting as acct
from condor.ledger_io import read_ledger
from explorer.models import Account, AccountEvent, AccountTarget

FIX = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
LEDGER = str(FIX / "ledger_sample.csv")
TARGETS = str(FIX / "ledger_sample_targets.csv")
TODAY = "2028-12-31"


def run(*args, **kw):
    out, err = io.StringIO(), io.StringIO()
    call_command(*args, stdout=out, stderr=err, **kw)
    return out.getvalue(), err.getvalue()


def do_import(user="rt", ledger=LEDGER, targets=TARGETS, **kw):
    args = ["import_ledger", ledger, "--user", user, "--replace",
            "--today", TODAY]
    if targets:
        args += ["--targets", targets]
    return run(*args, **kw)


def snapshot(acc):
    return (list(acc.events.values_list(
        "date", "kind", "ticker", "shares", "price", "amount", "fees",
        "maturity", "note")), acc.target_weights(), acc.currency, acc.mirror)


class ImportCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rt", password="pw")

    def test_fixture_makes_two_mirror_accounts(self):
        out, _ = do_import()
        self.assertIn("broker_a: 9 events", out)
        a = Account.objects.get(owner=self.user, label="broker_a")
        t = Account.objects.get(owner=self.user, label="tesoro")
        self.assertEqual((a.currency, a.mirror, a.name), ("USD", True, "broker_a"))
        self.assertEqual((t.currency, t.mirror), ("EUR", True))
        self.assertIsNotNone(a.imported_at)
        self.assertEqual(a.target_weights(), {"AAA": 0.3, "BBB": 0.3})
        self.assertEqual(t.target_weights(), {})
        self.assertEqual(a.events.count(), 9)
        bill = t.events.get(kind="buy")
        self.assertEqual(str(bill.maturity), "2028-01-14")
        self.assertEqual(bill.ticker, "LETRA-2028-01-14")

    def test_stored_events_equal_the_engine_input(self):
        """model change: the DB round-trips to exactly what ledger_io parsed."""
        do_import()
        parsed = read_ledger(LEDGER, today=pd.Timestamp(TODAY).date())
        for label, imp in parsed.items():
            acc = Account.objects.get(label=label)
            got = acct.ledger_state(acc.events_frame())
            want = acct.ledger_state(imp.events)
            self.assertEqual(got, want)
            self.assertEqual(list(acc.events_frame()["kind"]),
                             list(imp.events["kind"]))

    def test_importing_twice_is_identical(self):
        do_import()
        first = {a.label: snapshot(a) for a in Account.objects.all()}
        n = Account.objects.count()
        do_import()
        self.assertEqual(Account.objects.count(), n)
        self.assertEqual(first, {a.label: snapshot(a)
                                 for a in Account.objects.all()})

    def test_replace_is_required(self):
        with self.assertRaisesRegex(CommandError, "--replace"):
            run("import_ledger", LEDGER, "--user", "rt", "--today", TODAY)
        self.assertEqual(Account.objects.count(), 0)

    def test_bad_file_writes_nothing_and_reports_every_error(self):
        text = Path(LEDGER).read_text().splitlines()
        text[2] = text[2].replace("BUY", "GIFT")
        text[4] = text[4].replace("2027-01-14", "2027-1-14")
        with tempfile.NamedTemporaryFile("w", suffix=".csv") as f:
            f.write("\n".join(text) + "\n")
            f.flush()
            out, err = io.StringIO(), io.StringIO()
            with self.assertRaises(CommandError):
                call_command("import_ledger", f.name, "--user", "rt",
                             "--replace", "--today", TODAY, stdout=out,
                             stderr=err)
        self.assertIn("line 3:", err.getvalue())
        self.assertIn("line 5:", err.getvalue())
        self.assertEqual(Account.objects.count(), 0)

    def test_label_clash_with_manual_account_is_refused(self):
        Account.objects.create(owner=self.user, label="broker_a", name="mine")
        with self.assertRaisesRegex(CommandError, "manual"):
            do_import()
        self.assertEqual(Account.objects.count(), 1)   # nothing else written
        self.assertEqual(AccountEvent.objects.count(), 0)

    def test_currency_change_is_refused(self):
        do_import()
        Account.objects.filter(label="tesoro").update(currency="USD")
        before = AccountEvent.objects.count()
        with self.assertRaisesRegex(CommandError, "EUR"):
            do_import()
        self.assertEqual(AccountEvent.objects.count(), before)

    def test_other_accounts_and_users_untouched(self):
        other = User.objects.create_user("zed", password="pw")
        mine = Account.objects.create(owner=self.user, name="manual")
        AccountEvent.objects.create(account=mine, date="2026-01-05",
                                    kind="deposit", amount=5)
        do_import()
        do_import("zed")
        self.assertEqual(mine.events.count(), 1)
        self.assertEqual(Account.objects.filter(owner=other).count(), 2)
        self.assertEqual(Account.objects.filter(owner=self.user).count(), 3)

    def test_dry_run_writes_nothing(self):
        out, _ = do_import(**{"dry_run": True})
        self.assertIn("broker_a", out)
        self.assertEqual(Account.objects.count(), 0)

    def test_targets_replaced_and_cleared(self):
        do_import()
        with tempfile.NamedTemporaryFile("w", suffix=".csv") as f:
            f.write("account,ticker,weight\ntesoro,ZZZ,0.5\n")
            f.flush()
            do_import(targets=f.name)
        self.assertEqual(Account.objects.get(label="broker_a").target_weights(), {})
        self.assertEqual(Account.objects.get(label="tesoro").target_weights(),
                         {"ZZZ": 0.5})
        do_import(targets=None)                       # no --targets: untouched
        self.assertEqual(AccountTarget.objects.count(), 1)

    def test_events_replaced_not_appended(self):
        do_import()
        do_import()
        self.assertEqual(AccountEvent.objects.count(), 12)

    def test_unknown_user(self):
        with self.assertRaisesRegex(CommandError, "no such user"):
            do_import("nobody")


class ExportCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rt", password="pw")
        do_import()

    def test_round_trip(self):
        out, _ = run("export_ledger", "--user", "rt")
        back = read_ledger(io.StringIO(out), today=pd.Timestamp(TODAY).date())
        want = read_ledger(LEDGER, today=pd.Timestamp(TODAY).date())
        self.assertEqual(list(back), list(want))
        for k in want:
            self.assertEqual(back[k].currency, want[k].currency)
            pd.testing.assert_frame_equal(back[k].events.reset_index(drop=True),
                                          want[k].events)

    def test_account_filter_and_output_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "out.csv"
            run("export_ledger", "--user", "rt", "--account", "tesoro",
                "-o", str(p))
            back = read_ledger(p, today=pd.Timestamp(TODAY).date())
        self.assertEqual(list(back), ["tesoro"])
        with self.assertRaisesRegex(CommandError, "no such account"):
            run("export_ledger", "--user", "rt", "--account", "nope")

    def test_manual_account_exports_under_name_slug(self):
        m = Account.objects.create(owner=self.user, name="My Account!")
        AccountEvent.objects.create(account=m, date="2026-01-05",
                                    kind="deposit", amount=5)
        out, _ = run("export_ledger", "--user", "rt", "--account", "my_account")
        self.assertIn("2026-01-05,my_account,CASH,DEPOSIT,5,1,0,USD,,", out)

    def test_forces_are_refused(self):
        m = Account.objects.create(owner=self.user, name="forced")
        AccountEvent.objects.create(account=m, date="2026-01-05",
                                    kind="set_cash", amount=5)
        with self.assertRaisesRegex(CommandError, "2026-01-05"):
            run("export_ledger", "--user", "rt", "--account", "forced")


# ------------------------------------------------------------- web layer

MIRROR_MSG = ("This account mirrors the imported ledger '{label}'. Change "
              "the source ledger and re-import; Condor never writes to it.")


def add_events(acc, rows):
    for r in rows:
        AccountEvent.objects.create(account=acc, **r)


def dep(d, amount):
    return dict(date=d, kind="deposit", amount=amount)


class WebTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rt", password="pw")
        self.client.force_login(self.user)
        idx = pd.bdate_range("2026-01-05", periods=4)
        self.closes = {
            "AAA": pd.Series([50.0, 50.0, 60.0, 60.0], index=idx),
            "BBB": pd.Series([10.0] * 4, index=idx)}

    def patched(self):
        tests = self

        def fake_history(tickers, start):
            return pd.DataFrame({t: tests.closes[t] for t in sorted(tickers)})
        return patch("explorer.account._close_history",
                     side_effect=fake_history)

    def call(self, method, url, body=None, expect=200):
        kw = {"content_type": "application/json"}
        if body is not None:
            kw["data"] = json.dumps(body)
        with self.patched():
            res = getattr(self.client, method)(url, **kw)
        self.assertEqual(res.status_code, expect, res.content)
        return res.json()

    def mirror(self, label="mir", currency="USD", rows=None):
        acc = Account.objects.create(owner=self.user, label=label, name=label,
                                     currency=currency, mirror=True)
        add_events(acc, rows if rows is not None else [
            dep("2026-01-05", 1000),
            dict(date="2026-01-06", kind="buy", ticker="AAA", shares=10,
                 price=50, fees=1.0),
            dict(date="2026-01-07", kind="dividend", ticker="AAA", amount=5),
            dict(date="2026-01-07", kind="fee", amount=2)])
        return acc


class MirrorWriteGuardTests(WebTestBase):
    def setUp(self):
        super().setUp()
        self.acc = self.mirror()
        self.q = f"?account={self.acc.id}"
        AccountTarget.objects.create(account=self.acc, ticker="AAA", weight=0.5)

    def test_every_writer_is_403_with_the_label(self):
        ev = self.acc.events.first()
        writers = [
            ("post", "/api/account/events", {"kind": "deposit", "amount": 5}),
            ("delete", f"/api/account/events/{ev.pk}", None),
            ("post", "/api/account/target", {"weights": {"AAA": 0.5}}),
            ("post", "/api/account/plan/confirm",
             {"trades": [{"ticker": "AAA", "shares": 1, "price": 60}]}),
            ("post", "/api/account/schedule", {"amount": 5}),
            ("post", "/api/account/contribution/confirm", {"amount": 5}),
        ]
        before = (AccountEvent.objects.count(), AccountTarget.objects.count())
        for method, url, body in writers:
            res = self.call(method, url + self.q, body, expect=403)
            self.assertEqual(res["error"], MIRROR_MSG.format(label="mir"), url)
        self.assertEqual(before, (AccountEvent.objects.count(),
                                  AccountTarget.objects.count()))
        self.assertFalse(hasattr(Account.objects.get(pk=self.acc.pk), "schedule"))

    def test_previews_stay_open(self):
        self.call("get", "/api/account" + self.q)
        self.call("get", "/api/account/plan" + self.q)
        self.call("get", "/api/account/contribution" + self.q + "&amount=100")

    def test_forecast_is_a_preview_but_usd_only(self):
        eur = self.mirror("eur", "EUR")
        res = self.call("post", f"/api/account/forecast?account={eur.id}",
                        {"horizon_years": 2}, expect=400)
        self.assertEqual(res["error"], "The forecast is USD-only for now.")

        def fake_prices(tickers, years=10, **kw):
            import numpy as np
            rng = np.random.default_rng(9)
            idx = pd.bdate_range("2020-01-01", periods=756)
            return pd.DataFrame(
                100 * np.cumprod(1 + 0.0004 + 0.01 * rng.standard_normal(
                    (756, len(tickers))), axis=0),
                index=idx, columns=list(tickers))
        with self.patched(), \
             patch("explorer.account.fetch_prices", side_effect=fake_prices), \
             patch("explorer.account.risk_free_rate",
                   return_value={"rate": 0.04}):
            res = self.client.post("/api/account/forecast" + self.q,
                                   data=json.dumps({"horizon_years": 2}),
                                   content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)


class AccountSelectionTests(WebTestBase):
    def test_foreign_unknown_and_malformed_ids_look_identical(self):
        other = User.objects.create_user("zed", password="pw")
        theirs = Account.objects.create(owner=other, name="theirs")
        bodies = set()
        for raw in (str(theirs.id), str(uuid_none()), "not-a-uuid", ""):
            for method, url in (("get", "/api/account"),
                                ("post", "/api/account/events"),
                                ("get", "/api/account/plan")):
                res = self.client.generic(
                    method.upper(), f"{url}?account={raw}",
                    data=json.dumps({"kind": "deposit", "amount": 1})
                    if method == "post" else "",
                    content_type="application/json")
                self.assertEqual(res.status_code, 404, (raw, url))
                bodies.add(res.content)
        self.assertEqual(len(bodies), 1)
        self.assertEqual(theirs.events.count(), 0)
        self.assertEqual(self.client.get(f"/account?account={theirs.id}")
                         .status_code, 404)

    def test_default_account_rule(self):
        # none -> auto-created "My account"
        d = self.call("get", "/api/account")
        self.assertEqual(d["account"]["name"], "My account")
        self.assertFalse(d["account"]["mirror"])
        Account.objects.all().delete()
        # only mirrors -> the first mirror
        a = self.mirror("first")
        self.mirror("second", rows=[dep("2026-01-05", 1)])
        self.assertEqual(self.call("get", "/api/account")["account"]["id"],
                         str(a.id))
        # a manual account (even created later) wins over mirrors
        m = Account.objects.create(owner=self.user, name="manual")
        d = self.call("get", "/api/account")
        self.assertEqual(d["account"]["id"], str(m.id))
        self.assertEqual([x["label"] for x in d["accounts"]],
                         ["first", "second", ""])
        self.assertEqual(Account.default_for(self.user).pk, m.pk)

    def test_query_string_selects_on_post_too(self):
        a = self.mirror("first")
        m = Account.objects.create(owner=self.user, name="manual")
        d = self.call("post", f"/api/account/events?account={m.id}",
                      dep("2026-01-05", 40))
        self.assertEqual(d["account"]["id"], str(m.id))
        self.assertEqual(m.events.count(), 1)
        self.assertEqual(a.events.count(), 4)

    def test_has_holdings_uses_default_rule_and_ignores_bills(self):
        from explorer.views import _has_holdings
        self.assertFalse(_has_holdings(self.user))
        self.mirror("bills", "EUR", rows=[
            dep("2026-01-06", 970.6),
            dict(date="2026-01-06", kind="buy", ticker="LETRA-2027-01-06",
                 shares=1000, price=0.9706, maturity="2027-01-06")])
        self.assertFalse(_has_holdings(self.user))     # bill-only
        self.mirror("stocks")
        self.assertFalse(_has_holdings(self.user))     # default = first mirror
        Account.objects.create(owner=self.user, name="manual")
        self.assertFalse(_has_holdings(self.user))     # manual default, empty


def uuid_none():
    import uuid
    return uuid.UUID(int=0)


class StatePayloadTests(WebTestBase):
    def test_gain_breakdown_and_position_fields(self):
        acc = self.mirror()
        d = self.call("get", f"/api/account?account={acc.id}")
        self.assertEqual(d["account"]["label"], "mir")
        self.assertEqual(d["account"]["currency"], "USD")
        self.assertTrue(d["account"]["mirror"])
        self.assertIsNone(d["account"]["imported_at"])
        # cash 1000 - 501 + 5 - 2; AAA 10 @ 60
        self.assertEqual(d["cash"], 502.0)
        self.assertEqual(d["total_value"], 1102.0)
        self.assertEqual(d["gain"], 102.0)
        self.assertEqual((d["realized_total"], d["unrealized_total"],
                          d["income_total"], d["charges_total"],
                          d["trade_fees_total"]), (0.0, 99.0, 5.0, 2.0, 1.0))
        self.assertAlmostEqual(
            d["gain"], d["realized_total"] + d["unrealized_total"]
            + d["income_total"] - d["charges_total"])
        p = d["positions"][0]
        self.assertEqual((p["ticker"], p["shares"], p["price"], p["value"]),
                         ("AAA", 10, 60.0, 600.0))
        self.assertEqual((p["cost"], p["avg_cost"], p["unrealized"]),
                         (501.0, 50.1, 99.0))
        self.assertAlmostEqual(p["unrealized_pct"], 600 / 501 - 1, places=5)
        self.assertEqual((p["income"], p["realized"], p["is_bill"],
                          p["maturity"]), (5.0, 0.0, False, None))
        fee = [e for e in d["events"] if e["kind"] == "fee"][0]
        self.assertEqual((fee["fees"], fee["maturity"]), (0.0, None))
        buy = [e for e in d["events"] if e["kind"] == "buy"][0]
        self.assertEqual(buy["fees"], 1.0)

    def test_state_equals_the_engine(self):
        acc = self.mirror()
        d = self.call("get", f"/api/account?account={acc.id}")
        s = acct.ledger_state(acc.events_frame())
        self.assertAlmostEqual(d["cash"], s.cash, places=2)
        self.assertAlmostEqual(d["net_contributions"], s.contributions, places=2)
        self.assertAlmostEqual(d["income_total"], sum(s.income.values()), places=2)

    def test_sold_out_ticker_still_values(self):
        acc = self.mirror(rows=[
            dep("2026-01-05", 1000),
            dict(date="2026-01-05", kind="buy", ticker="BBB", shares=10, price=10),
            dict(date="2026-01-07", kind="sell", ticker="BBB", shares=10, price=12)])
        d = self.call("get", f"/api/account?account={acc.id}")
        self.assertEqual(d["positions"], [])
        self.assertEqual(d["realized_total"], 20.0)
        self.assertEqual(d["total_value"], 1020.0)

    def test_bill_account_valued_without_closes(self):
        acc = self.mirror("bills", "EUR", rows=[
            dep("2026-01-06", 970.6),
            dict(date="2026-01-06", kind="buy", ticker="LETRA-2027-01-06",
                 shares=1000, price=0.9706, maturity="2027-01-06")])
        d = self.call("get", f"/api/account?account={acc.id}")
        self.assertEqual(d["account"]["currency"], "EUR")
        days = (pd.Timestamp(d["series"]["dates"][-1])
                - pd.Timestamp("2026-01-06")).days
        accreted = 970.6 + 29.4 * days / 365
        self.assertAlmostEqual(d["total_value"], accreted, places=2)
        p = d["positions"][0]
        self.assertTrue(p["is_bill"])
        self.assertEqual((p["shares"], p["maturity"]), (1000, "2027-01-06"))
        self.assertAlmostEqual(p["price"], accreted / 1000, places=4)
        self.assertAlmostEqual(p["unrealized"], accreted - 970.6, places=2)
        self.assertAlmostEqual(d["gain"], accreted - 970.6, places=2)

    def test_plans_leave_bills_out(self):
        acc = self.mirror("mix", rows=[
            dep("2026-01-05", 2000),
            dict(date="2026-01-05", kind="buy", ticker="LETRA-2027-01-05",
                 shares=1000, price=0.97, maturity="2027-01-05"),
            dep("2026-01-05", 100)])
        AccountTarget.objects.create(account=acc, ticker="AAA", weight=0.5)
        plan = self.call("get", f"/api/account/plan?account={acc.id}")
        self.assertEqual([r["ticker"] for r in plan["rows"]], ["AAA"])
        # total = cash only (2000 + 100 - 970), bills not in the base
        self.assertEqual(plan["total"], 1130.0)
        con = self.call("get", f"/api/account/contribution?account={acc.id}&amount=100")
        self.assertEqual([r["ticker"] for r in con["rows"]], ["AAA"])


class ManualEventTests(WebTestBase):
    def post(self, body, expect=200):
        return self.call("post", "/api/account/events", body, expect)

    def test_income_fee_and_trade_fees_on_manual_accounts(self):
        self.post(dep("2026-01-05", 1000))
        self.post({"kind": "buy", "ticker": "AAA", "date": "2026-01-06",
                   "shares": 10, "price": 50, "fees": 1})
        self.post({"kind": "dividend", "ticker": "AAA", "date": "2026-01-07",
                   "amount": 5, "fees": 0.5})
        self.post({"kind": "interest", "date": "2026-01-07", "amount": 1})
        self.post({"kind": "interest", "ticker": "AAA", "date": "2026-01-07",
                   "amount": 1})
        d = self.post({"kind": "fee", "date": "2026-01-07", "amount": 2})
        # cash: 1000 - 501 + 4.5 + 1 + 1 - 2
        self.assertEqual(d["cash"], 503.5)
        self.assertEqual(d["income_total"], 7.0)
        self.assertEqual(d["charges_total"], 2.5)
        self.assertEqual(d["trade_fees_total"], 1.0)
        self.assertEqual(d["gain"], d["total_value"] - 1000)

    def test_validation_of_new_kinds(self):
        self.post(dep("2026-01-05", 100))
        self.post({"kind": "dividend", "date": "2026-01-06", "amount": 5},
                  expect=400)                         # ticker required
        self.post({"kind": "dividend", "ticker": "AAA", "amount": -1},
                  expect=400)
        self.post({"kind": "fee", "amount": 0}, expect=400)
        self.post({"kind": "fee", "amount": 500}, expect=400)   # no cash
        self.post({"kind": "buy", "ticker": "AAA", "shares": 1, "price": 5,
                   "fees": -1, "date": "2026-01-06"}, expect=400)

    def test_bills_are_import_only(self):
        self.post(dep("2026-01-05", 1000))
        for body in ({"kind": "redeem", "ticker": "AAA", "shares": 1,
                      "price": 1},
                     {"kind": "buy", "ticker": "AAA", "shares": 1, "price": 5,
                      "date": "2026-01-06", "maturity": "2027-01-01"}):
            res = self.post(body, expect=400)
            self.assertEqual(res["error"],
                             "Bills come in through import_ledger only.")

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

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

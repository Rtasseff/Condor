"""Mirror an external CSV ledger into Condor accounts (ADR 0005).

    manage.py import_ledger LEDGER [--targets TARGETS] --user NAME --replace

Format: docs/LEDGER-FORMAT.md. The source ledger is the record: each
labelled account's events (and targets, with --targets) are fully
replaced, in one transaction. Parsing and validation live in the pure
`condor.ledger_io`; this command only persists.
"""

import datetime as dt

import pandas as pd
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from condor import accounting as acct
from condor.ledger_io import LedgerFormatError, read_ledger, read_targets

from explorer.models import Account, AccountEvent, AccountTarget


def _none(x):
    return None if x is None or pd.isna(x) else float(x)


class Command(BaseCommand):
    help = "Import a ledger CSV (format v1) as read-only mirror accounts."

    def add_arguments(self, parser):
        parser.add_argument("ledger", metavar="LEDGER")
        parser.add_argument("--targets", metavar="TARGETS")
        parser.add_argument("--user", required=True, metavar="USERNAME")
        parser.add_argument("--replace", action="store_true",
                            help="required: replace each account's events")
        parser.add_argument("--dry-run", action="store_true",
                            help="validate and report; write nothing")
        parser.add_argument("--today", metavar="YYYY-MM-DD",
                            help="date the file is checked against "
                                 "(default: the real date)")

    def handle(self, *args, **opt):
        if not opt["replace"]:
            raise CommandError(
                "--replace is required: ledger format v1 has no merge mode; "
                "an import fully replaces each account's events.")
        try:
            user = get_user_model().objects.get(username=opt["user"])
        except get_user_model().DoesNotExist:
            raise CommandError(f"no such user: {opt['user']!r}")
        try:
            today = (dt.date.fromisoformat(opt["today"])
                     if opt["today"] else None)
        except ValueError:
            raise CommandError("--today must be YYYY-MM-DD.")

        try:
            ledgers = read_ledger(opt["ledger"], today=today)
            targets = (read_targets(opt["targets"])
                       if opt["targets"] else None)
        except OSError as e:
            raise CommandError(str(e))
        except LedgerFormatError as e:
            for msg in e.errors:
                self.stderr.write(msg)
            raise CommandError(
                f"rejected: {len(e.errors)} error(s); nothing written.")
        if targets is not None:
            unknown = sorted(set(targets) - set(ledgers))
            if unknown:
                raise CommandError(
                    f"targets for accounts not in the ledger: {unknown}; "
                    "nothing written.")

        with transaction.atomic():
            for label, imp in ledgers.items():
                acc = Account.objects.filter(owner=user, label=label).first()
                if acc is None:
                    acc = Account.objects.create(
                        owner=user, label=label, name=label,
                        currency=imp.currency, mirror=True)
                elif not acc.mirror:
                    raise CommandError(
                        f"account label {label!r} already belongs to a "
                        "manual (non-mirror) account; nothing written.")
                elif acc.currency != imp.currency:
                    raise CommandError(
                        f"account {label!r} is {acc.currency} here but "
                        f"{imp.currency} in the file; nothing written.")
                acc.events.all().delete()
                AccountEvent.objects.bulk_create(
                    AccountEvent(
                        account=acc, date=e.date.date(), kind=e.kind,
                        ticker=e.ticker if isinstance(e.ticker, str) else "",
                        shares=_none(e.shares), price=_none(e.price),
                        amount=_none(e.amount), fees=float(e.fees),
                        maturity=(None if pd.isna(e.maturity)
                                  else e.maturity.date()),
                        note=e.note)
                    for e in imp.events.itertuples(index=False))
                acc.imported_at = timezone.now()
                acc.save(update_fields=["imported_at"])
                if targets is not None:
                    acc.targets.all().delete()
                    AccountTarget.objects.bulk_create(
                        AccountTarget(account=acc, ticker=t, weight=w)
                        for t, w in targets.get(label, {}).items())
                s = acct.ledger_state(imp.events)
                held = ", ".join(sorted(s.shares)) or "none"
                self.stdout.write(
                    f"{label}: {len(imp.events)} events, cash "
                    f"{s.cash:.2f} {imp.currency}, open: {held}")
            if opt["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write("dry run: nothing written.")

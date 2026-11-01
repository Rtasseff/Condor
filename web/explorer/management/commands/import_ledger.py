"""Mirror an external CSV ledger into Condor accounts (ADR 0005).

    manage.py import_ledger LEDGER [--targets T] [--payin P] [--rules R]
                            --user NAME --replace

Format: docs/LEDGER-FORMAT.md. The source ledger is the record: each
labelled account's events (and targets / pay-in plan / rules, with
--targets / --payin / --rules) are fully replaced, in one transaction. Parsing and validation live in the pure
`condor.ledger_io`; this command only persists.
"""

import datetime as dt

import pandas as pd
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from condor import accounting as acct
from condor.ledger_io import (LedgerFormatError, read_ledger, read_payin,
                               read_rules, read_targets_full, RuleSpec)

from explorer.models import (Account, AccountEvent, AccountRule,
                             AccountTarget, PayInPlan)


def _none(x):
    return None if x is None or pd.isna(x) else float(x)


class Command(BaseCommand):
    help = "Import a ledger CSV (format v1) as read-only mirror accounts."

    def add_arguments(self, parser):
        parser.add_argument("ledger", metavar="LEDGER")
        parser.add_argument("--targets", metavar="TARGETS")
        parser.add_argument("--payin", metavar="PAYIN",
                            help="payin.csv (format v1.1)")
        parser.add_argument("--rules", metavar="RULES",
                            help="rules.csv (format v1.1)")
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
            targets = (read_targets_full(opt["targets"])
                       if opt["targets"] else None)
            payin = read_payin(opt["payin"]) if opt["payin"] else None
            rules = read_rules(opt["rules"]) if opt["rules"] else None
        except OSError as e:
            raise CommandError(str(e))
        except LedgerFormatError as e:
            for msg in e.errors:
                self.stderr.write(msg)
            raise CommandError(
                f"rejected: {len(e.errors)} error(s); nothing written.")
        for name, given in (("targets", targets), ("pay-in", payin),
                            ("rules", rules)):
            unknown = sorted(set(given or {}) - set(ledgers))
            if unknown:
                raise CommandError(
                    f"{name} for accounts not in the ledger: {unknown}; "
                    "nothing written.")
        self._cross_check(user, ledgers, targets, payin, rules)

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
                        AccountTarget(account=acc, ticker=t, weight=sp.weight,
                                      timing=sp.timing, line=sp.line)
                        for t, sp in targets.get(label, {}).items())
                extra = ""
                if payin is not None:
                    PayInPlan.objects.filter(account=acc).delete()
                    plan = payin.get(label)
                    if plan:
                        PayInPlan.objects.create(
                            account=acc, total=plan.total,
                            dates=[d.isoformat() for d in plan.dates])
                    extra += f", pay-in {len(plan.dates) if plan else 0} tranches"
                if rules is not None:
                    acc.rules.all().delete()
                    AccountRule.objects.bulk_create(
                        AccountRule(
                            account=acc, rule_id=r.id, rule=r.rule,
                            ticker=r.ticker, threshold=r.threshold,
                            action=r.action, tranches=r.tranches,
                            targets=" ".join(r.targets))
                        for r in rules.get(label, []))
                    extra += f", rules {len(rules.get(label, []))}"
                s = acct.ledger_state(imp.events)
                held = ", ".join(sorted(s.shares)) or "none"
                self.stdout.write(
                    f"{label}: {len(imp.events)} events, cash "
                    f"{s.cash:.2f} {imp.currency}, open: {held}{extra}")
            if opt["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write("dry run: nothing written.")

    def _cross_check(self, user, ledgers, targets, payin, rules):
        """Cross-file rules, all before any write. A pay-in or rule is
        judged against the targets in this run, else the stored ones."""
        errs = []

        def specs(label):
            if targets is not None:
                return {t: sp.timing for t, sp in targets.get(label, {}).items()}
            acc = Account.objects.filter(owner=user, label=label).first()
            return ({t.ticker: t.timing for t in acc.targets.all()}
                    if acc else {})

        def stored(label):
            return Account.objects.filter(owner=user, label=label).first()

        # a pay-in / rules file in this run, else the stored ones, must
        # fit the targets that will be in force afterwards
        have_plan = {l for l in ledgers
                     if (l in payin if payin is not None
                         else (a := stored(l)) is not None
                         and hasattr(a, "payin"))}
        for label in sorted(have_plan):
            if "dca" not in specs(label).values():
                hint = (" Pass v1.1 targets (timing, line) with --targets."
                        if payin is None else "")
                errs.append(f"pay-in for '{label}' needs at least one "
                            f"target with timing dca.{hint}")
        for label in ledgers:
            if rules is not None:
                rs = rules.get(label, [])
            else:
                a = stored(label)
                rs = [RuleSpec(r.rule_id, r.rule, r.ticker, r.threshold,
                               r.action, r.tranches, tuple(r.targets.split()))
                      for r in a.rules.all()] if a else []
            dca = {t for t, tm in specs(label).items() if tm == "dca"}
            for r in rs:
                bad = [t for t in r.targets if t not in dca]
                if bad:
                    hint = (" Pass v1.1 targets (timing, line) with "
                            "--targets." if rules is None else "")
                    errs.append(f"rule '{r.id}' of '{label}' targets "
                                f"{bad}, which are not dca targets.{hint}")
        if errs:
            for m in errs:
                self.stderr.write(m)
            raise CommandError(
                f"rejected: {len(errs)} error(s); nothing written.")

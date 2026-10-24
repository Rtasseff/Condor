"""Write a user's accounts as a ledger CSV (format v1).

    manage.py export_ledger --user NAME [--account LABEL ...] [-o FILE]

Mirror accounts export under their label; manual accounts under a slug
of their name. Targets are not exported. Accounts holding manual
set_shares / set_cash forces cannot be expressed in v1 and are refused.
"""

import io
import re

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from condor.ledger_io import write_ledger

from explorer.models import Account


def _labels(accounts):
    """-> [(label, account)]; manual accounts get a unique name slug."""
    out, used = [], {a.label for a in accounts if a.label}
    for a in accounts:
        label = a.label
        if not label:
            base = re.sub(r"[^a-z0-9]+", "_", a.name.lower()).strip("_")
            base = (base or "account")[:36]
            label, n = base, 2
            while label in used:
                label, n = f"{base}_{n}", n + 1
            used.add(label)
        out.append((label, a))
    return out


class Command(BaseCommand):
    help = "Export accounts as a ledger CSV (format v1)."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, metavar="USERNAME")
        parser.add_argument("--account", action="append", metavar="LABEL",
                            help="only this label (repeatable)")
        parser.add_argument("-o", "--output", metavar="FILE")

    def handle(self, *args, **opt):
        try:
            user = get_user_model().objects.get(username=opt["user"])
        except get_user_model().DoesNotExist:
            raise CommandError(f"no such user: {opt['user']!r}")
        pairs = _labels(list(Account.objects.filter(owner=user)))
        if opt["account"]:
            known = {l for l, _ in pairs}
            missing = [l for l in opt["account"] if l not in known]
            if missing:
                raise CommandError(f"no such account label(s): {missing}")
            pairs = [(l, a) for l, a in pairs if l in opt["account"]]
        accounts = [(l, a.currency, a.events_frame()) for l, a in pairs]
        try:
            if opt["output"]:
                write_ledger(accounts, opt["output"])
            else:
                buf = io.StringIO()
                write_ledger(accounts, buf)
                self.stdout.write(buf.getvalue(), ending="")
        except ValueError as e:
            raise CommandError(str(e))

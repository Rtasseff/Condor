"""Storage for saved portfolio configurations.

These Django models are STORAGE ONLY (see ARCHITECTURE.md). They hold the
*inputs* a user picked — tickers, weights, method, lookback, risk-free rate —
and nothing derived from prices. Behaviour lives in `condor`: hand
`to_config()` to the analyze endpoint (or `compute_analysis`) to get numbers.
"""

import uuid

from django.conf import settings
from django.db import models


class SavedPortfolio(models.Model):
    """One saved configuration, addressed by an unguessable uuid4.

    Access control: every view requires a login; within the logged-in
    team, anyone with the link can *read* a portfolio (that's the sharing
    model), but the saved list is scoped to `owner` and only the owner
    can update or delete.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.CASCADE, related_name="portfolios",
        help_text="Who saved it. Null = legacy row from before accounts; "
                  "claimed by whoever edits it next.")
    name = models.CharField(max_length=80)
    method = models.CharField(max_length=16, default="robust")
    years = models.PositiveSmallIntegerField(default=10)
    risk_free_rate = models.FloatField(default=0.02)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.name} ({self.id})"

    def set_holdings(self, weights):
        """Replace all holdings with `{ticker: weight}`.

        Weights are stored as fractions of 1 — the same rescaling `condor`
        applies at analysis time — so a stored config carries no unit
        convention of its own. Rescaling only; no analysis happens here.
        """
        total = sum(float(w) for w in weights.values())
        if total <= 0:
            raise ValueError("weights must sum to a positive number")
        self.holdings.all().delete()
        Holding.objects.bulk_create(
            [
                Holding(portfolio=self, ticker=t, weight=float(w) / total)
                for t, w in weights.items()
            ]
        )

    def to_config(self):
        """The saved inputs, in the shape `/api/analyze` expects."""
        holdings = list(self.holdings.all())
        return {
            "tickers": [h.ticker for h in holdings],
            "weights": {h.ticker: h.weight for h in holdings},
            "method": self.method,
            "years": self.years,
            "risk_free_rate": self.risk_free_rate,
        }


class DraftPortfolio(models.Model):
    """The single in-progress mix a user is building on the Build page.

    Storage only (see ARCHITECTURE.md): `payload` holds
    `{"assets": [{"symbol": "MSFT", "weight": 0.25}, ...]}`, weights
    already normalised to sum to 1. One per user, created lazily.
    Optimize reads it to prefill; adopting a point there writes it back —
    it is the thread between the two pages.
    """

    owner = models.OneToOneField(settings.AUTH_USER_MODEL,
                                 on_delete=models.CASCADE,
                                 related_name="draft")
    payload = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Draft ({self.owner})"

    @property
    def assets(self):
        return (self.payload or {}).get("assets", [])

    def set_assets(self, items):
        """Replace the draft with `[(ticker, weight), ...]`, weight > 0.

        Normalises to sum to 1, in the given order — rescaling only, like
        `SavedPortfolio.set_holdings`; no analysis happens here.
        """
        total = sum(w for _, w in items)
        if total <= 0:
            raise ValueError("weights must sum to a positive number")
        self.payload = {"assets": [{"symbol": t, "weight": w / total}
                                   for t, w in items]}


class Holding(models.Model):
    """One ticker's share of a saved portfolio (fraction of 1)."""

    portfolio = models.ForeignKey(
        SavedPortfolio, on_delete=models.CASCADE, related_name="holdings"
    )
    ticker = models.CharField(max_length=10)
    weight = models.FloatField()

    class Meta:
        ordering = ["id"]  # insertion order = the order the user listed them
        constraints = [
            models.UniqueConstraint(
                fields=["portfolio", "ticker"], name="unique_ticker_per_portfolio"
            )
        ]

    def __str__(self):
        return f"{self.ticker} {self.weight:.3f}"


# ---------------------------------------------------------------- accounts
# ADR 0004: an Account is MONEY — an append-only ledger of events plus a
# setpoint. SavedPortfolio stays configuration (the "draft"). All derived
# numbers (positions, value, contributions vs return, drift, plans) come
# from condor.accounting over `events_frame()`; nothing derived is stored.


class Account(models.Model):
    """One tracked (pretend or mirrored-real) account."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL,
                              on_delete=models.CASCADE,
                              related_name="accounts")
    name = models.CharField(max_length=80, default="My account")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.name} ({self.owner})"

    def events_frame(self):
        """Ledger -> the engine's event-table shape (condor.accounting)."""
        import pandas as pd
        rows = [{"date": e.date, "kind": e.kind,
                 "ticker": e.ticker or None, "shares": e.shares,
                 "price": e.price, "amount": e.amount}
                for e in self.events.order_by("date", "created_at", "pk")]
        return pd.DataFrame(rows, columns=["date", "kind", "ticker",
                                           "shares", "price", "amount"])

    def target_weights(self):
        return {t.ticker: t.weight for t in self.targets.all()}


class AccountTarget(models.Model):
    """Setpoint allocation: fraction of total value per ticker.

    Cash is the implicit remainder (1 - sum), which is exactly what a
    CAL draft produces. Replaced wholesale when a draft is adopted."""

    account = models.ForeignKey(Account, on_delete=models.CASCADE,
                                related_name="targets")
    ticker = models.CharField(max_length=10)
    weight = models.FloatField()

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["account", "ticker"], name="unique_target_per_account")]
        ordering = ["-weight", "ticker"]

    def __str__(self):
        return f"{self.ticker} {self.weight:.1%}"


class AccountEvent(models.Model):
    """One ledger entry. Append-only in spirit: rows are added by the
    user (or by confirming a rebalance plan) and may be deleted to fix
    mistakes, never silently rewritten."""

    KINDS = ["deposit", "withdraw", "buy", "sell", "set_shares", "set_cash"]

    account = models.ForeignKey(Account, on_delete=models.CASCADE,
                                related_name="events")
    date = models.DateField()
    kind = models.CharField(max_length=12,
                            choices=[(k, k) for k in KINDS])
    ticker = models.CharField(max_length=10, blank=True, default="")
    shares = models.FloatField(null=True, blank=True)
    price = models.FloatField(null=True, blank=True)
    amount = models.FloatField(null=True, blank=True)
    note = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "created_at", "pk"]

    def __str__(self):
        core = self.ticker or f"${self.amount}"
        return f"{self.date} {self.kind} {core}"


class ContributionSchedule(models.Model):
    """The regular-contribution plan for an account (DCA).

    One per account: a fixed amount on a cadence. `next_due` in the
    past means "due now" — surfaced as a login reminder; confirming a
    contribution advances it cadence-by-cadence until it is in the
    future (no drift: advancing starts from the due date, not today).
    """

    CADENCES = ["weekly", "monthly", "quarterly", "yearly"]

    account = models.OneToOneField(Account, on_delete=models.CASCADE,
                                   related_name="schedule")
    amount = models.FloatField()
    cadence = models.CharField(max_length=10,
                               choices=[(c, c) for c in CADENCES],
                               default="monthly")
    next_due = models.DateField()
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        state = "on" if self.enabled else "off"
        return f"${self.amount} {self.cadence} (next {self.next_due}, {state})"

    @staticmethod
    def _add_months(d, months):
        import calendar
        y, m = divmod(d.month - 1 + months, 12)
        y, m = d.year + y, m + 1
        return d.replace(year=y, month=m,
                         day=min(d.day, calendar.monthrange(y, m)[1]))

    def advance(self, past_date):
        """Move next_due forward, one cadence at a time, until it is
        after `past_date`. Call after a confirmed contribution."""
        import datetime as _dt
        step = {"weekly": lambda d: d + _dt.timedelta(days=7),
                "monthly": lambda d: self._add_months(d, 1),
                "quarterly": lambda d: self._add_months(d, 3),
                "yearly": lambda d: self._add_months(d, 12)}[self.cadence]
        while self.next_due <= past_date:
            self.next_due = step(self.next_due)

    @property
    def due(self):
        import datetime as _dt
        return self.enabled and self.next_due <= _dt.date.today()

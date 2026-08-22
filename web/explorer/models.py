"""Storage for saved portfolio configurations.

These Django models are STORAGE ONLY (see ARCHITECTURE.md). They hold the
*inputs* a user picked — tickers, weights, method, lookback, risk-free rate —
and nothing derived from prices. Behaviour lives in `condor`: hand
`to_config()` to the analyze endpoint (or `compute_analysis`) to get numbers.
"""

import uuid

from django.db import models


class SavedPortfolio(models.Model):
    """One saved configuration, addressed by an unguessable uuid4.

    That uuid is the prototype's only access control: anyone with the link
    can read the portfolio (small, trusted group — users/auth come later).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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

"""Explorer views: the page, the JSON analysis endpoint, and saved portfolios.

This is the HTTP boundary only: validate input, build the domain objects
(via the `compute_analysis` facade today), return `to_dict()` payloads as
JSON. No numerics here — see ARCHITECTURE.md. Persistence is the same deal
in reverse: `explorer.models` stores the inputs, `condor` does the maths.
"""

import json
import logging
import math
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from condor import DataFetchError, compute_analysis, fetch_prices, risk_free_rate
from condor.stats import METHODS

from .models import SavedPortfolio

log = logging.getLogger(__name__)

TICKER_RE = re.compile(r"^[A-Z0-9.\-^]{1,10}$")
MAX_ASSETS = 15
MAX_NAME = 80


# ---------------------------------------------------------------- pages


def _render_page(request, preset=None):
    """The one page. Prefills the risk-free field from FRED (3-month
    Treasury constant maturity); if FRED and the cache are both
    unavailable, the template's hardcoded default stands. `preset` is a
    saved config injected for the JS to load on first paint."""
    rf = None
    try:
        rf = risk_free_rate()  # cached ~12h next to the price store
    except Exception:
        log.warning("risk-free rate unavailable; using field default")
    ctx = {
        "rf": rf,
        "rf_pct": round(rf["rate"] * 100, 2) if rf else 4.0,
        "preset": preset,
    }
    return render(request, "explorer/index.html", ctx)


@ensure_csrf_cookie
def index(request):
    return _render_page(request)


@ensure_csrf_cookie
def shared_portfolio(request, pid):
    """`/p/<uuid>` — the same page, preloaded with a saved portfolio."""
    portfolio = _get_portfolio(pid)
    if portfolio is None:
        raise Http404("No saved portfolio with that id.")
    preset = {"id": str(portfolio.id), "name": portfolio.name, **portfolio.to_config()}
    return _render_page(request, preset=preset)


# ------------------------------------------------------------ validation


def _bad(msg, status=400):
    return JsonResponse({"error": msg}, status=status)


def _json_body(request):
    """-> (body, error message)."""
    try:
        return json.loads(request.body or "{}"), None
    except json.JSONDecodeError:
        return None, "Request body must be JSON."


def _clean_tickers(raw):
    """Normalize + validate a list of symbols -> (tickers, error message)."""
    if not isinstance(raw, list) or not raw:
        return None, "Add at least one asset."
    tickers = [str(t).strip().upper() for t in raw]
    tickers = list(dict.fromkeys(tickers))  # dedupe, keep order
    if len(tickers) > MAX_ASSETS:
        return None, f"Prototype is capped at {MAX_ASSETS} assets."
    for t in tickers:
        if not TICKER_RE.match(t):
            return None, f"'{t}' does not look like a ticker symbol."
    return tickers, None


def _clean_settings(body):
    """Validate years / risk_free_rate / method -> (settings, error message)."""
    try:
        years = int(body.get("years", 10))
        rf = float(body.get("risk_free_rate", 0.02))
    except (TypeError, ValueError):
        return None, "years and risk_free_rate must be numbers."
    if not 1 <= years <= 25:
        return None, "Lookback must be between 1 and 25 years."
    if not -0.05 <= rf <= 0.25:
        return None, "Risk-free rate must be between -5% and 25%."
    method = body.get("method", "normal")
    if method not in METHODS:
        return None, f"method must be one of {METHODS}."
    return {"years": years, "risk_free_rate": rf, "method": method}, None


def _clean_weights(raw):
    """Validate a `{ticker: weight}` map -> (weights, error message).

    Keys go through the same ticker rules as `tickers`; values must be
    finite and non-negative, with at least one above zero (long-only).
    """
    if not isinstance(raw, dict) or not raw:
        return None, "weights must be an object of ticker -> weight."
    weights = {}
    for key, value in raw.items():
        ticker = str(key).strip().upper()
        try:
            w = float(value)
        except (TypeError, ValueError):
            return None, f"weight for '{ticker}' must be a number."
        if not math.isfinite(w) or w < 0:
            return None, "weights must be non-negative numbers."
        weights[ticker] = w
    tickers, err = _clean_tickers(list(weights))
    if err:
        return None, err
    if sum(weights.values()) <= 0:
        return None, "weights must add up to more than zero."
    return {t: weights[t] for t in tickers}, None


# ---------------------------------------------------------------- analyze


@require_POST
def api_analyze(request):
    body, err = _json_body(request)
    if err:
        return _bad(err)

    tickers, err = _clean_tickers(body.get("tickers") or [])
    if err:
        return _bad(err)

    settings, err = _clean_settings(body)
    if err:
        return _bad(err)

    weights = body.get("weights") or None
    if weights is not None and not isinstance(weights, dict):
        return _bad("weights must be an object of ticker -> weight.")

    try:
        prices = fetch_prices(tickers, years=settings["years"])
        result = compute_analysis(
            prices,
            weights=weights,
            risk_free_rate=settings["risk_free_rate"],
            method=settings["method"],
        )
    except DataFetchError as e:
        return _bad(str(e))
    except Exception:
        log.exception("analysis failed for %s", tickers)
        return _bad("Analysis failed unexpectedly; see server log.", status=500)

    return JsonResponse(result)


# ------------------------------------------------------- saved portfolios


def _get_portfolio(pid):
    """A SavedPortfolio by id, or None (also for ids that aren't uuids)."""
    try:
        return SavedPortfolio.objects.get(pk=pid)
    except (SavedPortfolio.DoesNotExist, ValidationError, ValueError, TypeError):
        return None


def _share_url(request, portfolio):
    return request.build_absolute_uri(
        reverse("shared_portfolio", args=[str(portfolio.id)])
    )


def _detail(request, portfolio):
    return {
        "id": str(portfolio.id),
        "name": portfolio.name,
        "url": _share_url(request, portfolio),
        "created_at": portfolio.created_at.isoformat(),
        "updated_at": portfolio.updated_at.isoformat(),
        **portfolio.to_config(),
    }


@require_http_methods(["GET", "POST"])
def api_portfolios(request):
    if request.method == "GET":
        rows = [
            {
                "id": str(p.id),
                "name": p.name,
                "tickers": [h.ticker for h in p.holdings.all()],
                "method": p.method,
                "updated_at": p.updated_at.isoformat(),
            }
            for p in SavedPortfolio.objects.prefetch_related("holdings").order_by(
                "-updated_at"
            )
        ]
        return JsonResponse(rows, safe=False)

    body, err = _json_body(request)
    if err:
        return _bad(err)

    name = str(body.get("name") or "").strip()
    if not name:
        return _bad("Give the portfolio a name.")
    if len(name) > MAX_NAME:
        return _bad(f"Name must be {MAX_NAME} characters or fewer.")

    weights, err = _clean_weights(body.get("weights"))
    if err:
        return _bad(err)

    settings, err = _clean_settings(body)
    if err:
        return _bad(err)

    portfolio = None
    if body.get("id"):
        portfolio = _get_portfolio(body["id"])
        if portfolio is None:
            return _bad("No saved portfolio with that id.", status=404)

    created = portfolio is None
    with transaction.atomic():
        if portfolio is None:
            portfolio = SavedPortfolio()
        portfolio.name = name
        portfolio.method = settings["method"]
        portfolio.years = settings["years"]
        portfolio.risk_free_rate = settings["risk_free_rate"]
        portfolio.save()
        portfolio.set_holdings(weights)

    return JsonResponse(
        {
            "id": str(portfolio.id),
            "name": portfolio.name,
            "url": _share_url(request, portfolio),
        },
        status=201 if created else 200,
    )


@require_http_methods(["GET", "DELETE"])
def api_portfolio(request, pid):
    portfolio = _get_portfolio(pid)
    if portfolio is None:
        return _bad("No saved portfolio with that id.", status=404)

    if request.method == "DELETE":
        portfolio.delete()
        return JsonResponse({"deleted": str(pid)})

    return JsonResponse(_detail(request, portfolio))

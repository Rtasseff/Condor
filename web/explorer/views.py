"""Explorer views: the page plus one JSON analysis endpoint.

This is the HTTP boundary only: validate input, build the domain objects
(via the `compute_analysis` facade today), return `to_dict()` payloads as
JSON. No numerics here — see ARCHITECTURE.md.
"""

import json
import logging
import re

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from condor import DataFetchError, compute_analysis, fetch_prices, risk_free_rate
from condor.stats import METHODS

log = logging.getLogger(__name__)

TICKER_RE = re.compile(r"^[A-Z0-9.\-^]{1,10}$")
MAX_ASSETS = 15


@ensure_csrf_cookie
def index(request):
    """Page shell. Prefills the risk-free field from FRED (3-month
    Treasury constant maturity); if FRED and the cache are both
    unavailable, the template's hardcoded default stands."""
    rf = None
    try:
        rf = risk_free_rate()  # cached ~12h next to the price store
    except Exception:
        log.warning("risk-free rate unavailable; using field default")
    ctx = {"rf": rf, "rf_pct": round(rf["rate"] * 100, 2) if rf else 4.0}
    return render(request, "explorer/index.html", ctx)


def _bad(msg, status=400):
    return JsonResponse({"error": msg}, status=status)


@require_POST
def api_analyze(request):
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _bad("Request body must be JSON.")

    tickers = body.get("tickers") or []
    if not isinstance(tickers, list) or not tickers:
        return _bad("Add at least one asset.")
    tickers = [str(t).strip().upper() for t in tickers]
    tickers = list(dict.fromkeys(tickers))  # dedupe, keep order
    if len(tickers) > MAX_ASSETS:
        return _bad(f"Prototype is capped at {MAX_ASSETS} assets.")
    for t in tickers:
        if not TICKER_RE.match(t):
            return _bad(f"'{t}' does not look like a ticker symbol.")

    try:
        years = int(body.get("years", 10))
        rf = float(body.get("risk_free_rate", 0.02))
    except (TypeError, ValueError):
        return _bad("years and risk_free_rate must be numbers.")
    if not 1 <= years <= 25:
        return _bad("Lookback must be between 1 and 25 years.")
    if not -0.05 <= rf <= 0.25:
        return _bad("Risk-free rate must be between -5% and 25%.")

    method = body.get("method", "normal")
    if method not in METHODS:
        return _bad(f"method must be one of {METHODS}.")

    weights = body.get("weights") or None
    if weights is not None and not isinstance(weights, dict):
        return _bad("weights must be an object of ticker -> weight.")

    try:
        prices = fetch_prices(tickers, years=years)
        result = compute_analysis(
            prices, weights=weights, risk_free_rate=rf, method=method
        )
    except DataFetchError as e:
        return _bad(str(e))
    except Exception:
        log.exception("analysis failed for %s", tickers)
        return _bad("Analysis failed unexpectedly; see server log.", status=500)

    return JsonResponse(result)

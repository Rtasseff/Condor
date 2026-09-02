"""Explorer views: the page, the JSON analysis endpoint, and saved portfolios.

This is the HTTP boundary only: validate input, build the domain objects
(via the `compute_analysis` facade today), return `to_dict()` payloads as
JSON. No numerics here — see ARCHITECTURE.md. Persistence is the same deal
in reverse: `explorer.models` stores the inputs, `condor` does the maths.
"""

import datetime
import functools
import json
import logging
import math
import re

from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from condor import (AssetSet, DataFetchError, PriceStore, compute_analysis,
                    fetch_prices, risk_free_rate)
from condor.stats import METHODS

from .models import DraftPortfolio, SavedPortfolio

log = logging.getLogger(__name__)

TICKER_RE = re.compile(r"^[A-Z0-9.\-^]{1,10}$")
MAX_ASSETS = 15
MAX_NAME = 80


# ---------------------------------------------------------------- pages


@login_required
@ensure_csrf_cookie
def index(request):
    """`/` — Build: pick assets, see the draft as a pie, friendly copy.
    Login lands here. Numerics happen client-side against `/api/draft`
    and `/api/asset`; this view just renders the shell."""
    return render(request, "explorer/home.html")


def _render_optimize(request, preset=None):
    """The frontier/CAL page (`/optimize`, and `/p/<uuid>`). Prefills the
    risk-free field from FRED (3-month Treasury constant maturity); if
    FRED and the cache are both unavailable, the template's hardcoded
    default stands. `preset` is a saved config injected for the JS to
    load on first paint, taking priority over the user's draft."""
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
    return render(request, "explorer/optimize.html", ctx)


@login_required
@ensure_csrf_cookie
def optimize(request):
    return _render_optimize(request)


@login_required
@ensure_csrf_cookie
def shared_portfolio(request, pid):
    """`/p/<uuid>` — the Optimize page, preloaded with a saved portfolio."""
    portfolio = _get_portfolio(pid)
    if portfolio is None:
        raise Http404("No saved portfolio with that id.")
    preset = {"id": str(portfolio.id), "name": portfolio.name, **portfolio.to_config()}
    return _render_optimize(request, preset=preset)


# ------------------------------------------------------------ validation


def _bad(msg, status=400):
    return JsonResponse({"error": msg}, status=status)


def api_login_required(view):
    """Like login_required, but JSON: a fetch() that has lost its session
    gets a 401 the front end can show, not a redirect to an HTML page."""
    @functools.wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _bad("Login required — reload the page to sign in.", status=401)
        return view(request, *args, **kwargs)
    return wrapped


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


@api_login_required
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


@api_login_required
@require_POST
def api_forecast(request):
    """Rung A forecast: closed-form constant-rate fan for the given mix.

    Same input contract as api_analyze plus `horizon_years` (1-30).
    Boundary is lenient about weights exactly like AssetSet.analysis():
    unknown tickers ignored, negatives clipped, all-zero -> equal.
    """
    body, err = _json_body(request)
    if err:
        return _bad(err)
    tickers, err = _clean_tickers(body.get("tickers") or [])
    if err:
        return _bad(err)
    settings, err = _clean_settings(body)
    if err:
        return _bad(err)
    try:
        horizon = float(body.get("horizon_years", 2))
    except (TypeError, ValueError):
        return _bad("horizon_years must be a number.")
    if not 1 <= horizon <= 30:
        return _bad("Forecast horizon must be between 1 and 30 years.")
    weights = body.get("weights") or None
    if weights is not None and not isinstance(weights, dict):
        return _bad("weights must be an object of ticker -> weight.")
    model = body.get("model", "steady")
    if model not in ("steady", "bootstrap"):
        return _bad("model must be 'steady' or 'bootstrap'.")

    try:
        prices = fetch_prices(tickers, years=settings["years"])
        aset = AssetSet(prices, method=settings["method"])
        clean = None
        if weights:  # boundary leniency, same as AssetSet.analysis()
            clean = {t: max(0.0, float(weights.get(t, 0.0)))
                     for t in aset.tickers}
            if sum(clean.values()) <= 0:
                clean = None
        result = aset.portfolio(clean).forecast(horizon_years=horizon,
                                                model=model).to_dict()
    except DataFetchError as e:
        return _bad(str(e))
    except Exception:
        log.exception("forecast failed for %s", tickers)
        return _bad("Forecast failed unexpectedly; see server log.", status=500)
    return JsonResponse(result)


# --------------------------------------------------------------- draft


def _draft_for(user) -> DraftPortfolio:
    """The user's draft (v1: exactly one, auto-created)."""
    draft, _ = DraftPortfolio.objects.get_or_create(owner=user)
    return draft


def _draft_dict(draft):
    return {"assets": draft.assets, "updated_at": draft.updated_at.isoformat()}


def _clean_draft_assets(raw):
    """`[{"symbol": .., "weight": ..}, ...]` -> ([(ticker, weight), ...], error).

    Same ticker rules as elsewhere; rejects unknown-looking or duplicate
    symbols. Weights need not already sum to 1 — `DraftPortfolio.set_assets`
    normalises on save, same rescaling-only contract as `SavedPortfolio`.
    """
    if not isinstance(raw, list) or not raw:
        return None, "Add at least one asset."
    if len(raw) > MAX_ASSETS:
        return None, f"Prototype is capped at {MAX_ASSETS} assets."
    seen = set()
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            return None, "each asset must be an object."
        symbol = str(entry.get("symbol") or "").strip().upper()
        if not TICKER_RE.match(symbol):
            return None, f"'{symbol}' does not look like a ticker symbol."
        if symbol in seen:
            return None, f"'{symbol}' is listed twice."
        seen.add(symbol)
        try:
            weight = float(entry.get("weight", 0))
        except (TypeError, ValueError):
            return None, f"weight for '{symbol}' must be a number."
        if not math.isfinite(weight) or weight < 0:
            return None, "weights must be non-negative numbers."
        items.append((symbol, weight))
    if sum(w for _, w in items) <= 0:
        return None, "weights must add up to more than zero."
    return items, None


@api_login_required
@require_http_methods(["GET", "PUT"])
def api_draft(request):
    """`GET`: the caller's draft. `PUT`: replace it wholesale — the Build
    page round-trips its whole asset list on every change, and Optimize's
    'Make this my portfolio' writes the adopted mix here too."""
    draft = _draft_for(request.user)
    if request.method == "GET":
        return JsonResponse(_draft_dict(draft))

    body, err = _json_body(request)
    if err:
        return _bad(err)
    items, err = _clean_draft_assets(body.get("assets"))
    if err:
        return _bad(err)
    draft.set_assets(items)
    draft.save()
    return JsonResponse(_draft_dict(draft))


# --------------------------------------------------------------- asset info


ASSET_INFO_DAYS_BUFFER = 400  # days of history fetched for a 1-year return


@functools.lru_cache(maxsize=1)
def _ticker_names():
    """symbol -> display name, from the bundled `tickers.json` (best-effort;
    an unlisted symbol just gets no name)."""
    path = finders.find("explorer/tickers.json")
    if not path:
        return {}
    with open(path) as f:
        rows = json.load(f)
    return {row["t"]: row["n"] for row in rows}


@api_login_required
@require_http_methods(["GET"])
def api_asset(request):
    """`GET /api/asset?symbol=X` — plain facts for one Build-page row:
    display name, last close + its date, and a 1-year simple return.
    Never more than one PriceStore fetch; a store miss degrades to
    `{"ok": false}` rather than a traceback (a brand-new or delisted
    ticker has no history yet)."""
    symbol = str(request.GET.get("symbol") or "").strip().upper()
    if not TICKER_RE.match(symbol):
        return _bad(f"'{symbol}' does not look like a ticker symbol.")
    name = _ticker_names().get(symbol)

    start = datetime.date.today() - datetime.timedelta(days=ASSET_INFO_DAYS_BUFFER)
    try:
        closes = PriceStore().get(symbol, start=start)["close"].dropna()
    except DataFetchError:
        closes = None
    except Exception:
        log.exception("asset info failed for %s", symbol)
        closes = None

    if closes is None or closes.empty:
        return JsonResponse({"ok": False, "symbol": symbol, "name": name})

    last_date = closes.index[-1]
    last_close = float(closes.iloc[-1])
    year_ago = closes[closes.index <= last_date - datetime.timedelta(days=365)]
    year_return = None
    if not year_ago.empty and float(year_ago.iloc[-1]) > 0:
        year_return = last_close / float(year_ago.iloc[-1]) - 1

    return JsonResponse({
        "ok": True,
        "symbol": symbol,
        "name": name,
        "last_close": round(last_close, 4),
        "as_of": str(last_date.date()),
        "year_return": round(year_return, 6) if year_return is not None else None,
    })


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


@api_login_required
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
            for p in SavedPortfolio.objects.filter(
                models.Q(owner=request.user) | models.Q(owner__isnull=True)
            ).prefetch_related("holdings").order_by("-updated_at")
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
        if portfolio.owner is not None and portfolio.owner != request.user:
            return _bad("That portfolio belongs to another user — "
                        "use 'Save as new' to make your own copy.", status=403)

    created = portfolio is None
    with transaction.atomic():
        if portfolio is None:
            portfolio = SavedPortfolio()
        portfolio.owner = request.user
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


@api_login_required
@require_http_methods(["GET", "DELETE"])
def api_portfolio(request, pid):
    portfolio = _get_portfolio(pid)
    if portfolio is None:
        return _bad("No saved portfolio with that id.", status=404)

    if request.method == "DELETE":
        if portfolio.owner is not None and portfolio.owner != request.user:
            return _bad("That portfolio belongs to another user.", status=403)
        portfolio.delete()
        return JsonResponse({"deleted": str(pid)})

    return JsonResponse(_detail(request, portfolio))

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
import smtplib

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import views as auth_views
from django.contrib.auth.models import User
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, models, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit

from condor import (AssetSet, DataFetchError, Forecast, PriceStore,
                    compute_analysis, fetch_prices, risk_free_rate)
from condor.forecast import (ANCHOR_MAX, ANCHOR_MIN, ANCHOR_PRIOR_SD,
                             MARKET_ANCHOR)
from condor.stats import METHODS

from .forms import ALREADY_REGISTERED, SignupForm
from .learn import learn_context
from .models import DraftPortfolio, SavedPortfolio
from .throttle import client_ip, json_rate_limit, rate_for

log = logging.getLogger(__name__)

TICKER_RE = re.compile(r"^[A-Z0-9.\-^]{1,10}$")
MAX_ASSETS = 15
MAX_NAME = 80


# ---------------------------------------------------------------- pages


def anchor_context() -> dict:
    """Template context for the forecast's expected-return control.

    The long-run market number and the range a custom one may take are
    engine constants — the copy on the page reads them from there rather
    than repeating them, so there is one place to change.
    """
    return {
        "market_anchor_pct": f"{100 * MARKET_ANCHOR:g}",
        "anchor_prior_sd_pct": f"{100 * ANCHOR_PRIOR_SD:g}",
        "anchor_min_pct": f"{100 * ANCHOR_MIN:g}",
        "anchor_max_pct": f"{100 * ANCHOR_MAX:g}",
    }


def rf_context() -> dict:
    """Template context for the risk-free rate (FRED 3-month Treasury,
    cached ~12h next to the price store). Both the Optimize field and the
    account page's hypothetical forecast — whose cash sleeve earns this —
    read it from here; if FRED and the cache are both out, callers fall
    back to the field default."""
    rf = None
    try:
        rf = risk_free_rate()
    except Exception:
        log.warning("risk-free rate unavailable; using field default")
    return {"rf": rf, "rf_pct": round(rf["rate"] * 100, 2) if rf else 4.0}


@ensure_csrf_cookie
def index(request):
    """`/` — Explore's entry point: pick assets, see the draft as a pie.
    Login lands here. Numerics happen client-side against `/api/draft`
    and `/api/asset`; this view just renders the shell. `has_real` tells
    the client whether an empty draft should offer "Load my portfolio" —
    read-only, same check `/optimize` uses (fix 1/2's promise applies
    here too: don't invent a starting mix).

    Public: a stranger can build a mix before they have an account. Their
    draft lives in their own browser (`condor.draft.v1` in localStorage,
    see `draft.js`) rather than in `/api/draft`, which still requires a
    login — nothing here reads or writes another person's data. The CSRF
    cookie matters more than ever now: an anonymous visitor's very first
    POST to `/api/analyze` needs a token, and this is where they get one.
    """
    return render(request, "explorer/home.html",
                  {"has_real": _has_holdings(request.user)})


def _has_holdings(user) -> bool:
    """Does the account hold any shares right now? Ledger replay is the
    only truth about that (ADR 0004), so ask the account engine.

    Read-only on purpose: this runs on every `GET /optimize`, and a page
    render must not create an Account row as a side effect — the account
    page creates it lazily when it is actually wanted. A user who has
    never opened that page simply has no holdings. Neither does an
    anonymous visitor, who has no account to replay at all.
    """
    from condor import accounting as acct

    from .models import Account
    if not user.is_authenticated:
        return False
    account = Account.objects.filter(owner=user).first()
    if account is None:
        return False
    try:
        shares, _, _ = acct.replay(account.events_frame())
    except Exception:
        # the page still has to render; a draft (or a preset) keeps the
        # workbench open regardless, and the client re-checks /api/account
        log.exception("holdings check failed for %s", user.pk)
        return False
    return any(n > 1e-9 for n in shares.values())


def _render_optimize(request, preset=None):
    """The frontier/CAL page (`/optimize`, and `/p/<uuid>`). Prefills the
    risk-free field from FRED. `preset` is a saved config injected for the
    JS to load on first paint, taking priority over the user's draft.

    Optimize refuses to invent a portfolio: with no draft, no holdings and
    no preset there is nothing to optimize, so the page renders a signpost
    back to Build instead of the toolbar, chart and example assets. The
    flags are server-side so a fresh user never sees the form flash first.

    An anonymous visitor's draft is in their browser, where the server
    cannot see it, so `has_source` alone would send someone who has just
    built a mix to the signpost. `client_gated` hands that one decision to
    the page: it renders both and an inline head script picks between them
    from localStorage before first paint — still no flash, just a client
    that knows something the server can't. Signed-in visitors keep the
    server-only gate exactly as it was; the one case where their browser
    knows better (a draft carried in from an anonymous session) is handled
    by importing it and reloading, see `signpost.js`.
    """
    user = request.user
    has_draft = bool(user.is_authenticated and _draft_for(user).assets)
    has_real = _has_holdings(user)
    has_source = bool(preset) or has_draft or has_real
    ctx = {
        "preset": preset,
        "has_draft": has_draft,
        "has_real": has_real,
        "has_source": has_source,
        "client_gated": not has_source and not user.is_authenticated,
        # what the source picker may offer (fix 2); a preset is neither
        "sources": {"draft": has_draft, "real": has_real,
                    "preset": bool(preset)},
        **rf_context(),
        **anchor_context(),
    }
    return render(request, "explorer/optimize.html", ctx)


@ensure_csrf_cookie
def optimize(request):
    """`/optimize` — public, like Build: the whole Explore journey works
    without an account (see `index`)."""
    return _render_optimize(request)


@ensure_csrf_cookie
def shared_portfolio(request, pid):
    """`/p/<uuid>` — the Optimize page, preloaded with a saved portfolio.

    Public on purpose: a share link is *meant* to be sent to someone who
    has no account — that is the whole point of sharing one. The uuid is
    the capability; holding the link is the permission. Nothing here
    exposes the owner, and editing still needs a login (`api_portfolios`).
    """
    portfolio = _get_portfolio(pid)
    if portfolio is None:
        raise Http404("No saved portfolio with that id.")
    preset = {"id": str(portfolio.id), "name": portfolio.name, **portfolio.to_config()}
    return _render_optimize(request, preset=preset)


def learn(request):
    """`/learn` — the public front door.

    The videos are public and education is the front door: someone who has
    not been given an account can still watch the sessions and read the
    glossary. Nothing user-specific renders here, so anonymous is the
    normal case rather than a degraded one. Explore is now public too, so
    Learn -> play -> sign in is one unbroken funnel; what still needs a
    login is anything touching a user's own data. Content is static copy
    from `explorer.learn` — no fetches, and the embeds are click-to-load
    facades.
    """
    return render(request, "explorer/learn.html", learn_context())


class ThrottledFormViewMixin:
    """Re-renders the bound form with a 429 instead of processing the POST
    when django-ratelimit has set `request.limited` — shared by every
    rate-limited Django auth FormView so the check/response shape lives
    in one place."""

    def post(self, request, *args, **kwargs):
        if getattr(request, "limited", False):
            return self.render_to_response(
                self.get_context_data(form=self.get_form()), status=429)
        return super().post(request, *args, **kwargs)


@method_decorator(
    ratelimit(key=client_ip, rate=rate_for("login", "10/m"),
              method="POST", block=False),
    name="dispatch")
class ThrottledLoginView(ThrottledFormViewMixin, auth_views.LoginView):
    """The sign-in page, with a per-IP cap on attempts.

    The cap counts POSTs only — reading the page is free, and someone who
    mistypes a password twice never meets it.

    A blocked attempt re-renders the form with a note rather than a bare
    429 body: this is the one rate-limited endpoint a human meets as a
    page, not as a fetch(). The status code is still 429.
    """

    template_name = "explorer/login.html"
    redirect_authenticated_user = True


# ----------------------------------------------------- signup & activation


class ActivationTokenGenerator(PasswordResetTokenGenerator):
    """A distinct key_salt from Django's `default_token_generator` (used for
    password resets) so an activation link and a reset link are never
    interchangeable — check_token() salts its HMAC with this class's
    dotted path, so a token minted by one generator always fails the
    other's check_token(), even for the same user/timestamp."""

    key_salt = "explorer.views.ActivationTokenGenerator"


activation_token_generator = ActivationTokenGenerator()


def _send_activation_email(request, user):
    """One line of what it is, the link, one line of who to ignore it as —
    the same plain-text voice as everywhere else."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = activation_token_generator.make_token(user)
    link = request.build_absolute_uri(reverse("activate", args=[uid, token]))
    body = (
        "Confirm your Condor Funds account by opening this link:\n\n"
        f"{link}\n\n"
        "If you didn't try to sign up, ignore this email."
    )
    send_mail("Confirm your Condor Funds account", body, None, [user.email])


@ratelimit(key=client_ip, rate=rate_for("signup", "5/h"), method="POST", block=False)
def signup(request):
    """`GET/POST /signup` — public, self-serve account creation.

    Closed in production until SMTP is configured (`SIGNUPS_ENABLED`):
    minting an inactive account whose activation link goes to a log file
    would just strand a real person.

    The honeypot check runs before the form does, on the raw POST body —
    a filled `website` field gets the exact same "check your email"
    response as a real signup, with nothing created and nothing logged
    that would tell a bot which part of the form it tripped.
    """
    if not settings.SIGNUPS_ENABLED:
        return render(request, "explorer/signup.html", {"closed": True})

    if request.method != "POST":
        return render(request, "explorer/signup.html", {"form": SignupForm()})

    if getattr(request, "limited", False):
        return render(request, "explorer/signup.html",
                      {"form": SignupForm(request.POST)}, status=429)

    if request.POST.get("website"):
        return render(request, "explorer/signup.html", {
            "sent": True, "email": request.POST.get("email", ""),
        })

    form = SignupForm(request.POST)
    if not form.is_valid():
        return render(request, "explorer/signup.html", {"form": form})

    email = form.cleaned_data["email"]
    is_retry = form.retry_user is not None
    old_password_hash = form.retry_user.password if is_retry else None
    try:
        with transaction.atomic():
            if is_retry:
                user = form.retry_user
                user.set_password(form.cleaned_data["password1"])
                user.save()
            else:
                user = form.save(commit=False)
                user.is_active = False
                user.save()
    except IntegrityError:
        # Two concurrent signups for the same not-yet-existing username
        # both pass form validation's (non-atomic) collision check before
        # either commits — the DB's own unique constraint is what actually
        # catches the second one.
        form.add_error("username", "That username is " + ALREADY_REGISTERED)
        return render(request, "explorer/signup.html", {"form": form})

    # SMTP is a blocking network call, deliberately made outside the
    # transaction above: this app runs on SQLite (a single writer), and
    # holding a write transaction open for the length of that call would
    # serialize every other request behind a slow or hung mail server. A
    # send failure is undone by hand instead of relying on a DB rollback.
    try:
        _send_activation_email(request, user)
    except (smtplib.SMTPException, OSError):
        log.exception("activation email failed for %s", email)
        if is_retry:
            user.password = old_password_hash
            user.save(update_fields=["password"])
        else:
            user.delete()
        return render(request, "explorer/signup.html",
                      {"send_failed": True}, status=502)

    return render(request, "explorer/signup.html", {"sent": True, "email": email})


def activate(request, uidb64, token):
    """`GET /activate/<uidb64>/<token>` — the other half of signup.

    A used-up or garbage token fails `check_token` the same way an
    expired one does (Django doesn't distinguish), so all three land on
    the same sorry page. `login()` below bumps `last_login`, which the
    token's hash covers — that alone stops the same link from being
    replayed after first use, no extra bookkeeping needed.
    """
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is None or not activation_token_generator.check_token(user, token):
        return render(request, "explorer/activate_invalid.html")

    user.is_active = True
    user.save(update_fields=["is_active"])
    auth_login(request, user)
    messages.success(request, "You're in — pretend money, go play.")
    return redirect("index")


@method_decorator(
    ratelimit(key=client_ip, rate=rate_for("reset", "5/h"), method="POST", block=False),
    name="dispatch")
class ThrottledPasswordResetView(ThrottledFormViewMixin, auth_views.PasswordResetView):
    """`/password-reset/` — Django's own view, our templates, our cap.

    Django's don't-reveal-existence behavior (always "check your email",
    whether or not the address has an account) is untouched — nothing
    here overrides `form_valid`.
    """

    template_name = "explorer/password_reset.html"
    email_template_name = "explorer/email/password_reset_email.txt"
    subject_template_name = "explorer/email/password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")


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


def _clean_anchor(body):
    """Validate the forecast's expected-return anchor -> (kwargs, error).

    `anchor` picks what the centre of the fan assumes; only "custom"
    carries a number, and it is bounded so a mistyped 800% can't produce
    a fantasy chart. The blend itself lives in the engine.
    """
    mode = body.get("anchor", "historical")
    if mode not in Forecast.ANCHORS:
        return None, f"anchor must be one of {list(Forecast.ANCHORS)}."
    if mode != "custom":
        return {"anchor": mode, "anchor_value": None}, None
    try:
        value = float(body.get("anchor_value"))
    except (TypeError, ValueError):
        return None, ("anchor_value must be a number — an annual return "
                      "as a fraction, e.g. 0.08 for 8%.")
    if not math.isfinite(value) or not ANCHOR_MIN <= value <= ANCHOR_MAX:
        return None, (f"A custom expected return must be between "
                      f"{ANCHOR_MIN:.0%} and {ANCHOR_MAX:.0%} a year.")
    return {"anchor": mode, "anchor_value": value}, None


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


@json_rate_limit("analyze", "15/m", method="POST")
@require_POST
def api_analyze(request):
    """Analyze a mix. Public — it computes from public price data and
    carries no user state — and rate-limited per IP because it can trigger
    a cold price download."""
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


@json_rate_limit("forecast", "15/m", method="POST")
@require_POST
def api_forecast(request):
    """Forecast the given mix: a fan chart from the model the caller picks.

    Public and rate-limited for the same reasons as `api_analyze`, plus
    one of its own: a bootstrap forecast is the most CPU this box spends
    on a single request.

    Same input contract as api_analyze plus `horizon_years` (1-30),
    `model` ("steady"/"bootstrap") and the expected-return `anchor`
    ("historical"/"market"/"custom" + `anchor_value`).
    Boundary is lenient about weights exactly like AssetSet.analysis():
    unknown tickers ignored, negatives clipped, all-zero -> equal.

    `cash_weight` (0-1, default 0) forecasts the *complete* portfolio —
    this mix constant-mixed with a cash sleeve earning `risk_free_rate`,
    the engine option `Portfolio.forecast` has always had. The account
    page's hypothetical forecast needs it: a setpoint's weights are
    fractions of the whole account, so whatever they leave over is cash.
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
        cash_weight = float(body.get("cash_weight") or 0.0)
    except (TypeError, ValueError):
        return _bad("cash_weight must be a number.")
    if not math.isfinite(cash_weight) or not 0 <= cash_weight <= 1:
        return _bad("cash_weight must be a fraction between 0 and 1.")
    anchor, err = _clean_anchor(body)
    if err:
        return _bad(err)

    try:
        prices = fetch_prices(tickers, years=settings["years"])
        aset = AssetSet(prices, method=settings["method"])
        clean = None
        if weights:  # boundary leniency, same as AssetSet.analysis()
            clean = {t: max(0.0, float(weights.get(t, 0.0)))
                     for t in aset.tickers}
            if sum(clean.values()) <= 0:
                clean = None
        # only a cash sleeve makes the rate matter; passing it otherwise
        # would change the all-risky payload's reported risk_free_rate
        sleeve = ({"cash_weight": cash_weight,
                   "risk_free_rate": settings["risk_free_rate"]}
                  if cash_weight else {})
        result = aset.portfolio(clean).forecast(horizon_years=horizon,
                                                model=model, **sleeve,
                                                **anchor).to_dict()
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
    'Make this my portfolio' writes the adopted mix here too.

    Login required, and it stays that way: this is a *user's* stored data.
    An anonymous visitor's draft never comes here — it lives in their own
    browser under `condor.draft.v1`, and `draft.js` imports it into this
    endpoint once, on the first page load after they sign in."""
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
SERIES_POINTS = 60  # target length of the downsampled sparkline/chart series


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


SERIES_RECENT_DAYS = 35  # dense tail so a client-side "1M" slice isn't blocky


def _downsample(closes, n=SERIES_POINTS, recent_days=SERIES_RECENT_DAYS):
    """Evenly-spaced subset of a close-price Series, biased toward the
    most recent `recent_days` so a client-side "last month" slice still
    shows near-daily resolution rather than the same coarse spacing as
    the full window. First and last point are always real endpoints,
    never interpolated — a shape for a sparkline/chart, not a data
    export."""
    if len(closes) <= n:
        return closes
    cutoff = closes.index[-1] - datetime.timedelta(days=recent_days)
    recent_start = closes.index.searchsorted(cutoff, side="right")
    recent_count = len(closes) - recent_start
    if recent_count >= n:
        positions = sorted({round(i * (len(closes) - 1) / (n - 1)) for i in range(n)})
        return closes.iloc[positions]
    remaining = n - recent_count
    last_older = recent_start - 1
    older_positions = (
        sorted({round(i * last_older / (remaining - 1)) for i in range(remaining)})
        if remaining > 1 else [0])
    return closes.iloc[older_positions + list(range(recent_start, len(closes)))]


@json_rate_limit("asset", "60/m", method="GET")
@require_http_methods(["GET"])
def api_asset(request):
    """`GET /api/asset?symbol=X` — plain facts for one Explore mix row:
    display name, last close + its date, 1-year and 1-month simple
    returns, and a downsampled `series` for an in-app sparkline/chart —
    all from the ~1y of closes this already fetches, no second PriceStore
    call. A store miss degrades to `{"ok": false}` rather than a
    traceback (a brand-new or delisted ticker has no history yet)."""
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

    def _trailing_return(days):
        prior = closes[closes.index <= last_date - datetime.timedelta(days=days)]
        if prior.empty or float(prior.iloc[-1]) <= 0:
            return None
        return last_close / float(prior.iloc[-1]) - 1

    year_return = _trailing_return(365)
    month_return = _trailing_return(30)
    series = _downsample(closes)

    return JsonResponse({
        "ok": True,
        "symbol": symbol,
        "name": name,
        "last_close": round(last_close, 4),
        "as_of": str(last_date.date()),
        "year_return": round(year_return, 6) if year_return is not None else None,
        "month_return": round(month_return, 6) if month_return is not None else None,
        "series": {
            "dates": [str(d.date()) for d in series.index],
            "closes": [round(float(c), 4) for c in series],
        },
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

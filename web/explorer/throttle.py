"""Per-IP rate limiting for the public compute endpoints.

Explore is open to strangers (no account needed to analyze or forecast),
so the endpoints that cost money or CPU — a cold Tiingo fetch, a bootstrap
forecast — need a cap. This module holds the two things every limited view
shares: how we identify a client, and what a limited client is told.

The limits themselves live in `settings.CONDOR_RATE_LIMITS` so a test can
override them without touching the decorators.
"""

import functools

from django.conf import settings
from django.http import JsonResponse
from django_ratelimit.decorators import ratelimit

# Shown to a visitor who has tripped a limit. Plain, unalarmed, and it says
# what to do — this is a person exploring, not an attacker being scolded.
TOO_MANY = ("Whoa — that's a lot of number crunching. "
            "Give it a minute and try again.")


def client_ip(group, request):
    """The real client's IP, for use as a rate-limit key.

    We run behind Fly's proxy, where `REMOTE_ADDR` is the proxy itself —
    keying on it would put every visitor in the world in one bucket, so
    one person's burst would throttle the whole site. Fly sets
    `Fly-Client-IP` to the true peer address and strips any client-sent
    copy, which makes it the one forwarded header we can trust.

    We deliberately do NOT read `X-Forwarded-For`: a client can send that
    header itself, and on a request that reaches us directly (dev, or any
    future non-Fly host) trusting it would hand every visitor a free
    unlimited-rate switch. Off Fly the header is absent and we fall back
    to `REMOTE_ADDR`, which is then the real peer.
    """
    fly = request.headers.get("Fly-Client-IP")
    if fly:
        return fly.strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def rate_for(name, default):
    """A django-ratelimit `rate` callable reading `CONDOR_RATE_LIMITS`.

    Callable rather than a literal so the limit is read per request:
    `override_settings(CONDOR_RATE_LIMITS=...)` then works in tests, where
    a decorator argument frozen at import time would not.
    """
    def rate(group, request):
        return getattr(settings, "CONDOR_RATE_LIMITS", {}).get(name, default)
    return rate


def json_rate_limit(name, default, method=ratelimit.ALL):
    """Cap a JSON endpoint at `CONDOR_RATE_LIMITS[name]` per client IP.

    Over the limit the view never runs and the caller gets a JSON 429 the
    front end already knows how to display (same `{"error": ...}` shape as
    every other refusal here).

    Pass the `method` the view actually answers. The quota is meant to
    meter work, and a request that only ever earns a 405 does none — left
    on ALL, a GET to a POST-only endpoint would spend someone's budget
    without ever reaching the code that costs anything.
    """
    def decorate(view):
        @functools.wraps(view)
        def guarded(request, *args, **kwargs):
            if getattr(request, "limited", False):
                return JsonResponse({"error": TOO_MANY}, status=429)
            return view(request, *args, **kwargs)

        # ratelimit() sets request.limited, then calls guarded() — hence
        # the order: counting has to happen before the check.
        return ratelimit(key=client_ip, rate=rate_for(name, default),
                         method=method, block=False)(guarded)
    return decorate

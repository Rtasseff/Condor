"""Account views: the tracked (pretend or mirrored-real) account.

HTTP boundary only, same rule as views.py: validate, call the engine
(`condor.accounting` — see ADR 0004), return payloads. Valuation uses
RAW closes from the shared PriceStore; nothing derived is stored.
"""

import datetime as dt
import logging

import pandas as pd
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from condor import DataFetchError, PriceStore
from condor import accounting as acct

from .models import Account, AccountEvent, AccountTarget
from .views import (MAX_ASSETS, TICKER_RE, _bad, _json_body,
                    api_login_required)

log = logging.getLogger(__name__)

PRICE_BUFFER_DAYS = 10   # history fetched a bit before the first event


# ---------------------------------------------------------------- helpers


def _account_for(user) -> Account:
    """The user's account (v1: exactly one, auto-created)."""
    acc = Account.objects.filter(owner=user).first()
    return acc or Account.objects.create(owner=user)


def _close_history(tickers, start) -> pd.DataFrame:
    """Raw close prices for valuation (columns = tickers)."""
    store = PriceStore()
    return pd.DataFrame({t: store.get(t, start=start)["close"]
                         for t in sorted(tickers)})


def _last_closes(closes: pd.DataFrame) -> pd.Series:
    return closes.ffill().iloc[-1]


def _round(x, nd=2):
    return round(float(x), nd)


def _state(account: Account) -> dict:
    """Everything the account page needs, derived fresh from the ledger."""
    ev_df = account.events_frame()
    shares, cash, contrib = acct.replay(ev_df)
    targets = account.target_weights()
    tickers = sorted(set(shares) | set(targets))

    today = dt.date.today()
    first = ev_df["date"].min() if len(ev_df) else today
    start = pd.Timestamp(first).date() - dt.timedelta(days=PRICE_BUFFER_DAYS)

    if tickers:
        closes = _close_history(tickers, start)
        last = _last_closes(closes)
        as_of = str(closes.index[-1].date())
    else:  # cash-only account still gets a calendar to chart on
        closes = pd.DataFrame(index=pd.bdate_range(start, today))
        last = pd.Series(dtype=float)
        as_of = str(today)

    daily = acct.daily_state(ev_df, closes)
    twr = acct.time_weighted_return(daily)
    total = float(daily["value"].iloc[-1]) if len(daily) else cash

    alloc = acct.allocation(shares, last, cash) if shares else None
    positions = []
    for t in tickers:
        held = alloc is not None and t in alloc.index
        positions.append({
            "ticker": t,
            "shares": _round(shares.get(t, 0.0), 4),
            "price": _round(last[t], 4) if t in last.index else None,
            "value": _round(alloc.loc[t, "value"]) if held else 0.0,
            "weight": round(float(alloc.loc[t, "weight"]), 6) if held else 0.0,
            "target_weight": round(float(targets.get(t, 0.0)), 6),
        })

    return {
        "account": {"id": str(account.id), "name": account.name},
        "as_of": as_of,
        "cash": _round(cash),
        "total_value": _round(total),
        "net_contributions": _round(contrib),
        "gain": _round(total - contrib),
        "twr": round(twr, 6),
        "target_cash_weight": round(1.0 - sum(targets.values()), 6),
        "positions": positions,
        "series": {
            "dates": [str(d.date()) for d in daily.index],
            "value": [_round(v) for v in daily["value"]],
            "contributions": [_round(v) for v in daily["contributions"]],
        },
        "events": [{
            "id": e.pk, "date": str(e.date), "kind": e.kind,
            "ticker": e.ticker or None, "shares": e.shares,
            "price": e.price, "amount": e.amount, "note": e.note,
        } for e in account.events.order_by("-date", "-created_at", "-pk")],
    }


def _state_response(account):
    try:
        return JsonResponse(_state(account))
    except DataFetchError as e:
        return _bad(str(e))
    except Exception:
        log.exception("account state failed for %s", account.pk)
        return _bad("Could not value the account; see server log.", status=500)


# ------------------------------------------------------------------ page


@login_required
@ensure_csrf_cookie
def account_page(request):
    _account_for(request.user)  # ensure it exists before the JS asks
    return render(request, "explorer/account.html")


# ------------------------------------------------------------------- API


@api_login_required
@require_http_methods(["GET"])
def api_account(request):
    return _state_response(_account_for(request.user))


def _parse_date(raw):
    if raw in (None, ""):
        return dt.date.today(), None
    try:
        d = dt.date.fromisoformat(str(raw))
    except ValueError:
        return None, "date must be YYYY-MM-DD."
    if d > dt.date.today():
        return None, "date cannot be in the future."
    return d, None


def _positive(body, field, allow_zero=False):
    try:
        v = float(body.get(field))
    except (TypeError, ValueError):
        return None, f"{field} must be a number."
    if v < 0 or (v == 0 and not allow_zero):
        return None, f"{field} must be {'>= 0' if allow_zero else '> 0'}."
    return v, None


def _default_price(ticker, on_date):
    """Last close on/before the date, for trades entered without a price."""
    try:
        closes = _close_history(
            [ticker], on_date - dt.timedelta(days=PRICE_BUFFER_DAYS))
    except DataFetchError:
        return None
    upto = closes[closes.index <= pd.Timestamp(on_date)]
    if upto.empty or upto[ticker].dropna().empty:
        return None
    return float(upto[ticker].dropna().iloc[-1])


def _validated_event(account, body):
    """-> (field dict ready for AccountEvent, error). Enforces the
    real-account invariants: no negative cash, no short positions —
    the escape hatch is the explicit set_* force kinds."""
    kind = body.get("kind")
    if kind not in AccountEvent.KINDS:
        return None, f"kind must be one of {AccountEvent.KINDS}."
    date, err = _parse_date(body.get("date"))
    if err:
        return None, err
    fields = {"kind": kind, "date": date,
              "note": str(body.get("note") or "")[:120]}

    if kind in ("deposit", "withdraw", "set_cash"):
        amount, err = _positive(body, "amount", allow_zero=(kind == "set_cash"))
        if err:
            return None, err
        fields["amount"] = amount
    else:
        ticker = str(body.get("ticker") or "").strip().upper()
        if not TICKER_RE.match(ticker):
            return None, f"'{ticker}' does not look like a ticker symbol."
        shares, err = _positive(body, "shares",
                                allow_zero=(kind == "set_shares"))
        if err:
            return None, err
        price = body.get("price")
        if price in (None, ""):
            price = _default_price(ticker, date)
            if price is None:
                return None, (f"No stored close for {ticker} on {date} — "
                              "give a price.")
        try:
            price = float(price)
        except (TypeError, ValueError):
            return None, "price must be a number."
        if price <= 0:
            return None, "price must be > 0."
        fields.update(ticker=ticker, shares=shares, price=price)

    # replay with the candidate appended: keep cash and positions >= 0
    ev_df = account.events_frame()
    candidate = pd.DataFrame([{
        "date": fields["date"], "kind": kind,
        "ticker": fields.get("ticker"), "shares": fields.get("shares"),
        "price": fields.get("price"), "amount": fields.get("amount")}])
    shares_after, cash_after, _ = acct.replay(
        pd.concat([ev_df, candidate], ignore_index=True))
    if cash_after < -1e-6:
        return None, ("Not enough cash on that date's ledger — record a "
                      "deposit first (or use set_cash to force it).")
    low = min(shares_after.values(), default=0.0)
    if low < -1e-9:
        return None, ("That would leave a negative position — check the "
                      "share count (or use set_shares to force it).")
    return fields, None


@api_login_required
@require_POST
def api_account_events(request):
    account = _account_for(request.user)
    body, err = _json_body(request)
    if err:
        return _bad(err)
    fields, err = _validated_event(account, body)
    if err:
        return _bad(err)
    AccountEvent.objects.create(account=account, **fields)
    return _state_response(account)


@api_login_required
@require_http_methods(["DELETE"])
def api_account_event(request, eid):
    account = _account_for(request.user)
    deleted, _ = AccountEvent.objects.filter(pk=eid, account=account).delete()
    if not deleted:
        return _bad("No such ledger entry.", status=404)
    return _state_response(account)


@api_login_required
@require_POST
def api_account_target(request):
    """Replace the setpoint with `{weights: {TICKER: fraction}}`.

    Fractions of total account value; the remainder is cash, so a CAL
    draft (weights summing to the risky share) drops in unchanged."""
    account = _account_for(request.user)
    body, err = _json_body(request)
    if err:
        return _bad(err)
    raw = body.get("weights")
    if not isinstance(raw, dict) or not raw:
        return _bad("weights must be an object of ticker -> fraction.")
    if len(raw) > MAX_ASSETS:
        return _bad(f"Prototype is capped at {MAX_ASSETS} assets.")
    weights = {}
    for key, value in raw.items():
        ticker = str(key).strip().upper()
        if not TICKER_RE.match(ticker):
            return _bad(f"'{ticker}' does not look like a ticker symbol.")
        try:
            w = float(value)
        except (TypeError, ValueError):
            return _bad(f"weight for '{ticker}' must be a number.")
        if w < 0:
            return _bad("weights must be non-negative fractions.")
        if w > 0:
            weights[ticker] = w
    total = sum(weights.values())
    if total > 1 + 1e-6:
        return _bad("weights are fractions of the account and must sum "
                    "to at most 1 (the rest is cash).")
    with transaction.atomic():
        account.targets.all().delete()
        AccountTarget.objects.bulk_create(
            AccountTarget(account=account, ticker=t, weight=w)
            for t, w in weights.items())
    return _state_response(account)


@api_login_required
@require_http_methods(["GET"])
def api_account_plan(request):
    """Whole-share trades from the current holdings to the setpoint."""
    account = _account_for(request.user)
    targets = account.target_weights()
    shares, cash, _ = acct.replay(account.events_frame())
    tickers = sorted(set(shares) | set(targets))
    if not tickers:
        return _bad("Set a target allocation first (or record holdings).")
    try:
        closes = _close_history(
            tickers, dt.date.today() - dt.timedelta(days=PRICE_BUFFER_DAYS))
        plan = acct.rebalance_plan(shares, _last_closes(closes), cash,
                                   pd.Series(targets, dtype=float))
    except DataFetchError as e:
        return _bad(str(e))
    rows = plan["rows"]
    return JsonResponse({
        "as_of": str(closes.index[-1].date()),
        "total": _round(plan["total"]),
        "cash_before": _round(plan["cash_before"]),
        "cash_after": _round(plan["cash_after"]),
        "target_cash_weight": round(plan["target_cash_weight"], 6),
        "rows": [{
            "ticker": t,
            "price": _round(r["price"], 4),
            "current_shares": _round(r["current_shares"], 4),
            "current_weight": round(float(r["current_weight"]), 6),
            "target_weight": round(float(r["target_weight"]), 6),
            "trade_shares": _round(r["trade_shares"], 4),
            "trade_value": _round(r["trade_value"]),
            "new_weight": round(float(r["new_weight"]), 6),
        } for t, r in rows.iterrows()],
    })


@api_login_required
@require_POST
def api_account_plan_confirm(request):
    """Write executed trades (possibly user-edited) into the ledger.

    Body: {trades: [{ticker, shares (+buy/-sell), price}], date?}.
    Sells are booked before buys so the sells fund the buys."""
    account = _account_for(request.user)
    body, err = _json_body(request)
    if err:
        return _bad(err)
    date, err = _parse_date(body.get("date"))
    if err:
        return _bad(err)
    raw = body.get("trades")
    if not isinstance(raw, list) or not raw:
        return _bad("trades must be a non-empty list.")

    trades = []
    for item in raw:
        if not isinstance(item, dict):
            return _bad("each trade must be an object.")
        ticker = str(item.get("ticker") or "").strip().upper()
        if not TICKER_RE.match(ticker):
            return _bad(f"'{ticker}' does not look like a ticker symbol.")
        try:
            n = float(item.get("shares"))
            price = float(item.get("price"))
        except (TypeError, ValueError):
            return _bad(f"shares and price for {ticker} must be numbers.")
        if n == 0:
            continue
        if price <= 0:
            return _bad("price must be > 0.")
        trades.append((ticker, n, price))
    if not trades:
        return _bad("No non-zero trades to record.")

    trades.sort(key=lambda x: x[1])          # sells (negative) first
    ev_df = account.events_frame()
    candidate = pd.concat([ev_df, pd.DataFrame([{
        "date": date, "kind": "buy" if n > 0 else "sell", "ticker": t,
        "shares": abs(n), "price": p, "amount": None}
        for t, n, p in trades])], ignore_index=True)
    shares_after, cash_after, _ = acct.replay(candidate)
    if cash_after < -1e-6:
        return _bad("Those trades overspend the cash on hand — adjust the "
                    "numbers (or record a deposit first).")
    if min(shares_after.values(), default=0.0) < -1e-9:
        return _bad("Those trades would leave a negative position — "
                    "adjust the share counts.")

    with transaction.atomic():
        for t, n, p in trades:
            AccountEvent.objects.create(
                account=account, date=date,
                kind="buy" if n > 0 else "sell", ticker=t,
                shares=abs(n), price=p, note="rebalance")
    return _state_response(account)

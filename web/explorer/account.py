"""Account views: the tracked (pretend or mirrored-real) account.

HTTP boundary only, same rule as views.py: validate, call the engine
(`condor.accounting` — see ADR 0004), return payloads. Valuation uses
RAW closes from the shared PriceStore; nothing derived is stored.
"""

import datetime as dt
import functools
import logging
import uuid

import pandas as pd
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from condor import AssetSet, DataFetchError, PriceStore, fetch_prices
from condor import accounting as acct
from condor.data import risk_free_rate

from .models import (Account, AccountEvent, AccountTarget,
                     ContributionSchedule)
from .views import (MAX_ASSETS, TICKER_RE, _bad, _clean_anchor, _json_body,
                    anchor_context, api_login_required, rf_context)

log = logging.getLogger(__name__)

PRICE_BUFFER_DAYS = 10   # history fetched a bit before the first event


# ---------------------------------------------------------------- helpers


def _account_for(request) -> Account:
    """The account a request is about. `?account=<uuid>` (query string,
    GET and POST alike) picks one of the user's own; unknown, malformed
    and someone else's ids are indistinguishable (Http404 — no existence
    leak). Without it: the default account (first manual, else first
    mirror), auto-created for a user who has none."""
    if "account" in request.GET:
        try:
            pk = uuid.UUID(request.GET["account"])
        except ValueError:
            raise Http404("No such account.")
        acc = Account.objects.filter(owner=request.user, pk=pk).first()
        if acc is None:
            raise Http404("No such account.")
        return acc
    return (Account.default_for(request.user)
            or Account.objects.create(owner=request.user))


def _json_404(view):
    """API views: an Http404 from `_account_for` becomes a JSON 404."""
    @functools.wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except Http404:
            return _bad("No such account.", status=404)
    return wrapped


def _mirror_guard(account: Account):
    """-> a 403 response if `account` mirrors an imported ledger, else
    None. Called explicitly at the top of every writer (ADR 0005)."""
    if account.mirror:
        return _bad(f"This account mirrors the imported ledger "
                    f"'{account.label}'. Change the source ledger and "
                    "re-import; Condor never writes to it.", status=403)
    return None


def _plan_inputs(account: Account):
    """-> (non-bill shares, cash, targets). Bills sit outside the plan
    math entirely (they accrete; you do not rebalance them)."""
    ev = account.events_frame()
    shares, cash, _ = acct.replay(ev)
    bills = acct.bill_tickers(ev)
    return ({t: n for t, n in shares.items() if t not in bills}, cash,
            account.target_weights())


def _close_history(tickers, start) -> pd.DataFrame:
    """Raw close prices for valuation (columns = tickers)."""
    store = PriceStore()
    return pd.DataFrame({t: store.get(t, start=start)["close"]
                         for t in sorted(tickers)})


def _last_closes(closes: pd.DataFrame) -> pd.Series:
    return closes.ffill().iloc[-1]


def _round(x, nd=2):
    return round(float(x), nd)


def _schedule_dict(account: Account):
    sched = getattr(account, "schedule", None)
    if sched is None:
        return None
    return {"amount": sched.amount, "cadence": sched.cadence,
            "next_due": str(sched.next_due), "enabled": sched.enabled,
            "due": sched.due}


def _opt(x, nd=4):
    return None if x is None or pd.isna(x) else round(float(x), nd)


def _state(account: Account) -> dict:
    """Everything the account page needs, derived fresh from the ledger."""
    ev_df = account.events_frame()
    state = acct.ledger_state(ev_df)
    shares, cash, contrib = state.shares, state.cash, state.contributions
    bills = acct.bill_tickers(ev_df)
    targets = account.target_weights()
    # every exchange ticker ever traded must be priced (a sold-out
    # position still shapes the history); bills price themselves
    traded = set(ev_df.loc[ev_df["kind"].isin(
        ["buy", "sell", "set_shares"]), "ticker"].dropna())
    tickers = sorted((traded | set(targets)) - bills)

    today = dt.date.today()
    first = ev_df["date"].min() if len(ev_df) else today
    start = pd.Timestamp(first).date() - dt.timedelta(days=PRICE_BUFFER_DAYS)

    if tickers:
        closes = _close_history(tickers, start)
        last = _last_closes(closes)
        as_of = str(closes.index[-1].date())
    else:  # cash/bill-only account still gets a calendar to chart on
        closes = pd.DataFrame(index=pd.bdate_range(start, today))
        last = pd.Series(dtype=float)
        as_of = str(today)

    daily = acct.daily_state(ev_df, closes)
    twr = acct.time_weighted_return(daily)
    total = float(daily["value"].iloc[-1]) if len(daily) else cash

    prices = last.copy()
    open_bills = [t for t in shares if t in bills]
    if open_bills:
        day = daily.index[-1] if len(daily) else pd.Timestamp(today)
        bp = acct.bill_prices(ev_df, pd.DatetimeIndex([day])).iloc[0]
        for t in open_bills:
            prices[t] = bp[t]
    alloc = acct.allocation(shares, prices, cash) if shares else None
    hold = acct.holdings(state, prices) if shares else None
    positions = []
    for t in sorted(set(shares) | set(targets)):
        held = alloc is not None and t in alloc.index
        pos = {
            "ticker": t,
            "shares": _round(shares.get(t, 0.0), 4),
            "price": _round(prices[t], 4) if t in prices.index else None,
            "value": _round(alloc.loc[t, "value"]) if held else 0.0,
            "weight": round(float(alloc.loc[t, "weight"]), 6) if held else 0.0,
            "target_weight": round(float(targets.get(t, 0.0)), 6),
            "cost": _round(hold.loc[t, "cost"]) if held else 0.0,
            "avg_cost": _round(hold.loc[t, "avg_cost"], 4) if held else None,
            "unrealized": _round(hold.loc[t, "unrealized"]) if held else 0.0,
            "unrealized_pct": (_opt(hold.loc[t, "unrealized_pct"], 6)
                               if held and hold.loc[t, "cost"] > 1e-12
                               else None),
            "realized": _round(state.realized.get(t, 0.0)),
            "income": _round(state.income.get(t, 0.0)),
            "is_bill": t in bills,
            "maturity": (str(state.bills[t][0].maturity)
                         if t in state.bills and state.bills[t] else None),
        }
        positions.append(pos)

    return {
        "account": {
            "id": str(account.id), "name": account.name,
            "label": account.label, "currency": account.currency,
            "mirror": account.mirror,
            "imported_at": (account.imported_at.isoformat()
                            if account.imported_at else None)},
        "accounts": [{"id": str(a.id), "name": a.name, "label": a.label,
                      "currency": a.currency, "mirror": a.mirror}
                     for a in Account.objects.filter(owner=account.owner)],
        "as_of": as_of,
        "cash": _round(cash),
        "total_value": _round(total),
        "net_contributions": _round(contrib),
        "gain": _round(total - contrib),
        "realized_total": _round(sum(state.realized.values())),
        "unrealized_total": _round(hold["unrealized"].sum()
                                   if hold is not None else 0.0),
        "income_total": _round(sum(state.income.values())),
        "charges_total": _round(state.charges),
        "trade_fees_total": _round(state.trade_fees),
        "twr": round(twr, 6),
        "target_cash_weight": round(1.0 - sum(targets.values()), 6),
        "positions": positions,
        "series": {
            "dates": [str(d.date()) for d in daily.index],
            "value": [_round(v) for v in daily["value"]],
            "contributions": [_round(v) for v in daily["contributions"]],
        },
        "schedule": _schedule_dict(account),
        "events": [{
            "id": e.pk, "date": str(e.date), "kind": e.kind,
            "ticker": e.ticker or None, "shares": e.shares,
            "price": e.price, "amount": e.amount, "fees": e.fees,
            "maturity": str(e.maturity) if e.maturity else None,
            "note": e.note,
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
    _account_for(request)  # ensure it exists (404 for a foreign id)
    # rf_context: an empty account's forecast is hypothetical — run on the
    # setpoint, whose leftover is a cash sleeve that earns the T-bill rate.
    return render(request, "explorer/account.html",
                  {**anchor_context(), **rf_context()})


# ------------------------------------------------------------------- API


@api_login_required
@_json_404
@require_http_methods(["GET"])
def api_account(request):
    return _state_response(_account_for(request))


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
    """-> (field dict ready for AccountEvent, error). Manual accounts
    only. Enforces the real-account invariants: no negative cash, no
    short positions — the escape hatch is the explicit set_* force
    kinds. Bills (`redeem`, `maturity`) come in through import only."""
    kind = body.get("kind")
    if kind not in AccountEvent.KINDS:
        return None, f"kind must be one of {AccountEvent.KINDS}."
    if kind == "redeem" or body.get("maturity") not in (None, ""):
        return None, "Bills come in through import_ledger only."
    date, err = _parse_date(body.get("date"))
    if err:
        return None, err
    fields = {"kind": kind, "date": date,
              "note": str(body.get("note") or "")[:120]}

    if kind in ("buy", "sell", "dividend", "interest") and \
            body.get("fees") not in (None, ""):
        fees, err = _positive(body, "fees", allow_zero=True)
        if err:
            return None, err
        fields["fees"] = fees

    if kind in ("deposit", "withdraw", "set_cash", "fee", "dividend",
                "interest"):
        amount, err = _positive(body, "amount", allow_zero=(kind == "set_cash"))
        if err:
            return None, err
        fields["amount"] = amount
    if kind in ("dividend", "interest", "fee"):
        # a dividend needs its ticker; interest may name one (blank = on
        # the cash balance); a fee is on the account, never a ticker
        ticker = ("" if kind == "fee"
                  else str(body.get("ticker") or "").strip().upper())
        if (ticker or kind == "dividend") and not TICKER_RE.match(ticker):
            return None, f"'{ticker}' does not look like a ticker symbol."
        if ticker:
            fields["ticker"] = ticker
    elif kind not in ("deposit", "withdraw", "set_cash"):
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
        "price": fields.get("price"), "amount": fields.get("amount"),
        "fees": fields.get("fees", 0.0), "maturity": None}])
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
@_json_404
@require_POST
def api_account_events(request):
    account = _account_for(request)
    if (denied := _mirror_guard(account)):
        return denied
    body, err = _json_body(request)
    if err:
        return _bad(err)
    fields, err = _validated_event(account, body)
    if err:
        return _bad(err)
    AccountEvent.objects.create(account=account, **fields)
    return _state_response(account)


@api_login_required
@_json_404
@require_http_methods(["DELETE"])
def api_account_event(request, eid):
    account = _account_for(request)
    if (denied := _mirror_guard(account)):
        return denied
    deleted, _ = AccountEvent.objects.filter(pk=eid, account=account).delete()
    if not deleted:
        return _bad("No such ledger entry.", status=404)
    return _state_response(account)


@api_login_required
@_json_404
@require_POST
def api_account_target(request):
    """Replace the setpoint with `{weights: {TICKER: fraction}}`.

    Fractions of total account value; the remainder is cash, so a CAL
    draft (weights summing to the risky share) drops in unchanged."""
    account = _account_for(request)
    if (denied := _mirror_guard(account)):
        return denied
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
@_json_404
@require_http_methods(["GET"])
def api_account_plan(request):
    """Whole-share trades from the current holdings to the setpoint."""
    account = _account_for(request)
    shares, cash, targets = _plan_inputs(account)
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
@_json_404
@require_POST
def api_account_plan_confirm(request):
    """Write executed trades (possibly user-edited) into the ledger.

    Body: {trades: [{ticker, shares (+buy/-sell), price}], date?}.
    Sells are booked before buys so the sells fund the buys."""
    account = _account_for(request)
    if (denied := _mirror_guard(account)):
        return denied
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


# ------------------------------------------------- regular contributions


@api_login_required
@_json_404
@require_POST
def api_account_schedule(request):
    """Save the DCA schedule: {amount, cadence, next_due?, enabled?}."""
    account = _account_for(request)
    if (denied := _mirror_guard(account)):
        return denied
    body, err = _json_body(request)
    if err:
        return _bad(err)
    amount, err = _positive(body, "amount")
    if err:
        return _bad(err)
    cadence = body.get("cadence", "monthly")
    if cadence not in ContributionSchedule.CADENCES:
        return _bad(f"cadence must be one of {ContributionSchedule.CADENCES}.")
    raw_due = body.get("next_due")
    if raw_due in (None, ""):
        next_due = dt.date.today()
    else:
        try:
            next_due = dt.date.fromisoformat(str(raw_due))
        except ValueError:
            return _bad("next_due must be YYYY-MM-DD.")
    enabled = bool(body.get("enabled", True))
    ContributionSchedule.objects.update_or_create(
        account=account, defaults={"amount": amount, "cadence": cadence,
                                   "next_due": next_due, "enabled": enabled})
    return _state_response(account)


@api_login_required
@_json_404
@require_http_methods(["GET"])
def api_account_contribution(request):
    """Where should this contribution go? Buys-only whole-share plan
    that nudges the account toward its setpoint (engine:
    contribution_plan). ?amount= overrides the scheduled amount."""
    account = _account_for(request)
    raw = request.GET.get("amount")
    if raw in (None, ""):
        sched = getattr(account, "schedule", None)
        if sched is None:
            return _bad("Give an amount (or save a schedule first).")
        amount = sched.amount
    else:
        try:
            amount = float(raw)
        except ValueError:
            return _bad("amount must be a number.")
        if amount <= 0:
            return _bad("amount must be > 0.")
    shares, cash, targets = _plan_inputs(account)
    if not targets:
        return _bad("Set a setpoint allocation first — the plan routes "
                    "money toward it.")
    tickers = sorted(set(shares) | set(targets))
    try:
        closes = _close_history(
            tickers, dt.date.today() - dt.timedelta(days=PRICE_BUFFER_DAYS))
        plan = acct.contribution_plan(shares, _last_closes(closes), cash,
                                      pd.Series(targets, dtype=float), amount)
    except DataFetchError as e:
        return _bad(str(e))
    rows = plan["rows"]
    return JsonResponse({
        "as_of": str(closes.index[-1].date()),
        "amount": plan["amount"],
        "spent": _round(plan["spent"]),
        "cash_after": _round(plan["cash_after"]),
        "total_after": _round(plan["total_after"]),
        "target_cash_weight": round(plan["target_cash_weight"], 6),
        "rows": [{
            "ticker": t,
            "price": _round(r["price"], 4),
            "current_weight": round(float(r["current_weight"]), 6),
            "target_weight": round(float(r["target_weight"]), 6),
            "buy_shares": _round(r["buy_shares"], 4),
            "buy_value": _round(r["buy_value"]),
            "new_weight": round(float(r["new_weight"]), 6),
        } for t, r in rows.iterrows()],
    })


@api_login_required
@_json_404
@require_POST
def api_account_contribution_confirm(request):
    """Book a contribution: one deposit + the (possibly edited) buys.
    Advances the schedule when this covers a due date."""
    account = _account_for(request)
    if (denied := _mirror_guard(account)):
        return denied
    body, err = _json_body(request)
    if err:
        return _bad(err)
    date, err = _parse_date(body.get("date"))
    if err:
        return _bad(err)
    amount, err = _positive(body, "amount")
    if err:
        return _bad(err)
    raw = body.get("trades") or []
    if not isinstance(raw, list):
        return _bad("trades must be a list.")
    buys = []
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
        if n < 0:
            return _bad("a contribution only buys — use the rebalancing "
                        "plan to sell.")
        if n == 0:
            continue
        if price <= 0:
            return _bad("price must be > 0.")
        buys.append((ticker, n, price))

    spend = sum(n * p_ for _, n, p_ in buys)
    _, cash_now, _ = acct.replay(account.events_frame())
    if spend > cash_now + amount + 1e-6:
        return _bad("Those buys cost more than the contribution plus the "
                    "cash on hand — trim a buy.")

    with transaction.atomic():
        AccountEvent.objects.create(account=account, date=date,
                                    kind="deposit", amount=amount,
                                    note="contribution")
        for t, n, p_ in buys:
            AccountEvent.objects.create(account=account, date=date,
                                        kind="buy", ticker=t, shares=n,
                                        price=p_, note="contribution")
        sched = getattr(account, "schedule", None)
        if sched is not None and sched.enabled and sched.next_due <= date:
            sched.advance(date)
            sched.save()
    return _state_response(account)


# ------------------------------------------------------ account forecast


@api_login_required
@_json_404
@require_POST
def api_account_forecast(request):
    """Forecast the COMPLETE account: current holdings (value-weighted)
    constant-mixed with its cash share at the live risk-free rate.
    Statistics use adjusted closes (fetch_prices); valuation weights
    use raw last closes — same split as everywhere else."""
    account = _account_for(request)
    if account.currency != "USD":
        return _bad("The forecast is USD-only for now.")
    body, err = _json_body(request)
    if err:
        return _bad(err)
    try:
        horizon = float(body.get("horizon_years", 2))
    except (TypeError, ValueError):
        return _bad("horizon_years must be a number.")
    if not 1 <= horizon <= 30:
        return _bad("Forecast horizon must be between 1 and 30 years.")
    try:
        years = int(body.get("years", 10))
    except (TypeError, ValueError):
        return _bad("years must be a number.")
    if not 1 <= years <= 25:
        return _bad("Lookback must be between 1 and 25 years.")
    model = body.get("model", "steady")
    if model not in ("steady", "bootstrap"):
        return _bad("model must be 'steady' or 'bootstrap'.")
    anchor, err = _clean_anchor(body)
    if err:
        return _bad(err)

    ev_df = account.events_frame()
    shares, cash, _ = _plan_inputs(account)
    if not shares:
        return _bad("Nothing to project yet — the account holds no assets. "
                    "(All-cash grows at the T-bill rate by definition.)")
    # bills join the cash sleeve at their accreted value
    state = acct.ledger_state(ev_df)
    bill_value = 0.0
    if state.bills:
        bp = acct.bill_prices(
            ev_df, pd.DatetimeIndex([pd.Timestamp(dt.date.today())])).iloc[0]
        bill_value = float(sum(state.shares[t] * bp[t] for t in state.bills))
    try:
        closes = _close_history(
            shares, dt.date.today() - dt.timedelta(days=PRICE_BUFFER_DAYS))
        alloc = acct.allocation(shares, _last_closes(closes), cash)
        total = float(alloc["value"].sum()) + cash + bill_value
        cw = (cash + bill_value) / total if total > 0 else 0.0
        try:
            rf = risk_free_rate()["rate"]
        except Exception:
            log.warning("risk-free rate unavailable; forecasting cash at 4%")
            rf = 0.04
        prices = fetch_prices(sorted(shares), years=years)
        aset = AssetSet(prices)
        fc = aset.portfolio(alloc["value"].to_dict()).forecast(
            horizon_years=horizon, cash_weight=max(0.0, min(1.0, cw)),
            risk_free_rate=rf, model=model, **anchor)
    except DataFetchError as e:
        return _bad(str(e))
    except Exception:
        log.exception("account forecast failed for %s", account.pk)
        return _bad("Forecast failed unexpectedly; see server log.",
                    status=500)
    payload = fc.to_dict()
    payload["start_value"] = _round(total)
    return JsonResponse(payload)

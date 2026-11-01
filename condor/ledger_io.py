"""Ledger exchange format v1.1: read, validate and write the CSVs.

See docs/LEDGER-FORMAT.md (the contract with the portfolio repo) and
ADR 0005. Pure: files/streams in, DataFrames out; no Django, no
database. `import_ledger` / `export_ledger` only persist.

Errors are collected, never partial: a bad file raises one
`LedgerFormatError` carrying every `line N:` message (header = line 1).
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from typing import NamedTuple

import pandas as pd

from .accounting import EVENT_COLUMNS

LEDGER_HEADER = ["date", "account", "ticker", "side", "qty", "price", "fees",
                 "ccy", "maturity", "note"]
TARGETS_HEADER = ["account", "ticker", "weight"]
TARGETS_HEADER_V11 = ["account", "ticker", "weight", "timing", "line"]
PAYIN_HEADER = ["account", "total", "date"]
RULES_HEADER = ["account", "id", "rule", "ticker", "threshold", "action",
                "tranches", "target"]
TIMINGS = ("dca", "lump", "reservoir")
RULE_KINDS = ("below_52w_high", "below_avg_cost", "drift")
ACTIONS = ("alert", "accelerate")

from .symbols import TICKER_RE  # noqa: E402  (the one shared ticker shape)
BILL_RE = re.compile(r"^[A-Z][A-Z0-9]*-(\d{4}-\d{2}-\d{2})$")
LABEL_RE = re.compile(r"^[a-z0-9_]{1,40}$")
CCY_RE = re.compile(r"^[A-Z]{3}$")
NUM_RE = re.compile(r"^\d+(\.\d+)?$")
LONG_DIGITS_RE = re.compile(r"\d{7,}")
CASH = "CASH"

SIDES = ("BUY", "SELL", "DEPOSIT", "WITHDRAW", "DIV", "INTEREST", "FEE",
         "REDEEM")
_KIND = {"DEPOSIT": "deposit", "WITHDRAW": "withdraw", "DIV": "dividend",
         "INTEREST": "interest", "FEE": "fee", "BUY": "buy", "SELL": "sell",
         "REDEEM": "redeem"}
_SIDE = {v: k for k, v in _KIND.items()}
_CASH_SIDES = ("DEPOSIT", "WITHDRAW", "DIV", "INTEREST", "FEE")
_FEES_OK = ("BUY", "SELL", "REDEEM", "DIV", "INTEREST")
_TOL_CASH = 1e-6
_TOL_POS = 1e-9


class LedgerFormatError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


class TargetSpec(NamedTuple):
    weight: float
    timing: str          # "" | dca | lump | reservoir
    line: str            # group key; default = ticker lowercased


class PayInSpec(NamedTuple):
    total: float
    dates: tuple         # of datetime.date, strictly increasing


class RuleSpec(NamedTuple):
    id: str
    rule: str
    ticker: str
    threshold: float
    action: str
    tranches: int | None
    targets: tuple       # tickers; () = every dca line


class LedgerImport(NamedTuple):
    currency: str
    events: pd.DataFrame        # EVENT_COLUMNS + note, in file order


def _open(src):
    """-> (text stream, should_close)."""
    if hasattr(src, "read"):
        return src, False
    return open(src, newline="", encoding="utf-8-sig"), True


def _rows(src, header, alt_headers=()):
    """-> (list[(line_no, row)], errors). Header must match as a set
    (`header`, or one of `alt_headers`)."""
    stream, close = _open(src)
    try:
        reader = csv.reader(stream)
        try:
            head = next(reader)
        except StopIteration:
            return [], ["line 1: empty file (header missing)."]
        if head and head[0].startswith("﻿"):
            head[0] = head[0][1:]
        options = [header, *alt_headers]
        if len(set(head)) != len(head) or not any(
                sorted(head) == sorted(h) for h in options):
            want = " or ".join(",".join(h) for h in options)
            return [], [f"line 1: header must be exactly "
                        f"{want} (got {','.join(head)})."]
        rows = []
        for row in reader:
            if not row:
                continue
            if len(row) != len(head):
                rows.append((reader.line_num, None))
                continue
            rows.append((reader.line_num, dict(zip(head, row))))
        return rows, []
    finally:
        if close:
            stream.close()


def _num(raw, field, errs, line):
    if not NUM_RE.match(raw or ""):
        errs.append(f"line {line}: {field} '{raw}' is not a plain "
                    "non-negative decimal number.")
        return None
    return float(raw)


def _iso(raw, field, errs, line):
    try:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", raw or ""):
            raise ValueError
        return date.fromisoformat(raw)
    except ValueError:
        errs.append(f"line {line}: {field} '{raw}' is not an ISO date "
                    "YYYY-MM-DD.")
        return None


def read_ledger(src, today: date | None = None) -> dict[str, LedgerImport]:
    """Parse and validate a v1 ledger -> {label: LedgerImport}, labels in
    order of first appearance. Raises `LedgerFormatError` with every
    error found."""
    today = today or date.today()
    rows, errs = _rows(src, LEDGER_HEADER)
    if errs:
        raise LedgerFormatError(errs)

    out: dict[str, list[dict]] = {}
    ccys: dict[str, str] = {}
    last_date: dict[str, date] = {}
    cash: dict[str, float] = {}
    pos: dict[str, dict[str, float]] = {}
    tainted: set[str] = set()
    for line, r in rows:
        if r is None:
            errs.append(f"line {line}: wrong number of columns.")
            continue
        n0 = len(errs)
        label = r["account"]
        if not LABEL_RE.match(label):
            errs.append(f"line {line}: account '{label}' must match "
                        "[a-z0-9_]{1,40}.")
        d = _iso(r["date"], "date", errs, line)
        if d and d > today:
            errs.append(f"line {line}: date {d} is in the future.")
        side = r["side"]
        if side not in SIDES:
            errs.append(f"line {line}: side '{side}' is not one of "
                        f"{' '.join(SIDES)}.")
        ticker = r["ticker"]
        bill = BILL_RE.match(ticker)
        if bill:
            try:
                date.fromisoformat(bill.group(1))
            except ValueError:
                errs.append(f"line {line}: bill ticker '{ticker}' has an "
                            "invalid date.")
                bill = None
        qty = _num(r["qty"], "qty", errs, line)
        price = _num(r["price"], "price", errs, line)
        fees = _num(r["fees"], "fees", errs, line)
        if qty is not None and qty <= 0:
            errs.append(f"line {line}: qty must be > 0.")
        if price is not None and price <= 0:
            errs.append(f"line {line}: price must be > 0.")
        if not CCY_RE.match(r["ccy"]):
            errs.append(f"line {line}: ccy '{r['ccy']}' is not an ISO 4217 "
                        "code.")
        elif label in ccys and ccys[label] != r["ccy"]:
            errs.append(f"line {line}: account '{label}' mixes currencies "
                        f"({ccys[label]} and {r['ccy']}).")
        note = r["note"]
        if len(note) > 120:
            errs.append(f"line {line}: note is longer than 120 characters.")
        if LONG_DIGITS_RE.search(note):
            errs.append(f"line {line}: note looks like an identifier "
                        "(a run of 7+ digits).")

        mat = None
        if side in SIDES:
            if side in ("DEPOSIT", "WITHDRAW") and ticker != CASH:
                errs.append(f"line {line}: {side} needs ticker CASH.")
            elif side == "DIV" and (ticker == CASH or bill
                                    or not TICKER_RE.match(ticker)):
                errs.append(f"line {line}: DIV needs a security ticker.")
            elif side in ("INTEREST", "FEE") and ticker != CASH and (
                    bill or not TICKER_RE.match(ticker)):
                errs.append(f"line {line}: {side} needs CASH or a "
                            "security ticker.")
            elif side in ("BUY", "SELL") and ticker == CASH:
                errs.append(f"line {line}: {side} needs a security or "
                            "bill ticker.")
            elif side in ("BUY", "SELL") and not bill and \
                    not TICKER_RE.match(ticker):
                errs.append(f"line {line}: ticker '{ticker}' is not a "
                            "valid ticker or bill identifier.")
            elif side == "REDEEM" and not bill:
                errs.append(f"line {line}: REDEEM needs a bill ticker "
                            "(PREFIX-YYYY-MM-DD).")
            if bill and side not in ("BUY", "SELL", "REDEEM"):
                errs.append(f"line {line}: a bill ticker only takes BUY, "
                            "SELL or REDEEM.")
            if (side in _CASH_SIDES or side == "REDEEM") and price not in \
                    (None, 1.0):
                errs.append(f"line {line}: price must be exactly 1 on "
                            f"{side}.")
            if side in ("BUY", "SELL", "REDEEM") and qty is not None and \
                    "." in r["qty"] and len(r["qty"].split(".")[1]) > 6:
                errs.append(f"line {line}: qty has more than 6 decimals.")
            if fees and side not in _FEES_OK:
                errs.append(f"line {line}: fees must be 0 on {side}.")
            if r["maturity"] and not (side == "BUY" and bill):
                errs.append(f"line {line}: maturity only belongs on a "
                            "bill BUY.")
            elif side == "BUY" and bill:
                mat = _iso(r["maturity"], "maturity", errs, line) \
                    if r["maturity"] else None
                if not r["maturity"]:
                    errs.append(f"line {line}: a bill BUY needs a maturity.")
                elif mat and mat.isoformat() != bill.group(1):
                    errs.append(f"line {line}: maturity {mat} differs from "
                                f"the date in {ticker}.")
                elif mat and d and mat <= d:
                    errs.append(f"line {line}: maturity must be after the "
                                "settlement date.")
        if d and label in last_date and d < last_date[label]:
            errs.append(f"line {line}: date {d} goes backwards for "
                        f"account '{label}'.")
        if d:
            last_date[label] = max(d, last_date.get(label, d))
        if len(errs) > n0:
            tainted.add(label)
            continue
        if label in tainted:    # its tally is incomplete: no cascades
            continue

        # running tally: cash and positions never go negative
        c = cash.get(label, 0.0)
        p = pos.setdefault(label, {})
        if side == "DEPOSIT":
            c += qty
        elif side == "WITHDRAW":
            c -= qty
        elif side == "BUY":
            c -= qty * price + fees
            p[ticker] = p.get(ticker, 0.0) + qty
        elif side in ("SELL", "REDEEM"):
            if side == "REDEEM":
                if d < date.fromisoformat(bill.group(1)):
                    errs.append(f"line {line}: REDEEM on {d} is before "
                                f"maturity {bill.group(1)}.")
                    tainted.add(label)
                    continue
                if qty > p.get(ticker, 0.0) + _TOL_POS:
                    errs.append(f"line {line}: REDEEM {r['qty']} exceeds "
                                f"the nominal held "
                                f"({p.get(ticker, 0.0):g}).")
                    tainted.add(label)
                    continue
            c += qty * price - fees
            p[ticker] = p.get(ticker, 0.0) - qty
        elif side in ("DIV", "INTEREST"):
            c += qty - fees
        elif side == "FEE":
            c -= qty
        if p.get(ticker, 0.0) < -_TOL_POS:
            errs.append(f"line {line}: {side} {r['qty']} {ticker} leaves a "
                        "negative position.")
            tainted.add(label)
            continue
        if c < -_TOL_CASH:
            errs.append(f"line {line}: cash would go negative "
                        f"({c:.2f}) after this row.")
            tainted.add(label)
            continue
        cash[label] = c
        ccys.setdefault(label, r["ccy"])

        security = side in ("BUY", "SELL", "REDEEM")
        out.setdefault(label, []).append({
            "date": pd.Timestamp(d), "kind": _KIND[side],
            "ticker": None if ticker == CASH else ticker,
            "shares": qty if security else float("nan"),
            "price": price if security else float("nan"),
            "amount": float("nan") if security else qty,
            "fees": fees,
            "maturity": pd.Timestamp(mat) if mat else pd.NaT,
            "note": note,
        })
    if errs:
        raise LedgerFormatError(errs)
    return {label: LedgerImport(
        ccys[label], pd.DataFrame(recs, columns=EVENT_COLUMNS + ["note"]))
        for label, recs in out.items()}


def read_targets_full(src) -> dict[str, dict[str, TargetSpec]]:
    """Parse targets.csv (v1 or v1.1) -> {label: {ticker: TargetSpec}}.
    v1 files (no timing/line) get timing "" and line = ticker lowercased."""
    rows, errs = _rows(src, TARGETS_HEADER, [TARGETS_HEADER_V11])
    if errs:
        raise LedgerFormatError(errs)
    out: dict[str, dict[str, TargetSpec]] = {}
    where: dict[str, int] = {}
    reservoir: dict[str, str] = {}
    for line, r in rows:
        if r is None:
            errs.append(f"line {line}: wrong number of columns.")
            continue
        n0 = len(errs)
        if not LABEL_RE.match(r["account"]):
            errs.append(f"line {line}: account '{r['account']}' must match "
                        "[a-z0-9_]{1,40}.")
        if not TICKER_RE.match(r["ticker"]) or r["ticker"] == CASH:
            errs.append(f"line {line}: ticker '{r['ticker']}' is not an "
                        "exchange ticker.")
        w = _num(r["weight"], "weight", errs, line)
        if w is not None and w > 1:
            errs.append(f"line {line}: weight must be in [0, 1].")
        timing = r.get("timing", "")
        if timing and timing not in TIMINGS:
            errs.append(f"line {line}: timing '{timing}' is not one of "
                        f"{' '.join(TIMINGS)} (or empty).")
        key = r.get("line", "")
        if key and not LABEL_RE.match(key):
            errs.append(f"line {line}: line '{key}' must match "
                        "[a-z0-9_]{1,40}.")
        if len(errs) > n0:
            continue
        acc = out.setdefault(r["account"], {})
        if r["ticker"] in acc:
            errs.append(f"line {line}: duplicate target for "
                        f"{r['account']}/{r['ticker']}.")
            continue
        if timing == "reservoir":
            if r["account"] in reservoir:
                errs.append(
                    f"line {line}: '{r['account']}' already has a reservoir "
                    f"ticker ({reservoir[r['account']]}); at most one.")
                continue
            reservoir[r["account"]] = r["ticker"]
        acc[r["ticker"]] = TargetSpec(w, timing, key or r["ticker"].lower())
        where[r["account"]] = line
    for label, ws in out.items():
        if sum(s.weight for s in ws.values()) > 1 + 1e-9:
            errs.append(f"line {where[label]}: targets for '{label}' sum to "
                        f"{sum(s.weight for s in ws.values()):.6g}, "
                        "more than 1.")
    if errs:
        raise LedgerFormatError(errs)
    return out


def read_targets(src) -> dict[str, dict[str, float]]:
    """Parse targets.csv -> {label: {ticker: weight}} (weights only)."""
    return {label: {t: s.weight for t, s in specs.items()}
            for label, specs in read_targets_full(src).items()}


def read_payin(src) -> dict[str, PayInSpec]:
    """Parse payin.csv (v1.1) -> {label: PayInSpec}. Future dates are
    fine: it is a plan."""
    rows, errs = _rows(src, PAYIN_HEADER)
    if errs:
        raise LedgerFormatError(errs)
    tot: dict[str, float] = {}
    dts: dict[str, list[date]] = {}
    for line, r in rows:
        if r is None:
            errs.append(f"line {line}: wrong number of columns.")
            continue
        n0 = len(errs)
        label = r["account"]
        if not LABEL_RE.match(label):
            errs.append(f"line {line}: account '{label}' must match "
                        "[a-z0-9_]{1,40}.")
        total = _num(r["total"], "total", errs, line)
        if total is not None and total <= 0:
            errs.append(f"line {line}: total must be > 0.")
        d = _iso(r["date"], "date", errs, line)
        if len(errs) > n0:
            continue
        if label in tot and abs(tot[label] - total) > 1e-9:
            errs.append(f"line {line}: total {r['total']} differs from "
                        f"{tot[label]:g} on the account's earlier rows.")
            continue
        if dts.get(label) and d <= dts[label][-1]:
            errs.append(f"line {line}: date {d} is not after the previous "
                        f"tranche ({dts[label][-1]}); dates must strictly "
                        "increase.")
            continue
        tot.setdefault(label, total)
        dts.setdefault(label, []).append(d)
    if errs:
        raise LedgerFormatError(errs)
    return {label: PayInSpec(tot[label], tuple(ds))
            for label, ds in dts.items()}


def read_rules(src) -> dict[str, list[RuleSpec]]:
    """Parse rules.csv (v1.1) -> {label: [RuleSpec]} in file order."""
    rows, errs = _rows(src, RULES_HEADER)
    if errs:
        raise LedgerFormatError(errs)
    out: dict[str, list[RuleSpec]] = {}
    for line, r in rows:
        if r is None:
            errs.append(f"line {line}: wrong number of columns.")
            continue
        n0 = len(errs)
        label, rid = r["account"], r["id"]
        if not LABEL_RE.match(label):
            errs.append(f"line {line}: account '{label}' must match "
                        "[a-z0-9_]{1,40}.")
        if not LABEL_RE.match(rid):
            errs.append(f"line {line}: id '{rid}' must match "
                        "[a-z0-9_]{1,40}.")
        elif any(x.id == rid for x in out.get(label, [])):
            errs.append(f"line {line}: duplicate rule id '{rid}' for "
                        f"'{label}'.")
        kind = r["rule"]
        if kind not in RULE_KINDS:
            errs.append(f"line {line}: rule '{kind}' is not one of "
                        f"{' '.join(RULE_KINDS)}.")
        ticker = r["ticker"]
        if kind == "drift":
            if ticker:
                errs.append(f"line {line}: a drift rule takes no ticker.")
        elif kind in RULE_KINDS:
            if not ticker:
                errs.append(f"line {line}: {kind} needs a ticker.")
            elif not TICKER_RE.match(ticker) or ticker == CASH:
                errs.append(f"line {line}: ticker '{ticker}' is not an "
                            "exchange ticker.")
        thr = _num(r["threshold"], "threshold", errs, line)
        if thr is not None and thr <= 0:
            errs.append(f"line {line}: threshold must be > 0.")
        action = r["action"]
        if action not in ACTIONS:
            errs.append(f"line {line}: action '{action}' is not one of "
                        f"{' '.join(ACTIONS)}.")
        tranches = None
        if action == "accelerate":
            if not re.match(r"^[1-9]\d{0,3}$", r["tranches"]):
                errs.append(f"line {line}: accelerate needs tranches, an "
                            "integer >= 1.")
            else:
                tranches = int(r["tranches"])
        elif action == "alert" and r["tranches"]:
            errs.append(f"line {line}: tranches must be empty on an alert.")
        targets = tuple(r["target"].split())
        for t in targets:
            if not TICKER_RE.match(t) or t == CASH:
                errs.append(f"line {line}: target '{t}' is not an exchange "
                            "ticker.")
        if len(set(targets)) != len(targets):
            errs.append(f"line {line}: target lists a ticker twice.")
        if len(r["target"]) > 120:
            errs.append(f"line {line}: target is longer than 120 characters.")
        if len(errs) > n0:
            continue
        out.setdefault(label, []).append(
            RuleSpec(rid, kind, ticker, thr, action, tranches, targets))
    if errs:
        raise LedgerFormatError(errs)
    return out


# ------------------------------------------------------------------ write


def _fmt(x) -> str:
    s = f"{float(x):.6f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def _day(x) -> str:
    return pd.Timestamp(x).date().isoformat()


def write_ledger(accounts, dst) -> None:
    """Write `(label, currency, events)` triples as a v1 ledger. `dst` is
    a path or a text stream. Raises ValueError if an account holds
    set_shares / set_cash forces (v1 has no such sides)."""
    lines = []
    for label, ccy, ev in accounts:
        if ev is None or len(ev) == 0:
            continue
        ev = ev.copy()
        ev["date"] = pd.to_datetime(ev["date"])
        ev = ev.sort_values("date", kind="stable")
        forced = ev[ev["kind"].isin(["set_shares", "set_cash"])]
        if len(forced):
            days = ", ".join(sorted({_day(d) for d in forced["date"]}))
            raise ValueError(
                f"account '{label}' has manual set_shares/set_cash events "
                f"on {days}; ledger format v1 cannot express them.")
        for e in ev.to_dict("records"):
            side = _SIDE[e["kind"]]
            tick = e.get("ticker")
            ticker = tick if isinstance(tick, str) and tick else CASH
            security = side in ("BUY", "SELL", "REDEEM")
            qty = e["shares"] if security else e["amount"]
            price = e["price"] if security and side != "REDEEM" else 1
            mat = e.get("maturity")
            note = e.get("note")
            lines.append([
                _day(e["date"]), label, ticker, side, _fmt(qty), _fmt(price),
                _fmt(0 if pd.isna(e.get("fees")) else e["fees"]), ccy,
                _day(mat) if mat is not None and not pd.isna(mat) else "",
                note if isinstance(note, str) else ""])
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(LEDGER_HEADER)
    w.writerows(lines)
    if hasattr(dst, "write"):
        dst.write(buf.getvalue())
    else:
        with open(dst, "w", newline="", encoding="utf-8") as f:
            f.write(buf.getvalue())

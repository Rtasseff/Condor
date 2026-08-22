"""Command-line interface: `python -m condor <command>`.

A thin boundary over the object API, exactly like `web/explorer/views.py`
is for HTTP: parse arguments, build domain objects, format their
`to_dict()` / properties as tables, CSV, or JSON. No numerics here —
see ARCHITECTURE.md.

    python -m condor analyze MSFT NEE CVX --method robust
    python -m condor portfolio MSFT=30 NEE=40 CVX=30
    python -m condor frontier MSFT NEE CVX --csv > frontier.csv
    python -m condor frontier MSFT NEE CVX --html chart.html
    python -m condor data ls | update | purge AAPL
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from . import AssetSet, DataFetchError, PriceStore, fetch_prices, risk_free_rate
from .stats import METHODS

DEFAULT_METHOD = "robust"  # matches the Explorer UI's default


# ----------------------------------------------------------------------
# formatting helpers (presentation only)
# ----------------------------------------------------------------------
def _pct(x: float) -> str:
    return f"{100 * x:.2f}%"


def _weights_str(weights: dict) -> str:
    parts = [f"{t} {100 * w:.1f}%" for t, w in weights.items() if w > 5e-4]
    return " · ".join(parts)


def _row(label: str, d: dict) -> str:
    return (f"{label:<16}{_pct(d['ret']):>10}{_pct(d['vol']):>12}"
            f"{d['sharpe']:>8.2f}   {_weights_str(d['weights'])}")


# ----------------------------------------------------------------------
# shared input handling
# ----------------------------------------------------------------------
def _resolve_rf(value: str) -> tuple[float, str]:
    """'auto' -> FRED 3-month; a number -> percent if >=1, else decimal."""
    if value == "auto":
        try:
            r = risk_free_rate()
            return r["rate"], (f"{_pct(r['rate'])} (3-mo T-bill, FRED, "
                               f"as of {r['as_of']})")
        except DataFetchError:
            return 0.02, "2.00% (FRED unavailable; fallback)"
    rf = float(value)
    if abs(rf) >= 1.0:
        rf /= 100.0
    return rf, f"{_pct(rf)} (given)"


def _asset_set(args) -> AssetSet:
    prices = fetch_prices(args.tickers, years=args.years,
                          source=getattr(args, "source", None))
    return AssetSet(prices, method=args.method)


def _header(aset: AssetSet, rf_note: str) -> str:
    return (f"{', '.join(aset.tickers)} — {aset.method} statistics, "
            f"{aset.start} to {aset.end} ({aset.n_days:,} trading days)\n"
            f"risk-free {rf_note}\n")


# ----------------------------------------------------------------------
# commands
# ----------------------------------------------------------------------
def cmd_analyze(args) -> int:
    rf, rf_note = _resolve_rf(args.rf)
    aset = _asset_set(args)
    if args.json:
        print(json.dumps(aset.analysis(risk_free_rate=rf), indent=1))
        return 0
    out = [_header(aset, rf_note)]
    out.append(f"{'Asset':<8}{'Exp. return':>12}{'Dispersion':>12}")
    for t, row in aset.summary().iterrows():
        out.append(f"{t:<8}{_pct(row['expected_return']):>12}"
                   f"{_pct(row['dispersion']):>12}")
    out.append("")
    out.append(f"{'Portfolio':<16}{'Ret':>10}{'Disp':>12}{'Sharpe':>8}   Weights")
    out.append(_row("Equal weights", aset.equal_weight().to_dict(rf)))
    if len(aset) >= 2:
        out.append(_row("Min dispersion", aset.min_vol().to_dict(rf)))
        tan = aset.tangency(rf)
        if tan is not None:
            out.append(_row("Tangency", tan.to_dict(rf)))
        else:
            out.append(f"{'Tangency':<16}   (no asset beats the risk-free rate)")
    print("\n".join(out))
    return 0


def cmd_portfolio(args) -> int:
    weights = {}
    for pair in args.holdings:
        ticker, sep, w = pair.partition("=")
        if not sep:
            raise SystemExit(f"'{pair}' is not TICKER=WEIGHT")
        weights[ticker.upper()] = float(w)
    rf, rf_note = _resolve_rf(args.rf)
    args.tickers = list(weights)
    aset = _asset_set(args)
    port = aset.portfolio(weights, label="Portfolio")
    if args.json:
        print(json.dumps(port.to_dict(rf), indent=1))
        return 0
    print(_header(aset, rf_note))
    print(f"{'Portfolio':<16}{'Ret':>10}{'Disp':>12}{'Sharpe':>8}   Weights")
    print(_row("Given mix", port.to_dict(rf)))
    return 0


def cmd_frontier(args) -> int:
    rf, rf_note = _resolve_rf(args.rf)
    aset = _asset_set(args)
    fr = aset.frontier(risk_free_rate=rf, n_points=args.points)
    if args.json:
        print(json.dumps(fr.to_dict(), indent=1))
        return 0
    if args.csv:
        cols = ["expected_return", "dispersion", "sharpe"] + aset.tickers
        print(",".join(cols))
        for p in fr:
            d = p.to_dict(rf)
            vals = [f"{d['ret']:.6f}", f"{d['vol']:.6f}", f"{d['sharpe']:.4f}"]
            vals += [f"{d['weights'].get(t, 0.0):.6f}" for t in aset.tickers]
            print(",".join(vals))
        return 0
    if args.html:
        _write_html(args.html, aset, fr, rf)
        print(f"wrote {args.html}")
        return 0
    print(_header(aset, rf_note))
    print(f"{'Point':<16}{'Ret':>10}{'Disp':>12}{'Sharpe':>8}   Weights")
    if fr.min_vol:
        print(_row("Min dispersion", fr.min_vol.to_dict(rf)))
    for i, p in enumerate(fr):
        print(_row(f"  #{i + 1}", p.to_dict(rf)))
    if fr.tangency:
        print(_row("Tangency", fr.tangency.to_dict(rf)))
    return 0


def cmd_data(args) -> int:
    store = PriceStore()
    if args.action == "ls":
        info = store.info()
        print(f"store: {store.root}")
        print("(empty)" if info.empty else info.to_string())
        return 0
    if args.action == "update":
        tickers = args.tickers or store.tickers()
        if not tickers:
            print("store is empty; nothing to update")
            return 0
        info = store.info()
        for t in tickers:
            t = t.upper()
            start = (date.fromisoformat(info.loc[t, "first"])
                     if t in info.index else date(date.today().year - 10, 1, 1))
            frame = store.get(t, start=start, max_age_hours=0.0)
            print(f"{t}: through {frame.index[-1].date()} ({len(frame):,} days)")
        return 0
    if args.action == "purge":
        tickers = args.tickers or store.tickers()
        for t in tickers:
            print(f"{t.upper()}: {'removed' if store.remove(t) else 'not in store'}")
        return 0
    raise SystemExit(f"unknown data action '{args.action}'")


# ----------------------------------------------------------------------
# optional HTML chart (presentation only; numbers come from to_dict)
# ----------------------------------------------------------------------
_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Condor frontier</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script></head>
<body><div id="c" style="max-width:900px;height:600px"></div>
<script>
const d = DATA;
const traces = [
 {x: d.assets.map(a=>a.vol), y: d.assets.map(a=>a.ret), text: d.assets.map(a=>a.ticker),
  mode: "markers+text", textposition: "top center", name: "Assets"},
 {x: d.frontier.map(p=>p.vol), y: d.frontier.map(p=>p.ret), mode: "lines",
  name: "Efficient frontier"}];
if (d.cal) traces.push({x: d.cal.x, y: d.cal.y, mode: "lines",
  line: {dash: "dash"}, name: "Capital allocation line"});
if (d.min_vol) traces.push({x: [d.min_vol.vol], y: [d.min_vol.ret],
  mode: "markers", marker: {size: 12}, name: "Min dispersion"});
if (d.tangency) traces.push({x: [d.tangency.vol], y: [d.tangency.ret],
  mode: "markers", marker: {size: 12}, name: "Tangency"});
Plotly.newPlot("c", traces, {xaxis: {title: "Dispersion (ann.)", tickformat: ".0%"},
  yaxis: {title: "Expected return (ann.)", tickformat: ".0%"},
  title: TITLE});
</script></body></html>
"""


def _write_html(path: str, aset: AssetSet, fr, rf: float) -> None:
    data = {"assets": aset.asset_points(), **fr.to_dict()}
    html = _HTML.replace("DATA", json.dumps(data)).replace(
        "TITLE", json.dumps(f"{', '.join(aset.tickers)} — {aset.method}, "
                            f"rf {100 * rf:.2f}%"))
    with open(path, "w") as f:
        f.write(html)


# ----------------------------------------------------------------------
# parser
# ----------------------------------------------------------------------
def _add_common(sub, tickers=True):
    if tickers:
        sub.add_argument("tickers", nargs="+", metavar="TICKER")
    sub.add_argument("--method", choices=METHODS, default=DEFAULT_METHOD)
    sub.add_argument("--years", type=int, default=10)
    sub.add_argument("--rf", default="auto",
                     help="risk-free rate: 'auto' (FRED 3-mo, default), "
                          "3.9 (percent) or 0.039 (decimal)")
    sub.add_argument("--source", choices=["yfinance", "tiingo"], default=None)
    sub.add_argument("--json", action="store_true", help="raw JSON payload")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="condor", description="Condor Funds portfolio analytics")
    cmds = ap.add_subparsers(dest="command", required=True)

    a = cmds.add_parser("analyze", help="per-asset stats + anchor portfolios")
    _add_common(a)
    a.set_defaults(fn=cmd_analyze)

    p = cmds.add_parser("portfolio", help="performance of a given mix")
    p.add_argument("holdings", nargs="+", metavar="TICKER=WEIGHT",
                   help="e.g. MSFT=30 NEE=40 CVX=30 (any scale; normalized)")
    _add_common(p, tickers=False)
    p.set_defaults(fn=cmd_portfolio)

    f = cmds.add_parser("frontier", help="the efficient frontier point by point")
    _add_common(f)
    f.add_argument("--points", type=int, default=40)
    f.add_argument("--csv", action="store_true", help="CSV to stdout")
    f.add_argument("--html", metavar="FILE", help="write an interactive chart")
    f.set_defaults(fn=cmd_frontier)

    d = cmds.add_parser("data", help="manage the local price store")
    d.add_argument("action", choices=["ls", "update", "purge"])
    d.add_argument("tickers", nargs="*", metavar="TICKER")
    d.set_defaults(fn=cmd_data)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except DataFetchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except (ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

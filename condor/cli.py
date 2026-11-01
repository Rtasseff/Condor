"""Command-line interface: `python -m condor <command>`.

A thin boundary over the object API, exactly like `web/explorer/views.py`
is for HTTP: parse arguments, build domain objects, format their
`to_dict()` / properties as tables, CSV, or JSON. No numerics here —
see ARCHITECTURE.md.

    python -m condor analyze MSFT NEE CVX --method robust
    python -m condor portfolio MSFT=30 NEE=40 CVX=30
    python -m condor analyze MSFT NEE CVX --stability 100
    python -m condor frontier MSFT NEE CVX --csv > frontier.csv
    python -m condor frontier MSFT NEE CVX --html chart.html
    python -m condor data ls | update | purge AAPL
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from pypfopt.exceptions import OptimizationError

from .assumptions import Assumptions
from .data import resolve_proxy
from . import (AssetSet, DataFetchError, PriceStore, fetch_prices,
               risk_free_history, risk_free_rate)
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


def _asset_set(args, rf: float) -> AssetSet:
    """Premium mode (expected return = rf + premium over T-bills) unless
    `--no-premium`; raw mode, with one warning, if the history is missing."""
    prices = fetch_prices(args.tickers, years=args.years,
                          source=getattr(args, "source", None))
    history = None
    if not args.no_premium:
        try:
            history = risk_free_history()
        except Exception:  # fetch failure, corrupt cache: run raw, say so
            print("warning: expected returns are raw: T-bill history "
                  "unavailable", file=sys.stderr)
    return AssetSet(prices, method=args.method, rf_history=history, rf_level=rf)


def _load_assumptions(args) -> Assumptions | None:
    """Read and validate `--assumptions FILE.json` (None when not given)."""
    path = getattr(args, "assumptions", None)
    if not path:
        return None
    if args.no_premium:
        raise ValueError("--assumptions needs premium mode; drop --no-premium")
    try:
        with open(path) as f:
            raw = json.load(f)
    except OSError as e:
        raise ValueError(f"can't read {path}: {e.strerror or e}")
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e}")
    return Assumptions.from_dict(raw)


def _under(args, aset: AssetSet, assumptions: Assumptions) -> AssetSet:
    """`aset` re-estimated under the assumptions, fetching the market proxy
    separately when it isn't one of the analysed tickers (so it can't shorten
    the analysis window)."""
    ref = resolve_proxy(assumptions.prior, aset.tickers, years=args.years,
                        source=getattr(args, "source", None),
                        fetch=fetch_prices)
    return aset.with_options(prior=assumptions.prior, reference_prices=ref)


def _prior_line(under: AssetSet) -> str:
    n = under.prior_note()
    if n["kind"] == "history":
        return "history only (no long-run view); your own views, if any, sit on top"
    s = (f"long-run view counts as {n['t0']:g} years of data, your history as "
         f"{n['t_effective']:.1f} years; market premium "
         f"{_pct(n['market_premium'])} measured against {n['reference']}")
    if n["t_effective"] < n["t_years"] - 1e-9:
        s += " (robust method: history counts less)"
    return s


def _ignored_line(under: AssetSet, cons) -> str:
    ign = list(cons.resolve(under.tickers).ignored) + under.ignored_views()
    return ("not used here: " + "; ".join(ign)) if ign else ""


def _header(aset: AssetSet, rf_note: str) -> str:
    if aset.premium_mode:
        basis = (f"T-bill {_pct(aset.rf_level)} + premium over T-bills "
                 f"(window T-bill mean {_pct(aset.tbill_window_mean)})")
    else:
        basis = "historical average (raw)"
    return (f"{', '.join(aset.tickers)} — {aset.method} statistics, "
            f"{aset.start} to {aset.end} ({aset.n_days:,} trading days)\n"
            f"risk-free {rf_note}\n"
            f"expected return = {basis}\n")


def _meta(aset: AssetSet, rf: float, rf_note: str) -> dict:
    return {**aset.meta(rf), "risk_free_source": rf_note}


# ----------------------------------------------------------------------
# commands
# ----------------------------------------------------------------------
def cmd_analyze(args) -> int:
    assumptions = _load_assumptions(args)
    rf, rf_note = _resolve_rf(args.rf)
    aset = _asset_set(args, rf)
    under = _under(args, aset, assumptions) if assumptions else None
    if args.json:
        payload = aset.analysis(risk_free_rate=rf)
        payload["meta"] = _meta(aset, rf, rf_note)
        if assumptions:
            payload["assumed"] = under.analysis_under(
                assumptions, None, rf, reference_prices=under.reference_prices)
        if args.stability is not None:
            payload["stability"] = aset.stability(rf, n=args.stability)
            if assumptions:
                payload["assumed"]["stability"] = under.stability(
                    rf, assumptions.constraints, n=args.stability)
        print(json.dumps(payload, indent=1))
        return 0
    out = [_header(aset, rf_note)]
    prem = aset.premium_mode
    out.append(f"{'Asset':<8}{'Exp. return':>12}{'Dispersion':>12}"
               + (f"{'Premium':>10}" if prem else ""))
    for t, row in aset.summary().iterrows():
        out.append(f"{t:<8}{_pct(row['expected_return']):>12}"
                   f"{_pct(row['dispersion']):>12}"
                   + (f"{_pct(row['premium']):>10}" if prem else ""))
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
    if assumptions:
        out.append("")
        out.extend(_analyze_under(under, assumptions, rf))
    if args.stability is not None and len(aset) >= 2:
        out.append("")
        out.extend(_stability_lines(aset.stability(rf, n=args.stability),
                                    "on history"))
        if assumptions:
            out.append("")
            out.extend(_stability_lines(
                under.stability(rf, assumptions.constraints, n=args.stability),
                f"under: {assumptions.name}"))
    print("\n".join(out))
    return 0


def _stability_lines(st: dict, label: str) -> list[str]:
    """Stability bands as text; the numbers are the model's."""
    out = [f"How stable is the best mix? {label}: {st['n']} reshuffles of the "
           f"history (blocks of {st['block']} days, seed {st['seed']})",
           f"{'Asset':<8}{'p10':>7}{'median':>8}{'p90':>7}{'held':>7}"]
    for t, v in st["assets"].items():
        if v["held_share"]:
            out.append(f"{t:<8}{_pct(v['p10']):>7}{_pct(v['p50']):>8}"
                       f"{_pct(v['p90']):>7}{_pct(v['held_share']):>7}")
    if st["n_failed"]:
        out.append(f"  {st['n_failed']} of {st['n']} reshuffles had no mix "
                   "beating the risk-free rate or no solution; ranges are "
                   "over the rest")
    out.append("  held = share of reshuffles with more than 1% in the asset. "
               "Wide ranges mean history can't pin this mix down.")
    return out


def _analyze_under(under: AssetSet, assumptions: Assumptions, rf: float):
    cons = assumptions.constraints
    out = [f"Under: {assumptions.name}", f"  {_prior_line(under)}"]
    eq = under.prior_premiums is not None
    out.append(f"{'Asset':<8}{'Exp. return':>12}{'Sample prem.':>14}"
               + (f"{'Prior prem.':>13}" if eq else ""))
    for t, row in under.summary().iterrows():
        out.append(f"{t:<8}{_pct(row['expected_return']):>12}"
                   f"{_pct(row['sample_premium']):>14}"
                   + (f"{_pct(row['prior_premium']):>13}" if eq else ""))
    out.append("")
    out.append(f"{'Portfolio':<16}{'Ret':>10}{'Disp':>12}{'Sharpe':>8}   Weights")
    if len(under) >= 2:
        out.append(_row("Min dispersion", under.min_vol(cons).to_dict(rf)))
        tan = under.tangency(rf, cons)
        out.append(_row("Tangency", tan.to_dict(rf)) if tan is not None else
                   f"{'Tangency':<16}   (no allowed mix beats the risk-free rate)")
        out.append(_row("Max return", under.max_return(cons).to_dict(rf)))
        note = _ignored_line(under, cons)
        if note:
            out.append(f"  {note}")
    return out


def cmd_portfolio(args) -> int:
    assumptions = _load_assumptions(args)
    weights = {}
    for pair in args.holdings:
        ticker, sep, w = pair.partition("=")
        if not sep:
            raise SystemExit(f"'{pair}' is not TICKER=WEIGHT")
        weights[ticker.upper()] = float(w)
    rf, rf_note = _resolve_rf(args.rf)
    args.tickers = list(weights)
    aset = _asset_set(args, rf)
    port = aset.portfolio(weights, label="Portfolio")
    under = _under(args, aset, assumptions) if assumptions else None
    if args.json:
        payload = {**port.to_dict(rf), "meta": _meta(aset, rf, rf_note),
                   "scenarios": port.scenarios()}
        if assumptions:
            payload["assumed"] = under.analysis_under(
                assumptions, weights, rf, reference_prices=under.reference_prices)
        print(json.dumps(payload, indent=1))
        return 0
    print(_header(aset, rf_note))
    print(f"{'Portfolio':<16}{'Ret':>10}{'Disp':>12}{'Sharpe':>8}   Weights")
    print(_row("Given mix", port.to_dict(rf)))
    print()
    print(_history_lines(port.history()))
    print()
    print(_scenario_lines(port.scenarios()))
    if assumptions:
        print()
        print("\n".join(_portfolio_under(under, assumptions, weights, rf)))
    return 0


def _portfolio_under(under: AssetSet, assumptions: Assumptions, weights, rf):
    cons = assumptions.constraints
    mine = under.portfolio(weights, label="Portfolio")
    fr = under.frontier(rf, constraints=cons)
    out = [f"Under: {assumptions.name}", f"  {_prior_line(under)}",
           f"{'Portfolio':<16}{'Ret':>10}{'Disp':>12}{'Sharpe':>8}   Weights",
           _row("Given mix", mine.to_dict(rf))]
    if fr.tangency is not None:
        out.append(_row("Best mix", fr.tangency.to_dict(rf)))
    else:
        out.append(f"{'Best mix':<16}   (no allowed mix beats the risk-free rate)")
    g = fr.gaps(mine)
    why = {
        "no_tangency": "no allowed mix beats the risk-free rate",
        "solver": "the optimizer couldn't finish this comparison",
    }
    steady = "your portfolio is steadier than any mix your limits allow"
    below = "your portfolio earns less than any mix your limits allow"
    above = "your portfolio earns more than any mix your limits allow"

    def line(label, val, fmt, reason):
        text = fmt(val) if val is not None else f"n/a: {reason}"
        out.append(f"  {label:<40}{text}")
    points = lambda x: f"{100 * x:.2f} points"  # noqa: E731
    out.append("How far is your portfolio from the best mix?")
    line("Risk-adjusted return (Sharpe) gap", g["sharpe_gap"],
         lambda x: f"{x:.2f}", why.get(g["sharpe_gap_reason"]))
    line("Return you could add at the same risk", g["return_gap"], points,
         steady if g["return_gap_reason"] == "below_range"
         else why.get(g["return_gap_reason"]))
    line("Risk you could shed at the same return", g["risk_gap"], points,
         {"below_range": below, "above_range": above}.get(
             g["risk_gap_reason"], why.get(g["risk_gap_reason"])))
    if g["violations"]:
        out.append("Your portfolio breaks these limits:")
        out.extend(f"  - {v}" for v in g["violations"])
    note = _ignored_line(under, cons)
    if note:
        out.append(f"  {note}")
    return out


def _scenario_lines(rows: list[dict]) -> str:
    out = ["Stress periods — fixed weights, rebalanced daily; one path "
           "through history, not a forecast",
           f"  {'Period':<24}{'Return':>9}{'Worst fall':>12}"]
    for w in rows:
        if w["covered"]:
            out.append(f"  {w['name']:<24}{_pct(w['ret']):>9}"
                       f"{_pct(w['max_drawdown']):>12}")
        else:
            out.append(f"  {w['name']:<24}not in this mix's shared history "
                       f"(starts {w['first']})")
    return "\n".join(out)


def _history_lines(h) -> str:
    dd = h.max_drawdown
    wy, wr = h.worst_year
    partial = " (partial year)" if h.is_partial(wy) else ""
    if dd["peak"] is None:
        fall = "none (never fell below a prior high)"
    else:
        rec = (f"recovered {dd['recovery'].date()}"
               if dd["recovery"] is not None else "not yet recovered")
        fall = (f"{_pct(dd['depth'])}  {dd['peak'].date()} → "
                f"{dd['trough'].date()}, {rec}")
    return (f"History — {h.basis}\n"
            f"  worst fall   {fall}\n"
            f"  worst year   {wy}: {_pct(wr)}{partial}\n"
            f"  growth/year  {_pct(h.cagr)}")


def cmd_frontier(args) -> int:
    rf, rf_note = _resolve_rf(args.rf)
    aset = _asset_set(args, rf)
    fr = aset.frontier(risk_free_rate=rf, n_points=args.points)
    if args.json:
        print(json.dumps({**fr.to_dict(), "meta": _meta(aset, rf, rf_note)},
                         indent=1))
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
    sub.add_argument("--no-premium", action="store_true",
                     help="raw historical expected returns instead of "
                          "T-bill rate + premium over T-bills")
    sub.add_argument("--json", action="store_true", help="raw JSON payload")


def _add_assumptions(sub):
    sub.add_argument("--assumptions", metavar="FILE.json",
                     help="also show the result under these assumptions "
                          "(limits + long-run view; see docs/CLI.md)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="condor", description="Condor Funds portfolio analytics")
    cmds = ap.add_subparsers(dest="command", required=True)

    a = cmds.add_parser("analyze", help="per-asset stats + anchor portfolios")
    _add_common(a)
    _add_assumptions(a)
    a.add_argument("--stability", nargs="?", type=int, const=100, default=None,
                   metavar="N",
                   help="also show how much the best mix moves on N "
                        "reshuffled versions of the history (default 100)")
    a.set_defaults(fn=cmd_analyze)

    p = cmds.add_parser("portfolio", help="performance of a given mix")
    p.add_argument("holdings", nargs="+", metavar="TICKER=WEIGHT",
                   help="e.g. MSFT=30 NEE=40 CVX=30 (any scale; normalized)")
    _add_common(p, tickers=False)
    _add_assumptions(p)
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
    except OptimizationError as e:
        print(f"error: the optimizer couldn't solve this ({e})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

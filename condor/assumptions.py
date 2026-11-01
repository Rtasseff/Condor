"""Assumptions: a user's limits and long-run view, as a small validated object.

Pure and dependency-free (no pandas, no Django).  `Assumptions.from_dict` is
the one validator -- the API, the CLI and storage all go through it -- and
raises `ValueError` naming the bad field.  `to_dict` round-trips exactly for
input in canonical form (a limit left at its default, 0 for a minimum and 1
for a maximum, is omitted).  See docs/decisions/0008-assumptions-mode.md.

    a = Assumptions.from_dict({
        "name": "Mine",
        "prior": {"kind": "equilibrium", "reference": "VT"},
        "constraints": {"bounds": {"AAA": {"max": 0.30}},
                        "groups": [{"tickers": ["AAA", "BBB"], "max": 0.40}]}})
    a.constraints.resolve(["AAA", "BBB", "CCC"])   # what the optimizer needs
    a.constraints.violations({"AAA": 0.5, ...})    # plain-words breaches
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MAX_GROUPS = 20
MAX_VIEWS = 15
MAX_NAME = 80
KINDS = ("history", "equilibrium")
DEFAULT_REFERENCE = "VT"
DEFAULT_T0 = 20.0
_TOL = 1e-5  # slack when judging a plan against a limit


def _num(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{field} must be a finite number")
    return v


def _weight(value, field: str) -> float:
    v = _num(value, field)
    if not 0.0 <= v <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1")
    return v


def _ticker(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a ticker")
    return value.strip().upper()


def _obj(value, field: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _limits(lo: float, hi: float) -> dict:
    out = {}
    if lo != 0.0:
        out["min"] = lo
    if hi != 1.0:
        out["max"] = hi
    return out


# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Group:
    """A limit on the combined weight of several assets."""

    tickers: tuple[str, ...]
    lo: float = 0.0
    hi: float = 1.0

    @classmethod
    def from_dict(cls, d, field: str = "group") -> "Group":
        d = _obj(d, field)
        raw = d.get("tickers")
        if not isinstance(raw, (list, tuple)) or not raw:
            raise ValueError(f"{field}.tickers must be a non-empty list")
        tickers = tuple(dict.fromkeys(
            _ticker(t, f"{field}.tickers") for t in raw))
        lo = _weight(d.get("min", 0.0), f"{field}.min")
        hi = _weight(d.get("max", 1.0), f"{field}.max")
        if lo > hi:
            raise ValueError(f"{field}: min is above max")
        return cls(tickers, lo, hi)

    def to_dict(self) -> dict:
        return {"tickers": list(self.tickers), **_limits(self.lo, self.hi)}


@dataclass(frozen=True)
class ResolvedConstraints:
    """Constraints matched to one analysis's tickers, ready for the solver.

    bounds: (lo, hi) per asset, in ticker order.
    groups: (member indices, lo, hi) per group still in force.
    ignored: names of limits dropped because their tickers aren't here.
    """

    bounds: tuple[tuple[float, float], ...]
    groups: tuple[tuple[tuple[int, ...], float, float], ...]
    ignored: tuple[str, ...]

    @property
    def binding_possible(self) -> bool:
        """False when every limit is the trivial 0..1 (nothing to enforce)."""
        return (any(b != (0.0, 1.0) for b in self.bounds)
                or any(lo > 0.0 or hi < 1.0 for _, lo, hi in self.groups))


@dataclass(frozen=True)
class Constraints:
    """Per-asset and group weight limits (long-only, fully invested)."""

    bounds: dict[str, tuple[float, float]]
    groups: tuple[Group, ...] = ()

    @classmethod
    def from_dict(cls, d, field: str = "constraints") -> "Constraints":
        d = _obj(d if d is not None else {}, field)
        raw = _obj(d.get("bounds", {}), f"{field}.bounds")
        bounds = {}
        for t, b in raw.items():
            name = _ticker(t, f"{field}.bounds")
            where = f"{field}.bounds.{name}"
            b = _obj(b, where)
            lo = _weight(b.get("min", 0.0), f"{where}.min")
            hi = _weight(b.get("max", 1.0), f"{where}.max")
            if lo > hi:
                raise ValueError(f"{where}: min is above max")
            bounds[name] = (lo, hi)
        graw = d.get("groups", [])
        if not isinstance(graw, (list, tuple)):
            raise ValueError(f"{field}.groups must be a list")
        if len(graw) > MAX_GROUPS:
            raise ValueError(f"{field}.groups: at most {MAX_GROUPS} groups")
        groups = tuple(Group.from_dict(g, f"{field}.groups[{i}]")
                       for i, g in enumerate(graw))
        return cls(bounds, groups)

    def to_dict(self) -> dict:
        return {"bounds": {t: _limits(lo, hi)
                           for t, (lo, hi) in self.bounds.items()},
                "groups": [g.to_dict() for g in self.groups]}

    def resolve(self, tickers) -> ResolvedConstraints:
        """Match the limits to `tickers` (a group keeps the members present
        and is ignored when none are)."""
        tickers = [str(t) for t in tickers]
        pos = {t: i for i, t in enumerate(tickers)}
        bounds = [self.bounds.get(t, (0.0, 1.0)) for t in tickers]
        ignored = [t for t in self.bounds if t not in pos]
        groups = []
        for g in self.groups:
            idx = tuple(pos[t] for t in g.tickers if t in pos)
            if idx:
                groups.append((idx, g.lo, g.hi))
            else:
                ignored.append("group " + " + ".join(g.tickers))
        return ResolvedConstraints(tuple(bounds), tuple(groups), tuple(ignored))

    def violations(self, weights) -> list[str]:
        """Plain-words list of limits `weights` ({ticker: weight}) breaks."""
        out = []
        for t, (lo, hi) in self.bounds.items():
            if t not in weights:
                continue
            w = float(weights[t])
            if w > hi + _TOL:
                out.append(f"{t} {_pct(w)} is above its {_pct(hi)} limit")
            elif w < lo - _TOL:
                out.append(f"{t} {_pct(w)} is below its {_pct(lo)} minimum")
        for g in self.groups:
            present = [t for t in g.tickers if t in weights]
            if not present:
                continue
            w = sum(float(weights[t]) for t in present)
            label = " + ".join(present)
            if w > g.hi + _TOL:
                out.append(f"{label} together {_pct(w)} is above their "
                           f"{_pct(g.hi)} limit")
            elif w < g.lo - _TOL:
                out.append(f"{label} together {_pct(w)} is below their "
                           f"{_pct(g.lo)} minimum")
        return out


@dataclass(frozen=True)
class View:
    """Your own expected annual total return for one asset, +/- `sd`."""

    ticker: str
    ret: float
    sd: float

    @classmethod
    def from_dict(cls, d, field: str = "view") -> "View":
        d = _obj(d, field)
        ret = _num(d.get("ret"), f"{field}.ret")
        sd = _num(d.get("sd"), f"{field}.sd")
        if sd <= 0:
            raise ValueError(f"{field}.sd must be above 0")
        if ret <= -1:
            raise ValueError(f"{field}.ret must be above -1 (-100%)")
        return cls(_ticker(d.get("ticker"), f"{field}.ticker"), ret, sd)

    def to_dict(self) -> dict:
        return {"ticker": self.ticker, "ret": self.ret, "sd": self.sd}


@dataclass(frozen=True)
class Prior:
    """Where expected returns start from before history and views weigh in."""

    kind: str = "equilibrium"
    reference: str = DEFAULT_REFERENCE
    market_premium: float | None = None
    t0: float = DEFAULT_T0
    views: tuple[View, ...] = ()

    @classmethod
    def from_dict(cls, d, field: str = "prior") -> "Prior":
        d = _obj(d if d is not None else {}, field)
        kind = d.get("kind", "equilibrium")
        if kind not in KINDS:
            raise ValueError(f"{field}.kind must be one of {list(KINDS)}")
        reference = _ticker(d.get("reference", DEFAULT_REFERENCE),
                            f"{field}.reference")
        mp = d.get("market_premium")
        if mp is not None:
            mp = _num(mp, f"{field}.market_premium")
            if mp < 0:
                raise ValueError(f"{field}.market_premium must be 0 or more")
        t0 = _num(d.get("t0", DEFAULT_T0), f"{field}.t0")
        if t0 < 0:
            raise ValueError(f"{field}.t0 must be 0 or more")
        raw = d.get("views", [])
        if not isinstance(raw, (list, tuple)):
            raise ValueError(f"{field}.views must be a list")
        if len(raw) > MAX_VIEWS:
            raise ValueError(f"{field}.views: at most {MAX_VIEWS} views")
        views = tuple(View.from_dict(v, f"{field}.views[{i}]")
                      for i, v in enumerate(raw))
        if len({v.ticker for v in views}) != len(views):
            raise ValueError(f"{field}.views: one view per asset")
        return cls(kind, reference, mp, t0, views)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "reference": self.reference,
                "market_premium": self.market_premium, "t0": self.t0,
                "views": [v.to_dict() for v in self.views]}


@dataclass(frozen=True)
class Assumptions:
    """A named set of assumptions: a prior plus weight limits."""

    name: str
    prior: Prior
    constraints: Constraints

    @classmethod
    def from_dict(cls, d) -> "Assumptions":
        d = _obj(d, "assumptions")
        name = d.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")
        name = name.strip()
        if len(name) > MAX_NAME:
            raise ValueError(f"name must be at most {MAX_NAME} characters")
        return cls(name, Prior.from_dict(d.get("prior")),
                   Constraints.from_dict(d.get("constraints")))

    def to_dict(self) -> dict:
        return {"name": self.name, "prior": self.prior.to_dict(),
                "constraints": self.constraints.to_dict()}

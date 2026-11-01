"""CLI = boundary only: parses args, formats object-API output. These
tests run offline — prices and rates are monkeypatched; data commands
run against a temp store with a scripted source."""

import json

import numpy as np
import pandas as pd
import pytest

from condor import cli


@pytest.fixture
def prices():
    rng = np.random.default_rng(11)
    n = 500
    idx = pd.bdate_range("2022-01-03", periods=n)
    rets = 0.0005 + 0.01 * rng.standard_normal((n, 3))
    return pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), index=idx,
                        columns=["AAA", "BBB", "CCC"])


@pytest.fixture(autouse=True)
def offline(monkeypatch, prices):
    monkeypatch.setattr(cli, "fetch_prices",
                        lambda tickers, years=10, source=None:
                        prices[[t.upper() for t in tickers]])
    monkeypatch.setattr(cli, "risk_free_rate",
                        lambda: {"rate": 0.03, "as_of": "2026-08-20",
                                 "maturity": "3m", "series": "DGS3MO"})
    t = np.linspace(0, 1, len(prices))
    monkeypatch.setattr(cli, "risk_free_history",
                        lambda: pd.Series(0.01 + 0.02 * t, index=prices.index))


def run(capsys, *argv):
    code = cli.main(list(argv))
    return code, capsys.readouterr().out


class TestAnalyze:
    def test_table(self, capsys):
        code, out = run(capsys, "analyze", "AAA", "BBB", "CCC")
        assert code == 0
        for label in ("AAA", "Equal weights", "Min dispersion", "Tangency"):
            assert label in out
        assert "3.00% (3-mo T-bill, FRED, as of 2026-08-20)" in out

    def test_json(self, capsys):
        code, out = run(capsys, "analyze", "AAA", "BBB", "--json", "--rf", "2")
        d = json.loads(out)
        assert d["risk_free_rate"] == pytest.approx(0.02)  # 2 -> percent
        assert set(d) >= {"tickers", "portfolio", "frontier", "tangency"}

    def test_single_asset_no_optimization(self, capsys):
        code, out = run(capsys, "analyze", "AAA")
        assert code == 0 and "Equal weights" in out and "Tangency" not in out


class TestPortfolio:
    def test_mix(self, capsys):
        code, out = run(capsys, "portfolio", "AAA=30", "BBB=70", "--rf", "0.02")
        assert code == 0
        assert "AAA 30.0% · BBB 70.0%" in out          # normalized from 30/70
        assert "2.00% (given)" in out

    def test_bad_pair(self, capsys):
        with pytest.raises(SystemExit):
            cli.main(["portfolio", "AAA:30"])

    def test_negative_weight_is_error(self, capsys):
        code, _ = run(capsys, "portfolio", "AAA=-1", "BBB=2")
        assert code == 2


class TestFrontier:
    def test_csv(self, capsys):
        code, out = run(capsys, "frontier", "AAA", "BBB", "CCC",
                        "--points", "6", "--csv")
        lines = out.strip().splitlines()
        assert lines[0] == "expected_return,dispersion,sharpe,AAA,BBB,CCC"
        assert 2 <= len(lines) <= 7
        w = [float(x) for x in lines[1].split(",")[3:]]
        assert sum(w) == pytest.approx(1.0, abs=1e-4)

    def test_json_and_html(self, capsys, tmp_path):
        code, out = run(capsys, "frontier", "AAA", "BBB", "--json")
        assert set(json.loads(out)) == {"min_vol", "tangency", "frontier", "cal", "meta"}
        f = tmp_path / "chart.html"
        code, out = run(capsys, "frontier", "AAA", "BBB", "--html", str(f))
        assert code == 0 and "Plotly.newPlot" in f.read_text()


class TestData:
    @pytest.fixture(autouse=True)
    def temp_store(self, monkeypatch, tmp_path, prices):
        monkeypatch.setenv("CONDOR_DATA_DIR", str(tmp_path / "prices"))

        class Src:
            name = "fake"
            def fetch(self, ticker, start=None):
                s = prices["AAA"]
                if start:
                    s = s.loc[str(start):]
                return pd.DataFrame({"close": s, "adj_close": s})
        monkeypatch.setattr("condor.data.store.get_sources",
                            lambda source=None: [Src()])

    def test_ls_update_purge(self, capsys):
        code, out = run(capsys, "data", "ls")
        assert code == 0 and "(empty)" in out
        from condor import PriceStore
        from datetime import date
        PriceStore().get("XYZ", start=date(2022, 6, 1))
        code, out = run(capsys, "data", "ls")
        assert "XYZ" in out and "fake" in out
        code, out = run(capsys, "data", "update")
        assert code == 0 and "XYZ: through" in out
        code, out = run(capsys, "data", "purge", "XYZ", "NOPE")
        assert "XYZ: removed" in out and "NOPE: not in store" in out
        code, out = run(capsys, "data", "ls")
        assert "(empty)" in out


class TestPremiumAndMeta:
    META = {"window", "method", "premium", "risk_free_rate",
            "tbill_window_mean", "risk_free_source"}

    @pytest.mark.parametrize("cmd", [["analyze", "AAA", "BBB"],
                                     ["portfolio", "AAA=1", "BBB=1"],
                                     ["frontier", "AAA", "BBB", "--points", "5"]])
    def test_json_meta_on_all_three(self, capsys, cmd):
        code, out = run(capsys, *cmd, "--json")
        d = json.loads(out)
        assert code == 0 and set(d["meta"]) == self.META
        assert d["meta"]["premium"] is True
        assert d["meta"]["risk_free_source"].startswith("3.00% (3-mo T-bill")
        assert d["meta"]["window"]["n_days"] == 500
        if cmd[0] == "portfolio":
            assert set(d["history"]) >= {"max_drawdown", "worst_year", "cagr"}

    def test_header_and_premium_column(self, capsys):
        code, out = run(capsys, "analyze", "AAA", "BBB")
        import re
        m = re.search(r"expected return = T-bill 3\.00% \+ premium over T-bills "
                      r"\(window T-bill mean (\d\.\d\d)%\)", out)
        assert m and 1.0 <= float(m.group(1)) <= 3.0
        assert "Premium" in out

    def test_no_premium_reproduces_raw_numbers(self, capsys, prices):
        from condor import AssetSet
        code, out = run(capsys, "analyze", "AAA", "BBB", "--json", "--no-premium")
        d = json.loads(out)
        raw = AssetSet(prices[["AAA", "BBB"]], "robust").analysis(risk_free_rate=0.03)
        assert d["meta"]["premium"] is False
        assert {k: v for k, v in d.items() if k != "meta"} == \
            {k: v for k, v in raw.items() if k != "meta"}
        _, table = run(capsys, "analyze", "AAA", "BBB", "--no-premium")
        assert "Premium" not in table and "historical average (raw)" in table

    def test_history_unavailable_warns_and_runs_raw(self, capsys, monkeypatch):
        def boom():
            raise cli.DataFetchError("FRED down")
        monkeypatch.setattr(cli, "risk_free_history", boom)
        code = cli.main(["analyze", "AAA", "BBB", "--json"])
        cap = capsys.readouterr()
        assert code == 0
        assert cap.err.count("expected returns are raw: T-bill history unavailable") == 1
        assert json.loads(cap.out)["meta"]["premium"] is False

    def test_portfolio_prints_history(self, capsys):
        code, out = run(capsys, "portfolio", "AAA=1", "BBB=1")
        assert "worst fall" in out and "worst year" in out and "growth/year" in out
        assert "fixed weights" in out


class TestScenariosAndStability:
    def test_portfolio_prints_scenarios(self, capsys):
        code, out = run(capsys, "portfolio", "AAA=1", "BBB=1")
        assert code == 0
        assert "Stress periods" in out and "2020 Covid crash" in out
        assert "before this analysis starts (2022-01-03)" in out   # 2008: data is 2022+

    def test_portfolio_json_carries_scenarios(self, capsys):
        code, out = run(capsys, "portfolio", "AAA=1", "BBB=1", "--json")
        sc = json.loads(out)["scenarios"]
        assert [w["name"] for w in sc][0] == "2008 financial crisis"
        # the data starts 2022-01-03, three days after the 2022 window opens
        assert sc[-1]["covered"] is False and sc[-1]["first"] == "2022-01-03"

    def test_analyze_stability_text_and_json(self, capsys):
        code, out = run(capsys, "analyze", "AAA", "BBB", "CCC", "--stability", "6")
        assert code == 0
        assert "How stable is the best mix?" in out and "6 reshuffles" in out
        assert "median" in out
        code, out = run(capsys, "analyze", "AAA", "BBB", "CCC", "--stability",
                        "6", "--json")
        d = json.loads(out)
        assert d["stability"]["n"] == 6 and "scenarios" in d
        plain = json.loads(run(capsys, "analyze", "AAA", "BBB", "CCC", "--json")[1])
        assert "stability" not in plain

    def test_stability_text_names_assets_never_held(self):
        from condor.cli import _stability_lines
        row = {"p10": 0.0, "p50": 0.5, "p90": 1.0, "held_share": 1.0}
        none = {"p10": 0.0, "p50": 0.0, "p90": 0.0, "held_share": 0.0}
        lines = _stability_lines({"n": 5, "n_failed": 0, "block": 21, "seed": 0,
                                  "assets": {"AAA": row, "BBB": none}}, "on history")
        assert "  never held: BBB" in lines
        assert "100.00%" in lines[2] and " 100.00%" in lines[2]  # columns stay apart

    def test_stability_json_with_one_ticker_is_null_not_a_crash(self, capsys):
        code, out = run(capsys, "analyze", "AAA", "--json", "--stability", "5")
        assert code == 0 and json.loads(out)["stability"] is None

    def test_infeasible_limits_are_a_clean_error(self, capsys, tmp_path):
        f = tmp_path / "a.json"
        f.write_text(json.dumps({"name": "x", "prior": {"kind": "history"},
            "constraints": {"bounds": {"AAA": {"min": 0.7}, "BBB": {"min": 0.7}}}}))
        code = cli.main(["analyze", "AAA", "BBB", "--stability", "3",
                         "--assumptions", str(f)])
        assert code == 2
        assert "beat the risk-free" not in capsys.readouterr().out

    def test_bare_stability_flag_means_100(self):
        args = cli.build_parser().parse_args(["analyze", "AAA", "BBB", "--stability"])
        assert args.stability == 100
        args = cli.build_parser().parse_args(["analyze", "AAA", "BBB"])
        assert args.stability is None


class TestAssumptions:
    SET = {"name": "Cautious",
           "prior": {"kind": "equilibrium", "reference": "VT", "t0": 20},
           "constraints": {"bounds": {"AAA": {"max": 0.3}, "ZZZ": {"max": 0.1}},
                           "groups": [{"tickers": ["BBB", "CCC"], "max": 0.8}]}}

    @pytest.fixture(autouse=True)
    def with_proxy(self, monkeypatch, prices):
        rng = np.random.default_rng(5)
        vt = pd.Series(100 * np.cumprod(1 + 0.0004 + 0.008 *
                       rng.standard_normal(len(prices))), index=prices.index,
                       name="VT")
        self.fetched = []

        def fetch(tickers, years=10, source=None):
            self.fetched.append(list(tickers))
            both = prices.join(vt)
            return both[[t.upper() for t in tickers]]
        monkeypatch.setattr(cli, "fetch_prices", fetch)

    def file(self, tmp_path, d=None):
        f = tmp_path / "a.json"
        f.write_text(json.dumps(d or self.SET))
        return str(f)

    def test_analyze_text_adds_an_under_section(self, capsys, tmp_path):
        code, out = run(capsys, "analyze", "AAA", "BBB", "CCC",
                        "--assumptions", self.file(tmp_path))
        assert code == 0
        assert "Under: Cautious" in out and "Sample prem." in out
        assert "Prior prem." in out and "Max return" in out
        assert "not used here: ZZZ" in out
        assert "view on" not in out
        assert out.index("Tangency") < out.index("Under: Cautious")
        assert self.fetched == [["AAA", "BBB", "CCC"], ["VT"]]

    def test_stability_honours_assumptions(self, capsys, tmp_path):
        code, out = run(capsys, "analyze", "AAA", "BBB", "CCC", "--json",
                        "--stability", "6", "--assumptions", self.file(tmp_path))
        d = json.loads(out)
        st = d["assumed"]["stability"]
        assert st["n"] == 6
        if st["n_failed"] < st["n"]:
            assert st["assets"]["AAA"]["p90"] <= 0.3 + 1e-6

    def test_analyze_json_has_assumed(self, capsys, tmp_path):
        code, out = run(capsys, "analyze", "AAA", "BBB", "CCC", "--json",
                        "--assumptions", self.file(tmp_path))
        d = json.loads(out)
        assert d["assumed"]["name"] == "Cautious"
        assert d["assumed"]["tangency"]["weights"]["AAA"] <= 0.3 + 1e-6
        plain = json.loads(run(capsys, "analyze", "AAA", "BBB", "CCC",
                               "--json")[1])
        assert "assumed" not in plain
        d.pop("assumed")
        assert d == plain

    def test_portfolio_gaps_and_violations(self, capsys, tmp_path):
        code, out = run(capsys, "portfolio", "AAA=60", "BBB=20", "CCC=20",
                        "--assumptions", self.file(tmp_path))
        assert code == 0
        assert "Under: Cautious" in out
        assert "Risk-adjusted return (Sharpe) gap" in out
        assert "Return you could add at the same risk" in out
        assert "AAA 60.0% is above its 30.0% limit" in out

    def test_portfolio_json(self, capsys, tmp_path):
        code, out = run(capsys, "portfolio", "AAA=60", "BBB=40", "--json",
                        "--assumptions", self.file(tmp_path))
        assert set(json.loads(out)["assumed"]["gaps"]) >= {"sharpe_gap",
                                                           "violations"}

    def test_errors(self, capsys, tmp_path):
        f = self.file(tmp_path)
        assert cli.main(["analyze", "AAA", "BBB", "--no-premium",
                         "--assumptions", f]) == 2
        assert "needs premium mode" in capsys.readouterr().err
        assert cli.main(["analyze", "AAA", "BBB", "--assumptions",
                         str(tmp_path / "missing.json")]) == 2
        assert "can't read" in capsys.readouterr().err
        bad = self.file(tmp_path, {**self.SET, "prior": {"t0": -1}})
        assert cli.main(["analyze", "AAA", "BBB", "--assumptions", bad]) == 2
        assert "prior.t0" in capsys.readouterr().err
        infeasible = self.file(tmp_path, {"name": "x", "constraints": {"bounds": {
            "AAA": {"min": 0.7}, "BBB": {"min": 0.7}}}})
        assert cli.main(["analyze", "AAA", "BBB", "--assumptions",
                         infeasible]) == 2
        assert "can't all hold" in capsys.readouterr().err

    def test_unused_view_and_partial_group_min_are_listed(self, capsys, tmp_path):
        d = {"name": "x", "prior": {"views": [{"ticker": "QQQ", "ret": .1, "sd": .05}]},
             "constraints": {"groups": [{"tickers": ["AAA", "QQQ"], "min": 0.1}]}}
        code, out = run(capsys, "analyze", "AAA", "BBB",
                        "--assumptions", self.file(tmp_path, d))
        assert code == 0
        assert "minimum not used: QQQ isn't in this mix" in out
        assert "view on QQQ" in out

    def test_optimizer_error_is_a_clean_exit(self, capsys, tmp_path, monkeypatch):
        from pypfopt.exceptions import OptimizationError

        def boom(*a, **k):
            raise OptimizationError("nope")
        monkeypatch.setattr("condor.model._constrained_tangency", boom)
        code = cli.main(["analyze", "AAA", "BBB", "--assumptions",
                         self.file(tmp_path)])
        assert code == 2 and "optimizer couldn't solve" in capsys.readouterr().err

    def test_proxy_resolution_is_shared(self):
        from condor.assumptions import Prior
        from condor.data import resolve_proxy
        seen = []

        def fetch(t, years=10, source=None):
            seen.append((t, years, source))
            return pd.DataFrame({"VT": [1.0]})
        assert resolve_proxy(Prior("history"), ["A"], fetch=fetch) is None
        assert resolve_proxy(Prior("equilibrium", "A"), ["A"], fetch=fetch) is None
        assert list(resolve_proxy(Prior("equilibrium"), ["A"], 7, "tiingo",
                                  fetch)) == [1.0]
        assert seen == [(["VT"], 7, "tiingo")]

    def test_gap_wording_follows_the_reason(self, capsys, tmp_path):
        d = {"name": "x", "constraints": {"bounds": {"AAA": {"min": 0.9}}}}
        code, out = run(capsys, "portfolio", "AAA=0", "BBB=100", "CCC=0",
                        "--assumptions", self.file(tmp_path, d))
        assert code == 0
        assert ("n/a: your portfolio is steadier than any mix your limits allow" in out
                or "n/a: your portfolio earns less than any mix your limits allow" in out
                or "n/a: your portfolio earns more than any mix your limits allow" in out)

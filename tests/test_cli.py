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

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
        assert set(json.loads(out)) == {"min_vol", "tangency", "frontier", "cal"}
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

"""Offline-Tests (unittest): python3 -m unittest discover -s tests -v"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from satellit import indicators as ind  # noqa: E402
from satellit import journal, regime  # noqa: E402
from satellit.config import load_settings  # noqa: E402
from satellit.data import StooqSource, SyntheticSource, _clean  # noqa: E402
from satellit.fx import FxTable  # noqa: E402
from satellit.pipeline import Proposal, select_entries  # noqa: E402
from satellit.screener import ScreenerContext, run_screener  # noqa: E402
from satellit.universe import Constituent, parse_ishares_csv, parse_number, to_yahoo_symbol  # noqa: E402

GERMAN_CSV = """Fondsname,iShares STOXX Europe 600 UCITS ETF (DE)
Positionen zum,"04.Sep.2026"

Emittententicker,Name,Sektor,Anlageklasse,Marktwert,Gewichtung (%),Nominalwert,Nominale,ISIN,Kurs,Standort,Börse,Marktwährung
"SAP","SAP SE","Informationstechnologie","Aktien","1.234.567,89","1,23","1.234.567,89","5.000,00","DE0007164600","210,50","Deutschland","Xetra","EUR"
"BP.","BP PLC","Energie","Aktien","999.999,00","0,80","999.999,00","200.000,00","GB0007980591","420,00","Vereinigtes Königreich","London Stock Exchange","GBP"
"ERIC B","ERICSSON B","Informationstechnologie","Aktien","500.000,00","0,40","500.000,00","60.000,00","SE0000108656","85,00","Schweden","Nasdaq Stockholm AB","SEK"
"ROG","ROCHE HOLDING AG","Gesundheit","Aktien","800.000,00","0,70","800.000,00","3.000,00","CH0012032048","270,00","Schweiz","SIX Swiss Exchange","CHF"
"EUR","EUR CASH","Barmittel und/oder Derivate","Barmittel","1.000,00","0,01","1.000,00","1.000,00","-","1,00","Europa","-","EUR"
"""

ENGLISH_CSV = """Fund Holdings as of,"Sep 04, 2026"

Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Shares,Price,Location,Exchange,Currency,FX Rate,Market Currency,Accrual Date
"AAPL","APPLE INC","Information Technology","Equity","1,000,000.00","6.50","1,000,000.00","5,000.00","200.00","United States","NASDAQ","USD","1.00","USD","-"
"BRK B","BERKSHIRE HATHAWAY INC CLASS B","Financials","Equity","500,000.00","1.60","500,000.00","1,000.00","500.00","United States","New York Stock Exchange Inc.","USD","1.00","USD","-"
"XTSLA","BLK CSH FND TREASURY SL AGENCY","Cash and/or Derivatives","Money Market","10.00","0.00","10.00","10.00","1.00","United States","-","USD","1.00","USD","-"
"""


def make_frame(days: int = 400, seed: int = 1, breakout: bool = False, trend: float = 0.0006) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=date(2026, 9, 4), periods=days)
    rets = rng.normal(trend, 0.012, days)
    if breakout:
        rets[:-110] = rng.normal(0.0015, 0.005, days - 110)   # sauberer Aufwärtstrend
        rets[-110:-6] = rng.normal(0.0, 0.003, 104)           # Base
        rets[-6:] = rng.normal(0.012, 0.002, 6)               # Ausbruch
    close = 100 * np.exp(np.cumsum(rets))
    df = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
                       "volume": np.full(days, 2_000_000.0)}, index=idx)
    df.index.name = "date"
    return df


class TestUniverse(unittest.TestCase):
    def test_parse_number(self):
        self.assertAlmostEqual(parse_number("1.234.567,89"), 1234567.89)
        self.assertAlmostEqual(parse_number("1,234,567.89"), 1234567.89)
        self.assertAlmostEqual(parse_number("12,3"), 12.3)
        self.assertAlmostEqual(parse_number("1,234"), 1234.0)
        self.assertTrue(np.isnan(parse_number("-")))

    def test_german_csv(self):
        cons = parse_ishares_csv(GERMAN_CSV, "EU")
        by = {c.ticker: c for c in cons}
        self.assertEqual(len(cons), 4)                       # Cash-Zeile raus
        self.assertEqual(by["SAP"].symbol, "SAP.DE")
        self.assertEqual(by["SAP"].isin, "DE0007164600")
        self.assertEqual(by["BP."].symbol, "BP.L")
        self.assertEqual(by["BP."].price_scale, 0.01)
        self.assertEqual(by["ERIC B"].symbol, "ERIC-B.ST")
        self.assertEqual(by["ROG"].symbol, "ROG.SW")
        self.assertAlmostEqual(by["SAP"].weight, 1.23)

    def test_english_csv(self):
        cons = parse_ishares_csv(ENGLISH_CSV, "US")
        self.assertEqual([c.symbol for c in cons], ["AAPL", "BRK-B"])
        self.assertEqual(cons[0].sector, "Information Technology")

    def test_symbol_mapping_unknown_exchange(self):
        sym, scale = to_yahoo_symbol("ABC", "Unbekannte Börse", "EUR", "EU")
        self.assertEqual(sym, "ABC")
        self.assertEqual(scale, 1.0)

    def test_stooq_symbols(self):
        self.assertEqual(StooqSource.to_stooq_symbol("AAPL"), "aapl.us")
        self.assertEqual(StooqSource.to_stooq_symbol("SAP.DE"), "sap.de")
        self.assertEqual(StooqSource.to_stooq_symbol("BP.L"), "bp.uk")


class TestIndicators(unittest.TestCase):
    def test_atr_and_breakout(self):
        df = make_frame(300)
        a = ind.atr(df, 20)
        self.assertTrue(np.isfinite(a.iloc[-1]) and a.iloc[-1] > 0)
        w = ind.weekly_closes(df)
        lvl = ind.breakout_level(w, 20)
        self.assertAlmostEqual(lvl, float(w.iloc[-21:-1].max()))

    def test_momentum(self):
        close = pd.Series(np.linspace(100, 200, 300))
        m = ind.momentum(close, 252, 21).iloc[-1]
        self.assertAlmostEqual(m, close.iloc[-22] / close.iloc[-253] - 1)

    def test_clean_handles_columns(self):
        raw = pd.DataFrame({"Date": ["2026-01-02", "2026-01-03"], "Open": [1, 2], "High": [2, 3], "Low": [0.5, 1],
                            "Close": [1.5, 2.5], "Volume": [10, 20]})
        df = _clean(raw)
        self.assertEqual(list(df.columns), ["open", "high", "low", "close", "volume"])
        self.assertEqual(len(df), 2)


class TestScreener(unittest.TestCase):
    def setUp(self):
        self.settings = load_settings(ROOT / "config" / "settings.yaml")
        self.fx = FxTable({}, "test")
        self.ctx = ScreenerContext(satellite_equity_eur=10_000, risk_pct=1.0, as_of=date(2026, 9, 4))

    def test_breakout_is_candidate(self):
        cons = [Constituent("EU", f"DE{i:010d}", f"T{i}", f"Test {i}", "Industrie", "Xetra", "EUR", 1.0, f"T{i}.DE", 1.0)
                for i in range(12)]
        frames = {c.symbol: make_frame(seed=i, breakout=(i == 0), trend=-0.0005 if i else 0.0012)
                  for i, c in enumerate(cons)}
        table = run_screener(cons, frames, self.settings, self.fx, self.ctx)
        row = table[table["symbol"] == "T0.DE"].iloc[0]
        self.assertTrue(row["trend_ok"])
        self.assertTrue(row["breakout"], msg=f"extension={row['extension']}")
        self.assertTrue(row["rs_top"])
        self.assertTrue(row["candidate"], msg=row["reason"])
        self.assertLess(row["initial_stop"], row["close"])

    def test_short_history_rejected(self):
        c = Constituent("US", "US1", "X", "X Corp", "Energie", "NASDAQ", "USD", 1.0, "X", 1.0)
        table = run_screener([c], {"X": make_frame(100)}, self.settings, self.fx, self.ctx)
        self.assertFalse(table.iloc[0]["candidate"])
        self.assertIn("Historie", table.iloc[0]["reason"])


class TestRegime(unittest.TestCase):
    def test_us_states(self):
        cfg = {"green_min": 60, "yellow_min": 40, "veto_below": 40}
        self.assertEqual(regime.us_raw_state(70, 50, cfg), "GREEN")
        self.assertEqual(regime.us_raw_state(70, 35, cfg), "YELLOW")   # Veto
        self.assertEqual(regime.us_raw_state(45, 80, cfg), "YELLOW")
        self.assertEqual(regime.us_raw_state(30, 80, cfg), "RED")
        self.assertIsNone(regime.us_raw_state(None, 80, cfg))

    def test_eu_states(self):
        cfg = {"green_p200": 0.55, "red_p200": 0.40, "red_p50": 0.40}
        self.assertEqual(regime.eu_raw_state(0.60, 0.5, True, cfg), "GREEN")
        self.assertEqual(regime.eu_raw_state(0.60, 0.5, False, cfg), "YELLOW")
        self.assertEqual(regime.eu_raw_state(0.35, 0.5, True, cfg), "RED")
        self.assertEqual(regime.eu_raw_state(0.45, 0.30, False, cfg), "RED")
        self.assertEqual(regime.eu_raw_state(0.45, 0.50, False, cfg), "YELLOW")

    def test_hysteresis(self):
        h = regime.apply_hysteresis
        self.assertEqual(h(["GREEN"], None, 2), "RED")                       # erster Lauf
        self.assertEqual(h(["GREEN", "GREEN"], None, 2), "GREEN")
        self.assertEqual(h(["GREEN", "RED"], "GREEN", 2), "RED")             # sofort runter
        self.assertEqual(h(["RED", "GREEN"], "RED", 2), "RED")               # noch nicht hoch
        self.assertEqual(h(["GREEN", "GREEN"], "RED", 2), "GREEN")           # nach 2 Wochen hoch
        self.assertEqual(h(["YELLOW", "GREEN"], "RED", 2), "RED")            # gemischt: bleibt
        self.assertEqual(h(["GREEN", "YELLOW"], "RED", 2), "YELLOW")
        self.assertEqual(h([None], "GREEN", 2), "RED")                       # unbekannt = rot

    def test_eu_breadth(self):
        frames = {"A": make_frame(300, seed=1, trend=0.002), "B": make_frame(300, seed=2, trend=-0.002), "IDX": make_frame(300, seed=3, trend=0.002)}
        p200, p50, idx_above, n = regime.eu_breadth(frames, ["A", "B"], "IDX", date(2026, 9, 4))
        self.assertEqual(n, 2)
        self.assertAlmostEqual(p200, 0.5)
        self.assertTrue(idx_above)


class TestSelection(unittest.TestCase):
    def test_limits(self):
        settings = load_settings(ROOT / "config" / "settings.yaml")
        rows = []
        for i in range(6):
            rows.append({"region": "US" if i < 4 else "EU", "symbol": f"S{i}", "isin": f"I{i}", "name": f"N{i}",
                         "sector": "Tech" if i < 3 else "Health", "currency": "USD" if i < 4 else "EUR",
                         "close": 100.0, "initial_stop": 94.0, "atr": 2.0, "breakout_level": 99.0,
                         "rs_rank_pct": 0.01 * (i + 1), "rs_score": 1.0 - 0.1 * i, "candidate": True})
        table = pd.DataFrame(rows)
        readings = {"US": regime.RegimeReading("2026-09-04", "US", "GREEN", "GREEN"),
                    "EU": regime.RegimeReading("2026-09-04", "EU", "RED", "RED")}
        acc = journal.Account(satellite_equity_eur=10_000, high_water_mark=10_000)
        props, skipped = select_entries(settings, table, readings, [], acc, FxTable({}, "t"),
                                        {"US": 1.0, "EU": 1.0}, blocked=False)
        self.assertEqual([p.symbol for p in props], ["S0", "S1"])          # max 2 je Woche (GRÜN), EU rot
        self.assertTrue(any("Sektor" in s for s in skipped) or any("Limit" in s for s in skipped))
        for p in props:
            self.assertLessEqual(p.value_eur, 2500)                           # 25 % Deckel
            self.assertLessEqual(p.risk_eur, 100 + 1e-6)                      # 1 % Risiko

    def test_blocked(self):
        settings = load_settings(ROOT / "config" / "settings.yaml")
        table = pd.DataFrame([{"region": "US", "symbol": "S", "isin": "I", "name": "N", "sector": "Tech", "currency": "USD",
                               "close": 100.0, "initial_stop": 94.0, "atr": 2.0, "breakout_level": 99.0, "rs_rank_pct": 0.01,
                               "rs_score": 1.0, "candidate": True}])
        readings = {"US": regime.RegimeReading("d", "US", "GREEN", "GREEN")}
        acc = journal.Account(satellite_equity_eur=10_000, high_water_mark=10_000)
        props, skipped = select_entries(settings, table, readings, [], acc, FxTable({}, "t"), {"US": 1.0}, blocked=True)
        self.assertEqual(props, [])
        self.assertIn("Kill-Switch", skipped[0])


class TestJournalMath(unittest.TestCase):
    def _thesis(self, pnl, entry, stop, shares):
        return {"outcome": {"pnl_dollars": pnl}, "entry": {"actual_price": entry},
                "position": {"shares": shares}, "origin": {"raw_provenance": {"initial_stop": stop}}, "exit": {}}

    def test_r_and_expectancy(self):
        t1 = self._thesis(200, 100, 90, 10)    # +2R
        t2 = self._thesis(-100, 100, 90, 10)   # -1R
        self.assertAlmostEqual(journal.r_multiple(t1), 2.0)
        exp, n, wr = journal.expectancy([t1, t2])
        self.assertEqual(n, 2)
        self.assertAlmostEqual(exp, 0.5)
        self.assertAlmostEqual(wr, 0.5)

    def test_account_drawdown(self):
        acc = journal.Account()
        acc.set_equity(1000, date(2026, 1, 1))
        acc.set_equity(800, date(2026, 2, 1))
        self.assertAlmostEqual(acc.drawdown, 0.2)
        self.assertEqual(acc.high_water_mark, 1000)


class TestSynthetic(unittest.TestCase):
    def test_synthetic_source(self):
        res = SyntheticSource(days=50).fetch(["A", "B"], date(2026, 1, 1), date(2026, 9, 4))
        self.assertEqual(set(res.frames), {"A", "B"})
        self.assertEqual(list(res.frames["A"].columns), ["open", "high", "low", "close", "volume"])


if __name__ == "__main__":
    unittest.main()

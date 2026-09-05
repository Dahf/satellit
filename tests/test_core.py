"""Offline-Tests (unittest): python3 -m unittest discover -s tests -v"""

from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from satellit import indicators as ind  # noqa: E402
from satellit import journal, regime  # noqa: E402
from satellit.config import Settings, load_settings, risikoprofil  # noqa: E402
from satellit.data import StooqSource, SyntheticSource, _clean  # noqa: E402
from satellit.fx import FxTable  # noqa: E402
from satellit.pipeline import Proposal, mindestkapital, run_weekly, select_entries  # noqa: E402
from satellit.screener import ScreenerContext, run_screener  # noqa: E402
from satellit.universe import (  # noqa: E402
    Constituent, _download, apply_overrides, import_holdings, load_universe, parse_ishares_csv,
    parse_number, save_universe_snapshot, snapshot_aktualisieren, to_yahoo_symbol,
)

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
        codes = {s.code for s in skipped}
        self.assertTrue({"MAX_SEKTOR", "AMPEL_LIMIT"} & codes, codes)
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
        self.assertEqual(skipped[0].code, "KILL_SWITCH")


class TestKleineDepots(unittest.TestCase):
    """Bei kleinem Kapital wird sonst wortlos ZU_TEUER gemeldet, ohne dass der Grund erscheint."""

    def _tabelle(self, close=100.0, stop=94.0):
        return pd.DataFrame([{"region": "US", "symbol": "S", "isin": "I", "name": "N", "sector": "Tech",
                              "currency": "EUR", "close": close, "close_eur": close, "initial_stop": stop,
                              "atr": 2.0, "breakout_level": close - 1, "rs_rank_pct": 0.01, "rs_score": 1.0,
                              "candidate": True, "trend_ok": True, "rs_top": True, "liquidity_ok": True,
                              "vol_ok": True}])

    def _auswahl(self, settings, equity):
        readings = {"US": regime.RegimeReading("d", "US", "GREEN", "GREEN")}
        acc = journal.Account(satellite_equity_eur=equity, high_water_mark=equity)
        return select_entries(settings, self._tabelle(), readings, [], acc, FxTable({}, "t"),
                              {"US": 0.5}, blocked=False)

    def _ganzstueck(self):
        """Einstellungen ohne Bruchstücke — der Zustand, für den die Ganzstück-Regeln gelten."""
        return load_settings(ROOT / "config" / "settings.yaml",
                             overrides={"risk": {"bruchstuecke": False}})

    def test_ohne_bruchstuecke_scheitert_der_kleine_satellit_an_der_stueckzahl(self):
        """250 EUR bei 0,5 % Risiko ergeben 1,25 EUR — weniger als ein Stück zu 100 EUR."""
        props, skipped = self._auswahl(self._ganzstueck(), 250.0)
        self.assertEqual(props, [])
        self.assertEqual(skipped[0].code, "ZU_TEUER")

    def test_mit_den_regelwerten_kann_der_kleine_satellit_kaufen(self):
        """Mit Bruchstücken (Vorgabe) entsteht eine Position, ohne dass das Risiko steigt."""
        settings = load_settings(ROOT / "config" / "settings.yaml")
        props, skipped = self._auswahl(settings, 250.0)
        self.assertEqual(len(props), 1, [s.code for s in skipped])
        self.assertAlmostEqual(props[0].risk_eur, 1.25, places=2)

    def test_konzentrationsprofil_greift_nur_unterhalb_der_schwelle(self):
        settings = load_settings(ROOT / "config" / "settings.yaml")
        self.assertTrue(risikoprofil(settings, 250.0)["klein"])
        self.assertFalse(risikoprofil(settings, 50_000.0)["klein"])
        # Unterhalb der Schwelle: wenige, größere Positionen.
        self.assertLess(risikoprofil(settings, 250.0)["max_positions"],
                        risikoprofil(settings, 50_000.0)["max_positions"])
        self.assertGreater(risikoprofil(settings, 250.0)["max_position_pct"],
                           risikoprofil(settings, 50_000.0)["max_position_pct"])

    def test_bruchstuecke_erzeugen_eine_position_statt_zu_teuer(self):
        settings = load_settings(ROOT / "config" / "settings.yaml",
                                 overrides={"risk": {"bruchstuecke": True, "min_order_eur": 1.0}})
        props, skipped = self._auswahl(settings, 250.0)
        self.assertEqual(len(props), 1, [s.code for s in skipped])
        self.assertLess(props[0].shares, 1.0)                       # ein Bruchstück
        self.assertAlmostEqual(props[0].risk_eur, 1.25, places=2)   # Risiko bleibt bei 0,5 %

    def test_bruchstueck_unter_der_mindestorder_wird_benannt(self):
        """Der Grund muss ein anderer sein als „zu teuer“ — sonst stimmt der Satz nicht."""
        settings = load_settings(ROOT / "config" / "settings.yaml",
                                 overrides={"risk": {"bruchstuecke": True, "min_order_eur": 500.0}})
        props, skipped = self._auswahl(settings, 250.0)
        self.assertEqual(props, [])
        self.assertEqual(skipped[0].code, "UNTER_MINDESTORDER")

    def test_mindestkapital_wird_gerechnet_und_verschwindet_wenn_es_reicht(self):
        settings = self._ganzstueck()
        fx = FxTable({}, "t")
        schwelle = mindestkapital(settings, self._tabelle(), fx, risk_pct=0.5, equity_eur=250.0)
        self.assertIsNotNone(schwelle)
        self.assertGreater(schwelle, 250.0)
        # Mit dieser Summe entsteht tatsächlich ein Vorschlag — die Zahl ist keine Zierde.
        props, skipped = self._auswahl(settings, schwelle)
        self.assertEqual(len(props), 1, [s.code for s in skipped])
        # Und sie verstummt, sobald das Kapital reicht.
        self.assertIsNone(mindestkapital(settings, self._tabelle(), fx, 0.5, equity_eur=schwelle))

    def test_mit_bruchstuecken_gibt_es_keine_untergrenze_mehr(self):
        """Die „zu klein"-Zeile darf nicht erscheinen, wenn gekauft werden kann."""
        settings = load_settings(ROOT / "config" / "settings.yaml")
        self.assertIsNone(mindestkapital(settings, self._tabelle(), FxTable({}, "t"), 0.5, 250.0))


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


class TestUniversumQuellen(unittest.TestCase):
    """Das Universum muss auch dann stehen, wenn der iShares-Download ausfällt."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        raw = copy.deepcopy(load_settings(ROOT / "config" / "settings.yaml").raw)
        # Nur eine Region, damit der Test nicht an der echten Konfiguration hängt.
        raw["universe"]["regions"] = {
            "EU": {"name": "Test", "currency": "EUR",
                   "quellen": [{"typ": "ishares_csv", "url": "https://example.invalid/a.csv"}],
                   "local_file": "state/universe/EXSA_holdings.csv"},
        }
        self.settings = Settings(raw=raw, root=Path(self.tmp.name))
        self.settings.ensure_dirs()
        self.snapshot = self.settings.universe_dir / "universe_snapshot.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_rettet_bei_download_ausfall(self):
        cons = parse_ishares_csv(GERMAN_CSV, "EU")
        save_universe_snapshot(cons, self.snapshot)
        with mock.patch("satellit.universe._download", side_effect=RuntimeError("HTTP 403, Content-Type text/html")):
            geladen, warnungen, status = load_universe(self.settings)
        self.assertEqual(len(geladen), len(cons))
        self.assertEqual(status["EU"]["quelle"], "snapshot")
        self.assertTrue(status["EU"]["ok"])
        self.assertTrue(any("403" in w for w in warnungen), warnungen)

    def test_ohne_jede_quelle_faellt_die_region_sichtbar_aus(self):
        with mock.patch("satellit.universe._download", side_effect=RuntimeError("HTTP 403")):
            geladen, _warnungen, status = load_universe(self.settings)
        self.assertEqual(geladen, [])
        self.assertFalse(status["EU"]["ok"])
        self.assertIsNone(status["EU"]["quelle"])

    def test_snapshot_wird_nicht_ueber_sich_selbst_geschrieben(self):
        """Sonst setzt das Neuschreiben die mtime zurück und verschleiert das Alter."""
        cons = parse_ishares_csv(GERMAN_CSV, "EU")
        save_universe_snapshot(cons, self.snapshot)
        vorher = self.snapshot.stat().st_mtime
        self.assertFalse(snapshot_aktualisieren(cons, {"EU": {"quelle": "snapshot"}}, self.snapshot))
        self.assertEqual(self.snapshot.stat().st_mtime, vorher)
        self.assertTrue(snapshot_aktualisieren(cons, {"EU": {"quelle": "download"}}, self.snapshot))

    def test_import_holdings_validiert_vor_dem_schreiben(self):
        anzahl, ziel = import_holdings(self.settings, "EU", GERMAN_CSV)
        self.assertEqual(anzahl, 4)                 # vier Aktien, die Cash-Zeile fällt raus
        self.assertTrue(ziel.exists())
        with self.assertRaises(ValueError):
            import_holdings(self.settings, "XX", GERMAN_CSV)
        with self.assertRaises(ValueError):
            import_holdings(self.settings, "EU", "irgendwas,ohne,tabellenkopf")

    def test_ausschluss_per_symbol_greift(self):
        """Trägt die Regel 'kein Doppelhalten' (Trading-Plan 3.5) — die Dateien haben keine ISIN mehr."""
        (Path(self.tmp.name) / "config").mkdir(exist_ok=True)
        (Path(self.tmp.name) / "config" / "exclusions.yaml").write_text(
            "core_holdings:\n  - symbol: SAP.DE\n    note: Kern\nnot_tradable: []\nmanual: []\n",
            encoding="utf-8")
        save_universe_snapshot(parse_ishares_csv(GERMAN_CSV, "EU"), self.snapshot)
        with mock.patch("satellit.universe._download", side_effect=RuntimeError("offline")):
            cons, warnungen, _status = load_universe(self.settings)
        self.assertNotIn("SAP.DE", {c.symbol for c in cons})
        self.assertEqual(len(cons), 3)
        self.assertFalse([w for w in warnungen if "ISIN-Spalte" in w])   # hier gibt es ISINs

    def test_warnt_wenn_isin_ausschluesse_nicht_greifen_koennen(self):
        """Ohne diese Warnung fällt ein wirkungsloser Ausschluss niemandem auf."""
        (Path(self.tmp.name) / "config").mkdir(exist_ok=True)
        (Path(self.tmp.name) / "config" / "exclusions.yaml").write_text(
            "core_holdings:\n  - isin: DE0007164600\n    note: Kern\nnot_tradable: []\nmanual: []\n",
            encoding="utf-8")
        ohne_isin = GERMAN_CSV.replace(",ISIN,", ",KeineIsin,")
        save_universe_snapshot(parse_ishares_csv(ohne_isin, "EU"), self.snapshot)
        with mock.patch("satellit.universe._download", side_effect=RuntimeError("offline")):
            _cons, warnungen, _status = load_universe(self.settings)
        self.assertTrue([w for w in warnungen if "ISIN-Spalte" in w], warnungen)

    def test_offline_laedt_nichts_herunter(self):
        """view.neu_rechnen läuft nach jedem Dashboard-Klick — es darf kein Netz anfassen."""
        save_universe_snapshot(parse_ishares_csv(GERMAN_CSV, "EU"), self.snapshot)
        with mock.patch("satellit.universe._download", side_effect=AssertionError("Download im Offline-Modus")):
            cons, _warnungen, status = load_universe(self.settings, offline=True)
        self.assertTrue(cons)
        self.assertEqual(status["EU"]["quelle"], "snapshot")

    def test_download_nennt_den_grund(self):
        antwort = mock.Mock(status_code=403, headers={"Content-Type": "text/html"}, text="<html>denied</html>")
        with mock.patch("satellit.universe.requests.Session") as Session, \
             mock.patch("satellit.universe.time.sleep"):
            Session.return_value.headers = {}
            Session.return_value.get.return_value = antwort
            with self.assertRaises(RuntimeError) as ctx:
                _download("https://example.invalid/a.csv")
        self.assertIn("403", str(ctx.exception))
        self.assertIn("text/html", str(ctx.exception))


class TestIsharesEchtformat(unittest.TestCase):
    """Fälle aus den echten Dateien (Stand 09/2026), die den Parser vorher gekippt haben."""

    # Ohne ISIN-Spalte, mit der iShares-Fußzeile aus einem geschützten Leerzeichen.
    US_CSV = (
        'Fondsposition per,"03.Sept.2026"\n'
        ' \n'
        'Emittententicker,Name,Sektor,Anlageklasse,Marktwert,Gewichtung (%),Nominalwert,'
        'Nominale,Kurs,Standort,Börse,Marktwährung\n'
        '"NVDA","NVIDIA","IT","Aktien","1,0","8,28","1,0","5,0","228,45","Vereinigte Staaten","NASDAQ","USD"\n'
        '"BRK B","BERKSHIRE B","Finanzen","Aktien","1,0","1,60","1,0","5,0","500,00","Vereinigte Staaten","New York Stock Exchange Inc.","USD"\n'
        '"ESU6","S&P500 EMINI SEP 26","Cash und/oder Derivate","Futures","0,00","0,00","1,0","9,0","7.754,75","-","Index And Options Market","USD"\n'
        '\xa0\n'
    )

    NORDIC_CSV = (
        'Fondsname,iShares STOXX Europe 600\n'
        'Positionen zum,"04.Sep.2026"\n'
        '\n'
        'Emittententicker,Name,Sektor,Anlageklasse,Gewichtung (%),Börse,Marktwährung\n'
        '"VOLV B","VOLVO B","Industrie","Aktien","0,40","Nasdaq Omx Nordic","SEK"\n'
        '"NOVO B","NOVO NORDISK B","Gesundheit","Aktien","1,90","Nasdaq Omx Nordic","DKK"\n'
        '"NOKIA","NOKIA OYJ","IT","Aktien","0,30","Nasdaq Omx Nordic","EUR"\n'
    )

    def test_fusszeile_und_fehlende_isin_kippen_den_parser_nicht(self):
        cons = parse_ishares_csv(self.US_CSV, "US")
        self.assertEqual([c.symbol for c in cons], ["NVDA", "BRK-B"])   # Futures fliegen raus
        self.assertTrue(all(c.isin == "" for c in cons))                # Datei hat keine ISIN-Spalte

    def test_nasdaq_omx_nordic_wird_ueber_die_waehrung_aufgeloest(self):
        """Ohne diese Regel greift die generische nasdaq-Regel und macht US-Symbole daraus."""
        symbole = [c.symbol for c in parse_ishares_csv(self.NORDIC_CSV, "EU")]
        self.assertEqual(symbole, ["VOLV-B.ST", "NOVO-B.CO", "NOKIA.HE"])

    def test_ausschluss_und_override_greifen_ueber_das_symbol(self):
        cons = parse_ishares_csv(self.US_CSV, "US")
        self.assertEqual(apply_overrides(list(cons), {"BRK-B": "BRK-B.US"})[1].symbol, "BRK-B.US")


class TestOfflineLauf(unittest.TestCase):
    """Der Offline-Modus trägt den Neuaufbau der Ansicht nach jeder Aktion.

    Vergisst er die Ersatzquelle abzuschalten, fragt jeder Klick sie für ~1.100 Symbole
    einzeln ab — gemessen 2 Minuten statt 0,4 Sekunden.
    """

    class _Stop(Exception):
        pass

    def setUp(self):
        self.settings = load_settings(ROOT / "config" / "settings.yaml")

    def _quellen_bau_zaehlen(self, offline: bool) -> list:
        gebaut = []
        with mock.patch("satellit.pipeline.load_universe", return_value=([], [], {})), \
             mock.patch("satellit.pipeline.build_source",
                        side_effect=lambda *a, **k: (gebaut.append(a[1:] or ("primaer",)), object())[1]), \
             mock.patch("satellit.pipeline.update_prices", side_effect=self._Stop):
            with self.assertRaises(self._Stop):
                run_weekly(self.settings, offline=offline)
        return gebaut

    def test_offline_baut_keine_kursquelle(self):
        self.assertEqual(self._quellen_bau_zaehlen(offline=True), [])

    def test_normaler_lauf_baut_primaer_und_ersatz(self):
        self.assertEqual(len(self._quellen_bau_zaehlen(offline=False)), 2)


class TestStooqOhneKey(unittest.TestCase):
    def test_ohne_key_wird_trotzdem_abgefragt(self):
        """Der frühere harter Abbruch ohne STOOQ_APIKEY machte den Fallback wirkungslos."""
        csv_text = "Date,Open,High,Low,Close,Volume\n2026-09-04,10,11,9,10.5,1000\n"
        antwort = mock.Mock(status_code=200, text=csv_text)
        with mock.patch("requests.get", return_value=antwort) as get, \
             mock.patch("satellit.data.time.sleep"):
            res = StooqSource(apikey="").fetch(["AAPL"], date(2026, 9, 1), date(2026, 9, 4))
        self.assertEqual(get.call_count, 1)
        self.assertNotIn("apikey", get.call_args[0][0])
        self.assertIn("AAPL", res.frames)


if __name__ == "__main__":
    unittest.main()

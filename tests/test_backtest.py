"""Kosten- und Steuermodell des Backtests.

Diese Zahlen entscheiden das Urteil aus TRADING_PLAN.md 10.3 („schlägt der Satellit nach
Kosten und Steuern den Kern-ETF?"). Sie sind deshalb einzeln festgenagelt — ein stiller
Vorzeichenfehler hier würde als Strategieaussage durchgehen.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from satellit import backtest as bta  # noqa: E402
from satellit import steuern as st  # noqa: E402
from satellit import universe_history as uh  # noqa: E402
from satellit.config import load_settings  # noqa: E402
from satellit.kosten import Kostenmodell, stop_fuellkurs  # noqa: E402
from satellit.universe import Constituent  # noqa: E402

EINSTELLUNGEN = load_settings(ROOT / "config" / "settings.yaml")


class TestKosten(unittest.TestCase):
    def setUp(self):
        self.k = Kostenmodell(order_gebuehr_eur=1.00, spread_pct=0.001)

    def test_pauschale_gilt_unabhaengig_von_der_ordergroesse(self):
        """41 von 41 gebührenpflichtigen Orders lagen bei exakt 1,00 € — ohne Varianz."""
        self.assertAlmostEqual(self.k.order(20.88), 1.0 + 0.02088, places=5)
        self.assertAlmostEqual(self.k.order(10_000.0), 1.0 + 10.0, places=5)

    def test_sparplan_ist_kostenlos(self):
        """Der strukturelle Vorteil des Kerns. Ihn wegzulassen verzerrt den Vergleich."""
        self.assertAlmostEqual(self.k.order(100.0, sparplan=True), 0.10, places=5)

    def test_kleine_position_verliert_den_grossteil_des_edges(self):
        """Die Rechnung, an der die Satellitengröße hängt: 83 € Position, 0,3R Edge,
        9 % Stopabstand — der Roundtrip frisst den überwiegenden Teil davon."""
        anteil = self.k.anteil_am_edge(83.0, edge_r=0.3, stop_abstand_pct=0.09)
        self.assertGreater(anteil, 0.85)

    def test_grosse_position_dreht_das_verhaeltnis(self):
        """500 €: 3,00 € Roundtrip gegen 13,50 € Bruttoedge — noch immer 22 %."""
        anteil = self.k.anteil_am_edge(500.0, edge_r=0.3, stop_abstand_pct=0.09)
        self.assertAlmostEqual(anteil, 0.2222, places=3)

    def test_der_spread_verschwindet_nicht_mit_der_groesse(self):
        """Die Pauschale lässt sich durch größere Positionen verdünnen, der Spread nicht —
        er ist proportional. Bei 0,1 % je Seite bleibt eine Untergrenze von 2 × 0,1 % /
        (0,3 × 9 %) ≈ 7,4 % des Edges stehen, egal wie groß die Position wird."""
        riesig = self.k.anteil_am_edge(1_000_000.0, edge_r=0.3, stop_abstand_pct=0.09)
        self.assertAlmostEqual(riesig, 0.0741, places=3)
        self.assertGreater(riesig, 0.0)

    def test_konfiguration_traegt_die_belegten_werte(self):
        k = Kostenmodell.aus_settings(EINSTELLUNGEN)
        self.assertEqual(k.order_gebuehr_eur, 1.00)
        self.assertEqual(k.sparplan_gebuehr_eur, 0.0)


class TestStopFuellkurs(unittest.TestCase):
    """Ohne Kurslücken ist jedes ausgewiesene R eine Behauptung statt einer Messung."""

    def test_kurslucke_fuellt_unter_dem_stop(self):
        self.assertAlmostEqual(stop_fuellkurs(stop=94.0, eroeffnung=88.0, tief=86.0), 88.0)

    def test_beruehrung_im_tagesverlauf_fuellt_am_stop(self):
        self.assertAlmostEqual(stop_fuellkurs(stop=94.0, eroeffnung=99.0, tief=93.0), 94.0)

    def test_ohne_beruehrung_kein_fill(self):
        self.assertIsNone(stop_fuellkurs(stop=94.0, eroeffnung=99.0, tief=95.0))

    def test_die_luecke_kostet_mehr_als_ein_r(self):
        """Einstieg 100, Stop 94 — 1R sind 6. Bei Eröffnung auf 88 wird daraus 2R."""
        fill = stop_fuellkurs(stop=94.0, eroeffnung=88.0, tief=88.0)
        self.assertAlmostEqual((100.0 - fill) / (100.0 - 94.0), 2.0)


class TestSteuern(unittest.TestCase):
    def setUp(self):
        self.konto = st.Steuerkonto(satz=st.Steuersatz(), pauschbetrag_eur=1000.0)

    def test_effektiver_satz(self):
        self.assertAlmostEqual(st.Steuersatz().effektiv, 0.26375, places=5)

    def test_pauschbetrag_geht_vor(self):
        self.konto.realisiere(2026, 800.0)
        self.assertAlmostEqual(self.konto.abrechnung()["steuer_eur"], 0.0)

    def test_ueber_dem_pauschbetrag_wird_versteuert(self):
        self.konto.realisiere(2026, 2000.0)
        self.assertAlmostEqual(self.konto.abrechnung()["steuer_eur"], 1000.0 * 0.26375, places=4)

    def test_verluste_werden_im_jahr_verrechnet(self):
        """Trendfolge erzeugt viele kleine Verluste. Wer nur Gewinne besteuert,
        überzeichnet die Last des Satelliten grob."""
        self.konto.realisiere(2026, 3000.0)
        self.konto.realisiere(2026, -1500.0)
        self.assertAlmostEqual(self.konto.abrechnung()["steuer_eur"], 500.0 * 0.26375, places=4)

    def test_verluste_werden_ins_folgejahr_vorgetragen(self):
        self.konto.realisiere(2025, -2000.0)
        self.konto.realisiere(2026, 3000.0)
        ab = self.konto.abrechnung()
        self.assertAlmostEqual(ab["je_jahr"][2025]["steuer_eur"], 0.0)
        self.assertAlmostEqual(ab["je_jahr"][2026]["steuer_eur"], 0.0)   # 3000-2000-1000 = 0

    def test_aktienverluste_verrechnen_nicht_mit_fondsertraegen(self):
        """§ 20 Abs. 6 EStG — getrennte Töpfe. Ohne das rechnete ein gemischtes Szenario
        still falsch."""
        self.konto.realisiere(2026, -5000.0, topf=st.TOPF_AKTIEN)
        self.konto.realisiere(2026, 5000.0, topf=st.TOPF_SONSTIGE)
        ab = self.konto.abrechnung()
        self.assertGreater(ab["steuer_eur"], 0.0)
        self.assertAlmostEqual(ab["verlustvortrag_eur"][st.TOPF_AKTIEN], 5000.0)

    def test_teilfreistellung_begunstigt_den_etf(self):
        """30 % steuerfrei beim Aktienfonds, nichts bei der Einzelaktie. Beide gleich zu
        rechnen benachteiligt den ETF — genau die Verzerrung, die 10.3 vermeiden will."""
        aktie = st.Steuerkonto(pauschbetrag_eur=0.0)
        aktie.realisiere(2026, 1000.0)
        fonds = st.Steuerkonto(pauschbetrag_eur=0.0)
        fonds.realisiere(2026, 1000.0, teilfreistellung=st.TEILFREISTELLUNG_AKTIENFONDS,
                         topf=st.TOPF_SONSTIGE)
        self.assertAlmostEqual(fonds.abrechnung()["steuer_eur"],
                               aktie.abrechnung()["steuer_eur"] * 0.7, places=4)


class TestVorabpauschale(unittest.TestCase):
    def setUp(self):
        self.konto = st.Steuerkonto(pauschbetrag_eur=0.0)

    def test_basisertrag_wird_auf_die_wertsteigerung_gedeckelt(self):
        """Basisertrag 10.000 × 2 % × 0,7 = 140; die Wertsteigerung beträgt nur 50."""
        p = self.konto.vorabpauschale(2026, wert_anfang=10_000, wert_ende=10_050, basiszins=0.02)
        self.assertAlmostEqual(p, 50.0)

    def test_ohne_wertsteigerung_faellt_keine_an(self):
        p = self.konto.vorabpauschale(2026, wert_anfang=10_000, wert_ende=9_000, basiszins=0.02)
        self.assertAlmostEqual(p, 0.0)

    def test_voller_basisertrag_bei_grosser_wertsteigerung(self):
        p = self.konto.vorabpauschale(2026, wert_anfang=10_000, wert_ende=13_000, basiszins=0.02)
        self.assertAlmostEqual(p, 140.0)

    def test_fehlender_basiszins_wird_gemeldet_statt_geraten(self):
        p = self.konto.vorabpauschale(2026, wert_anfang=10_000, wert_ende=13_000, basiszins=None)
        self.assertAlmostEqual(p, 0.0)
        self.assertTrue(any("Basiszins" in h for h in self.konto.hinweise))

    def test_vorab_versteuertes_mindert_den_gewinn_beim_verkauf(self):
        """Sonst würde derselbe Ertrag zweimal besteuert und der ETF zu schlecht dargestellt."""
        self.konto.vorabpauschale(2026, wert_anfang=10_000, wert_ende=13_000, basiszins=0.02)
        self.konto.verkauf_fonds(2027, 1000.0)
        # 140 sind bereits vorab erfasst, zu versteuern bleiben (1000 - 140) * 0,7
        ab = self.konto.abrechnung()
        erwartet = (140.0 * 0.7 + (1000.0 - 140.0) * 0.7) * st.Steuersatz().effektiv
        self.assertAlmostEqual(ab["steuer_eur"], erwartet, places=4)

    def test_leere_tabelle_ist_absicht(self):
        """Geratene Basiszinsen wären erfundene Zahlen in einer Steuerrechnung."""
        self.assertEqual(st.basiszins_tabelle(EINSTELLUNGEN), {})


def _con(ticker: str, region: str = "US") -> Constituent:
    return Constituent(region, f"US{ticker}", ticker, f"{ticker} Inc", "Tech", "NASDAQ",
                       "USD", 1.0, ticker, 1.0)


class TestUniversumshistorie(unittest.TestCase):
    """Punkt-in-Zeit-Mitgliedschaft — und die ehrliche Grenze dessen, was sie leistet."""

    def setUp(self):
        self.heute = [_con("AAA"), _con("BBB"), _con("NEU"), _con("SAP", region="EU")]
        self.aenderungen = [
            uh.Aenderung(date(2025, 3, 1), aufgenommen="NEU", entfernt="ALT"),
            uh.Aenderung(date(2025, 9, 1), aufgenommen="", entfernt="BBB"),
        ]
        self.hist = uh.Universumshistorie(self.heute, self.aenderungen)

    def test_spaeter_aufgenommene_titel_fehlen_vorher(self):
        """Der Blick in die Zukunft, den die Rekonstruktion tatsächlich entfernt."""
        vorher = {c.ticker for c in self.hist.am(date(2025, 1, 1)) if c.region == "US"}
        self.assertNotIn("NEU", vorher)
        self.assertIn("AAA", vorher)

    def test_spaeter_entfernte_titel_sind_vorher_noch_drin(self):
        mitglieder = uh.mitglieder_am(date(2025, 1, 1), {"AAA", "BBB", "NEU"}, self.aenderungen)
        self.assertIn("ALT", mitglieder)
        self.assertIn("BBB", mitglieder)

    def test_nach_allen_aenderungen_gilt_der_heutige_stand(self):
        heute = {c.ticker for c in self.hist.am(date(2026, 1, 1)) if c.region == "US"}
        self.assertEqual(heute, {"AAA", "BBB", "NEU"})

    def test_eu_bleibt_unberuehrt(self):
        """Für den STOXX 600 gibt es keine freie Historie — das darf nicht so aussehen,
        als wäre er ebenfalls bereinigt."""
        eu = [c.ticker for c in self.hist.am(date(2025, 1, 1)) if c.region == "EU"]
        self.assertEqual(eu, ["SAP"])
        self.assertFalse(self.hist.vollstaendig["EU"])

    def test_abdeckung_benennt_den_ungeloesten_rest(self):
        """ALT war damals im Index, liegt aber nicht als Stammdatensatz vor. Genau dieser
        Anteil ist der Survivorship Bias, der bleibt."""
        a = self.hist.abdeckung(date(2025, 1, 1))
        self.assertEqual(a["fehlend"], 1)              # ALT
        self.assertEqual(a["mitglieder"], 3)           # AAA, BBB, ALT
        self.assertAlmostEqual(a["anteil"], 2 / 3)

    def test_ohne_historie_wird_die_verzerrung_offen_gemeldet(self):
        blind = uh.Universumshistorie(self.heute, [])
        a = blind.abdeckung(date(2025, 1, 1))
        self.assertIsNone(a["anteil"])
        self.assertIn("überlebensverzerrt", a["hinweis"])

    def test_kaputte_zeilen_werden_gemeldet_statt_geraten(self):
        pfad = Path(tempfile.mkdtemp()) / uh.AENDERUNGSDATEI
        pfad.write_text("datum,aufgenommen,entfernt\n2025-03-01,NEU,ALT\nquatsch,X,Y\n",
                        encoding="utf-8")
        aenderungen, hinweise = uh.lies_aenderungen(pfad)
        self.assertEqual(len(aenderungen), 1)
        self.assertTrue(any("nicht lesbar" in h for h in hinweise))

    def test_fehlende_datei_ist_ein_hinweis_kein_absturz(self):
        aenderungen, hinweise = uh.lies_aenderungen(Path(tempfile.mkdtemp()) / "gibtsnicht.csv")
        self.assertEqual(aenderungen, [])
        self.assertTrue(any("punkt-in-zeit" in h for h in hinweise))


def _frame(tage: int = 700, ende: date = date(2026, 9, 4), seed: int = 1,
           trend: float = 0.0006, luecke_am: int | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=ende, periods=tage)
    rets = rng.normal(trend, 0.010, tage)
    close = 100 * np.exp(np.cumsum(rets))
    df = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                       "close": close, "volume": np.full(tage, 5_000_000.0)}, index=idx)
    if luecke_am is not None:
        # Ein Absturz um 25 % über Nacht: Eröffnung weit unter dem Vortagesschluss.
        df.iloc[luecke_am:, :4] *= 0.75
        df.iloc[luecke_am, df.columns.get_loc("open")] = float(df["close"].iloc[luecke_am - 1]) * 0.75
    df.index.name = "date"
    return df


def _konstituenten(n: int) -> list[Constituent]:
    return [Constituent("EU", f"DE{i:010d}", f"T{i}", f"Test {i}", f"Sektor{i % 4}", "Xetra",
                        "EUR", 1.0, f"T{i}.DE", 1.0) for i in range(n)]


class TestBacktestMotor(unittest.TestCase):
    """Der Motor läuft offline gegen synthetische Kurse. Geprüft wird nicht die Rendite —
    die sagt bei erfundenen Daten nichts —, sondern dass die Mechanik greift."""

    def setUp(self):
        self.settings = load_settings(ROOT / "config" / "settings.yaml")
        self.cons = _konstituenten(12)
        self.frames = {c.symbol: _frame(seed=i, trend=0.0012 if i < 4 else -0.0004)
                       for i, c in enumerate(self.cons)}
        self.frames["EXSA.DE"] = _frame(seed=99, trend=0.0010)
        self.hist = uh.Universumshistorie(self.cons, [])

    def _lauf(self, kapital=50_000.0, von=date(2025, 1, 3), bis=date(2026, 9, 4)):
        bt = bta.Backtest(self.settings, self.frames, self.cons, self.hist, kapital,
                          index_symbols={"EU": "EXSA.DE"})
        return bt, bt.run(von, bis)

    def test_lauf_erzeugt_ein_bewertbares_ergebnis(self):
        _, erg = self._lauf()
        self.assertGreater(len(erg.equity), 30)
        self.assertEqual(erg.equity[0][0].weekday(), 4)          # Stichtag ist Freitag
        self.assertGreaterEqual(erg.endkapital_eur, 0.0)

    def test_kosten_fallen_je_order_an(self):
        _, erg = self._lauf()
        if not erg.trades:
            self.skipTest("keine Trades in dieser Zufallsreihe")
        # Mindestens Kauf + Verkauf je Trade, also 2 EUR Pauschale aufwärts.
        self.assertGreaterEqual(erg.kosten_eur, 2.0 * len(erg.trades))

    def test_lauf_ist_deterministisch(self):
        _, a = self._lauf()
        _, b = self._lauf()
        self.assertEqual(len(a.trades), len(b.trades))
        self.assertAlmostEqual(a.endkapital_eur, b.endkapital_eur, places=6)

    def test_fehlender_wechselkurs_bricht_vorher_ab_statt_mittendrin(self):
        """Der Live-Pfad nimmt bei unbekannter Währung 1:1 an. Über Jahre wäre das eine
        erfundene Rendite — hier bricht der Lauf ab, aber mit Ansage und vor Woche 1."""
        cons = [Constituent("US", "US0", "T0", "Test", "Tech", "NASDAQ", "USD", 1.0, "T0", 1.0)]
        frames = {"T0": _frame(seed=1)}                      # kein EURUSD=X
        bt = bta.Backtest(self.settings, frames, cons, uh.Universumshistorie(cons, []), 10_000.0)
        self.assertEqual(bt.fehlende_wechselkurse(), ["USD"])
        erg = bt.run(date(2025, 1, 3), date(2026, 9, 4))
        self.assertEqual(erg.trades, [])
        self.assertTrue(any("Wechselkursreihen" in h for h in erg.hinweise))
        self.assertIsNone(erg.besteht())

    def test_vorhandener_wechselkurs_wird_nicht_bemaengelt(self):
        cons = [Constituent("US", "US0", "T0", "Test", "Tech", "NASDAQ", "USD", 1.0, "T0", 1.0)]
        frames = {"T0": _frame(seed=1), "EURUSD=X": _frame(seed=2, trend=0.0)}
        bt = bta.Backtest(self.settings, frames, cons, uh.Universumshistorie(cons, []), 10_000.0)
        self.assertEqual(bt.fehlende_wechselkurse(), [])

    def test_ohne_stichtag_kein_urteil(self):
        _, erg = self._lauf(von=date(2026, 9, 1), bis=date(2026, 9, 2))
        self.assertIsNone(erg.besteht())
        self.assertTrue(any("Wochenstichtag" in h for h in erg.hinweise))

    def _mit_position(self, kurse: dict[str, float], *, stop: float, einstand: float,
                      stueck: float = 10.0):
        """Eine gesetzte Position und eine Woche mit bekanntem Verlauf — kein Zufall.

        Der Lückenfall über einen Zufallslauf zu erzeugen hieße, den wichtigsten Test dem
        Würfel zu überlassen; er wurde vorher regelmäßig übersprungen.
        """
        idx = pd.bdate_range(end=date(2026, 9, 4), periods=400)
        close = np.full(400, einstand)
        df = pd.DataFrame({"open": close.copy(), "high": close * 1.01, "low": close * 0.99,
                           "close": close.copy(), "volume": np.full(400, 5e6)}, index=idx)
        for spalte, wert in kurse.items():
            df.iloc[-1, df.columns.get_loc(spalte)] = wert
        frames = {"T0.DE": df}
        bt = bta.Backtest(self.settings, frames, _konstituenten(1),
                          uh.Universumshistorie(_konstituenten(1), []), 10_000.0)
        bt.positionen["T0.DE"] = bta.Position(
            "T0.DE", "Test", "EU", "EUR", "Sektor0", stueck, einstand, einstand * stueck,
            stop, date(2026, 8, 21), 1.0, risiko_eur=(einstand - stop) * stueck)
        return bt, idx[-1].date()

    def test_kurslucke_kostet_mehr_als_ein_r(self):
        """Der Kern der Sache: füllt der Backtest immer am Stop, ist jedes R eine
        Behauptung. Einstand 100, Stop 94 — 1R sind 60 €. Eröffnet der Titel bei 88,
        ist der Verlust 120 €, also −2R."""
        bt, tag = self._mit_position({"open": 88.0, "low": 87.0, "close": 89.0},
                                     stop=94.0, einstand=100.0)
        bt._exits(tag, tag - timedelta(days=7))
        self.assertEqual(len(bt.trades), 1)
        t = bt.trades[0]
        self.assertEqual(t.grund, "kurslücke")
        self.assertLess(t.r_multiple, -1.9)

    def test_beruehrung_ohne_luecke_kostet_genau_ein_r(self):
        """Gegenprobe: ohne Lücke muss der Stop bei rund −1R füllen, sonst wäre der
        Lückenfall oben nicht aussagekräftig."""
        bt, tag = self._mit_position({"open": 99.0, "low": 93.0, "close": 95.0},
                                     stop=94.0, einstand=100.0)
        bt._exits(tag, tag - timedelta(days=7))
        self.assertEqual(len(bt.trades), 1)
        self.assertEqual(bt.trades[0].grund, "stop")
        self.assertAlmostEqual(bt.trades[0].r_multiple, -1.0, delta=0.1)

    def test_r_misst_gegen_das_anfangsrisiko_nicht_gegen_den_nachgezogenen_stop(self):
        """Sobald der Stop über den Einstand wandert, ist sein Abstand der gesicherte
        Gewinn, nicht das Risiko. Dagegen zu messen machte jedes R bedeutungslos."""
        bt, tag = self._mit_position({"open": 130.0, "low": 129.0, "close": 131.0},
                                     stop=94.0, einstand=100.0)
        pos = bt.positionen["T0.DE"]
        pos.stop = 128.0                       # nachgezogen, weit über dem Einstand
        bt._schliessen(pos, tag, 128.0, "stop")
        t = bt.trades[0]
        self.assertAlmostEqual(t.r_geplant_eur, 60.0, places=2)   # (100 − 94) × 10, nicht (128 − …)
        self.assertGreater(t.r_multiple, 4.0)                     # +280 € auf 60 € Anfangsrisiko

    def test_urteil_vergleicht_gegen_den_etf(self):
        _, erg = self._lauf()
        erg.benchmark = bta.kern_etf_referenz(self.settings, self.frames, "EXSA.DE",
                                              date(2025, 1, 3), date(2026, 9, 4), 50_000.0)
        self.assertIn("netto_eur", erg.benchmark)
        self.assertIsInstance(erg.besteht(), (bool, type(None)))

    def test_referenz_zieht_steuern_und_teilfreistellung(self):
        ref = bta.kern_etf_referenz(self.settings, self.frames, "EXSA.DE",
                                    date(2025, 1, 3), date(2026, 9, 4), 50_000.0)
        self.assertLess(ref["netto_eur"], ref["brutto_eur"] + 1e-9)
        self.assertGreaterEqual(ref["steuer_eur"], 0.0)

    def test_fehlende_kursreihe_ist_ein_gemeldeter_fehler(self):
        ref = bta.kern_etf_referenz(self.settings, self.frames, "GIBTSNICHT",
                                    date(2025, 1, 3), date(2026, 9, 4), 1000.0)
        self.assertIn("fehler", ref)


class TestFxHistorie(unittest.TestCase):
    """Der Euro-Wert einer USD-Position wandert über die Haltedauer. Im Live-Pfad wird mit
    einem Tageskurs gerechnet — über Jahre wäre das grob falsch."""

    def setUp(self):
        idx = pd.bdate_range(end=date(2026, 9, 4), periods=400)
        kurse = np.linspace(1.00, 1.25, 400)          # USD je EUR steigt
        self.frames = {"EURUSD=X": pd.DataFrame({"close": kurse}, index=idx)}

    def test_kurs_folgt_dem_stichtag(self):
        fx = bta.FxHistorie(self.frames)
        fx.setze_stichtag(date(2026, 9, 4))
        spaet = fx.to_eur(100.0, "USD")
        fx.setze_stichtag(self.frames["EURUSD=X"].index[0].date())
        frueh = fx.to_eur(100.0, "USD")
        self.assertLess(spaet, frueh)                 # starker EUR -> weniger Euro
        self.assertAlmostEqual(frueh, 100.0, places=2)

    def test_euro_bleibt_euro(self):
        fx = bta.FxHistorie(self.frames)
        fx.setze_stichtag(date(2026, 9, 4))
        self.assertAlmostEqual(fx.to_eur(100.0, "EUR"), 100.0)

    def test_fehlender_kurs_wird_nicht_still_als_eins_zu_eins_angenommen(self):
        """Der Live-Pfad nimmt bei unbekannter Währung 1:1 an und warnt. Über Jahre
        summiert sich das zu einer erfundenen Rendite."""
        fx = bta.FxHistorie(self.frames)
        fx.setze_stichtag(date(2026, 9, 4))
        with self.assertRaises(LookupError):
            fx.to_eur(100.0, "JPY")


if __name__ == "__main__":
    unittest.main()

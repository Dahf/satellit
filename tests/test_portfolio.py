"""Tests des Kern-Portfolios: python -m pytest tests/test_portfolio.py

Offline, ohne Kurse, ohne Netz. Das Kassenbuch ist die Grundlage jeder Zahl, die der
Nutzer sieht — Rechenfehler hier fallen sonst erst auf, wenn das Geld weg ist.
"""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from satellit import portfolio as pf  # noqa: E402
from satellit import journal, tr_import  # noqa: E402
from satellit.config import Settings, load_settings  # noqa: E402


def einstellungen(tmp: str) -> Settings:
    raw = copy.deepcopy(load_settings(ROOT / "config" / "settings.yaml").raw)
    s = Settings(raw=raw, root=Path(tmp))
    s.ensure_dirs()
    return s


def b(datum: str, typ: str, topf: str, betrag: float = 0.0, **kw) -> pf.Buchung:
    return pf.Buchung(datum=datum, typ=typ, topf=topf, betrag_eur=betrag, **kw)


class TestBuchung(unittest.TestCase):
    def test_unbekannte_werte_werden_abgelehnt(self):
        with self.assertRaises(ValueError):
            b("2026-09-06", "quatsch", "cash", 100)
        with self.assertRaises(ValueError):
            b("2026-09-06", "einzahlung", "sparbuch", 100)
        with self.assertRaises(ValueError):
            b("06.09.2026", "einzahlung", "cash", 100)

    def test_negative_betraege_sind_verboten(self):
        """Die Richtung steckt im Typ. Vorzeichen zusätzlich zuzulassen lädt zu Doppeldeutigkeit ein."""
        with self.assertRaises(ValueError):
            b("2026-09-06", "einzahlung", "cash", -100)

    def test_schluessel_ist_stabil_und_unterscheidet(self):
        eins = b("2026-09-06", "einzahlung", "cash", 100)
        gleich = b("2026-09-06", "einzahlung", "cash", 100)
        anders = b("2026-09-06", "einzahlung", "cash", 101)
        self.assertEqual(eins.quelle_id, gleich.quelle_id)
        self.assertNotEqual(eins.quelle_id, anders.quelle_id)


class TestKassenbuch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = einstellungen(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_schreiben_und_lesen(self):
        pf.schreibe_buchungen(self.s, [
            b("2026-09-06", "einzahlung", "cash", 5000, notiz="Start"),
            b("2026-09-06", "umschichtung", "kern_etf", 3600),
        ])
        gelesen = pf.lies_ledger(self.s)
        self.assertEqual(len(gelesen), 2)
        self.assertEqual(gelesen[0].notiz, "Start")
        self.assertEqual(pf.cash(gelesen, "kern_etf"), 3600)
        self.assertEqual(pf.cash(gelesen, "cash"), 1400)
        self.assertEqual(pf.cash(gelesen), 5000)          # Umschichtung ändert die Summe nicht

    def test_kaputte_zeile_macht_nicht_das_ganze_buch_unlesbar(self):
        pf.schreibe_buchung(self.s, b("2026-09-06", "einzahlung", "cash", 5000))
        with open(pf.ledger_pfad(self.s), "a", encoding="utf-8") as fh:
            fh.write("kaputt,quatsch,nirgends,,,,,,,,,,,\n")
        pf.schreibe_buchung(self.s, b("2026-09-07", "einzahlung", "cash", 100))
        self.assertEqual(len(pf.lies_ledger(self.s)), 2)

    def test_storno_hebt_auf_ohne_zu_loeschen(self):
        original = b("2026-09-06", "einzahlung", "cash", 5000)
        pf.schreibe_buchung(self.s, original)
        pf.storniere(self.s, original.quelle_id, "Tippfehler", heute=date(2026, 9, 7))
        gelesen = pf.lies_ledger(self.s)
        self.assertEqual(len(gelesen), 2)                  # beide Zeilen bleiben stehen
        self.assertEqual(pf.cash(gelesen, "cash"), 0.0)    # wirtschaftlich aufgehoben

    def test_storno_auf_unbekannten_schluessel_scheitert(self):
        with self.assertRaises(ValueError):
            pf.storniere(self.s, "gibtesnicht", "x")


class TestBestaende(unittest.TestCase):
    def test_kauf_und_teilverkauf(self):
        buchungen = [
            b("2026-09-06", "sparplan", "kern_etf", 450, isin="IE00BK5BQT80", symbol="VWCE.DE",
              stueck=3.0, kurs=150.0),
            b("2026-10-01", "sparplan", "kern_etf", 400, isin="IE00BK5BQT80", symbol="VWCE.DE",
              stueck=2.0, kurs=200.0),
        ]
        best = pf.bestaende(buchungen)["kern_etf:IE00BK5BQT80"]
        self.assertAlmostEqual(best.stueck, 5.0)
        self.assertAlmostEqual(best.einstand_eur, 850.0)
        self.assertAlmostEqual(best.einstand_je_stueck, 170.0)

        buchungen.append(b("2026-11-01", "kern_verkauf", "kern_etf", 500, isin="IE00BK5BQT80",
                           symbol="VWCE.DE", stueck=2.5, kurs=200.0))
        best = pf.bestaende(buchungen)["kern_etf:IE00BK5BQT80"]
        self.assertAlmostEqual(best.stueck, 2.5)
        self.assertAlmostEqual(best.einstand_eur, 425.0)   # anteilig ausgebucht

    def test_gebuehr_zaehlt_zum_einstand(self):
        best = pf.bestaende([b("2026-09-06", "kern_kauf", "kern_aktie", 849, isin="DE0007164600",
                               symbol="SAP.DE", stueck=4, kurs=212.0, gebuehr_eur=1.0)])
        self.assertAlmostEqual(best["kern_aktie:DE0007164600"].einstand_eur, 850.0)


class TestMonatUndEinzahlungen(unittest.TestCase):
    def test_monatsgrenzen(self):
        buchungen = [
            b("2026-09-30", "sparplan", "kern_etf", 400, isin="X", stueck=1),
            b("2026-10-01", "sparplan", "kern_etf", 400, isin="X", stueck=1),
            b("2026-10-07", "kern_kauf", "kern_aktie", 800, isin="Y", stueck=4, gebuehr_eur=1.0),
            b("2026-10-05", "umschichtung", "satellit", 500),        # keine Ausgabe
        ]
        sept = pf.monatsausgaben(buchungen, "2026-09")
        okt = pf.monatsausgaben(buchungen, "2026-10")
        self.assertAlmostEqual(sept["ausgegeben_eur"], 400.0)
        self.assertAlmostEqual(okt["ausgegeben_eur"], 1201.0)       # inkl. Gebühr, ohne Umschichtung
        self.assertEqual(len(okt["posten"]), 2)

    def test_offener_rest_gegen_die_monatsrate(self):
        plan = pf.Plan(monatsrate_eur=500.0)
        m = pf.monatsausgaben([b("2026-10-01", "sparplan", "kern_etf", 400, isin="X", stueck=1)],
                              "2026-10", plan)
        self.assertAlmostEqual(m["offen_eur"], 100.0)

    def test_einzahlungen_netto(self):
        e = pf.einzahlungen([
            b("2026-09-06", "einzahlung", "cash", 5000),
            b("2026-10-06", "einzahlung", "cash", 500),
            b("2026-11-06", "auszahlung", "cash", 200),
            b("2026-11-07", "umschichtung", "satellit", 500),        # zählt nicht
        ])
        self.assertAlmostEqual(e["netto_eur"], 5300.0)
        self.assertEqual(len(e["fluesse"]), 3)

    def test_sparplan_gelaufen(self):
        buchungen = [b("2026-10-01", "sparplan", "kern_etf", 400, isin="IE00BK5BQT80", stueck=2)]
        self.assertTrue(pf.sparplan_gelaufen(buchungen, "2026-10"))
        self.assertFalse(pf.sparplan_gelaufen(buchungen, "2026-11"))
        self.assertFalse(pf.sparplan_gelaufen(buchungen, "2026-10", isin="ANDERE"))


class TestBewertung(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = einstellungen(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _depot(self):
        plan = pf.Plan(etf={"isin": "IE00BK5BQT80", "symbol": "VWCE.DE", "anteil_kern": 0.8})
        buchungen = [
            b("2026-09-06", "einzahlung", "cash", 10000),
            b("2026-09-06", "umschichtung", "kern_etf", 7200),
            b("2026-09-06", "umschichtung", "kern_aktie", 1800),
            b("2026-09-06", "umschichtung", "satellit", 1000),
            b("2026-09-07", "sparplan", "kern_etf", 7200, isin="IE00BK5BQT80", symbol="VWCE.DE",
              stueck=40.0, kurs=180.0),
        ]
        return plan, buchungen

    def test_gesamtwert_und_anteile(self):
        plan, buchungen = self._depot()
        w = pf.bewerte(self.s, plan, buchungen, {"VWCE.DE": 200.0})
        self.assertAlmostEqual(w.kern_etf_eur, 8000.0)              # 40 x 200
        self.assertAlmostEqual(w.kern_aktien_cash_eur, 1800.0)      # wartet aufs Kauffenster
        self.assertAlmostEqual(w.kern_eur, 9800.0)                  # ETF-Wert + Aktien-Cash
        self.assertAlmostEqual(w.gesamt_eur, 10800.0)               # + 1000 Satelliten-Cash
        self.assertAlmostEqual(w.satellit_pct, 1000 / 10800)

    def test_ohne_kurs_wird_der_einstand_genommen_und_gemeldet(self):
        plan, buchungen = self._depot()
        w = pf.bewerte(self.s, plan, buchungen, {})
        self.assertIn("VWCE.DE", w.nicht_bewertbar)
        self.assertAlmostEqual(w.kern_etf_eur, 7200.0)              # Einstand statt Marktwert
        self.assertFalse(w.je_position["kern_etf:IE00BK5BQT80"]["bewertet"])

    def test_band_pruefung(self):
        plan, buchungen = self._depot()
        # Bandgrenzen liegen bei 7 % und 15 % des Gesamtwerts, nicht des Kerns.
        for satellit, erwartet in ((690.0, "unter"), (1000.0, "ok"), (1800.0, "ueber")):
            gesamt = 9800.0 + satellit
            w = pf.Werte(gesamt_eur=gesamt, kern_eur=9800.0, satellit_pct=satellit / gesamt)
            self.assertEqual(pf.band_pruefung(w, self.s)["status"], erwartet,
                             f"Satellit {satellit} von {gesamt}")


class TestKauffenster(unittest.TestCase):
    def test_oktober_2026_ist_der_erste_bis_zweite(self):
        """Der 1.10.2026 ist ein Donnerstag — das Fenster ist zwei Tage lang."""
        f = pf.kern_kauffenster(date(2026, 10, 1))
        self.assertTrue(f["offen"])
        self.assertEqual(f["grund"], "quartal")
        self.assertEqual((f["von"], f["bis"]), ("2026-10-01", "2026-10-02"))
        self.assertTrue(pf.kern_kauffenster(date(2026, 10, 2))["offen"])
        self.assertFalse(pf.kern_kauffenster(date(2026, 10, 5))["offen"])

    def test_alle_vier_quartale_zweier_jahre(self):
        for jahr in (2026, 2027):
            for monat in (1, 4, 7, 10):
                von, bis = pf._quartalsfenster(jahr, monat)
                self.assertLessEqual(von.weekday(), 4, f"{jahr}-{monat}: Start am Wochenende")
                self.assertEqual(bis.weekday(), 4, f"{jahr}-{monat}: Ende nicht am Freitag")
                self.assertTrue(pf.kern_kauffenster(von)["offen"])
                self.assertTrue(pf.kern_kauffenster(bis)["offen"])

    def test_ausserhalb_nennt_das_naechste_fenster(self):
        f = pf.kern_kauffenster(date(2026, 9, 5))
        self.assertFalse(f["offen"])
        self.assertEqual(f["naechstes"], "2026-10-01")

    def test_ersteinstieg_oeffnet_einmalig(self):
        """Die dokumentierte Ausnahme von Regel 3.4 für den Startbetrag."""
        offen = pf.Plan(startbetrag={"ersteinstieg_aktien_offen": True})
        zu = pf.Plan(startbetrag={"ersteinstieg_aktien_offen": False})
        f = pf.kern_kauffenster(date(2026, 9, 5), offen)
        self.assertTrue(f["offen"])
        self.assertEqual(f["grund"], "ersteinstieg")
        self.assertFalse(pf.kern_kauffenster(date(2026, 9, 5), zu)["offen"])


class TestGrenzen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = einstellungen(self.tmp.name)
        self.w = pf.Werte(gesamt_eur=20000.0, kern_eur=18000.0, kern_aktien_eur=0.0, je_position={})

    def tearDown(self):
        self.tmp.cleanup()

    def test_fuenf_prozent_je_titel(self):
        ok, _ = pf.kern_grenze_ok(self.w, self.s, "DE000", 999.0)
        self.assertTrue(ok)
        ok, grund = pf.kern_grenze_ok(self.w, self.s, "DE000", 1001.0)
        self.assertFalse(ok)
        self.assertIn("5 %", grund)

    def test_bestand_zaehlt_mit(self):
        self.w.je_position = {"kern_aktie:DE000": {"topf": "kern_aktie", "isin": "DE000", "wert_eur": 900.0}}
        ok, _ = pf.kern_grenze_ok(self.w, self.s, "DE000", 200.0)
        self.assertFalse(ok)

    def test_zwanzig_prozent_des_kerns(self):
        self.w.kern_aktien_eur = 3500.0
        ok, grund = pf.kern_grenze_ok(self.w, self.s, "NEU", 200.0)
        self.assertFalse(ok)
        self.assertIn("20 %", grund)

    def test_ohne_depotwert_keine_freigabe(self):
        ok, grund = pf.kern_grenze_ok(pf.Werte(), self.s, "DE000", 100.0)
        self.assertFalse(ok)
        self.assertIn("Depotwert", grund)


class TestRendite(unittest.TestCase):
    def test_xirr_gegen_handrechnung(self):
        """Eine Einzahlung, ein Jahr, +10 % — die Antwort muss 10 % sein."""
        r = pf.xirr([(date(2026, 1, 1), -1000.0), (date(2027, 1, 1), 1100.0)])
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r, 0.1, places=3)

    def test_xirr_beachtet_die_zeitpunkte(self):
        """Zwei gleiche Einzahlungen, die zweite spät — die Rendite liegt über dem
        einfachen Geldgewinn, weil das zweite Geld kürzer gearbeitet hat."""
        r = pf.xirr([(date(2026, 1, 1), -1000.0), (date(2026, 11, 1), -1000.0),
                     (date(2027, 1, 1), 2100.0)])
        einfach = 100.0 / 2000.0
        self.assertIsNotNone(r)
        self.assertGreater(r, einfach)

    def test_xirr_verlust(self):
        r = pf.xirr([(date(2026, 1, 1), -1000.0), (date(2027, 1, 1), 900.0)])
        self.assertAlmostEqual(r, -0.1, places=3)

    def test_xirr_schweigt_bei_zu_kurzer_historie(self):
        self.assertIsNone(pf.xirr([(date(2026, 9, 1), -1000.0), (date(2026, 9, 20), 1010.0)]))
        self.assertIsNone(pf.xirr([(date(2026, 9, 1), -1000.0)]))
        self.assertIsNone(pf.xirr([(date(2026, 1, 1), -1000.0), (date(2027, 1, 1), -500.0)]))

    def test_performance_trennt_gewinn_von_einzahlung(self):
        """Der Kernfehler, den es zu vermeiden gilt: eine Einzahlung ist kein Gewinn."""
        buchungen = [b("2026-01-01", "einzahlung", "cash", 10000),
                     b("2026-06-01", "einzahlung", "cash", 5000)]
        p = pf.performance(pf.Werte(gesamt_eur=15000.0), buchungen, heute=date(2027, 1, 1))
        self.assertAlmostEqual(p["eingezahlt_netto_eur"], 15000.0)
        self.assertAlmostEqual(p["gewinn_eur"], 0.0)        # trotz 15.000 im Depot: kein Gewinn
        self.assertAlmostEqual(p["xirr_pct"] or 0.0, 0.0, places=3)


class TestKillSwitchEinlage(unittest.TestCase):
    """Regressionstest: eine Einzahlung darf den Drawdown-Kill-Switch nicht verstellen."""

    def test_einzahlung_hebt_den_hoechststand_mit(self):
        acc = journal.Account()
        acc.set_equity(10_000, date(2026, 1, 1))
        acc.set_equity(8_000, date(2026, 6, 1))            # 20 % Drawdown
        self.assertAlmostEqual(acc.drawdown, 0.2)

        acc.einlage(2_000)                                  # Einzahlung, kein Gewinn
        self.assertAlmostEqual(acc.satellite_equity_eur, 10_000)
        self.assertAlmostEqual(acc.high_water_mark, 12_000)
        self.assertAlmostEqual(acc.drawdown, 1 - 10_000 / 12_000)   # Drawdown bleibt bestehen

    def test_ohne_die_korrektur_waere_der_drawdown_verschwunden(self):
        """So verhielt sich das System vorher — der Vergleich hält den Unterschied fest."""
        acc = journal.Account()
        acc.set_equity(10_000, date(2026, 1, 1))
        acc.set_equity(8_000, date(2026, 6, 1))
        acc.set_equity(10_000, date(2026, 6, 2))            # Einzahlung als 'neues Kapital' getippt
        self.assertAlmostEqual(acc.drawdown, 0.0)           # Verlust unsichtbar geworden

    def test_entnahme_senkt_den_hoechststand(self):
        acc = journal.Account()
        acc.set_equity(10_000, date(2026, 1, 1))
        acc.einlage(-3_000)
        self.assertAlmostEqual(acc.satellite_equity_eur, 7_000)
        self.assertAlmostEqual(acc.high_water_mark, 7_000)
        self.assertAlmostEqual(acc.drawdown, 0.0)


class TestStartbetrag(unittest.TestCase):
    def test_aufteilung_folgt_dem_plan(self):
        plan = pf.Plan(etf={"anteil_kern": 0.8},
                       startbetrag={"kern_eur": 4500.0, "satellit_eur": 500.0})
        buchungen = pf.startbetrag_buchungen(plan, date(2026, 9, 6))
        nach_topf = {b_.topf: b_.betrag_eur for b_ in buchungen if b_.typ == "umschichtung"}
        self.assertAlmostEqual(nach_topf["kern_etf"], 3600.0)
        self.assertAlmostEqual(nach_topf["kern_aktie"], 900.0)
        self.assertAlmostEqual(nach_topf["satellit"], 500.0)
        self.assertAlmostEqual(pf.cash(buchungen), 5000.0)
        self.assertAlmostEqual(pf.cash(buchungen, "cash"), 0.0)

    def test_hundert_prozent_etf_legt_keinen_aktien_topf_an(self):
        plan = pf.Plan(etf={"anteil_kern": 1.0}, startbetrag={"kern_eur": 4500.0, "satellit_eur": 500.0})
        toepfe = {b_.topf for b_ in pf.startbetrag_buchungen(plan, date(2026, 9, 6))}
        self.assertNotIn("kern_aktie", toepfe)

    def test_leerer_startbetrag_bucht_nichts(self):
        self.assertEqual(pf.startbetrag_buchungen(pf.Plan(), date(2026, 9, 6)), [])


class TestPlanIO(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = einstellungen(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rundlauf(self):
        plan = pf.Plan(monatsrate_eur=500.0, sparplan_tag=1,
                       etf={"isin": "IE00BK5BQT80", "symbol": "VWCE.DE", "anteil_kern": 0.8},
                       onboarding_erledigt=True)
        pf.speichere_plan(self.s, plan, heute=date(2026, 9, 6))
        zurueck = pf.lade_plan(self.s)
        self.assertEqual(zurueck.etf_symbol, "VWCE.DE")
        self.assertAlmostEqual(zurueck.etf_anteil, 0.8)
        self.assertEqual(zurueck.updated, "2026-09-06")

    def test_fehlende_datei_gibt_leeren_plan(self):
        self.assertFalse(pf.lade_plan(self.s).onboarding_erledigt)

    def test_etf_katalog_ist_lesbar_und_vollstaendig(self):
        s = load_settings(ROOT / "config" / "settings.yaml")
        katalog = pf.lade_etf_katalog(s)
        self.assertGreaterEqual(len(katalog), 10)
        for e in katalog:
            for feld in ("isin", "symbol", "name", "ter", "ertrag", "gruppe"):
                self.assertIn(feld, e, f"{e.get('name')}: {feld} fehlt")
        self.assertTrue(any(e["isin"] == "IE00BK5BQT80" for e in katalog))


TR_CSV = """Date;Type;Value;ISIN;Note;Shares;Fee
2026-09-06;Deposit;5000,00;;Überweisung;;
2026-09-07;Savings plan;-450,00;IE00BK5BQT80;Vanguard FTSE All-World;2,6779;0,00
2026-10-01;Savings plan;-450,00;IE00BK5BQT80;Vanguard FTSE All-World;2,5411;0,00
2026-10-07;Buy;-2178,40;US0378331005;Apple Inc;12;1,00
2026-11-02;Dividend;12,50;US0378331005;Apple Dividende;;
2026-11-03;Kaffeekasse;-3,50;;Was auch immer;;
2026-11-04;Sell;900,00;US0378331005;Apple Inc;5;1,00
;;;;;;
"""


class TestTrImport(unittest.TestCase):
    """Die pytr-CSV ist ein undokumentiertes Fremdformat — der Parser muss misstrauisch sein."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = einstellungen(self.tmp.name)
        plan = pf.Plan(etf={"isin": "IE00BK5BQT80", "symbol": "VWCE.DE", "anteil_kern": 0.8},
                       onboarding_erledigt=True)
        pf.speichere_plan(self.s, plan)

    def tearDown(self):
        self.tmp.cleanup()

    def test_zuordnung_und_unbekanntes(self):
        buchungen, warnungen = tr_import.parse_tr_csv(TR_CSV, pf.lade_plan(self.s))
        nach_typ = {b.typ for b in buchungen}
        self.assertIn("einzahlung", nach_typ)
        self.assertIn("sparplan", nach_typ)           # ETF-ISIN -> Kern
        self.assertIn("satellit_kauf", nach_typ)      # fremde ISIN -> Satellit
        self.assertIn("satellit_verkauf", nach_typ)
        self.assertIn("dividende", nach_typ)
        # Unbekannte Art wird gemeldet, nicht geraten.
        self.assertTrue(any("Kaffeekasse" in w for w in warnungen), warnungen)
        self.assertNotIn("kaffeekasse", {b.typ for b in buchungen})

    def test_deutsche_zahlen_und_betraege_ohne_vorzeichen(self):
        buchungen, _ = tr_import.parse_tr_csv(TR_CSV, pf.lade_plan(self.s))
        sparplan = next(b for b in buchungen if b.typ == "sparplan")
        self.assertAlmostEqual(sparplan.betrag_eur, 450.0)     # Minuszeichen fällt weg
        self.assertAlmostEqual(sparplan.stueck, 2.6779)
        kauf = next(b for b in buchungen if b.typ == "satellit_kauf")
        self.assertAlmostEqual(kauf.gebuehr_eur, 1.0)

    def test_wiederholter_import_bucht_nichts_doppelt(self):
        """pytr exportiert immer die ganze Historie — ohne Abgleich verdoppelt sich alles."""
        erst = tr_import.uebernehmen(self.s, TR_CSV)
        self.assertGreater(erst["gebucht"], 0)
        zweit = tr_import.uebernehmen(self.s, TR_CSV)
        self.assertEqual(zweit["gebucht"], 0)
        self.assertEqual(zweit["bereits_gebucht"], erst["gebucht"])
        self.assertEqual(len(pf.lies_ledger(self.s)), erst["gebucht"])

    def test_vorschau_schreibt_nicht(self):
        v = tr_import.vorschau(self.s, TR_CSV)
        self.assertGreater(v["neu"], 0)
        self.assertEqual(len(pf.lies_ledger(self.s)), 0)
        self.assertEqual(v["zeitraum"][0], "2026-09-06")

    def test_datumsformate(self):
        self.assertEqual(tr_import._datum("06.09.2026"), "2026-09-06")
        self.assertEqual(tr_import._datum("2026-09-06"), "2026-09-06")
        self.assertEqual(tr_import._datum("2026-09-06T14:33:00Z"), "2026-09-06")
        self.assertIsNone(tr_import._datum("irgendwann"))

    def test_fremde_datei_wird_klar_abgelehnt(self):
        with self.assertRaises(ValueError) as ctx:
            tr_import.parse_tr_csv("a,b,c\n1,2,3\n", None)
        self.assertIn("pytr", str(ctx.exception))


class TestAktionsWhitelist(unittest.TestCase):
    """Jede API-Aktion muss auch in der Dashboard-Whitelist stehen.

    Sonst existiert die Aktion serverseitig, das Dashboard antwortet aber mit
    'unbekannte Aktion' — ein Fehler, der beim Testen der Python-Seite unsichtbar bleibt.
    """

    def test_api_und_dashboard_kennen_dieselben_aktionen(self):
        import re

        from satellit import api

        route = (ROOT / "dashboard" / "app" / "api" / "action" / "route.ts").read_text(encoding="utf-8")
        block = route[route.index("const ALLOWED"):route.index("};", route.index("const ALLOWED"))]
        erlaubt = set(re.findall(r'"(/[a-z/]+)"', block))
        # /run/weekly wird in api.py gesondert behandelt und steht nicht in ACTIONS.
        self.assertEqual(set(api.ACTIONS) | {"/run/weekly"}, erlaubt)


if __name__ == "__main__":
    unittest.main()

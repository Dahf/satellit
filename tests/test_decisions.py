"""Tests des Entscheidungsmodells: python -m pytest tests/test_decisions.py

Offline, ohne Kursdaten, ohne Netz — decisions.py ist bewusst frei von pandas und von
Laufzeit-Importen aus pipeline, damit genau das möglich ist.
"""

from __future__ import annotations

import json
import math
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from satellit import decisions as dec  # noqa: E402
from satellit import view  # noqa: E402
from satellit.decisions import Kontext, SkipInfo  # noqa: E402
from satellit.pipeline import PositionView, Proposal  # noqa: E402


def kontext(**kw) -> Kontext:
    basis = dict(
        as_of=date(2026, 9, 4),
        ampel={"US": "GREEN", "EU": "YELLOW"},
        ampel_label={"US": "GRÜN", "EU": "GELB"},
        ampel_detail={"US": "Uptrend 66 · Breadth 58", "EU": "P200 61 % · P50 55 %"},
        risk_pct={"US": 1.0, "EU": 0.5},
        max_neue_einstiege={"US": 2, "EU": 1},
        wochenkurse={"AAPL": [{"d": "2026-08-28", "kurs": 210.0, "sma10w": 200.0}]},
        equity_eur=10_000.0, cash_eur=2_000.0,
        soft_exit_wochen=10, max_positionen=5,
    )
    basis.update(kw)
    return Kontext(**basis)


def position(**kw) -> PositionView:
    basis = dict(
        thesis_id="th_AAPL_1", symbol="AAPL", name="Apple", region="US", currency="USD",
        sector="IT", shares=12, entry=200.0, entry_date="2026-07-01", stop=180.0,
        close=210.0, week_low=205.0, new_stop=180.0, stop_raised=False, soft_exit=False,
        hard_stop_hit=False, pnl_pct=0.05, open_risk_eur=300.0,
        wert_eur=2170.0, einstand_eur=2066.0, gewinn_eur=104.0,
    )
    basis.update(kw)
    return PositionView(**basis)


def kandidat(**kw) -> Proposal:
    basis = dict(
        symbol="AAPL", isin="", name="Apple", region="US", currency="USD", sector="IT",
        close=210.0, breakout_level=208.0, initial_stop=180.0, atr=10.0, rs_rank_pct=0.04,
        shares=12, value_eur=2170.0, risk_eur=100.0, risk_pct=1.0, limit_price=212.1,
        ampel="GRÜN",
    )
    basis.update(kw)
    return Proposal(**basis)


class TestPositionsurteile(unittest.TestCase):
    def test_stop_moeglicherweise_ausgeloest_hat_vorrang(self):
        d = dec.urteil_satellit_position(position(hard_stop_hit=True, week_low=179.0, soft_exit=True), kontext())
        self.assertEqual(d.verdikt, dec.PRUEFEN)
        self.assertEqual(d.dringlichkeit, dec.SOFORT)
        self.assertIn("179", d.begruendung)
        self.assertEqual(d.aktion.body["reason"], "stop")

    def test_trendbruch_verkauft_alles(self):
        d = dec.urteil_satellit_position(position(soft_exit=True), kontext())
        self.assertEqual(d.verdikt, dec.VERKAUFEN)
        self.assertEqual(d.stueck, 12)
        # Der Grund ist fest vorbelegt: ein Regel-Exit darf nicht als "manual" (Regelbruch) landen.
        self.assertEqual(d.aktion.body["reason"], "trend")
        self.assertNotIn("reason", [f["name"] for f in d.aktion.felder])

    def test_stop_anheben_nennt_alt_und_neu(self):
        d = dec.urteil_satellit_position(position(stop_raised=True, new_stop=195.5), kontext())
        self.assertEqual(d.verdikt, dec.STOP_ANHEBEN)
        self.assertEqual(d.neuer_stop, 195.5)
        self.assertIn("180", d.begruendung)
        self.assertIn("195,5", d.begruendung)          # deutsche Schreibweise
        self.assertEqual(d.aktion.aktion, "journal.stop")

    def test_ruhige_position_ist_nur_information(self):
        d = dec.urteil_satellit_position(position(), kontext())
        self.assertEqual(d.verdikt, dec.HALTEN)
        self.assertEqual(d.dringlichkeit, dec.INFO)
        self.assertIsNone(d.aktion)                    # ohne Aktion gibt es keinen Knopf
        self.assertIn("Nichts tun", d.begruendung)

    def test_fehlende_kurse_werden_nicht_als_halten_getarnt(self):
        d = dec.urteil_satellit_position(position(note="keine Kursdaten", close=None), kontext())
        self.assertEqual(d.verdikt, dec.PRUEFEN)


class TestKandidatenurteil(unittest.TestCase):
    def test_begruendung_nennt_menge_stop_und_verlustgrenze(self):
        d = dec.urteil_satellit_kandidat(kandidat(), kontext())
        self.assertEqual(d.verdikt, dec.KAUFEN)
        self.assertEqual(d.stueck, 12)
        for teil in ("12 Stück", "180", "100"):
            self.assertIn(teil, d.begruendung, d.begruendung)
        self.assertEqual(d.aktion.aktion, "journal.new")

    def test_kill_switch_sperrt_den_knopf_mit_grund(self):
        d = dec.urteil_satellit_kandidat(kandidat(), kontext(kill_aktiv=True, kill_grund="Drawdown 26 %"))
        self.assertIsNone(d.aktion)
        self.assertIn("Kill-Switch", d.gesperrt_weil)

    def test_trockenlauf_sperrt_ebenfalls(self):
        d = dec.urteil_satellit_kandidat(kandidat(), kontext(trockenlauf_bis="2026-09-20"))
        self.assertIsNone(d.aktion)
        self.assertIn("2026-09-20", d.gesperrt_weil)


class TestAblehnungen(unittest.TestCase):
    def test_jeder_code_erzeugt_einen_deutschen_satz(self):
        for code in dec.SKIP_TEXTE:
            s = SkipInfo(symbol="AAPL", name="Apple", region="US", sektor="IT", code=code,
                         params={"limit": 2, "max": 2, "preis_eur": 900.0, "grenze_eur": 500.0,
                                 "ampel_label": "GELB"})
            d = dec.urteil_abgelehnt(s, kontext())
            self.assertTrue(d.begruendung.endswith("."), f"{code}: {d.begruendung}")
            self.assertGreater(len(d.begruendung), 25, code)
            self.assertNotIn(code, d.begruendung)      # kein Code-Kürzel in der Anzeige

    def test_hysterese_wird_erklaert(self):
        """'Uptrend 66, trotzdem ROT' sieht ohne Erklärung wie ein Fehler des Systems aus."""
        ctx = kontext(ampel={"US": "RED"}, ampel_label={"US": "ROT"},
                      ampel_note={"US": "Die Rohwerte stehen bereits auf GRÜN, die Ampel schaltet aber erst "
                                        "nach 2 Wochen in Folge um."})
        d = dec.urteil_abgelehnt(SkipInfo(symbol="AAPL", region="US", code="AMPEL_LIMIT",
                                          params={"ampel_label": "ROT", "limit": 0}), ctx)
        self.assertIn("2 Wochen in Folge", d.begruendung)

    def test_unbekannter_code_kippt_nicht(self):
        d = dec.urteil_abgelehnt(SkipInfo(symbol="X", code="GIBTESNICHT"), kontext())
        self.assertTrue(d.begruendung)


class TestZusammenbau(unittest.TestCase):
    def test_sortierung_nach_dringlichkeit(self):
        pos = [position(thesis_id="th_ruhig"), position(thesis_id="th_verkauf", soft_exit=True)]
        out, _ = dec.alle_urteile(pos, [kandidat()], [], kontext())
        self.assertEqual([d.dringlichkeit for d in out], sorted((d.dringlichkeit for d in out), reverse=True))
        self.assertEqual(out[0].verdikt, dec.VERKAUFEN)

    def test_nachkaufen_im_satelliten_ist_strukturell_verboten(self):
        """Trading-Plan 7 — die Regel wird erzwungen, nicht bloß nicht verletzt."""
        original = dec.urteil_cash
        dec.urteil_cash = lambda ctx: dec.Decision(
            schluessel="X", art="cash", topf="SATELLIT", verdikt=dec.NACHKAUFEN,
            verdikt_label="Nachkaufen", dringlichkeit=0, begruendung="verboten")
        try:
            with self.assertRaises(AssertionError):
                dec.alle_urteile([], [], [], kontext())
        finally:
            dec.urteil_cash = original

    def test_ohne_kapital_gibt_es_eine_anleitung_statt_leere(self):
        """Sonst zeigt die Startseite nichts an und der Grund steht nur unter den Ablehnungen."""
        out, _ = dec.alle_urteile([], [], [], kontext(equity_eur=None, cash_eur=None))
        einrichtung = [d for d in out if d.art == "einrichtung"]
        self.assertEqual(len(einrichtung), 1)
        self.assertEqual(einrichtung[0].dringlichkeit, dec.SOFORT)
        self.assertEqual(einrichtung[0].aktion.aktion, "account")

    def test_mit_kapital_keine_einrichtungszeile(self):
        out, _ = dec.alle_urteile([], [], [], kontext(equity_eur=10_000.0))
        self.assertFalse([d for d in out if d.art == "einrichtung"])

    def test_cash_zeile_erlaubt_nichtstun(self):
        out, _ = dec.alle_urteile([], [], [], kontext(cash_eur=2000.0))
        cash = [d for d in out if d.art == "cash"]
        self.assertEqual(len(cash), 1)
        self.assertEqual(cash[0].verdikt, dec.HALTEN)


class TestZuKleinerSatellit(unittest.TestCase):
    """Ohne diese Zeile meldet die Ansicht wochenlang nur „zu teuer“, ohne den Grund zu nennen."""

    def test_zu_klein_nennt_vorhandenes_und_noetiges_kapital(self):
        d = dec.urteil_satellit_zu_klein(kontext(equity_eur=250.0, cash_eur=250.0,
                                                 mindestkapital_eur=1000.0))
        self.assertIsNotNone(d)
        self.assertEqual(d.verdikt, dec.WARTEN)
        self.assertEqual(d.dringlichkeit, dec.INFO)
        self.assertIn("250", d.begruendung)
        self.assertIn("1.000", d.begruendung)
        self.assertIn("750", d.begruendung)          # was fehlt, nicht nur was nötig ist
        self.assertIsNone(d.aktion)                  # es gibt nichts zu klicken

    def test_zu_klein_stellt_den_kern_ausdruecklich_frei(self):
        """Der Satz darf nicht als „mach gar nichts“ gelesen werden — der Kern läuft weiter."""
        d = dec.urteil_satellit_zu_klein(kontext(equity_eur=250.0, mindestkapital_eur=1000.0))
        self.assertTrue(any("Kern" in h for h in d.hinweise))

    def test_ohne_mindestkapital_keine_zeile(self):
        self.assertIsNone(dec.urteil_satellit_zu_klein(kontext(equity_eur=10_000.0)))

    def test_ersetzt_die_cash_zeile_statt_sie_zu_ergaenzen(self):
        """Zwei Zeilen über dasselbe Geld widersprechen sich: „wartet auf ein Signal“ wäre
        falsch, wenn kein Signal je zu einer Order führen könnte."""
        out, _ = dec.alle_urteile([], [], [], kontext(equity_eur=250.0, cash_eur=250.0,
                                                      mindestkapital_eur=1000.0))
        arten = [d.art for d in out]
        self.assertIn("satellit_zu_klein", arten)
        self.assertNotIn("cash", arten)

    def test_bei_ausreichendem_kapital_bleibt_die_cash_zeile(self):
        out, _ = dec.alle_urteile([], [], [], kontext(equity_eur=10_000.0, cash_eur=2_000.0))
        arten = [d.art for d in out]
        self.assertIn("cash", arten)
        self.assertNotIn("satellit_zu_klein", arten)


class TestKernKandidat(unittest.TestCase):
    """Der Kern kennt weder Ampel noch Trockenlauf — beide betreffen nur den Satelliten."""

    def _kandidat(self, **kw):
        from satellit.kern_screener import KernKandidat, Kriterium

        basis = dict(
            symbol="SAP.DE", isin="DE0007164600", name="SAP SE", sektor="IT", region="EU",
            kurs_eur=210.0, jahre_abgedeckt=5, daten_stand="2026-09-05",
            kriterien=[Kriterium(1, "Geschäftsmodell in zwei Sätzen erklärbar", None, "offen"),
                       Kriterium(2, "Wachstum über den Zyklus", True, "steigend"),
                       Kriterium(3, "Kapitalrendite über 10 %", True, "ROIC 18 %"),
                       Kriterium(4, "Nettoverschuldung / EBITDA unter 2,5", True, "0,80"),
                       Kriterium(5, "Free Cashflow positiv", None, "5 von 5 — Fenster nicht abgedeckt"),
                       Kriterium(6, "Über 5 Jahre notiert", True, "seit 1988"),
                       Kriterium(7, "Kill-Kriterien schriftlich", None, "offen", "Trading-Plan 3.2")],
            soll=[Kriterium(0, "Dividende nicht gekürzt", True, "keine Kürzung")],
        )
        basis.update(kw)
        return KernKandidat(**basis)

    def test_offenes_fenster_erlaubt_die_these(self):
        d = dec.urteil_kern_kandidat(self._kandidat(), kontext(kauffenster={"offen": True, "grund": "quartal"}))
        self.assertIsNotNone(d.aktion)
        self.assertEqual(d.aktion.aktion, "journal.new")
        self.assertTrue(d.aktion.body["core"])
        self.assertIsNone(d.gesperrt_weil)

    def test_geschlossenes_fenster_sperrt_den_kauf_nicht_die_these(self):
        """Trading-Plan 3.4: „Zwischen den Terminen werden Kandidaten nur notiert, nie gekauft.“"""
        d = dec.urteil_kern_kandidat(self._kandidat(),
                                     kontext(kauffenster={"offen": False, "naechstes": "2026-10-01"}))
        self.assertIsNotNone(d.aktion)                 # notieren bleibt möglich
        self.assertIn("2026-10-01", d.gesperrt_weil)

    def test_menschliche_kriterien_sind_pflichtfelder(self):
        """Kriterium 1 und 7 kann kein Code beantworten — die Oberfläche erzwingt sie."""
        d = dec.urteil_kern_kandidat(self._kandidat(), kontext(kauffenster={"offen": True}))
        pflicht = {f["name"] for f in d.aktion.felder if f["pflicht"]}
        self.assertEqual(pflicht, {"geschaeftsmodell", "kill_1", "kill_2"})

    def test_durchgefallener_titel_bekommt_keine_aktion(self):
        from satellit.kern_screener import Kriterium

        k = self._kandidat()
        k.kriterien[3] = Kriterium(4, "Nettoverschuldung / EBITDA unter 2,5", False, "6,10")
        d = dec.urteil_kern_kandidat(k, kontext(kauffenster={"offen": True}))
        self.assertIsNone(d.aktion)
        self.assertEqual(d.verdikt, dec.NICHT_KAUFEN)
        self.assertIn("Kriterium 4", d.gesperrt_weil)

    def test_ausschluss_schlaegt_alles(self):
        d = dec.urteil_kern_kandidat(self._kandidat(ausschluss="Läuft im Satelliten."),
                                     kontext(kauffenster={"offen": True}))
        self.assertIsNone(d.aktion)
        self.assertIn("Satelliten", d.gesperrt_weil)

    def test_kein_ampelbezug_im_kern(self):
        d = dec.urteil_kern_kandidat(self._kandidat(), kontext(kauffenster={"offen": True}))
        self.assertIsNone(d.ampel)
        self.assertFalse([b for b in d.belege if "Ampel" in b.label])

    def test_trockenlauf_sperrt_den_kern_nicht(self):
        """Der Trockenlauf ist eine Satelliten-Regel (10.1). Griffe er hier, stünde der Kern still."""
        d = dec.urteil_kern_kandidat(self._kandidat(),
                                     kontext(kauffenster={"offen": True}, trockenlauf_bis="2026-12-31"))
        self.assertIsNotNone(d.aktion)
        self.assertIsNone(d.gesperrt_weil)

    def test_offene_kriterien_werden_als_offen_ausgewiesen(self):
        d = dec.urteil_kern_kandidat(self._kandidat(), kontext(kauffenster={"offen": True}))
        offen = [b for b in d.belege if b.erfuellt is None and b.label.startswith("·")]
        self.assertEqual(len(offen), 3)               # Kriterien 1, 5 und 7
        self.assertTrue(any("nicht geprüft" in h for h in d.hinweise))

    def test_kandidaten_landen_nicht_unter_zu_tun(self):
        """Ein Kandidat ist keine Aufgabe für den Montag."""
        d = dec.urteil_kern_kandidat(self._kandidat(), kontext(kauffenster={"offen": True}))
        self.assertEqual(d.dringlichkeit, dec.INFO)


class TestStueckzahlFormat(unittest.TestCase):
    """Ganze Anteile und Bruchstücke müssen beide stimmen — ein festes Format macht eines falsch."""

    def test_ganze_stueck_ohne_nachkommastellen(self):
        self.assertEqual(dec.stueck(12), "12")
        self.assertEqual(dec.stueck(12.0), "12")

    def test_bruchstueck_mit_nachkommastellen(self):
        self.assertEqual(dec.stueck(0.2634), "0,2634")

    def test_nachlaufende_nullen_fallen_weg(self):
        self.assertEqual(dec.stueck(1.5), "1,5")

    def test_fehlende_zahl_wird_nicht_zu_null(self):
        self.assertEqual(dec.stueck(None), "–")
        self.assertEqual(dec.stueck(float("nan")), "–")

    def test_kandidat_zeigt_bruchstuecke_lesbar(self):
        d = dec.urteil_satellit_kandidat(kandidat(shares=0.2634, value_eur=55.3), kontext())
        self.assertIn("0,2634 Stück", d.begruendung)


class TestFormatierung(unittest.TestCase):
    def test_deutsche_zahlen(self):
        self.assertEqual(dec.zahl(1234.5), "1.234,50")
        self.assertEqual(dec.zahl(None), "–")
        self.assertEqual(dec.zahl(float("nan")), "–")
        self.assertEqual(dec.prozent(0.057), "5,7 %")


class TestPayloadSerialisierung(unittest.TestCase):
    def test_nan_wird_zu_null(self):
        """json.dumps schreibt aus NaN das Literal NaN — Nodes JSON.parse wirft darauf."""
        roh = {"a": float("nan"), "b": float("inf"), "c": [1.0, float("nan")],
               "d": {"e": date(2026, 9, 4)}, "f": 2.5}
        sauber = view._sauber(roh)
        text = json.dumps(sauber, allow_nan=False)     # würde bei NaN eine Ausnahme werfen
        zurueck = json.loads(text)
        self.assertIsNone(zurueck["a"])
        self.assertIsNone(zurueck["b"])
        self.assertEqual(zurueck["c"], [1.0, None])
        self.assertEqual(zurueck["d"]["e"], "2026-09-04")
        self.assertEqual(zurueck["f"], 2.5)

    def test_entscheidung_ueberlebt_den_rundlauf(self):
        d = dec.urteil_satellit_kandidat(kandidat(rs_rank_pct=math.nan), kontext())
        text = json.dumps(view._sauber([d]), allow_nan=False, ensure_ascii=False)
        zurueck = json.loads(text)[0]
        self.assertEqual(zurueck["verdikt"], dec.KAUFEN)
        self.assertIsNone(zurueck["kurs"] and None)    # Struktur steht
        self.assertIn("begruendung", zurueck)
        self.assertIsInstance(zurueck["belege"], list)


if __name__ == "__main__":
    unittest.main()

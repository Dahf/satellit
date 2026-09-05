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

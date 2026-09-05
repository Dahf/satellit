"""Tests des Kern-Kriterienkatalogs: python -m unittest tests.test_kern_screener

Offline, ohne Netz. Der Katalog aus docs/KERN.md 6 ist ein Filter, kein Score — geprüft wird
deshalb vor allem, dass er nicht durchwinkt, was er nicht weiß.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from satellit import kern_screener as ks  # noqa: E402
from satellit.config import load_settings  # noqa: E402
from satellit.fundamentals import (  # noqa: E402
    Fundamentals, FundamentalsCache, FixtureFundamentals, SyntheticFundamentals,
    von_dict, zu_dict,
)

EINSTELLUNGEN = load_settings(ROOT / "config" / "settings.yaml")


def reihe(start_jahr: int, jahre: int, wert: float, wachstum: float = 1.0) -> dict[int, float]:
    return {start_jahr + i: wert * (wachstum ** i) for i in range(jahre)}


def fundamentals(**kw) -> Fundamentals:
    """Ein Titel, der alle rechenbaren Kriterien erfüllt — Abweichungen setzt der Test."""
    basis = dict(
        symbol="GUT", waehrung="EUR", marktkap_eur=25e9, erstnotiz="2005-01-01",
        umsatz=reihe(2016, 10, 1e9, 1.08),
        eps=reihe(2016, 10, 4.0, 1.09),
        roe=reihe(2016, 10, 0.18),
        roic=reihe(2016, 10, 0.16),
        nettoschulden=1.0e9, ebitda=1.0e9,
        fcf=reihe(2016, 10, 3e8),
        dividende=reihe(2016, 10, 1.0, 1.05),
        aktienzahl=reihe(2016, 10, 1e9, 0.98),
        quelle="test", abgerufen_am="2026-09-05",
    )
    basis.update(kw)
    return Fundamentals(**basis)


def kriterium(k: ks.KernKandidat, nummer: int) -> ks.Kriterium:
    return next(x for x in k.kriterien if x.nummer == nummer)


class TestMussKriterien(unittest.TestCase):
    def test_guter_titel_besteht(self):
        k = ks.pruefe(fundamentals(), EINSTELLUNGEN, jahre_notiert=20.0)
        self.assertTrue(k.bestanden, [f"{x.nummer}: {x.wert}" for x in k.durchgefallen])

    def test_kriterium_2_faellt_bei_schrumpfendem_umsatz(self):
        k = ks.pruefe(fundamentals(umsatz=reihe(2016, 10, 1e9, 0.95)), EINSTELLUNGEN, jahre_notiert=20.0)
        self.assertFalse(kriterium(k, 2).erfuellt)
        self.assertFalse(k.bestanden)

    def test_kriterium_3_faellt_bei_zu_kleiner_kapitalrendite(self):
        k = ks.pruefe(fundamentals(roic=reihe(2016, 10, 0.04), roe=reihe(2016, 10, 0.04)),
                      EINSTELLUNGEN, jahre_notiert=20.0)
        self.assertFalse(kriterium(k, 3).erfuellt)

    def test_kriterium_3_nutzt_roe_wenn_roic_fehlt(self):
        k = ks.pruefe(fundamentals(roic={}), EINSTELLUNGEN, jahre_notiert=20.0)
        self.assertTrue(kriterium(k, 3).erfuellt)
        self.assertIn("ROE", kriterium(k, 3).wert)

    def test_kriterium_4_faellt_bei_hoher_verschuldung(self):
        k = ks.pruefe(fundamentals(nettoschulden=9e9, ebitda=1e9), EINSTELLUNGEN, jahre_notiert=20.0)
        self.assertFalse(kriterium(k, 4).erfuellt)
        self.assertIn("9,00", kriterium(k, 4).wert)

    def test_kriterium_4_zaehlt_nettoliquiditaet_als_erfuellt(self):
        k = ks.pruefe(fundamentals(nettoschulden=-2e9), EINSTELLUNGEN, jahre_notiert=20.0)
        self.assertTrue(kriterium(k, 4).erfuellt)

    def test_kriterium_5_faellt_bei_zu_vielen_negativen_jahren(self):
        fcf = reihe(2016, 10, 3e8)
        for j in list(fcf)[:4]:
            fcf[j] = -1e8
        k = ks.pruefe(fundamentals(fcf=fcf), EINSTELLUNGEN, jahre_notiert=20.0)
        self.assertFalse(kriterium(k, 5).erfuellt)

    def test_kriterium_6_faellt_bei_zu_kleiner_marktkapitalisierung(self):
        k = ks.pruefe(fundamentals(marktkap_eur=1e9), EINSTELLUNGEN, jahre_notiert=20.0)
        self.assertFalse(kriterium(k, 6).erfuellt)

    def test_kriterium_6_faellt_bei_zu_junger_notierung(self):
        """IPOs jünger als fünf Jahre sind ausdrücklich ausgeschlossen."""
        k = ks.pruefe(fundamentals(erstnotiz="2024-01-01"), EINSTELLUNGEN,
                      jahre_notiert=2.0, as_of=date(2026, 9, 5))
        self.assertFalse(kriterium(k, 6).erfuellt)

    def test_kurze_kurshistorie_ist_kein_ausschlussgrund(self):
        """Der Kurs-Cache umfasst anfangs rund 420 Tage. Würde daraus auf ein junges
        Unternehmen geschlossen, fiele beim ersten Lauf das gesamte Universum durch."""
        k = ks.pruefe(fundamentals(erstnotiz="1998-05-03"), EINSTELLUNGEN,
                      jahre_notiert=1.6, as_of=date(2026, 9, 5))
        self.assertTrue(kriterium(k, 6).erfuellt)
        self.assertIn("1998", kriterium(k, 6).wert)

    def test_ohne_erstnotiz_belegt_lange_kurshistorie_das_alter(self):
        k = ks.pruefe(fundamentals(erstnotiz=None), EINSTELLUNGEN, jahre_notiert=12.0)
        self.assertTrue(kriterium(k, 6).erfuellt)

    def test_ohne_erstnotiz_und_mit_kurzer_historie_bleibt_es_offen(self):
        """Nicht „durchgefallen“ — unbekannt. Der Unterschied ist der Punkt."""
        k = ks.pruefe(fundamentals(erstnotiz=None), EINSTELLUNGEN, jahre_notiert=1.6)
        self.assertIsNone(kriterium(k, 6).erfuellt)
        self.assertIn("unbekannt", kriterium(k, 6).wert)


class TestEhrlichkeitUeberDieDatenlage(unittest.TestCase):
    """Der Kern der Sache: was nicht bekannt ist, darf nicht als erfüllt gelten."""

    def test_fehlende_jahre_werden_nicht_als_erfuellt_getarnt(self):
        """Vier positive von vier bekannten Jahren beantworten „8 von 10" nicht."""
        k = ks.pruefe(fundamentals(fcf=reihe(2022, 4, 3e8)), EINSTELLUNGEN, jahre_notiert=20.0)
        self.assertIsNone(kriterium(k, 5).erfuellt)
        self.assertNotEqual(kriterium(k, 5).erfuellt, True)
        self.assertIn("nicht abgedeckt", kriterium(k, 5).wert)

    def test_kurze_historie_kippt_kriterium_5_trotzdem_wenn_es_schon_reisst(self):
        """Drei negative Jahre reißen die Grenze, egal wie viele noch fehlen — das ist
        keine Unsicherheit mehr, sondern ein Ergebnis."""
        fcf = {2023: -1e8, 2024: -1e8, 2025: -1e8, 2026: 1e8}
        k = ks.pruefe(fundamentals(fcf=fcf), EINSTELLUNGEN, jahre_notiert=20.0)
        self.assertFalse(kriterium(k, 5).erfuellt)

    def test_kurze_reihe_macht_kriterium_2_ungeprueft(self):
        k = ks.pruefe(fundamentals(umsatz=reihe(2023, 3, 1e9, 1.08), eps=reihe(2023, 3, 4.0, 1.08)),
                      EINSTELLUNGEN, jahre_notiert=20.0)
        self.assertIsNone(kriterium(k, 2).erfuellt)

    def test_kurzer_schnitt_macht_kriterium_3_ungeprueft(self):
        """Zwei gute Jahre sind kein Fünfjahresschnitt."""
        k = ks.pruefe(fundamentals(roic=reihe(2025, 2, 0.20), roe=reihe(2025, 2, 0.20)),
                      EINSTELLUNGEN, jahre_notiert=20.0)
        self.assertIsNone(kriterium(k, 3).erfuellt)

    def test_menschliche_kriterien_bleiben_offen(self):
        k = ks.pruefe(fundamentals(), EINSTELLUNGEN, jahre_notiert=20.0)
        self.assertIsNone(kriterium(k, 1).erfuellt)
        self.assertIsNone(kriterium(k, 7).erfuellt)
        self.assertEqual(kriterium(k, 7).regel, "Trading-Plan 3.2")

    def test_ungeprueftes_verhindert_das_bestehen_nicht_bleibt_aber_sichtbar(self):
        k = ks.pruefe(fundamentals(fcf=reihe(2022, 4, 3e8)), EINSTELLUNGEN, jahre_notiert=20.0)
        self.assertTrue(k.bestanden)
        self.assertIn(5, [x.nummer for x in k.ungeprueft])

    def test_leere_quelle_besteht_nicht_still(self):
        """Ohne Daten darf kein Titel als geprüft gelten — sonst besteht jeder Unbekannte."""
        k = ks.pruefe(Fundamentals(symbol="LEER"), EINSTELLUNGEN)
        self.assertEqual(len(k.ungeprueft), len(ks.MUSS))
        self.assertEqual(k.jahre_abgedeckt, 0)


class TestAusschluss(unittest.TestCase):
    def test_titel_im_satelliten_wird_ausgeschlossen(self):
        """KERN.md 6 und Trading-Plan 3.5: kein Doppelhalten."""
        k = ks.pruefe(fundamentals(), EINSTELLUNGEN, jahre_notiert=20.0, im_satelliten=True)
        self.assertFalse(k.bestanden)
        self.assertIn("Satelliten", k.ausschluss)

    def test_titel_auf_der_watchlist_wird_ausgeschlossen(self):
        k = ks.pruefe(fundamentals(), EINSTELLUNGEN, jahre_notiert=20.0, auf_watchlist=True)
        self.assertFalse(k.bestanden)
        self.assertTrue(k.ausschluss)


class TestSollUndRangfolge(unittest.TestCase):
    def test_dividendenkuerzung_wird_erkannt(self):
        div = reihe(2016, 10, 1.0)
        div[2022] = 0.4
        k = ks.pruefe(fundamentals(dividende=div), EINSTELLUNGEN, jahre_notiert=20.0)
        soll = next(x for x in k.soll if "Dividende" in x.label)
        self.assertFalse(soll.erfuellt)
        # Soll-Kriterien sind Tiebreaker, kein Muss — der Titel besteht weiter.
        self.assertTrue(k.bestanden)

    def test_sinkende_aktienzahl_zaehlt_als_soll(self):
        k = ks.pruefe(fundamentals(), EINSTELLUNGEN, jahre_notiert=20.0)
        soll = next(x for x in k.soll if "Aktienzahl" in x.label)
        self.assertTrue(soll.erfuellt)

    def test_bestandene_stehen_vor_durchgefallenen(self):
        gut = ks.pruefe(fundamentals(symbol="GUT"), EINSTELLUNGEN, jahre_notiert=20.0)
        schlecht = ks.pruefe(fundamentals(symbol="SCHLECHT", marktkap_eur=1e8),
                             EINSTELLUNGEN, jahre_notiert=20.0)
        self.assertEqual([k.symbol for k in ks.rangfolge([schlecht, gut])], ["GUT", "SCHLECHT"])

    def test_trichter_addiert_sich_zur_gesamtzahl(self):
        alle = [
            ks.pruefe(fundamentals(symbol="A"), EINSTELLUNGEN, jahre_notiert=20.0),
            ks.pruefe(fundamentals(symbol="B", marktkap_eur=1e8), EINSTELLUNGEN, jahre_notiert=20.0),
            ks.pruefe(fundamentals(symbol="C"), EINSTELLUNGEN, jahre_notiert=20.0, im_satelliten=True),
        ]
        t = ks.trichter(alle)
        summe = t["ausgeschlossen"] + t["bestanden"] + sum(t[f"kriterium_{n}"] for n in ks.MUSS)
        self.assertEqual(summe, t["gesamt"])


class TestFundamentalsSpeicher(unittest.TestCase):
    def test_rundlauf_erhaelt_jahreszahlen_als_int(self):
        """JSON kennt keine Zahl als Schlüssel — ohne Rückwandlung bricht jede Jahresrechnung."""
        f = fundamentals()
        zurueck = von_dict(json.loads(json.dumps(zu_dict(f))))
        self.assertEqual(zurueck.umsatz.keys(), f.umsatz.keys())
        self.assertTrue(all(isinstance(j, int) for j in zurueck.umsatz))
        self.assertEqual(zurueck.jahre_abgedeckt, f.jahre_abgedeckt)

    def test_cache_schreibt_und_liest(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = FundamentalsCache(tmp)
            cache.save(fundamentals(symbol="SAP.DE"))
            geladen = cache.load("SAP.DE")
            self.assertIsNotNone(geladen)
            self.assertEqual(geladen.symbol, "SAP.DE")
            self.assertEqual(cache.alter_tage(geladen, date(2026, 9, 12)), 7)

    def test_cache_uebersteht_kaputte_datei(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "X.json").write_text("{kein json", encoding="utf-8")
            self.assertIsNone(FundamentalsCache(tmp).load("X"))

    def test_synthetische_quelle_laesst_titel_durchfallen(self):
        """Ein Demo, in dem alles besteht, zeigt den Filter nicht."""
        symbole = [f"DEMO{i}" for i in range(30)]
        daten = SyntheticFundamentals().fetch(symbole).daten
        ergebnis = [ks.pruefe(daten[s], EINSTELLUNGEN, jahre_notiert=10.0) for s in symbole]
        bestanden = [k for k in ergebnis if k.bestanden]
        self.assertTrue(0 < len(bestanden) < len(ergebnis))

    def test_fixture_quelle_meldet_fehlende_datei(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "DA.json").write_text(
                json.dumps(zu_dict(fundamentals(symbol="DA"))), encoding="utf-8")
            res = FixtureFundamentals(tmp).fetch(["DA", "WEG"])
            self.assertIn("DA", res.daten)
            self.assertIn("WEG", res.failed)


if __name__ == "__main__":
    unittest.main()

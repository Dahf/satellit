"""Indexmitgliedschaft rückwirkend rekonstruieren — gegen Survivorship Bias.

Ein Backtest auf den *heutigen* Indexmitgliedern misst eine Strategie an einem Universum,
das per Konstruktion nur Überlebende enthält. Bei Momentum-Ausbrüchen ist das die denkbar
schlechteste Verzerrung: gerade die Titel, deren Ausbruch nicht hielt, die abgestürzt sind
und deshalb aus dem Index flogen, fehlen vollständig. Die Strategie wird an genau den
Fällen gemessen, in denen sie funktioniert hat.

Deshalb wird für die USA die Mitgliedschaft je Stichtag aus einer Änderungshistorie
zurückgerechnet: Ausgangspunkt sind die heutigen Mitglieder, dann wird Änderung für
Änderung rückwärts gelaufen — wer später aufgenommen wurde, wird entfernt; wer später
entfernt wurde, kommt zurück.

**Das behebt den Survivorship Bias nur zur Hälfte, und die andere Hälfte bleibt offen.**
Die Rekonstruktion liefert die *Mitgliedschaft*, aber nicht die *Stammdaten und Kurse* der
entfernten Titel: iShares veröffentlicht ausschließlich aktuelle Bestände, und für viele
delistete Ticker liefert die Kursquelle nichts mehr. Was dieses Modul sicher entfernt, ist
der Blick in die Zukunft — heutige Indexmitglieder, die zum Stichtag noch gar nicht
aufgenommen waren, fallen aus dem Universum. Was es *nicht* leisten kann, ist die Rückkehr
der Abgestürzten ins Testfeld. Genau deshalb ist `abdeckung()` keine Nebeninformation: die
Kennzahl sagt, welcher Anteil des damaligen Index überhaupt geprüft werden konnte, und ein
Backtest-Ergebnis ohne sie ist nicht bewertbar. Eine vollständige Behebung bräuchte eine
Kursquelle, die delistete Titel führt — die gibt es nicht kostenlos.

**Für Europa gibt es nicht einmal die Mitgliedschaftshistorie frei.** Diese Asymmetrie wird
nicht kaschiert: `EU` läuft auf den heutigen Konstituenten, und das Ergebnis ist als
Obergrenze auszuweisen, nicht als Prognose (Trading-Plan 10.3 — ein Ergebnis, das nur auf
dem EU-Teil beruht, zählt nicht als Bestehen).

Die Änderungsdatei (`state/universe/sp500_changes.csv`) wird **nicht** von diesem Modul
heruntergeladen. Sie ist eine Eingabe, die der Nutzer bereitstellt; ein Backtest, der sich
seine Datenbasis still selbst beschafft, verbirgt, worauf sein Urteil beruht. Format:

    datum,aufgenommen,entfernt
    2024-03-18,SMCI,WHR
    2024-04-03,,DFS

Eine Zeile je Änderung, `datum` als ISO-Datum, leere Felder erlaubt.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .universe import Constituent

log = logging.getLogger(__name__)

AENDERUNGSDATEI = "sp500_changes.csv"


@dataclass(frozen=True)
class Aenderung:
    datum: date
    aufgenommen: str = ""
    entfernt: str = ""


def lies_aenderungen(pfad: Path) -> tuple[list[Aenderung], list[str]]:
    """Änderungshistorie einlesen. Gibt (Änderungen, Hinweise) zurück.

    Unlesbare Zeilen werden übersprungen und gemeldet, nicht geraten — eine falsch geratene
    Indexänderung verschiebt das Universum eines ganzen Zeitraums.
    """
    if not pfad.exists():
        return [], [f"Keine Änderungshistorie unter {pfad} — das US-Universum wäre nur "
                    f"überlebensbereinigt, nicht punkt-in-zeit."]
    out: list[Aenderung] = []
    hinweise: list[str] = []
    with pfad.open(encoding="utf-8", newline="") as f:
        for nr, zeile in enumerate(csv.DictReader(f), start=2):
            roh = (zeile.get("datum") or "").strip()
            try:
                d = date.fromisoformat(roh)
            except ValueError:
                hinweise.append(f"Zeile {nr}: Datum '{roh}' nicht lesbar — übersprungen")
                continue
            out.append(Aenderung(d,
                                 (zeile.get("aufgenommen") or "").strip().upper(),
                                 (zeile.get("entfernt") or "").strip().upper()))
    out.sort(key=lambda a: a.datum)
    return out, hinweise


def mitglieder_am(stichtag: date, heutige: set[str], aenderungen: list[Aenderung]) -> set[str]:
    """Welche Ticker waren am `stichtag` im Index?

    Rückwärts von heute: jede Änderung *nach* dem Stichtag wird zurückgedreht. Wer nach dem
    Stichtag aufgenommen wurde, war damals nicht drin; wer nach dem Stichtag entfernt wurde,
    war damals noch drin.
    """
    menge = set(heutige)
    for a in reversed(aenderungen):
        if a.datum <= stichtag:
            break
        if a.aufgenommen:
            menge.discard(a.aufgenommen)
        if a.entfernt:
            menge.add(a.entfernt)
    return menge


class Universumshistorie:
    """Konstituenten je Stichtag — punkt-in-zeit für US, heutiger Stand für EU.

    `vollstaendig` sagt je Region, ob die Rückrechnung überhaupt möglich war. Der Bericht
    des Backtests muss das ausweisen; ein Ergebnis ohne diese Angabe ist nicht bewertbar.
    """

    def __init__(self, konstituenten: list[Constituent], aenderungen: list[Aenderung] | None = None,
                 hinweise: list[str] | None = None):
        self.konstituenten = konstituenten
        self.aenderungen = aenderungen or []
        self.hinweise = list(hinweise or [])
        self._je_ticker = {c.ticker.upper(): c for c in konstituenten if c.region == "US"}
        self._heute_us = set(self._je_ticker)

    @classmethod
    def laden(cls, konstituenten: list[Constituent], universe_dir: Path) -> "Universumshistorie":
        aenderungen, hinweise = lies_aenderungen(universe_dir / AENDERUNGSDATEI)
        if aenderungen:
            hinweise.append(f"US punkt-in-zeit: {len(aenderungen)} Indexänderungen ab "
                            f"{aenderungen[0].datum.isoformat()}")
        hinweise.append("EU ohne Punkt-in-Zeit-Historie — Ergebnis ist eine Obergrenze, "
                        "keine Prognose (Trading-Plan 10.3)")
        return cls(konstituenten, aenderungen, hinweise)

    @property
    def vollstaendig(self) -> dict[str, bool]:
        return {"US": bool(self.aenderungen), "EU": False}

    def am(self, stichtag: date) -> list[Constituent]:
        """Das Universum, wie es am Stichtag ausgesehen hat."""
        if not self.aenderungen:
            return list(self.konstituenten)
        us = mitglieder_am(stichtag, self._heute_us, self.aenderungen)
        out = [c for c in self.konstituenten if c.region != "US"]
        for ticker in sorted(us):
            c = self._je_ticker.get(ticker)
            if c is not None:
                out.append(c)
        return out

    def fehlende_stammdaten(self, stichtag: date) -> set[str]:
        """Ticker, die damals im Index waren, für die aber keine Stammdaten vorliegen.

        Das sind die zwischenzeitlich entfernten Titel — genau die, deren Fehlen den
        Survivorship Bias ausmacht. Sie tauchen in der Mitgliedschaft auf, aber nicht im
        Testfeld, weil iShares nur aktuelle Bestände liefert.
        """
        if not self.aenderungen:
            return set()
        return mitglieder_am(stichtag, self._heute_us, self.aenderungen) - set(self._je_ticker)

    def abdeckung(self, stichtag: date) -> dict:
        """Wie viel des damaligen US-Index konnte tatsächlich geprüft werden?

        Die ehrliche Kennzahl zum Survivorship Bias. `anteil` von 1,0 hieße: jeder Titel,
        der am Stichtag im Index stand, liegt auch als Stammdatensatz vor. Alles darunter
        ist der Rest der Verzerrung — benannt, nicht behoben. Gehört in jeden Bericht;
        ein Backtest, der sie verschweigt, behauptet mehr, als er geprüft hat.
        """
        if not self.aenderungen:
            return {"mitglieder": len(self._heute_us), "geprueft": len(self._heute_us),
                    "fehlend": 0, "anteil": None,
                    "hinweis": "keine Änderungshistorie — nur heutige Mitglieder, voll überlebensverzerrt"}
        mitglieder = mitglieder_am(stichtag, self._heute_us, self.aenderungen)
        fehlend = mitglieder - set(self._je_ticker)
        gesamt = len(mitglieder)
        return {
            "mitglieder": gesamt,
            "geprueft": gesamt - len(fehlend),
            "fehlend": len(fehlend),
            "anteil": (gesamt - len(fehlend)) / gesamt if gesamt else None,
        }

"""Import der Umsatzliste aus Trade Republic.

Trade Republic hat keine offizielle Schnittstelle. Es gibt `pytr`, einen inoffiziellen
Zugang zur privaten App-API; dessen Befehl `export_transactions` erzeugt eine CSV.

Bewusste Festlegung: **pytr läuft auf dem Rechner des Nutzers, nicht auf dem Server.**
Die Datei wird hier hochgeladen. So liegen Telefonnummer, PIN und Gerätschlüssel nie auf
einer dauerhaft laufenden Maschine.

Das Spaltenformat ist nirgends dokumentiert und kann sich ohne Ankündigung ändern. Der
Parser ordnet deshalb über Spalten-Aliase zu, überspringt Unbekanntes mit einer Warnung
statt zu raten, und jede Übernahme läuft zweistufig: erst Vorschau, dann Buchung.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date, datetime

from .config import Settings
from .portfolio import (Buchung, lade_plan, lies_ledger, schreibe_buchungen, schluessel)
from .universe import _decode, _normalise_header, parse_number

log = logging.getLogger(__name__)

MAX_ZEILEN = 20_000

# Spaltenüberschriften. pytr übersetzt sie in die gewählte Sprache (Standard: Systemsprache
# oder Englisch), deshalb müssen mindestens Deutsch und Englisch abgedeckt sein.
# Geprüft gegen pytr 0.4.10, `pytr.transactions.CSVCOLUMN_TO_TRANSLATION_KEY`.
SPALTEN_ALIASE = {
    "datum": {"date", "datum", "timestamp", "zeitpunkt"},
    "typ": {"type", "typ", "transaction type", "event type"},
    "wert": {"value", "wert", "amount", "betrag"},
    "isin": {"isin"},
    "titel": {"note", "notiz", "title", "titel", "description", "beschreibung"},
    "stueck": {"shares", "stück", "stueck", "quantity", "anzahl"},
    "gebuehr": {"fees", "gebühren", "gebuehren", "fee", "gebühr", "gebuehr"},
    "steuer": {"taxes", "steuern", "tax", "steuer"},
}

# TR-Ereignisart -> (Buchungstyp, Topf). Alle Werte stammen aus den Übersetzungstabellen
# von pytr 0.4.10 (`pytr.event.PPEventType` durch `setup_translation`), nicht aus Vermutung.
# "?" heißt: der Topf ergibt sich aus der ISIN (Kern-ETF, Kern-Aktie oder Satellit).
#
# Ein Sparplan ist bei TR kein eigener Ereignistyp — er kommt als Kauf mit der ETF-ISIN an
# und wird darüber erkannt.
TYP_ZUORDNUNG: dict[str, tuple[str, str]] = {
    # Geld hinein
    "deposit": ("einzahlung", "cash"),
    "einlage": ("einzahlung", "cash"),
    "transfer (inbound)": ("einzahlung", "cash"),
    "umbuchung (eingang)": ("einzahlung", "cash"),
    # Geld hinaus
    "removal": ("auszahlung", "cash"),
    "entnahme": ("auszahlung", "cash"),
    "transfer (outbound)": ("auszahlung", "cash"),
    "umbuchung (ausgang)": ("auszahlung", "cash"),
    # Wertpapiere
    "buy": ("kauf", "?"),
    "kauf": ("kauf", "?"),
    "sell": ("verkauf", "?"),
    "verkauf": ("verkauf", "?"),
    # Erträge
    "dividend": ("dividende", "cash"),
    "dividende": ("dividende", "cash"),
    "interest": ("dividende", "cash"),
    "zinsen": ("dividende", "cash"),
    # Kosten
    "fees": ("gebuehr", "cash"),
    "gebühren": ("gebuehr", "cash"),
    "interest charge": ("gebuehr", "cash"),
    "zinsbelastung": ("gebuehr", "cash"),
    "taxes": ("steuer", "cash"),
    "steuern": ("steuer", "cash"),
    # Erstattungen
    "tax refund": ("korrektur", "cash"),
    "steuerrückerstattung": ("korrektur", "cash"),
    "fees refund": ("korrektur", "cash"),
    "gebührenerstattung": ("korrektur", "cash"),
}

# Bekannt, aber bewusst nicht automatisch gebucht: reine Stückzahl-Ereignisse ohne
# Geldfluss. Sie brauchen eine Entscheidung darüber, wie der Einstand aufgeteilt wird —
# das kann nur der Depotinhaber. Sie werden gemeldet, nicht geraten.
NICHT_AUTOMATISCH = {
    "spinoff": "Abspaltung", "split": "Aktiensplit", "swap": "Tausch",
}

# Trade Republic ist Bank **und** Broker; der Export mischt beides. Ein- und Auszahlungen
# sind Kontobewegungen, keine Anlageentscheidungen — Kartenzahlungen erst recht. Würden sie
# als Portfolio-Einzahlungen gebucht, wäre "Eingezahlt" die Summe aus Anlagegeld und
# Alltagsausgaben, und Gewinn wie Rendite wären wertlos.
GELDBEWEGUNGEN = {"einzahlung", "auszahlung"}
KARTENZAHLUNG = "kartentransaktion"


def _datum(text: str) -> str | None:
    """TT.MM.JJJJ, JJJJ-MM-TT und ISO-Zeitstempel. Im Repo gab es dafür bisher nichts."""
    roh = (text or "").strip()
    if not roh:
        return None
    roh = roh.split("T")[0].split(" ")[0]
    for muster in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(roh, muster).date().isoformat()
        except ValueError:
            continue
    return None


def _topf_fuer(isin: str, plan, kern_isins: set[str] | None = None) -> str:
    """Kern-ETF, Kern-Aktie oder Satellit? Die ISIN entscheidet.

    `kern_isins` sind die ISINs offener Kern-Thesen. Ohne sie landete jeder importierte
    Aktienkauf im Satelliten — auch eine Kern-Aktie. Die Folge war ein Satellit, der im
    Kassenbuch größer aussieht, als er ist, und ein Kern, dessen Aktienteil nie erscheint.
    """
    if not isin:
        return "satellit"
    if plan is not None and isin == plan.etf_isin:
        return "kern_etf"
    if kern_isins and isin.upper() in kern_isins:
        return "kern_aktie"
    return "satellit"


def kern_isins(settings) -> set[str]:
    """ISINs der offenen Kern-Thesen — die einzige Stelle, an der eine Aktie zum Kern gehört."""
    from . import journal

    out: set[str] = set()
    for these in journal.core_positions(settings):
        prov = (these.get("origin") or {}).get("raw_provenance") or {}
        if prov.get("isin"):
            out.add(str(prov["isin"]).strip().upper())
    return out


def parse_tr_csv(text: str, plan=None, mit_geldbewegungen: bool = False,
                 ab: str | None = None, kern: set[str] | None = None
                 ) -> tuple[list[Buchung], list[str]]:
    """CSV -> Buchungen + Warnungen. Wirft nur, wenn die Datei gar keine Tabelle ist.

    `mit_geldbewegungen=False` (Standard) überspringt Ein- und Auszahlungen: bei Trade
    Republic sind das Kontobewegungen des Verrechnungskontos, nicht Anlageentscheidungen.
    Was ins Portfolio geflossen ist, legst du bei der Einrichtung fest.

    `ab` begrenzt auf Buchungen ab diesem Datum — nützlich, wenn das Depot einen definierten
    Startzeitpunkt hat und die Vorgeschichte nicht dazugehört.

    `kern` sind die ISINs der Kern-Aktien (siehe `kern_isins`). Ohne sie landet jeder
    Aktienkauf im Satelliten.
    """
    kern = {s.upper() for s in (kern or set())}
    warnungen: list[str] = []
    uebersprungen = {"karte": 0, "geld": 0, "alt": 0}
    zeilen = text.splitlines()
    if not zeilen:
        raise ValueError("Die Datei ist leer.")

    trenner = ";" if zeilen[0].count(";") > zeilen[0].count(",") else ","
    leser = csv.reader(io.StringIO(text), delimiter=trenner)
    try:
        kopf = next(leser)
    except StopIteration as exc:
        raise ValueError("Die Datei enthält keinen Tabellenkopf.") from exc

    cols: dict[str, int] = {}
    for idx, zelle in enumerate(kopf):
        key = zelle.strip().lower().lstrip("﻿")
        for feld, aliase in SPALTEN_ALIASE.items():
            if key in aliase and feld not in cols:
                cols[feld] = idx
    for pflicht in ("datum", "typ", "wert"):
        if pflicht not in cols:
            raise ValueError(
                f"Spalte für '{pflicht}' nicht gefunden. Gelesener Kopf: {', '.join(kopf[:8])}. "
                "Stammt die Datei aus `pytr export_transactions`?")

    def zelle(row: list[str], feld: str) -> str:
        i = cols.get(feld)
        return row[i].strip() if i is not None and i < len(row) else ""

    out: list[Buchung] = []
    for nr, row in enumerate(leser, start=2):
        if nr > MAX_ZEILEN:
            warnungen.append(f"Nur die ersten {MAX_ZEILEN} Zeilen gelesen.")
            break
        if not row or not any(z.strip() for z in row):
            continue
        datum = _datum(zelle(row, "datum"))
        if not datum:
            warnungen.append(f"Zeile {nr}: Datum {zelle(row, 'datum')!r} nicht lesbar — übersprungen.")
            continue
        roh_typ = re.sub(r"\s+", " ", zelle(row, "typ")).strip().lower()
        if roh_typ in NICHT_AUTOMATISCH:
            warnungen.append(f"Zeile {nr}: {NICHT_AUTOMATISCH[roh_typ]} ({zelle(row, 'titel')[:40]}) — "
                             f"verändert nur die Stückzahl, nicht das Geld. Bitte von Hand buchen.")
            continue
        zuordnung = TYP_ZUORDNUNG.get(roh_typ)
        if zuordnung is None:
            warnungen.append(f"Zeile {nr}: Art {zelle(row, 'typ')!r} unbekannt — übersprungen, "
                             f"bitte von Hand buchen.")
            continue
        if ab and datum < ab:
            uebersprungen["alt"] += 1
            continue

        typ, topf = zuordnung
        notiz = zelle(row, "titel")
        # Kartenzahlungen sind Alltagsausgaben, nie eine Anlageentscheidung.
        if notiz.lower().startswith(KARTENZAHLUNG):
            uebersprungen["karte"] += 1
            continue
        if typ in GELDBEWEGUNGEN and not mit_geldbewegungen:
            uebersprungen["geld"] += 1
            continue

        betrag = parse_number(zelle(row, "wert"))
        if betrag != betrag:
            warnungen.append(f"Zeile {nr}: Betrag {zelle(row, 'wert')!r} nicht lesbar — übersprungen.")
            continue
        isin = zelle(row, "isin").upper()
        if typ == "kauf":
            topf = _topf_fuer(isin, plan, kern)
            typ = {"kern_etf": "sparplan", "kern_aktie": "kern_kauf"}.get(topf, "satellit_kauf")
        elif typ == "verkauf":
            topf = _topf_fuer(isin, plan, kern)
            typ = "kern_verkauf" if topf.startswith("kern") else "satellit_verkauf"

        stueck = parse_number(zelle(row, "stueck"))
        gebuehr = parse_number(zelle(row, "gebuehr"))
        out.append(Buchung(
            datum=datum, typ=typ, topf=topf, betrag_eur=abs(betrag), isin=isin,
            stueck=0.0 if stueck != stueck else abs(stueck),
            gebuehr_eur=0.0 if gebuehr != gebuehr else abs(gebuehr),
            notiz=notiz[:80], quelle="tr_import",
            quelle_id=schluessel(datum, typ, isin, abs(betrag),
                                 0.0 if stueck != stueck else abs(stueck)),
        ))
    if uebersprungen["karte"]:
        warnungen.append(f"{uebersprungen['karte']} Kartenzahlungen übersprungen — Alltagsausgaben "
                         f"vom Verrechnungskonto gehören nicht ins Depot.")
    if uebersprungen["geld"]:
        warnungen.append(f"{uebersprungen['geld']} Ein-/Auszahlungen übersprungen. Trade Republic ist "
                         f"Bank und Broker zugleich; was davon Anlagegeld ist, legst du bei der "
                         f"Einrichtung fest.")
    if uebersprungen["alt"]:
        warnungen.append(f"{uebersprungen['alt']} Buchungen vor dem Startdatum übersprungen.")
    if not out and not warnungen:
        warnungen.append("Die Datei enthielt keine verwertbaren Zeilen.")
    return out, warnungen


def _neue(settings: Settings, buchungen: list[Buchung]) -> tuple[list[Buchung], int]:
    """Bereits vorhandene Buchungen aussortieren.

    pytr exportiert immer die vollständige Historie. Ohne diesen Abgleich würde jeder
    zweite Import alles doppelt buchen.
    """
    bekannt = {b.quelle_id for b in lies_ledger(settings)}
    neu, gesehen = [], set()
    for b in buchungen:
        if b.quelle_id in bekannt or b.quelle_id in gesehen:
            continue
        gesehen.add(b.quelle_id)
        neu.append(b)
    return neu, len(buchungen) - len(neu)


def _startdatum(settings: Settings, ab: str | None) -> str | None:
    """Ohne ausdrückliches Datum ab dem Depotstart importieren.

    Der TR-Export enthält die vollständige Kontohistorie — bei einem Konto, das vorher als
    Giro- und Handelskonto lief, sind das Jahre, die mit diesem Depot nichts zu tun haben.
    Sie würden ein Cash-Guthaben erzeugen, das es im Portfolio nie gab.
    """
    if ab:
        return ab
    plan = lade_plan(settings)
    return plan.start_datum or None


def vorschau(settings: Settings, text: str, mit_geldbewegungen: bool = False,
             ab: str | None = None) -> dict:
    """Was gebucht würde — ohne etwas zu schreiben.

    Bei einem undokumentierten Fremdformat ist ein stiller Direktimport nicht vertretbar.
    """
    buchungen, warnungen = parse_tr_csv(text, lade_plan(settings), mit_geldbewegungen,
                                        _startdatum(settings, ab), kern=kern_isins(settings))
    neu, doppelt = _neue(settings, buchungen)
    nach_typ: dict[str, int] = {}
    for b in neu:
        nach_typ[b.typ] = nach_typ.get(b.typ, 0) + 1
    return {
        "gelesen": len(buchungen), "neu": len(neu), "bereits_gebucht": doppelt,
        "nach_typ": nach_typ, "warnungen": warnungen[:20],
        "zeitraum": [min((b.datum for b in neu), default=None), max((b.datum for b in neu), default=None)],
        "beispiele": [{"datum": b.datum, "typ": b.typ, "topf": b.topf, "betrag_eur": b.betrag_eur,
                       "isin": b.isin, "notiz": b.notiz} for b in neu[:10]],
    }


def uebernehmen(settings: Settings, text: str, mit_geldbewegungen: bool = False,
                ab: str | None = None) -> dict:
    buchungen, warnungen = parse_tr_csv(text, lade_plan(settings), mit_geldbewegungen,
                                        _startdatum(settings, ab), kern=kern_isins(settings))
    neu, doppelt = _neue(settings, buchungen)
    geschrieben = schreibe_buchungen(settings, neu)
    log.info("TR-Import: %d neu, %d bereits vorhanden, %d Warnungen", geschrieben, doppelt, len(warnungen))
    return {"gebucht": geschrieben, "bereits_gebucht": doppelt, "warnungen": warnungen[:20]}

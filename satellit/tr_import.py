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

# Spalten, die pytr in verschiedenen Fassungen verwendet hat.
SPALTEN_ALIASE = {
    "datum": {"date", "datum", "timestamp", "zeitpunkt"},
    "typ": {"type", "typ", "transaction type", "event type", "eventtype"},
    "wert": {"value", "amount", "betrag", "wert"},
    "isin": {"isin"},
    "titel": {"note", "notiz", "title", "titel", "name", "description", "beschreibung"},
    "stueck": {"shares", "stück", "stueck", "quantity", "anzahl"},
    "gebuehr": {"fee", "fees", "gebühr", "gebuehr"},
    "steuer": {"tax", "taxes", "steuer", "steuern"},
}

# TR-Ereignis -> (Buchungstyp, Topf). Was hier nicht steht, wird nicht geraten.
TYP_ZUORDNUNG: dict[str, tuple[str, str]] = {
    "deposit": ("einzahlung", "cash"),
    "einzahlung": ("einzahlung", "cash"),
    "incoming transfer": ("einzahlung", "cash"),
    "payment inbound": ("einzahlung", "cash"),
    "withdrawal": ("auszahlung", "cash"),
    "auszahlung": ("auszahlung", "cash"),
    "payment outbound": ("auszahlung", "cash"),
    "savings plan": ("sparplan", "kern_etf"),
    "sparplan": ("sparplan", "kern_etf"),
    "savings plan execution": ("sparplan", "kern_etf"),
    "buy": ("kauf", "?"),                 # Topf ergibt sich aus der ISIN
    "kauf": ("kauf", "?"),
    "order buy": ("kauf", "?"),
    "sell": ("verkauf", "?"),
    "verkauf": ("verkauf", "?"),
    "order sell": ("verkauf", "?"),
    "dividend": ("dividende", "cash"),
    "dividende": ("dividende", "cash"),
    "interest": ("dividende", "cash"),
    "zinsen": ("dividende", "cash"),
    "tax": ("steuer", "cash"),
    "steuer": ("steuer", "cash"),
    "tax refund": ("korrektur", "cash"),
    "fee": ("gebuehr", "cash"),
    "gebuehr": ("gebuehr", "cash"),
}


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


def _topf_fuer(isin: str, plan) -> str:
    """Kern-ETF, Kern-Aktie oder Satellit? Die ISIN entscheidet."""
    if isin and plan is not None and isin == plan.etf_isin:
        return "kern_etf"
    return "satellit"


def parse_tr_csv(text: str, plan=None) -> tuple[list[Buchung], list[str]]:
    """CSV -> Buchungen + Warnungen. Wirft nur, wenn die Datei gar keine Tabelle ist."""
    warnungen: list[str] = []
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
        roh_typ = re.sub(r"[_\-]+", " ", zelle(row, "typ")).strip().lower()
        zuordnung = TYP_ZUORDNUNG.get(roh_typ)
        if zuordnung is None:
            warnungen.append(f"Zeile {nr}: Art {zelle(row, 'typ')!r} unbekannt — übersprungen, "
                             f"bitte von Hand buchen.")
            continue
        betrag = parse_number(zelle(row, "wert"))
        if betrag != betrag:
            warnungen.append(f"Zeile {nr}: Betrag {zelle(row, 'wert')!r} nicht lesbar — übersprungen.")
            continue

        typ, topf = zuordnung
        isin = zelle(row, "isin").upper()
        if typ == "kauf":
            typ = "kern_kauf" if _topf_fuer(isin, plan) == "kern_etf" else "satellit_kauf"
            topf = _topf_fuer(isin, plan)
            if topf == "kern_etf":
                typ = "sparplan"
        elif typ == "verkauf":
            topf = _topf_fuer(isin, plan)
            typ = "kern_verkauf" if topf.startswith("kern") else "satellit_verkauf"

        stueck = parse_number(zelle(row, "stueck"))
        gebuehr = parse_number(zelle(row, "gebuehr"))
        out.append(Buchung(
            datum=datum, typ=typ, topf=topf, betrag_eur=abs(betrag), isin=isin,
            stueck=0.0 if stueck != stueck else abs(stueck),
            gebuehr_eur=0.0 if gebuehr != gebuehr else abs(gebuehr),
            notiz=zelle(row, "titel")[:80], quelle="tr_import",
            quelle_id=schluessel(datum, typ, isin, abs(betrag),
                                 0.0 if stueck != stueck else abs(stueck)),
        ))
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


def vorschau(settings: Settings, text: str) -> dict:
    """Was gebucht würde — ohne etwas zu schreiben.

    Bei einem undokumentierten Fremdformat ist ein stiller Direktimport nicht vertretbar.
    """
    buchungen, warnungen = parse_tr_csv(text, lade_plan(settings))
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


def uebernehmen(settings: Settings, text: str) -> dict:
    buchungen, warnungen = parse_tr_csv(text, lade_plan(settings))
    neu, doppelt = _neue(settings, buchungen)
    geschrieben = schreibe_buchungen(settings, neu)
    log.info("TR-Import: %d neu, %d bereits vorhanden, %d Warnungen", geschrieben, doppelt, len(warnungen))
    return {"gebucht": geschrieben, "bereits_gebucht": doppelt, "warnungen": warnungen[:20]}

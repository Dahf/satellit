"""Kern-Portfolio: Plan, Kassenbuch, Bewertung.

Bis hierher kannte das System nur den 10-%-Satelliten. Die 90 % im Kern — ETF-Sparplan,
Kern-Aktien, Einzahlungen, Gesamtwert — existierten nirgends, obwohl der Trading-Plan sie
regelt. Dieses Modul führt sie.

Zwei Festlegungen tragen den Entwurf:

1. **Das Kassenbuch ist fortschreibend.** Zeilen werden angehängt, nie geändert. Eine
   Korrektur ist eine Gegenbuchung mit Verweis. Nur so bleibt nachvollziehbar, warum eine
   Zahl heute anders aussieht als letzten Monat.
2. **`betrag_eur` ist, was der Broker tatsächlich belastet hat.** Damit ist die Kostenbasis
   wechselkurs-ehrlich, ohne historische Kurse rekonstruieren zu müssen.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import yaml

from .config import Settings

log = logging.getLogger(__name__)

_SCHREIB_LOCK = threading.Lock()

# --------------------------------------------------------------------------- Vokabular
# Geldbewegungen. Der Betrag ist immer positiv; die Richtung steckt im Typ.
EINZAHLUNGEN = {"einzahlung"}
AUSZAHLUNGEN = {"auszahlung"}
KAEUFE = {"sparplan", "kern_kauf", "satellit_kauf"}
VERKAEUFE = {"kern_verkauf", "satellit_verkauf"}
ERTRAEGE = {"dividende"}
KOSTEN = {"gebuehr", "steuer"}
TYPEN = (EINZAHLUNGEN | AUSZAHLUNGEN | KAEUFE | VERKAEUFE | ERTRAEGE | KOSTEN
         | {"umschichtung", "korrektur", "storno"})

TOEPFE = {"kern_etf", "kern_aktie", "satellit", "cash"}
KERN_TOEPFE = {"kern_etf", "kern_aktie"}

SPALTEN = ["datum", "typ", "topf", "isin", "symbol", "waehrung", "stueck", "kurs",
           "betrag_eur", "gebuehr_eur", "thesis_id", "notiz", "quelle", "quelle_id"]


# --------------------------------------------------------------------------- Datentypen
@dataclass
class Buchung:
    datum: str                      # ISO
    typ: str
    topf: str
    betrag_eur: float = 0.0         # immer positiv, Richtung steckt im Typ
    isin: str = ""
    symbol: str = ""
    waehrung: str = "EUR"
    stueck: float = 0.0
    kurs: float = 0.0
    gebuehr_eur: float = 0.0
    thesis_id: str = ""
    notiz: str = ""
    quelle: str = "dashboard"
    quelle_id: str = ""

    def __post_init__(self) -> None:
        if self.typ not in TYPEN:
            raise ValueError(f"Unbekannter Buchungstyp {self.typ!r} — erlaubt: {', '.join(sorted(TYPEN))}")
        if self.topf not in TOEPFE:
            raise ValueError(f"Unbekannter Topf {self.topf!r} — erlaubt: {', '.join(sorted(TOEPFE))}")
        try:
            date.fromisoformat(self.datum)
        except ValueError as exc:
            raise ValueError(f"Ungültiges Datum {self.datum!r}: {exc}") from exc
        for feld in ("betrag_eur", "gebuehr_eur", "stueck", "kurs"):
            wert = float(getattr(self, feld) or 0.0)
            if wert != wert or wert in (float("inf"), float("-inf")):
                raise ValueError(f"{feld} ist keine endliche Zahl")
            setattr(self, feld, wert)
        if self.betrag_eur < 0:
            raise ValueError("betrag_eur ist immer positiv — die Richtung ergibt sich aus dem Typ")
        if not self.quelle_id:
            self.quelle_id = schluessel(self.datum, self.typ, self.isin, self.betrag_eur, self.stueck)

    def zeile(self) -> dict:
        return {k: getattr(self, k) for k in SPALTEN}


@dataclass
class Bestand:
    topf: str
    isin: str
    symbol: str
    waehrung: str = "EUR"
    stueck: float = 0.0
    einstand_eur: float = 0.0       # was tatsächlich bezahlt wurde, inkl. Gebühren

    @property
    def einstand_je_stueck(self) -> float | None:
        return self.einstand_eur / self.stueck if self.stueck else None


@dataclass
class Werte:
    gesamt_eur: float = 0.0
    kern_etf_eur: float = 0.0
    kern_aktien_eur: float = 0.0
    satellit_eur: float = 0.0
    cash_eur: float = 0.0                       # alle Töpfe zusammen
    cash_je_topf: dict[str, float] = field(default_factory=dict)
    kern_eur: float = 0.0
    kern_pct: float | None = None
    satellit_pct: float | None = None
    band_status: str = "unbekannt"              # ok | unter | ueber | unbekannt
    kern_aktien_cash_eur: float = 0.0
    je_position: dict[str, dict] = field(default_factory=dict)
    nicht_bewertbar: list[str] = field(default_factory=list)


@dataclass
class Plan:
    start_datum: str | None = None
    monatsrate_eur: float = 0.0
    sparplan_tag: int = 1
    etf: dict = field(default_factory=dict)     # {isin, symbol, name, anteil_kern}
    startbetrag: dict = field(default_factory=dict)
    onboarding_erledigt: bool = False
    depotwert_abgleich: dict = field(default_factory=dict)
    updated: str | None = None

    @property
    def etf_symbol(self) -> str:
        return str(self.etf.get("symbol") or "")

    @property
    def etf_isin(self) -> str:
        return str(self.etf.get("isin") or "")

    @property
    def etf_anteil(self) -> float:
        return float(self.etf.get("anteil_kern", 1.0) or 1.0)

    @property
    def ersteinstieg_offen(self) -> bool:
        """Die einmalige Ausnahme von Trading-Plan 3.4 für den Kern-Startbetrag."""
        return bool(self.startbetrag.get("ersteinstieg_aktien_offen"))


# --------------------------------------------------------------------------- Schlüssel
def schluessel(datum: str, typ: str, isin: str, betrag_eur: float, stueck: float = 0.0) -> str:
    """Stabiler Schlüssel je Buchung — trägt die Dublettenprüfung beim Broker-Import.

    pytr exportiert immer die vollständige Historie; ohne diesen Schlüssel würde jeder
    zweite Import alles doppelt buchen.
    """
    roh = f"{datum}|{typ}|{isin}|{betrag_eur:.2f}|{stueck:.6f}"
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- Plan-IO
def plan_pfad(settings: Settings) -> Path:
    return settings.state_dir / "portfolio.yaml"


def lade_plan(settings: Settings) -> Plan:
    p = plan_pfad(settings)
    if not p.exists():
        return Plan()
    try:
        roh = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        log.warning("portfolio.yaml nicht lesbar (%s) — leerer Plan", exc)
        return Plan()
    bekannt = {f for f in Plan.__dataclass_fields__}
    return Plan(**{k: v for k, v in roh.items() if k in bekannt})


def speichere_plan(settings: Settings, plan: Plan, heute: date | None = None) -> Path:
    plan.updated = (heute or date.today()).isoformat()
    p = plan_pfad(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(asdict(plan), sort_keys=False, allow_unicode=True), encoding="utf-8")
    return p


def lade_etf_katalog(settings: Settings) -> list[dict]:
    """Auswahlhilfe fürs Onboarding aus config/etf_universe.yaml — bewusst offline."""
    p = settings.root / "config" / "etf_universe.yaml"
    if not p.exists():
        return []
    try:
        return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("etfs") or []
    except (OSError, yaml.YAMLError) as exc:
        log.warning("etf_universe.yaml nicht lesbar: %s", exc)
        return []


# --------------------------------------------------------------------------- Ledger-IO
def ledger_pfad(settings: Settings) -> Path:
    return settings.state_dir / "ledger.csv"


def lies_ledger(settings: Settings) -> list[Buchung]:
    p = ledger_pfad(settings)
    if not p.exists():
        return []
    out: list[Buchung] = []
    with open(p, newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh), start=2):
            try:
                out.append(Buchung(
                    datum=row["datum"], typ=row["typ"], topf=row["topf"],
                    betrag_eur=float(row.get("betrag_eur") or 0), isin=row.get("isin", ""),
                    symbol=row.get("symbol", ""), waehrung=row.get("waehrung") or "EUR",
                    stueck=float(row.get("stueck") or 0), kurs=float(row.get("kurs") or 0),
                    gebuehr_eur=float(row.get("gebuehr_eur") or 0), thesis_id=row.get("thesis_id", ""),
                    notiz=row.get("notiz", ""), quelle=row.get("quelle") or "dashboard",
                    quelle_id=row.get("quelle_id") or "",
                ))
            except (ValueError, KeyError) as exc:
                # Eine kaputte Zeile darf nicht das ganze Kassenbuch unlesbar machen.
                log.warning("Ledger-Zeile %d übersprungen: %s", i, exc)
    return out


def schreibe_buchungen(settings: Settings, buchungen: Iterable[Buchung]) -> int:
    """Anhängen, nie ändern. Gibt die Zahl geschriebener Zeilen zurück.

    Der Wochenlauf arbeitet in einem Hintergrund-Thread, während der Nutzer buchen kann —
    deshalb O_APPEND plus Modul-Lock.
    """
    buchungen = list(buchungen)
    if not buchungen:
        return 0
    p = ledger_pfad(settings)
    with _SCHREIB_LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        neu = not p.exists() or p.stat().st_size == 0
        with open(p, "a", newline="", encoding="utf-8") as fh:
            schreiber = csv.DictWriter(fh, fieldnames=SPALTEN)
            if neu:
                schreiber.writeheader()
            for b in buchungen:
                schreiber.writerow(b.zeile())
    return len(buchungen)


def schreibe_buchung(settings: Settings, b: Buchung) -> int:
    return schreibe_buchungen(settings, [b])


def storniere(settings: Settings, quelle_id: str, notiz: str, heute: date | None = None) -> Buchung:
    """Gegenbuchung statt Löschen. Die Originalzeile bleibt im Kassenbuch stehen."""
    original = next((b for b in lies_ledger(settings) if b.quelle_id == quelle_id), None)
    if original is None:
        raise ValueError(f"Keine Buchung mit Schlüssel {quelle_id}")
    gegen = Buchung(
        datum=(heute or date.today()).isoformat(), typ="storno", topf=original.topf,
        betrag_eur=original.betrag_eur, isin=original.isin, symbol=original.symbol,
        waehrung=original.waehrung, stueck=original.stueck, kurs=original.kurs,
        notiz=f"Storno zu {quelle_id}: {notiz}".strip(), quelle="dashboard",
        quelle_id=schluessel((heute or date.today()).isoformat(), "storno", original.isin,
                             original.betrag_eur, original.stueck),
    )
    # Der Storno merkt sich, was er aufhebt — die Faltung braucht das.
    gegen.thesis_id = original.quelle_id
    schreibe_buchung(settings, gegen)
    return gegen


# --------------------------------------------------------------------------- Faltung
def _wirksame(buchungen: list[Buchung]) -> list[Buchung]:
    """Stornierte Buchungen und die Stornos selbst herausnehmen."""
    aufgehoben = {b.thesis_id for b in buchungen if b.typ == "storno" and b.thesis_id}
    return [b for b in buchungen if b.typ != "storno" and b.quelle_id not in aufgehoben]


def bestaende(buchungen: list[Buchung]) -> dict[str, Bestand]:
    """Stückzahlen und Einstand je (Topf, ISIN). Schlüssel: '<topf>:<isin oder symbol>'."""
    out: dict[str, Bestand] = {}
    for b in _wirksame(buchungen):
        if b.typ not in (KAEUFE | VERKAEUFE) or not (b.isin or b.symbol):
            continue
        k = f"{b.topf}:{b.isin or b.symbol}"
        best = out.setdefault(k, Bestand(topf=b.topf, isin=b.isin, symbol=b.symbol, waehrung=b.waehrung))
        if not best.symbol and b.symbol:
            best.symbol = b.symbol
        if b.typ in KAEUFE:
            best.stueck += b.stueck
            best.einstand_eur += b.betrag_eur + b.gebuehr_eur
        else:
            # Verkauf: Einstand anteilig ausbuchen, damit der Rest-Einstand stimmt.
            anteil = (b.stueck / best.stueck) if best.stueck else 0.0
            best.einstand_eur -= best.einstand_eur * min(1.0, max(0.0, anteil))
            best.stueck -= b.stueck
    return {k: v for k, v in out.items() if abs(v.stueck) > 1e-9}


def cash_je_topf(buchungen: list[Buchung]) -> dict[str, float]:
    """Barbestand je Topf.

    Konvention: `umschichtung` bucht immer vom Topf 'cash' in den genannten Zieltopf.
    Käufe und Gebühren belasten den Topf der Buchung, Verkäufe und Erträge schreiben ihm gut.
    """
    konten = {t: 0.0 for t in TOEPFE}
    for b in _wirksame(buchungen):
        if b.typ in EINZAHLUNGEN:
            konten[b.topf] += b.betrag_eur
        elif b.typ in AUSZAHLUNGEN:
            konten[b.topf] -= b.betrag_eur
        elif b.typ == "umschichtung":
            konten["cash"] -= b.betrag_eur
            konten[b.topf] += b.betrag_eur
        elif b.typ in KAEUFE:
            konten[b.topf] -= b.betrag_eur + b.gebuehr_eur
        elif b.typ in VERKAEUFE:
            konten[b.topf] += b.betrag_eur - b.gebuehr_eur
        elif b.typ in ERTRAEGE:
            konten[b.topf] += b.betrag_eur
        elif b.typ in KOSTEN:
            konten[b.topf] -= b.betrag_eur
        elif b.typ == "korrektur":
            konten[b.topf] += b.betrag_eur
    return konten


def cash(buchungen: list[Buchung], topf: str | None = None) -> float:
    konten = cash_je_topf(buchungen)
    return konten.get(topf, 0.0) if topf else sum(konten.values())


def einzahlungen(buchungen: list[Buchung]) -> dict:
    """Was tatsächlich von außen hereinkam. Grundlage für 'Gewinn' und XIRR."""
    netto = 0.0
    je_monat: dict[str, float] = {}
    fluesse: list[tuple[date, float]] = []
    for b in sorted(_wirksame(buchungen), key=lambda x: x.datum):
        if b.typ not in (EINZAHLUNGEN | AUSZAHLUNGEN):
            continue
        vorzeichen = 1.0 if b.typ in EINZAHLUNGEN else -1.0
        netto += vorzeichen * b.betrag_eur
        je_monat[b.datum[:7]] = je_monat.get(b.datum[:7], 0.0) + vorzeichen * b.betrag_eur
        fluesse.append((date.fromisoformat(b.datum), vorzeichen * b.betrag_eur))
    return {"netto_eur": netto, "je_monat": je_monat, "fluesse": fluesse}


def monatsausgaben(buchungen: list[Buchung], monat: str, plan: Plan | None = None) -> dict:
    """Was in diesem Monat investiert wurde — 'wie viel habe ich ausgegeben'.

    Gezählt werden Käufe (Sparplan, Kern, Satellit), nicht Umschichtungen: Geld von einem
    eigenen Topf in den anderen zu schieben ist keine Ausgabe.
    """
    posten = [b for b in _wirksame(buchungen) if b.typ in KAEUFE and b.datum[:7] == monat]
    ausgegeben = sum(b.betrag_eur + b.gebuehr_eur for b in posten)
    geplant = float(plan.monatsrate_eur) if plan else 0.0
    return {
        "monat": monat,
        "plan_eur": geplant or None,
        "ausgegeben_eur": ausgegeben,
        "offen_eur": max(0.0, geplant - ausgegeben) if geplant else None,
        "posten": [{"datum": b.datum, "typ": b.typ, "symbol": b.symbol or b.isin,
                    "betrag_eur": b.betrag_eur + b.gebuehr_eur} for b in posten],
    }


def sparplan_gelaufen(buchungen: list[Buchung], monat: str, isin: str = "") -> bool:
    for b in _wirksame(buchungen):
        if b.typ == "sparplan" and b.datum[:7] == monat and (not isin or b.isin == isin):
            return True
    return False


# --------------------------------------------------------------------------- Bewertung
def bewerte(settings: Settings, plan: Plan, buchungen: list[Buchung], kurse: dict[str, float],
            satellit_positionen_eur: float = 0.0) -> Werte:
    """Alles zu Marktwerten. `kurse` bildet Symbol -> Kurs in EUR ab.

    Der Satelliten-Positionswert kommt aus der Pipeline (dort liegen Kursreihen und FX),
    damit hier nicht ein zweites Mal bewertet wird.
    """
    w = Werte()
    konten = cash_je_topf(buchungen)
    w.cash_je_topf = konten
    w.cash_eur = sum(konten.values())
    w.kern_aktien_cash_eur = konten.get("kern_aktie", 0.0)

    for schl, best in bestaende(buchungen).items():
        kurs = kurse.get(best.symbol) or kurse.get(best.isin)
        if kurs is None:
            w.nicht_bewertbar.append(best.symbol or best.isin)
            wert = best.einstand_eur          # ohne Kurs lieber Einstand als gar nichts
        else:
            wert = best.stueck * float(kurs)
        w.je_position[schl] = {
            "topf": best.topf, "isin": best.isin, "symbol": best.symbol,
            "stueck": best.stueck, "wert_eur": wert, "einstand_eur": best.einstand_eur,
            "gewinn_eur": wert - best.einstand_eur, "bewertet": kurs is not None,
        }
        if best.topf == "kern_etf":
            w.kern_etf_eur += wert
        elif best.topf == "kern_aktie":
            w.kern_aktien_eur += wert
        elif best.topf == "satellit":
            w.satellit_eur += wert

    # Satelliten-Positionen führt das Journal, nicht das Kassenbuch.
    if satellit_positionen_eur:
        w.satellit_eur = satellit_positionen_eur

    w.kern_eur = w.kern_etf_eur + w.kern_aktien_eur + konten.get("kern_etf", 0.0) + konten.get("kern_aktie", 0.0)
    satellit_gesamt = w.satellit_eur + konten.get("satellit", 0.0)
    w.gesamt_eur = w.kern_eur + satellit_gesamt + konten.get("cash", 0.0)
    if w.gesamt_eur > 0:
        w.kern_pct = w.kern_eur / w.gesamt_eur
        w.satellit_pct = satellit_gesamt / w.gesamt_eur
    return w


def band_pruefung(werte: Werte, settings: Settings) -> dict:
    """Kern/Satellit gegen das Band aus Trading-Plan 1 (7 % / 15 %)."""
    low = float(settings.get("portfolio.satellite_band_low", 0.07))
    high = float(settings.get("portfolio.satellite_band_high", 0.15))
    ziel = float(settings.get("portfolio.satellite_share", 0.10))
    anteil = werte.satellit_pct
    if anteil is None:
        status = "unbekannt"
    elif anteil < low:
        status = "unter"
    elif anteil > high:
        status = "ueber"
    else:
        status = "ok"
    werte.band_status = status
    return {"status": status, "anteil": anteil, "low": low, "high": high, "ziel": ziel}


# --------------------------------------------------------------------------- Kauffenster
def _quartalsfenster(jahr: int, monat: int) -> tuple[date, date]:
    """Erste Handelswoche: erster Werktag des Monats bis Freitag derselben Woche.

    Näherung ohne Feiertagskalender — der 1. Januar ist Börsenfeiertag, das Fenster kann
    dort einen Tag zu früh öffnen. Bei einem einwöchigen Fenster ist das vertretbar.
    """
    d = date(jahr, monat, 1)
    while d.weekday() > 4:
        d += timedelta(days=1)
    return d, d + timedelta(days=4 - d.weekday())


def kern_kauffenster(heute: date, plan: Plan | None = None) -> dict:
    """Darf heute eine Kern-Aktie gekauft werden?

    Zwei Öffnungsgründe: das reguläre Quartalsfenster (Trading-Plan 3.4) und die einmalige
    Startbetrags-Ausnahme aus KERN.md 5.3 (siehe CHANGELOG_REGELN).
    """
    monate = (1, 4, 7, 10)
    if heute.month in monate:
        von, bis = _quartalsfenster(heute.year, heute.month)
        if von <= heute <= bis:
            return {"offen": True, "grund": "quartal", "von": von.isoformat(), "bis": bis.isoformat(),
                    "naechstes": None}
    # nächstes reguläres Fenster suchen
    jahr, monat = heute.year, heute.month
    for _ in range(13):
        if monat in monate:
            von, bis = _quartalsfenster(jahr, monat)
            if von > heute:
                naechstes = (von, bis)
                break
        monat += 1
        if monat > 12:
            monat, jahr = 1, jahr + 1
    else:  # pragma: no cover — bei 13 Versuchen unerreichbar
        naechstes = _quartalsfenster(heute.year + 1, 1)

    if plan is not None and plan.ersteinstieg_offen:
        return {"offen": True, "grund": "ersteinstieg", "von": None, "bis": None,
                "naechstes": naechstes[0].isoformat()}
    return {"offen": False, "grund": "geschlossen", "von": naechstes[0].isoformat(),
            "bis": naechstes[1].isoformat(), "naechstes": naechstes[0].isoformat()}


def kern_grenze_ok(werte: Werte, settings: Settings, isin: str, betrag_eur: float) -> tuple[bool, str]:
    """Trading-Plan 3.3: <= 5 % des Gesamtportfolios je Titel, <= 20 % des Kerns in Aktien."""
    if werte.gesamt_eur <= 0:
        return False, "Ohne Depotwert lassen sich die Grenzen nicht prüfen."
    max_titel = float(settings.get("portfolio.max_core_stock_pct", 0.05))
    max_aktien = float(settings.get("portfolio.max_core_stocks_share", 0.20))

    def _eur(x: float) -> str:
        return f"{x:,.0f}".replace(",", ".")

    gehalten = sum(p["wert_eur"] for p in werte.je_position.values()
                   if p["topf"] == "kern_aktie" and p["isin"] == isin)
    if gehalten + betrag_eur > max_titel * werte.gesamt_eur + 1e-6:
        return False, (f"Mit diesem Kauf läge der Titel über {max_titel * 100:.0f} % des "
                       f"Gesamtportfolios (höchstens {_eur(max_titel * werte.gesamt_eur)} EUR).")
    if werte.kern_eur > 0 and werte.kern_aktien_eur + betrag_eur > max_aktien * werte.kern_eur + 1e-6:
        return False, (f"Einzelaktien dürfen höchstens {max_aktien * 100:.0f} % des Kerns ausmachen "
                       f"(höchstens {_eur(max_aktien * werte.kern_eur)} EUR).")
    return True, ""


# --------------------------------------------------------------------------- Rendite
def xirr(fluesse: list[tuple[date, float]], startwert: float = 0.1) -> float | None:
    """Interner Zinsfuß bei unregelmäßigen Zahlungen — die ehrliche Jahresrendite.

    Erwartet Einzahlungen negativ und den heutigen Depotwert positiv. Gibt None zurück,
    wenn zu wenig Historie da ist: über wenige Wochen hochgerechnet entstehen absurde
    Jahreswerte, die mehr verwirren als erklären.
    """
    if len(fluesse) < 2:
        return None
    geordnet = sorted(fluesse, key=lambda x: x[0])
    t0 = geordnet[0][0]
    tage = (geordnet[-1][0] - t0).days
    if tage < 30:
        return None
    if not (any(f < 0 for _, f in geordnet) and any(f > 0 for _, f in geordnet)):
        return None

    def barwert(r: float) -> float:
        if r <= -0.999999:
            return float("inf")
        return sum(f / (1.0 + r) ** ((d - t0).days / 365.0) for d, f in geordnet)

    # Newton
    r = startwert
    for _ in range(60):
        f0 = barwert(r)
        if abs(f0) < 1e-7:
            return r
        f1 = barwert(r + 1e-6)
        ableitung = (f1 - f0) / 1e-6
        if abs(ableitung) < 1e-12:
            break
        naechst = r - f0 / ableitung
        if naechst <= -0.999999 or abs(naechst) > 1e6:
            break
        if abs(naechst - r) < 1e-9:
            return naechst
        r = naechst

    # Bisektion als Rückfall — langsamer, aber sie findet die Wurzel auch dort,
    # wo Newton wegläuft.
    lo, hi = -0.9999, 10.0
    f_lo, f_hi = barwert(lo), barwert(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mitte = (lo + hi) / 2
        f_m = barwert(mitte)
        if abs(f_m) < 1e-9 or (hi - lo) < 1e-10:
            return mitte
        if f_lo * f_m < 0:
            hi, f_hi = mitte, f_m
        else:
            lo, f_lo = mitte, f_m
    return (lo + hi) / 2


def performance(werte: Werte, buchungen: list[Buchung], heute: date | None = None) -> dict:
    """Gewinn in Euro und als echte Jahresrendite."""
    heute = heute or date.today()
    ein = einzahlungen(buchungen)
    netto = ein["netto_eur"]
    gewinn = werte.gesamt_eur - netto
    realisiert = 0.0
    for b in _wirksame(buchungen):
        if b.typ in VERKAEUFE:
            realisiert += b.betrag_eur - b.gebuehr_eur
    fluesse = list(ein["fluesse"]) + [(heute, werte.gesamt_eur)]
    rendite = xirr(fluesse)
    return {
        "eingezahlt_netto_eur": netto,
        "wert_eur": werte.gesamt_eur,
        "gewinn_eur": gewinn,
        "gewinn_pct": (gewinn / netto) if netto > 0 else None,
        "unrealisiert_eur": sum(p["gewinn_eur"] for p in werte.je_position.values()),
        "xirr_pct": rendite,
        "xirr_hinweis": ("Rendite pro Jahr, die Zeitpunkte deiner Einzahlungen eingerechnet."
                         if rendite is not None else
                         "Für eine Jahresrendite ist die Historie noch zu kurz."),
    }


# --------------------------------------------------------------------------- Startbetrag
def startbetrag_buchungen(plan: Plan, heute: date) -> list[Buchung]:
    """Die Eröffnungsbuchungen: Einzahlung, dann Aufteilung in die Töpfe.

    Der Kern wird nach KERN.md 1 in ETF-Anteil und Aktien-Cash geteilt; letzterer liegt
    bereit, bis ein Kauffenster offen ist.
    """
    kern = float(plan.startbetrag.get("kern_eur") or 0.0)
    sat = float(plan.startbetrag.get("satellit_eur") or 0.0)
    if kern <= 0 and sat <= 0:
        return []
    d = heute.isoformat()
    out = [Buchung(datum=d, typ="einzahlung", topf="cash", betrag_eur=kern + sat,
                   notiz="Startbetrag", quelle="dashboard")]
    etf_anteil = plan.etf_anteil
    kern_etf = round(kern * etf_anteil, 2)
    kern_aktien = round(kern - kern_etf, 2)
    if kern_etf:
        out.append(Buchung(datum=d, typ="umschichtung", topf="kern_etf", betrag_eur=kern_etf,
                           notiz="Startbetrag Kern-ETF"))
    if kern_aktien:
        out.append(Buchung(datum=d, typ="umschichtung", topf="kern_aktie", betrag_eur=kern_aktien,
                           notiz="Startbetrag Kern-Aktien (wartet auf Kauffenster)"))
    if sat:
        out.append(Buchung(datum=d, typ="umschichtung", topf="satellit", betrag_eur=sat,
                           notiz="Startbetrag Satellit"))
    return out


def zusammenfassung(settings: Settings, kurse: dict[str, float] | None = None,
                    heute: date | None = None) -> dict:
    """Alles auf einmal — für die CLI und für den Payload-Bau."""
    heute = heute or date.today()
    plan = lade_plan(settings)
    buchungen = lies_ledger(settings)
    werte = bewerte(settings, plan, buchungen, kurse or {})
    band = band_pruefung(werte, settings)
    return {
        "plan": plan,
        "werte": werte,
        "band": band,
        "monat": monatsausgaben(buchungen, heute.strftime("%Y-%m"), plan),
        "gewinn": performance(werte, buchungen, heute),
        "kauffenster": kern_kauffenster(heute, plan),
        "buchungen": len(buchungen),
    }

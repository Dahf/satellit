"""Kern-Aktien suchen: Universum und Watchlist gegen den Kriterienkatalog prüfen.

Bewusst **nicht** Teil des Wochenlaufs. Zwei Gründe: der Katalog braucht je Titel einen
eigenen Fundamentaldaten-Abruf, was über ein Indexuniversum Minuten bis Viertelstunden
dauert — und er beantwortet eine Frage, die nur viermal im Jahr gestellt wird, weil Kern-
Aktien nur in der ersten Handelswoche von Januar, April, Juli und Oktober gekauft werden
(Trading-Plan 3.4). Der 90-Tage-Cache macht daraus faktisch einen Quartalslauf.

Der Kern kennt keine Ampel (Trading-Plan 2: „Es wird nicht getimt"). In diesem Modul darf
deshalb nirgends ein Regime-Zustand auftauchen — auch nicht als Sortierkriterium.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

import pandas as pd
import yaml

from . import journal, kern_screener as ks
from .config import Settings
from .data import NullSource, PriceSource, SyntheticSource, build_source, update_prices
from .fundamentals import (
    FundamentalsSource, NullFundamentals, SyntheticFundamentals, update_fundamentals,
)
from .fx import FxTable, load_fx
from .universe import Constituent, load_universe

log = logging.getLogger(__name__)

WATCHLIST_DATEI = "kern_watchlist.yaml"
STAND_DATEI = "kern_stand.json"
HANDELSTAGE_JE_JAHR = 252.0


@dataclass
class KernScanResult:
    as_of: date
    kandidaten: list[ks.KernKandidat] = field(default_factory=list)
    trichter: dict[str, int] = field(default_factory=dict)
    geprueft: int = 0
    vorgefiltert: int = 0                  # ohne Fundamentaldaten-Abruf aussortiert
    daten_fehlt: dict[str, str] = field(default_factory=dict)
    hinweise: list[str] = field(default_factory=list)
    quelle: str = ""
    demo: bool = False

    @property
    def bestanden(self) -> list[ks.KernKandidat]:
        return [k for k in self.kandidaten if k.bestanden]


# --------------------------------------------------------------------------- Watchlist
def lade_watchlist(settings: Settings) -> list[dict]:
    """Eigene Titel zur Prüfung. Liegt in `state/`, nicht in `config/`.

    Grund: das Dashboard bekommt `config/` nicht gemountet (docker-compose.yml), kann die
    Datei also nicht lesen. In `state/` liegt sie im selben Volume wie alles andere, das
    über die API geschrieben wird.
    """
    p = settings.state_dir / WATCHLIST_DATEI
    if not p.exists():
        return []
    try:
        roh = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        log.warning("Kern-Watchlist unlesbar (%s) — wird als leer behandelt", exc)
        return []
    eintraege = roh.get("titel") if isinstance(roh, dict) else roh
    out = []
    for e in eintraege or []:
        if isinstance(e, str):
            out.append({"symbol": e.strip().upper(), "name": "", "isin": "", "notiz": ""})
        elif isinstance(e, dict) and e.get("symbol"):
            out.append({"symbol": str(e["symbol"]).strip().upper(),
                        "name": str(e.get("name") or ""), "isin": str(e.get("isin") or ""),
                        "notiz": str(e.get("notiz") or "")})
    return out


def speichere_watchlist(settings: Settings, titel: list[dict]) -> None:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    p = settings.state_dir / WATCHLIST_DATEI
    kopf = ("# Eigene Kandidaten für den Kern-Kriterienkatalog (docs/KERN.md 6).\n"
            "# Wird über das Dashboard gepflegt; Handeintragungen sind ebenso gültig.\n")
    p.write_text(kopf + yaml.safe_dump({"titel": titel}, allow_unicode=True, sort_keys=False),
                 encoding="utf-8")


def watchlist_ergaenzen(settings: Settings, symbol: str, name: str = "", isin: str = "",
                        notiz: str = "") -> list[dict]:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("Ohne Symbol lässt sich kein Titel prüfen.")
    titel = lade_watchlist(settings)
    for e in titel:
        if e["symbol"] == symbol:
            # Vorhandenes anreichern statt doppelt anzulegen.
            e["name"] = name or e["name"]
            e["isin"] = isin or e["isin"]
            e["notiz"] = notiz or e["notiz"]
            speichere_watchlist(settings, titel)
            return titel
    titel.append({"symbol": symbol, "name": name, "isin": isin, "notiz": notiz})
    speichere_watchlist(settings, titel)
    return titel


def watchlist_entfernen(settings: Settings, symbol: str) -> list[dict]:
    symbol = (symbol or "").strip().upper()
    titel = [e for e in lade_watchlist(settings) if e["symbol"] != symbol]
    speichere_watchlist(settings, titel)
    return titel


# --------------------------------------------------------------------------- Vorfilter
def _jahre_notiert(df: pd.DataFrame | None) -> float | None:
    """Länge der Kursreihe in Jahren — eine **Untergrenze**, keine Erstnotiz.

    Der Cache wird mit `data.history_days` gefüllt (rund 420 Tage), reicht also anfangs bei
    jedem Titel nur gut ein Jahr zurück, auch bei hundertjährigen Konzernen. Der Wert kann
    ein Mindestalter belegen, aber nie eines widerlegen. `kern_screener` behandelt ihn
    entsprechend; als Ausschlussgrund taugt er nicht.
    """
    if df is None or df.empty:
        return None
    return round(len(df) / HANDELSTAGE_JE_JAHR, 2)


def _satelliten_symbole(settings: Settings) -> set[str]:
    out = set()
    for t in journal.open_positions(settings):
        s = journal.provenance(t).get("symbol") or t.get("ticker")
        if s:
            out.add(str(s).upper())
    return out


def _watchlist_symbole(settings: Settings, as_of: date) -> set[str]:
    """Titel auf der Screener-Watchlist des Satelliten — Ausschlussgrund nach KERN.md 6.

    Aus der jüngsten Screener-CSV. Fehlt sie, ist die Menge leer; das ist die richtige
    Richtung, denn ein fehlender Ausschluss wird beim nächsten Lauf nachgeholt, ein
    erfundener nicht.
    """
    dateien = sorted(settings.reports_dir.glob("screener_*.csv"))
    if not dateien:
        return set()
    try:
        t = pd.read_csv(dateien[-1])
    except Exception as exc:  # noqa: BLE001
        log.warning("Screener-CSV nicht lesbar (%s) — Watchlist-Ausschluss entfällt", exc)
        return set()
    if "watchlist" not in t.columns or "symbol" not in t.columns:
        return set()
    return {str(s).upper() for s in t.loc[t["watchlist"].fillna(False).astype(bool), "symbol"]}


# --------------------------------------------------------------------------- Lauf
def run_kern_scan(settings: Settings, as_of: date | None = None, *, nur_watchlist: bool = False,
                  demo: bool = False, offline: bool = False,
                  source: PriceSource | None = None,
                  fundamentals_source: FundamentalsSource | None = None,
                  progress: Callable[[int, int], None] | None = None,
                  max_titel: int | None = None) -> KernScanResult:
    """Kandidaten für den Kern suchen und gegen KERN.md 6 prüfen.

    `nur_watchlist=True` prüft ausschließlich die eigenen Titel — schnell, weil kein
    Indexuniversum geladen wird. Ohne das wird beides geprüft: Universum und Watchlist.
    """
    settings.ensure_dirs()
    as_of = as_of or date.today()
    res = KernScanResult(as_of=as_of, demo=demo)

    # 1. Titelmenge
    watchlist = lade_watchlist(settings)
    cons: list[Constituent] = []
    if not nur_watchlist:
        if demo:
            from .pipeline import demo_universe
            cons = demo_universe()
            res.hinweise.append("DEMO-Modus: synthetisches Universum und erfundene Kennzahlen")
        else:
            cons, warn, _ = load_universe(settings, offline=offline)
            res.hinweise.extend(warn)
    res.quelle = "watchlist" if nur_watchlist else ("demo" if demo else "universum")

    nach_symbol: dict[str, dict] = {}
    for c in cons:
        nach_symbol[c.symbol] = {"symbol": c.symbol, "isin": c.isin, "name": c.name,
                                 "sektor": c.sector, "region": c.region, "scale": c.price_scale,
                                 "waehrung": c.currency}
    for e in watchlist:
        vorhanden = nach_symbol.get(e["symbol"], {})
        nach_symbol[e["symbol"]] = {
            "symbol": e["symbol"], "isin": e["isin"] or vorhanden.get("isin", ""),
            "name": e["name"] or vorhanden.get("name", e["symbol"]),
            "sektor": vorhanden.get("sektor", ""), "region": vorhanden.get("region", "WATCH"),
            "scale": vorhanden.get("scale", 1.0), "waehrung": vorhanden.get("waehrung", ""),
        }
    if not nach_symbol:
        res.hinweise.append("Keine Titel zu prüfen — Universum leer und Watchlist leer.")
        res.trichter = ks.trichter([])
        return res

    # 2. Kurse. Nur für Notierungsdauer und Kurs — der Katalog ist sonst kursunabhängig,
    #    und das ist Absicht: „weil der Kurs gerade gefallen ist" ist ausdrücklich kein
    #    Qualitätsargument (KERN.md 6, Ausschlusskriterien).
    symbole = sorted(nach_symbol)
    if demo:
        source = source or SyntheticSource(days=int(settings.get("data.history_days", 420)))
    elif offline:
        source = source or NullSource()
    else:
        source = source or build_source(settings)
    frames, kurs_fehlt, kurs_notes = update_prices(
        settings, symbole, scales={s: nach_symbol[s]["scale"] for s in symbole},
        source=source, fallback=None, today=as_of)
    res.hinweise.extend(kurs_notes)
    fx = FxTable({}, "demo") if demo else load_fx(settings, offline=offline)

    # 3. Vorfilter — was ohne Netz entscheidbar ist, wird ohne Netz entschieden. Ein
    #    Fundamentaldaten-Abruf je Titel ist teuer; ihn für einen Titel auszugeben, der
    #    schon an der Notierungsdauer scheitert, wäre Verschwendung.
    # Dieselbe Liste, die auch der Screener anwendet — Einträge sind {isin, symbol, note}.
    # `core_holdings` steht bewusst mit drin: ein Titel, den der Kern schon hält, ist kein
    # Kandidat mehr, sondern ein Bestand.
    ausschluesse: set[str] = set()
    if not demo:
        gruppen = settings.load_yaml("exclusions_file", {}) or {}
        for gruppe in ("core_holdings", "not_tradable", "manual"):
            for eintrag in gruppen.get(gruppe) or []:
                if not isinstance(eintrag, dict):
                    continue
                for schluessel in ("isin", "symbol"):
                    if eintrag.get(schluessel):
                        ausschluesse.add(str(eintrag[schluessel]).strip().upper())
    watchlist_symbole = {e["symbol"] for e in watchlist}

    # Kein Vorfilter auf die Notierungsdauer: die Länge der Kursreihe misst das Alter des
    # Caches, nicht das der Firma (er wird mit data.history_days gefüllt, also rund 420
    # Tagen). Ein solcher Filter hätte beim ersten Lauf das gesamte Universum verworfen.
    # Kriterium 6 entscheidet stattdessen später anhand der Erstnotiz aus der Quelle.
    zu_pruefen: list[str] = []
    for s in symbole:
        meta = nach_symbol[s]
        if s.upper() in ausschluesse or (meta["isin"] or "").upper() in ausschluesse:
            res.vorgefiltert += 1
            continue
        zu_pruefen.append(s)
    if res.vorgefiltert:
        res.hinweise.append(f"{res.vorgefiltert} Titel über config/exclusions.yaml ausgeschlossen "
                            f"(bereits im Kern, nicht handelbar oder manuell gesperrt)")
    if max_titel is not None:
        zu_pruefen = zu_pruefen[:max_titel]

    # 4. Fundamentaldaten
    if demo:
        fundamentals_source = fundamentals_source or SyntheticFundamentals()
    elif offline:
        fundamentals_source = fundamentals_source or NullFundamentals()
    log.info("Kern-Scan: %d Titel zu prüfen (%d vorgefiltert)", len(zu_pruefen), res.vorgefiltert)
    kennzahlen, fehlt, f_notes = update_fundamentals(
        settings, zu_pruefen, source=fundamentals_source, today=as_of, progress=progress)
    res.hinweise.extend(f_notes)
    res.daten_fehlt = fehlt

    # 5. Prüfen
    im_satelliten = _satelliten_symbole(settings)
    auf_watchlist = _watchlist_symbole(settings, as_of)
    for s in zu_pruefen:
        f = kennzahlen.get(s)
        if f is None:
            continue
        meta = nach_symbol[s]
        kurs_eur = None
        df = frames.get(s)
        if df is not None and not df.empty:
            kurs_eur = fx.to_eur(float(df["close"].iloc[-1]), meta["waehrung"] or "EUR")
        if f.marktkap_eur is not None and f.waehrung and f.waehrung != "EUR":
            f.marktkap_eur = fx.to_eur(f.marktkap_eur, f.waehrung)
        res.kandidaten.append(ks.pruefe(
            f, settings, isin=meta["isin"], name=meta["name"], sektor=meta["sektor"],
            region=meta["region"], kurs_eur=kurs_eur, jahre_notiert=_jahre_notiert(df),
            im_satelliten=s.upper() in im_satelliten,
            auf_watchlist=s.upper() in auf_watchlist and s not in watchlist_symbole,
            as_of=as_of))
    res.geprueft = len(res.kandidaten)
    res.kandidaten = ks.rangfolge(res.kandidaten)
    res.trichter = ks.trichter(res.kandidaten)
    schreibe_csv(res, settings)
    return res


# --------------------------------------------------------------------------- Stand
def schreibe_stand(settings: Settings, res: KernScanResult) -> None:
    """Das Ergebnis für Wochenlauf und Ansicht ablegen.

    Der Scan läuft eigenständig und selten; der Wochenlauf soll ihn weder auslösen noch
    wiederholen. Er liest deshalb nur diesen Stand — und sieht an `as_of`, wie alt er ist.
    Es werden ausschließlich Titel abgelegt, die den Katalog bestehen: Durchgefallene
    füllten die Ansicht mit Hunderten von Zeilen, die alle dasselbe sagen.
    """
    from dataclasses import asdict

    inhalt = {
        "as_of": res.as_of.isoformat(),
        "quelle": res.quelle,
        "geprueft": res.geprueft,
        "vorgefiltert": res.vorgefiltert,
        "trichter": res.trichter,
        "hinweise": res.hinweise,
        "demo": res.demo,
        "kandidaten": [asdict(k) for k in res.bestanden],
    }
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    (settings.state_dir / STAND_DATEI).write_text(
        json.dumps(inhalt, ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")


def lade_stand(settings: Settings) -> dict:
    """Letzter Scan als Rohdaten. Fehlt er, ist das kein Fehler — dann wurde nie gescannt."""
    p = settings.state_dir / STAND_DATEI
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        log.warning("Kern-Stand unlesbar (%s) — wird ignoriert", exc)
        return {}


def kandidaten_aus_stand(settings: Settings) -> tuple[list[ks.KernKandidat], dict]:
    """(Kandidaten, Kopfdaten). Die Kopfdaten tragen Datum und Trichter für die Ansicht."""
    stand = lade_stand(settings)
    if not stand:
        return [], {}
    kandidaten = []
    for roh in stand.get("kandidaten") or []:
        kriterien = [ks.Kriterium(**k) for k in roh.get("kriterien") or []]
        soll = [ks.Kriterium(**k) for k in roh.get("soll") or []]
        felder = {k: v for k, v in roh.items() if k not in ("kriterien", "soll")}
        kandidaten.append(ks.KernKandidat(kriterien=kriterien, soll=soll, **felder))
    kopf = {k: v for k, v in stand.items() if k != "kandidaten"}
    return kandidaten, kopf


def schreibe_csv(res: KernScanResult, settings: Settings) -> str | None:
    """Ein Lauf, eine Datei — wie beim Screener. Die Kriterien kommen als eigene Spalten,
    damit sich das Ergebnis auch in einer Tabellenkalkulation nachvollziehen lässt."""
    if not res.kandidaten:
        return None
    zeilen = []
    for k in res.kandidaten:
        zeile = {"symbol": k.symbol, "isin": k.isin, "name": k.name, "sektor": k.sektor,
                 "region": k.region, "kurs_eur": k.kurs_eur, "bestanden": k.bestanden,
                 "ausschluss": k.ausschluss, "jahre_abgedeckt": k.jahre_abgedeckt,
                 "soll_erfuellt": k.erfuellte_soll, "daten_stand": k.daten_stand}
        for kr in k.kriterien:
            zeile[f"k{kr.nummer}"] = {True: "ja", False: "nein"}.get(kr.erfuellt, "offen")
            zeile[f"k{kr.nummer}_wert"] = kr.wert
        zeilen.append(zeile)
    p = settings.reports_dir / f"kern_{res.as_of.isoformat()}.csv"
    pd.DataFrame(zeilen).to_csv(p, index=False, float_format="%.4f")
    return str(p)

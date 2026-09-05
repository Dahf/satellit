"""Universum: Konstituenten aus iShares-Holdings-CSVs (S&P 500, STOXX Europe 600).

Die iShares-Dateien liefern je Position ISIN, Ticker, Sektor, Börse und Handelswährung.
Daraus wird das Yahoo-Symbol abgeleitet (Ticker + Börsensuffix), mit manuellen
Korrekturen aus config/symbol_overrides.yaml.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import requests

from .config import Settings

log = logging.getLogger(__name__)

HEADER_FIRST_CELLS = {"ticker", "emittententicker", "issuer ticker"}

COLUMN_ALIASES = {
    "ticker": {"ticker", "emittententicker", "issuer ticker"},
    "name": {"name"},
    "sector": {"sector", "sektor"},
    "asset_class": {"asset class", "anlageklasse"},
    "weight": {"weight (%)", "gewichtung (%)", "weight"},
    "isin": {"isin"},
    "price": {"price", "kurs"},
    "location": {"location", "standort"},
    "exchange": {"exchange", "börse", "boerse"},
    "currency": {"market currency", "marktwährung", "marktwaehrung", "currency", "währung"},
}

EQUITY_CLASSES = {"equity", "aktien", "aktie", "stock", "stocks"}

# Börse (iShares-Schreibweise, Teilstring, kleingeschrieben) -> Yahoo-Suffix
EXCHANGE_SUFFIX = [
    ("xetra", ".DE"), ("frankfurt", ".DE"), ("deutsche boerse", ".DE"), ("deutsche börse", ".DE"),
    ("london", ".L"),
    ("paris", ".PA"), ("amsterdam", ".AS"), ("brussels", ".BR"), ("bruxelles", ".BR"),
    ("lisbon", ".LS"), ("lisboa", ".LS"), ("dublin", ".IR"), ("irish", ".IR"),
    ("swiss", ".SW"), ("six", ".SW"), ("zurich", ".SW"),
    ("italiana", ".MI"), ("milan", ".MI"), ("mailand", ".MI"),
    ("madrid", ".MC"), ("bolsa de", ".MC"),
    ("stockholm", ".ST"), ("copenhagen", ".CO"), ("kopenhagen", ".CO"), ("helsinki", ".HE"),
    ("oslo", ".OL"), ("wien", ".VI"), ("vienna", ".VI"), ("warsaw", ".WA"), ("warschau", ".WA"),
    ("athens", ".AT"), ("prague", ".PR"), ("toronto", ".TO"),
    ("nasdaq", ""), ("new york", ""), ("nyse", ""), ("cboe", ""), ("bats", ""),
]

# "Nasdaq Omx Nordic" nennt die Börse nicht — die Handelswährung entscheidet.
NORDIC_BY_CURRENCY = {"SEK": ".ST", "DKK": ".CO", "NOK": ".OL", "EUR": ".HE", "ISK": ".IC"}


@dataclass
class Constituent:
    region: str
    isin: str
    ticker: str
    name: str
    sector: str
    exchange: str
    currency: str
    weight: float
    symbol: str           # Yahoo-Symbol
    price_scale: float    # 0.01 für LSE-Notierungen in Pence

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- parsing
def parse_number(text: str) -> float:
    """'1,234.56' | '1.234,56' | '12,3' | '' -> float"""
    s = (text or "").strip().replace("%", "").replace(" ", "")
    if not s or s in {"-", "–"}:
        return float("nan")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):      # deutsches Format 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:                                 # englisches Format 1,234.56
            s = s.replace(",", "")
    elif "," in s:
        # nur Komma: deutsches Dezimalkomma, außer es sieht nach Tausendertrennung aus
        parts = s.split(",")
        s = s.replace(",", "") if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3) else s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _normalise_header(cells: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(cells):
        key = cell.strip().lower().lstrip("﻿")
        for field, aliases in COLUMN_ALIASES.items():
            if key in aliases and field not in mapping:
                mapping[field] = idx
    return mapping


def _cell(row: list[str], cols: dict[str, int], key: str, default: str = "") -> str:
    """Feld aus einer CSV-Zeile. Fehlende Spalte oder zu kurze Zeile -> default."""
    idx = cols.get(key)
    if idx is None or idx >= len(row):
        return default
    return row[idx].strip()


def parse_ishares_csv(text: str, region: str) -> list[Constituent]:
    """iShares-Holdings-CSV (deutsche oder englische Seite) -> Konstituenten (nur Aktien)."""
    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        first = line.split(",")[0].strip().strip('"').lower().lstrip("﻿")
        if first in HEADER_FIRST_CELLS:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("Kein Tabellenkopf in der iShares-CSV gefunden (Ticker/Emittententicker)")

    reader = csv.reader(io.StringIO("\n".join(lines[header_idx:])))
    header = next(reader)
    cols = _normalise_header(header)
    for required in ("ticker", "name", "asset_class"):
        if required not in cols:
            raise ValueError(f"Spalte '{required}' fehlt in der iShares-CSV: {header}")

    out: list[Constituent] = []
    for row in reader:
        # Kurze Zeilen überspringen: iShares hängt eine Fußzeile aus einem einzelnen
        # geschützten Leerzeichen an, und einzelne Datenzeilen sind gelegentlich gekürzt.
        if not row or len(row) < 2:
            continue
        if _cell(row, cols, "asset_class").lower() not in EQUITY_CLASSES:
            continue
        ticker = _cell(row, cols, "ticker")
        if not ticker or ticker == "-":
            continue
        exchange = _cell(row, cols, "exchange")
        currency = _cell(row, cols, "currency").upper()
        symbol, scale = to_yahoo_symbol(ticker, exchange, currency, region)
        out.append(Constituent(
            region=region, isin=_cell(row, cols, "isin"), ticker=ticker,
            name=_cell(row, cols, "name"), sector=_cell(row, cols, "sector") or "Unknown",
            exchange=exchange, currency=currency,
            weight=parse_number(_cell(row, cols, "weight")), symbol=symbol, price_scale=scale,
        ))
    if not out:
        raise ValueError("iShares-CSV enthält keine Aktienpositionen")
    return out


# --------------------------------------------------------------------------- mapping
def exchange_suffix(exchange: str, region: str, currency: str = "") -> str | None:
    ex = (exchange or "").lower()
    # "Nasdaq Omx Nordic" fasst Stockholm, Helsinki, Kopenhagen und Oslo unter einem Namen
    # zusammen; erst die Handelswährung sagt, welche Börse gemeint ist. Muss vor der
    # generischen nasdaq-Regel stehen — sonst landen die nordischen Titel als US-Symbole
    # im Universum und schlagen beim Kursabruf fehl.
    if "omx" in ex or "nordic" in ex:
        return NORDIC_BY_CURRENCY.get((currency or "").upper())
    for needle, suffix in EXCHANGE_SUFFIX:
        if needle in ex:
            return suffix
    if region == "US":
        return ""
    return None


def normalise_ticker(ticker: str, suffix: str) -> str:
    t = ticker.strip().upper()
    t = re.sub(r"\s+", "-", t)          # "ERIC B" -> "ERIC-B", "BRK B" -> "BRK-B"
    if suffix == ".L":
        t = t.rstrip(".")                # "BP." -> "BP"
        t = t.replace(".", "-")          # "BT.A" -> "BT-A"
    else:
        t = t.replace("/", "-")          # "BRK/B" -> "BRK-B"
    return t


def to_yahoo_symbol(ticker: str, exchange: str, currency: str, region: str) -> tuple[str, float]:
    suffix = exchange_suffix(exchange, region, currency)
    if suffix is None:
        suffix = ""  # unbekannte Börse: Ticker roh übernehmen, Bericht zeigt Ladefehler
    base = normalise_ticker(ticker, suffix)
    symbol = f"{base}{suffix}"
    scale = 0.01 if (suffix == ".L" and currency in {"GBP", "GBX", "GBP."}) else 1.0
    return symbol, scale


def apply_overrides(constituents: Iterable[Constituent], overrides: dict[str, str]) -> list[Constituent]:
    """Schlüssel darf ISIN, Yahoo-Symbol oder Ticker sein.

    Die iShares-Dateien liefern seit 09/2026 keine ISIN-Spalte mehr; ein rein ISIN-basierter
    Schlüssel würde also stillschweigend nie greifen.
    """
    out = []
    for c in constituents:
        neu = overrides.get(c.isin) if c.isin else None
        if not neu:
            neu = overrides.get(c.symbol) or overrides.get(c.ticker)
        if neu:
            c.symbol = neu
        out.append(c)
    return out


# --------------------------------------------------------------------------- loading
# Der iShares-CDN weist Anfragen mit knappen Headern ab, besonders aus Rechenzentren.
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    "Accept": "text/csv,text/plain,application/octet-stream,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
}

RETRY_PAUSEN = (5, 15)   # Sekunden vor dem 2. und 3. Versuch


def _decode(content: bytes) -> str:
    # iShares liefert teils UTF-8 mit BOM, teils latin-1
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _alter_tage(path: Path) -> int:
    return max(0, (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).days)


def _download(url: str, referer: str | None = None, timeout: int = 60) -> str:
    """Holdings-CSV holen. Wirft mit einer Meldung, aus der man den Grund ablesen kann.

    Der Referer-Aufruf holt vorher die Produktseite und setzt damit die Cookies, die der
    CDN erwartet — das ist der häufigste Grund für ein 403 auf den Download-Link.
    """
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    if referer:
        session.headers["Referer"] = referer
        try:
            session.get(referer, timeout=timeout)
        except requests.RequestException as exc:      # unkritisch: nur die Cookies fehlen dann
            log.debug("Referer-Aufruf fehlgeschlagen (%s): %s", referer, exc)

    letzter = "kein Versuch ausgeführt"
    for versuch in range(len(RETRY_PAUSEN) + 1):
        if versuch:
            time.sleep(RETRY_PAUSEN[versuch - 1])
        try:
            r = session.get(url, timeout=timeout)
        except requests.RequestException as exc:
            letzter = f"Netzwerkfehler: {exc}"
            continue
        ctype = r.headers.get("Content-Type", "?")
        if r.status_code != 200:
            letzter = f"HTTP {r.status_code}, Content-Type {ctype}, Anfang: {r.text[:120]!r}"
            continue
        text = _decode(r.content)
        if "<html" in text[:400].lower():
            letzter = f"HTML statt CSV, Content-Type {ctype}, Anfang: {text[:120]!r}"
            continue
        return text
    raise RuntimeError(letzter)


def _quellen(cfg: dict) -> list[dict]:
    """Quellen einer Region. Erlaubt beides: eine einzelne ishares_url oder eine Liste quellen."""
    roh = cfg.get("quellen")
    if isinstance(roh, list) and roh:
        return [q for q in roh if isinstance(q, dict) and q.get("url")]
    url = cfg.get("ishares_url")
    return [{"url": url, "referer": cfg.get("referer")}] if url else []


def load_snapshot(path: Path, region: str) -> list[Constituent]:
    """Konstituenten aus dem Snapshot des letzten erfolgreichen Laufs — die letzte Rettung."""
    if not path.exists():
        return []
    out: list[Constituent] = []
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if (row.get("region") or "") != region or not row.get("symbol"):
                    continue
                out.append(Constituent(
                    region=region, isin=row.get("isin", ""), ticker=row.get("ticker", ""),
                    name=row.get("name", ""), sector=row.get("sector") or "Unknown",
                    exchange=row.get("exchange", ""), currency=(row.get("currency") or "").upper(),
                    weight=parse_number(row.get("weight", "")), symbol=row["symbol"],
                    price_scale=parse_number(row.get("price_scale", "")) or 1.0,
                ))
    except (OSError, csv.Error) as exc:
        log.warning("Snapshot %s nicht lesbar: %s", path, exc)
        return []
    return out


def import_holdings(settings: Settings, region: str, text: str) -> tuple[int, Path]:
    """Manuell heruntergeladene Holdings-CSV übernehmen. Validiert vor dem Schreiben."""
    regionen = settings.get("universe.regions", {}) or {}
    if region not in regionen:
        raise ValueError(f"Unbekannte Region {region!r} — bekannt: {', '.join(regionen) or '(keine)'}")
    cons = parse_ishares_csv(text, region)          # wirft, wenn die Datei nicht passt
    settings.ensure_dirs()
    ziel = settings.universe_dir / f"{region}_holdings.csv"
    ziel.write_text(text, encoding="utf-8")
    return len(cons), ziel


def load_universe(settings: Settings, force: bool = False,
                  offline: bool = False) -> tuple[list[Constituent], list[str], dict[str, dict]]:
    """Konstituenten aller Regionen laden.

    Reihenfolge je Region: frischer Cache -> Quellen der Reihe nach -> alter Cache
    -> local_file -> Snapshot des letzten erfolgreichen Laufs.

    `offline=True` überspringt den Download-Schritt vollständig — für den Neuaufbau der
    Ansicht nach einer Dashboard-Aktion, der in Sekunden fertig sein muss.

    Gibt (Konstituenten, Warnungen, Status je Region) zurück. Der Status hält fest, woher
    die Daten kamen und wie alt sie sind — ohne ihn bleibt ein Ausfall unsichtbar und die
    Pipeline rechnet stillschweigend auf einem leeren Universum weiter.
    """
    settings.ensure_dirs()
    warnings: list[str] = []
    status: dict[str, dict] = {}
    overrides = (settings.load_yaml("symbol_overrides_file", {}) or {}).get("overrides", {}) or {}
    exclusions = settings.load_yaml("exclusions_file", {}) or {}
    excluded_isin: dict[str, str] = {}
    excluded_symbol: dict[str, str] = {}
    for group in ("core_holdings", "not_tradable", "manual"):
        for item in exclusions.get(group) or []:
            if not isinstance(item, dict):
                continue
            grund = f"{group}: {item.get('note', '')}".strip()
            if item.get("isin"):
                excluded_isin[str(item["isin"]).strip()] = grund
            if item.get("symbol"):
                excluded_symbol[str(item["symbol"]).strip().upper()] = grund
    refresh_days = int(settings.get("universe.refresh_days", 30))
    snapshot_pfad = settings.universe_dir / "universe_snapshot.csv"

    all_cons: list[Constituent] = []
    for region, cfg in settings.get("universe.regions", {}).items():
        cache_file = settings.universe_dir / f"{region}_holdings.csv"
        text: str | None = None
        quelle: str | None = None
        alter: int | None = None

        fresh = cache_file.exists() and (
            datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime) < timedelta(days=refresh_days)
        )
        if fresh and not force:
            text, quelle, alter = cache_file.read_text(encoding="utf-8"), "cache", _alter_tage(cache_file)
        else:
            for q in ([] if offline else _quellen(cfg)):
                try:
                    kandidat = _download(q["url"], q.get("referer"))
                    parse_ishares_csv(kandidat, region)      # validieren, bevor der Cache überschrieben wird
                    cache_file.write_text(kandidat, encoding="utf-8")
                    text, quelle, alter = kandidat, "download", 0
                    break
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"{region}: Download fehlgeschlagen ({exc})")
            if text is None and cache_file.exists():
                text, quelle, alter = cache_file.read_text(encoding="utf-8"), "cache", _alter_tage(cache_file)
                warnings.append(f"{region}: Konstituenten aus Cache, {alter} Tage alt")
            if text is None and cfg.get("local_file"):
                lf = settings._resolve(cfg["local_file"])
                if lf.exists():
                    text, quelle, alter = lf.read_text(encoding="utf-8", errors="replace"), "local_file", _alter_tage(lf)
                    warnings.append(f"{region}: Konstituenten aus local_file {lf.name}")

        cons: list[Constituent] | None = None
        if text is not None:
            try:
                cons = parse_ishares_csv(text, region)
            except ValueError as exc:
                warnings.append(f"{region}: iShares-CSV nicht lesbar ({exc})")
                cons = None
        if not cons:
            cons = load_snapshot(snapshot_pfad, region)
            if cons:
                quelle, alter = "snapshot", _alter_tage(snapshot_pfad)
                warnings.append(f"{region}: Konstituenten aus dem letzten erfolgreichen Lauf ({alter} Tage alt)")
        if not cons:
            warnings.append(f"{region}: KEINE Konstituenten verfügbar — Region wird übersprungen")
            status[region] = {"quelle": None, "alter_tage": None, "anzahl": 0, "ok": False}
            continue

        cons = apply_overrides(cons, overrides)
        if excluded_isin and not any(c.isin for c in cons):
            warnings.append(
                f"{region}: Datei enthält keine ISIN-Spalte — {len(excluded_isin)} ISIN-Ausschlüsse "
                "greifen hier nicht. Stattdessen 'symbol:' in exclusions.yaml eintragen."
            )
        kept = []
        for c in cons:
            grund = excluded_isin.get(c.isin) if c.isin else None
            grund = grund or excluded_symbol.get(c.symbol.upper()) or excluded_symbol.get(c.ticker.upper())
            if grund:
                log.info("Ausschluss %s %s (%s)", c.symbol, c.name, grund)
                continue
            kept.append(c)
        all_cons.extend(kept)
        status[region] = {"quelle": quelle, "alter_tage": alter, "anzahl": len(kept), "ok": True}
        log.info("%s: %d Konstituenten aus %s (%d ausgeschlossen)", region, len(kept), quelle, len(cons) - len(kept))

    # Doppelte Symbole (z. B. Dual Listings) entfernen — erstes Vorkommen gewinnt
    seen: set[str] = set()
    unique = []
    for c in all_cons:
        if c.symbol in seen:
            continue
        seen.add(c.symbol)
        unique.append(c)
    return unique, warnings, status


def save_universe_snapshot(constituents: list[Constituent], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(Constituent.__dataclass_fields__.keys()))
        writer.writeheader()
        for c in constituents:
            writer.writerow(c.to_dict())


def snapshot_aktualisieren(constituents: list[Constituent], status: dict[str, dict], path: Path) -> bool:
    """Snapshot nur schreiben, wenn mindestens eine Region aus einer echten Quelle kam.

    Kam alles aus dem Snapshot selbst, würde das Neuschreiben nur seine mtime zurücksetzen —
    und damit sein Alter verschleiern, also genau die Information vernichten, für die er da ist.
    """
    if not constituents:
        return False
    if all((s.get("quelle") in (None, "snapshot")) for s in status.values()):
        return False
    save_universe_snapshot(constituents, path)
    return True

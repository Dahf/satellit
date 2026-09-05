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
        if not row or len(row) <= cols["ticker"]:
            continue
        asset_class = row[cols["asset_class"]].strip().lower()
        if asset_class not in EQUITY_CLASSES:
            continue
        ticker = row[cols["ticker"]].strip()
        if not ticker or ticker == "-":
            continue
        isin = row[cols["isin"]].strip() if "isin" in cols else ""
        exchange = row[cols["exchange"]].strip() if "exchange" in cols else ""
        currency = row[cols["currency"]].strip().upper() if "currency" in cols else ""
        weight = parse_number(row[cols["weight"]]) if "weight" in cols else float("nan")
        sector = row[cols["sector"]].strip() if "sector" in cols else "Unknown"
        symbol, scale = to_yahoo_symbol(ticker, exchange, currency, region)
        out.append(Constituent(
            region=region, isin=isin, ticker=ticker, name=row[cols["name"]].strip(),
            sector=sector or "Unknown", exchange=exchange, currency=currency,
            weight=weight, symbol=symbol, price_scale=scale,
        ))
    if not out:
        raise ValueError("iShares-CSV enthält keine Aktienpositionen")
    return out


# --------------------------------------------------------------------------- mapping
def exchange_suffix(exchange: str, region: str) -> str | None:
    ex = (exchange or "").lower()
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
    suffix = exchange_suffix(exchange, region)
    if suffix is None:
        suffix = ""  # unbekannte Börse: Ticker roh übernehmen, Bericht zeigt Ladefehler
    base = normalise_ticker(ticker, suffix)
    symbol = f"{base}{suffix}"
    scale = 0.01 if (suffix == ".L" and currency in {"GBP", "GBX", "GBP."}) else 1.0
    return symbol, scale


def apply_overrides(constituents: Iterable[Constituent], overrides: dict[str, str]) -> list[Constituent]:
    out = []
    for c in constituents:
        if c.isin and c.isin in overrides:
            c.symbol = overrides[c.isin]
        out.append(c)
    return out


# --------------------------------------------------------------------------- loading
def _download(url: str, timeout: int = 60) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (satellit-pipeline; private use)"}
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    content = r.content
    # iShares liefert teils UTF-8 mit BOM, teils latin-1
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def load_universe(settings: Settings, force: bool = False) -> tuple[list[Constituent], list[str]]:
    """Konstituenten aller Regionen laden. Gibt (Liste, Warnungen) zurück.

    Reihenfolge je Region: frische Cache-Datei -> Download -> alte Cache-Datei -> local_file.
    """
    settings.ensure_dirs()
    warnings: list[str] = []
    overrides = (settings.load_yaml("symbol_overrides_file", {}) or {}).get("overrides", {}) or {}
    exclusions = settings.load_yaml("exclusions_file", {}) or {}
    excluded = {}
    for group in ("core_holdings", "not_tradable", "manual"):
        for item in exclusions.get(group) or []:
            if isinstance(item, dict) and item.get("isin"):
                excluded[item["isin"]] = f"{group}: {item.get('note', '')}".strip()
    refresh_days = int(settings.get("universe.refresh_days", 30))

    all_cons: list[Constituent] = []
    for region, cfg in settings.get("universe.regions", {}).items():
        cache_file = settings.universe_dir / f"{region}_holdings.csv"
        text: str | None = None
        fresh = cache_file.exists() and (
            datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime) < timedelta(days=refresh_days)
        )
        if fresh and not force:
            text = cache_file.read_text(encoding="utf-8")
        else:
            url = cfg.get("ishares_url")
            if url:
                try:
                    text = _download(url)
                    parse_ishares_csv(text, region)          # validieren, bevor der Cache überschrieben wird
                    cache_file.write_text(text, encoding="utf-8")
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"{region}: Download der iShares-Holdings fehlgeschlagen ({exc}); nutze Cache/local_file")
                    text = None
            if text is None and cache_file.exists():
                text = cache_file.read_text(encoding="utf-8")
                age = (datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)).days
                warnings.append(f"{region}: Konstituenten aus Cache, {age} Tage alt")
            if text is None and cfg.get("local_file"):
                lf = settings._resolve(cfg["local_file"])
                if lf.exists():
                    text = lf.read_text(encoding="utf-8", errors="replace")
                    warnings.append(f"{region}: Konstituenten aus local_file {lf.name}")
        if text is None:
            warnings.append(f"{region}: KEINE Konstituenten verfügbar — Region wird übersprungen")
            continue
        try:
            cons = parse_ishares_csv(text, region)
        except ValueError as exc:
            warnings.append(f"{region}: iShares-CSV nicht lesbar ({exc}) — Region wird übersprungen")
            continue
        cons = apply_overrides(cons, overrides)
        kept = []
        for c in cons:
            if c.isin in excluded:
                log.info("Ausschluss %s %s (%s)", c.symbol, c.name, excluded[c.isin])
                continue
            kept.append(c)
        all_cons.extend(kept)
        log.info("%s: %d Konstituenten (%d ausgeschlossen)", region, len(kept), len(cons) - len(kept))

    # Doppelte Symbole (z. B. Dual Listings) entfernen — erstes Vorkommen gewinnt
    seen: set[str] = set()
    unique = []
    for c in all_cons:
        if c.symbol in seen:
            continue
        seen.add(c.symbol)
        unique.append(c)
    return unique, warnings


def save_universe_snapshot(constituents: list[Constituent], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(Constituent.__dataclass_fields__.keys()))
        writer.writeheader()
        for c in constituents:
            writer.writerow(c.to_dict())

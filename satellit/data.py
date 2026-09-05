"""Kursdaten: austauschbare Quellen (yfinance, Stooq, Fixture, Synthetic) + lokaler CSV-Cache.

Datenmodell je Symbol: DataFrame mit DatetimeIndex (tz-naiv, aufsteigend) und den Spalten
open, high, low, close, volume — split-/dividendenbereinigt, soweit die Quelle das liefert.
"""

from __future__ import annotations

import io
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Settings

log = logging.getLogger(__name__)

COLUMNS = ["open", "high", "low", "close", "volume"]


@dataclass
class FetchResult:
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)      # symbol -> Grund
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------- helpers
def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Beliebigen OHLCV-Frame in das Standardformat bringen."""
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNS)
    out = df.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]
    rename = {"adj close": "adj_close", "date": "date"}
    out = out.rename(columns=rename)
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out = out.dropna(subset=["date"]).set_index("date")
    out.index = pd.to_datetime(out.index)
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_localize(None)
    out.index.name = "date"
    for c in COLUMNS:
        if c not in out.columns:
            out[c] = np.nan
    out = out[COLUMNS].apply(pd.to_numeric, errors="coerce")
    out = out.dropna(subset=["close"])
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def _stale_days(df: pd.DataFrame, today: date) -> int:
    if df is None or df.empty:
        return 10_000
    return (today - df.index[-1].date()).days


# ------------------------------------------------------------------------- sources
class PriceSource(ABC):
    name = "abstract"

    @abstractmethod
    def fetch(self, symbols: list[str], start: date, end: date | None = None) -> FetchResult:
        """Tageskurse für Symbole ab `start`."""


class YFinanceSource(PriceSource):
    """Primärquelle. Inoffizielle Yahoo-Finance-Schnittstelle — Rate-Limits möglich."""

    name = "yfinance"

    def __init__(self, batch_size: int = 80, pause: float = 3.0, retries: int = 2):
        self.batch_size = batch_size
        self.pause = pause
        self.retries = retries

    def fetch(self, symbols: list[str], start: date, end: date | None = None) -> FetchResult:
        try:
            import yfinance as yf  # noqa: WPS433
        except ImportError as exc:  # pragma: no cover
            res = FetchResult()
            res.notes.append(f"yfinance nicht installiert: {exc}")
            for s in symbols:
                res.failed[s] = "yfinance fehlt"
            return res

        res = FetchResult()
        for i in range(0, len(symbols), self.batch_size):
            batch = symbols[i:i + self.batch_size]
            data = None
            for attempt in range(self.retries + 1):
                try:
                    data = yf.download(
                        tickers=batch, start=start.isoformat(),
                        end=(end + timedelta(days=1)).isoformat() if end else None,
                        auto_adjust=True, group_by="ticker", threads=False,
                        progress=False, actions=False,
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    wait = 30 * (attempt + 1)
                    log.warning("yfinance Batch %d fehlgeschlagen (%s) — warte %ds", i // self.batch_size, exc, wait)
                    res.notes.append(f"yfinance Fehler: {exc}")
                    time.sleep(wait)
            if data is None or data.empty:
                for s in batch:
                    res.failed[s] = "keine Daten (yfinance)"
                continue
            for s in batch:
                try:
                    if isinstance(data.columns, pd.MultiIndex):
                        if s not in data.columns.get_level_values(0):
                            res.failed[s] = "Symbol unbekannt (yfinance)"
                            continue
                        df = data[s]
                    else:
                        df = data
                    df = _clean(df)
                    if df.empty:
                        res.failed[s] = "leere Kursreihe (yfinance)"
                    else:
                        res.frames[s] = df
                except Exception as exc:  # noqa: BLE001
                    res.failed[s] = f"Parse-Fehler: {exc}"
            if i + self.batch_size < len(symbols):
                time.sleep(self.pause)
        return res


class StooqSource(PriceSource):
    """Fallback. Seit 04/2026 ist ein (kostenloser) API-Key nötig: STOOQ_APIKEY.

    Verifizierte Suffixe: .us, .de, .uk. Andere Börsen werden versucht, sind aber nicht verifiziert.
    """

    name = "stooq"
    SUFFIX_MAP = {"": ".us", ".DE": ".de", ".L": ".uk", ".PA": ".fr", ".AS": ".nl", ".MI": ".it",
                  ".MC": ".es", ".SW": ".ch", ".ST": ".se", ".CO": ".dk", ".HE": ".fi", ".OL": ".no",
                  ".BR": ".be", ".LS": ".pt", ".VI": ".at", ".WA": "", ".IR": ".ie", ".TO": ".ca"}

    def __init__(self, apikey: str | None = None, pause: float = 0.5):
        self.apikey = apikey or os.environ.get("STOOQ_APIKEY", "")
        self.pause = pause

    @classmethod
    def to_stooq_symbol(cls, symbol: str) -> str | None:
        if symbol.startswith("^"):
            return symbol.lower()
        base, suffix = symbol, ""
        if "." in symbol:
            base, suf = symbol.rsplit(".", 1)
            suffix = "." + suf
        mapped = cls.SUFFIX_MAP.get(suffix)
        if mapped is None:
            return None
        return f"{base}{mapped}".lower()

    def fetch(self, symbols: list[str], start: date, end: date | None = None) -> FetchResult:
        import requests

        res = FetchResult()
        if not self.apikey:
            res.notes.append("Stooq: kein STOOQ_APIKEY gesetzt — Fallback inaktiv")
            for s in symbols:
                res.failed[s] = "Stooq ohne API-Key"
            return res
        for s in symbols:
            ss = self.to_stooq_symbol(s)
            if ss is None:
                res.failed[s] = "Stooq: Börse nicht abgebildet"
                continue
            url = (f"https://stooq.com/q/d/l/?s={ss}&i=d&d1={start.strftime('%Y%m%d')}"
                   f"&d2={(end or date.today()).strftime('%Y%m%d')}&apikey={self.apikey}")
            try:
                r = requests.get(url, timeout=30)
                text = r.text
                if r.status_code != 200 or "<html" in text.lower() or "Exceeded" in text:
                    res.failed[s] = f"Stooq: {text.strip()[:60]}"
                    continue
                df = _clean(pd.read_csv(io.StringIO(text)))
                if df.empty:
                    res.failed[s] = "Stooq: leer"
                else:
                    res.frames[s] = df
            except Exception as exc:  # noqa: BLE001
                res.failed[s] = f"Stooq: {exc}"
            time.sleep(self.pause)
        return res


class FixtureSource(PriceSource):
    """Liest CSV-Dateien <dir>/<symbol>.csv — für Tests und Trockenläufe ohne Netz."""

    name = "fixture"

    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def fetch(self, symbols: list[str], start: date, end: date | None = None) -> FetchResult:
        res = FetchResult()
        for s in symbols:
            p = self.directory / f"{s}.csv"
            if not p.exists():
                res.failed[s] = "Fixture fehlt"
                continue
            df = _clean(pd.read_csv(p))
            res.frames[s] = df[df.index.date >= start]
        return res


class SyntheticSource(PriceSource):
    """Deterministische Zufallskurse (Demo-Modus). Erzeugt bewusst einige Ausbrüche."""

    name = "synthetic"

    def __init__(self, seed: int = 7, days: int = 420):
        self.seed = seed
        self.days = days

    def fetch(self, symbols: list[str], start: date, end: date | None = None) -> FetchResult:
        res = FetchResult()
        end = end or date.today()
        idx = pd.bdate_range(end=end, periods=self.days)
        for n, s in enumerate(symbols):
            rng = np.random.default_rng(self.seed + n * 101 + sum(map(ord, s)))
            drift = rng.normal(0.0004, 0.0006)
            vol = rng.uniform(0.010, 0.025)
            rets = rng.normal(drift, vol, len(idx))
            # jedes 7. Symbol: Base + frischer Ausbruch in den letzten Tagen
            if n % 7 == 3:
                rets[-120:-8] = rng.normal(0.0, 0.006, 112)
                rets[-8:] = rng.normal(0.012, 0.006, 8)
            close = 50 * np.exp(np.cumsum(rets)) * rng.uniform(0.4, 6.0)
            high = close * (1 + rng.uniform(0.002, 0.02, len(idx)))
            low = close * (1 - rng.uniform(0.002, 0.02, len(idx)))
            openp = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, 0.003, len(idx)))
            volume = rng.uniform(2e5, 5e6, len(idx))
            df = pd.DataFrame({"open": openp, "high": high, "low": low, "close": close, "volume": volume}, index=idx)
            df.index.name = "date"
            res.frames[s] = df[df.index.date >= start]
        return res


def build_source(settings: Settings, which: str | None = None) -> PriceSource:
    kind = (which or settings.get("data.primary", "yfinance")).lower()
    if kind == "yfinance":
        return YFinanceSource(batch_size=int(settings.get("data.batch_size", 80)),
                              pause=float(settings.get("data.batch_pause_seconds", 3)))
    if kind == "stooq":
        return StooqSource()
    if kind == "fixture":
        fixture_dir = settings.get("data.fixture_dir") or (settings.state_dir / "fixtures")
        return FixtureSource(settings._resolve(str(fixture_dir)))
    if kind == "synthetic":
        return SyntheticSource(days=int(settings.get("data.history_days", 420)))
    raise ValueError(f"Unbekannte Kursquelle: {kind}")


# ------------------------------------------------------------------------- cache
class PriceCache:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        safe = symbol.replace("^", "_idx_").replace("=", "_eq_").replace("/", "_")
        return self.directory / f"{safe}.csv"

    def load(self, symbol: str) -> pd.DataFrame | None:
        p = self._path(symbol)
        if not p.exists():
            return None
        try:
            return _clean(pd.read_csv(p))
        except Exception:  # noqa: BLE001
            return None

    def save(self, symbol: str, df: pd.DataFrame) -> None:
        df = _clean(df)
        df.to_csv(self._path(symbol), float_format="%.6f")

    def merge(self, symbol: str, new: pd.DataFrame) -> pd.DataFrame:
        old = self.load(symbol)
        if old is None or old.empty:
            merged = _clean(new)
        else:
            merged = _clean(pd.concat([old, new]))
        self.save(symbol, merged)
        return merged


# ------------------------------------------------------------------------- update
def update_prices(settings: Settings, symbols: list[str], scales: dict[str, float] | None = None,
                  source: PriceSource | None = None, fallback: PriceSource | None = None,
                  today: date | None = None) -> tuple[dict[str, pd.DataFrame], dict[str, str], list[str]]:
    """Cache aktualisieren und alle Kursreihen zurückgeben.

    Returns: (frames, failed, notes)
    """
    today = today or date.today()
    scales = scales or {}
    cache = PriceCache(settings.cache_dir)
    source = source or build_source(settings)
    history_days = int(settings.get("data.history_days", 420))
    max_stale = int(settings.get("data.max_stale_days", 5))

    frames: dict[str, pd.DataFrame] = {}
    need_full: list[str] = []
    need_incr: list[str] = []
    for s in symbols:
        cached = cache.load(s)
        if cached is None or cached.empty or len(cached) < 30 or _stale_days(cached, today) > 60:
            need_full.append(s)          # neu, zu kurz oder sehr alt: komplett laden
        else:
            frames[s] = cached
            if _stale_days(cached, today) > 0:
                need_incr.append(s)

    notes: list[str] = []
    failed: dict[str, str] = {}

    def _apply(result: FetchResult, scale_needed: bool) -> None:
        for s, df in result.frames.items():
            if scale_needed and scales.get(s, 1.0) != 1.0:
                df = df.copy()
                df[["open", "high", "low", "close"]] *= scales[s]
            frames[s] = cache.merge(s, df)
        failed.update(result.failed)
        notes.extend(result.notes)

    if need_full:
        start = today - timedelta(days=int(history_days * 1.5))
        log.info("Vollständiger Download für %d Symbole ab %s (%s)", len(need_full), start, source.name)
        _apply(source.fetch(need_full, start, today), scale_needed=True)
    if need_incr:
        start = min(frames[s].index[-1].date() for s in need_incr) - timedelta(days=7)
        log.info("Inkrementelles Update für %d Symbole ab %s (%s)", len(need_incr), start, source.name)
        _apply(source.fetch(need_incr, start, today), scale_needed=True)

    # Fallback für gescheiterte Symbole
    if failed and fallback is not None:
        retry = list(failed.keys())
        log.info("Fallback %s für %d Symbole", fallback.name, len(retry))
        fb = fallback.fetch(retry, today - timedelta(days=int(history_days * 1.5)), today)
        for s in fb.frames:
            failed.pop(s, None)
        _apply(fb, scale_needed=True)

    # Veraltete Reihen kennzeichnen
    stale = [s for s, df in frames.items() if _stale_days(df, today) > max_stale]
    if stale:
        notes.append(f"{len(stale)} Kursreihen älter als {max_stale} Tage (z. B. {', '.join(stale[:5])})")
    return frames, failed, notes

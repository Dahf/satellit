"""Regime-Ampel USA (uptrend-analyzer + market-breadth-analyzer) und Europa (eigener Proxy).

Zustände: GREEN > YELLOW > RED. Hysterese: Herabstufung sofort, Heraufstufung erst,
wenn die Bedingung `hysteresis_weeks` Wochen in Folge erfüllt ist.
"""

from __future__ import annotations

import csv
import glob
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import indicators as ind
from .config import Settings

log = logging.getLogger(__name__)

STATES = ["RED", "YELLOW", "GREEN"]
RANK = {s: i for i, s in enumerate(STATES)}
LABEL = {"GREEN": "GRÜN", "YELLOW": "GELB", "RED": "ROT", None: "UNBEKANNT"}


@dataclass
class RegimeReading:
    date: str
    region: str
    raw: str | None
    effective: str | None
    uptrend: float | None = None
    breadth: float | None = None
    p200: float | None = None
    p50: float | None = None
    idx_above: bool | None = None
    note: str = ""

    @property
    def label(self) -> str:
        return LABEL.get(self.effective, "UNBEKANNT")


# ------------------------------------------------------------------ US scripts
def _newest(pattern: str) -> str | None:
    # Die Skills legen neben dem Report eine fortlaufende *_history.json ins
    # selbe Verzeichnis. Die ist eine Liste, kein Report — nie mitzählen.
    files = [f for f in glob.glob(pattern) if not os.path.basename(f).endswith("_history.json")]
    return max(files, key=os.path.getmtime) if files else None


def _composite_score(path: str) -> float | None:
    """composite.composite_score aus einem Skill-Report. None, wenn die Datei nicht passt."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return float(data["composite"]["composite_score"])
    except (OSError, ValueError, TypeError, KeyError) as exc:
        log.warning("Report %s nicht verwertbar: %s", path, exc)
        return None


def _run_script(script: Path, args: list[str], timeout: int = 300) -> tuple[bool, str]:
    cmd = [sys.executable, str(script), *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(script.parent))
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        return False, " | ".join(tail)
    return True, proc.stdout


def run_us_scores(settings: Settings) -> tuple[float | None, float | None, list[str]]:
    """Composite-Scores der beiden Skills. None, wenn ein Skill nicht läuft."""
    notes: list[str] = []
    skills = settings.vendor_skills_dir
    out_up = settings.regime_dir / "uptrend"
    out_br = settings.regime_dir / "breadth"
    out_up.mkdir(parents=True, exist_ok=True)
    out_br.mkdir(parents=True, exist_ok=True)

    uptrend = breadth = None
    ok, msg = _run_script(skills / "uptrend-analyzer" / "scripts" / "uptrend_analyzer.py", ["--output-dir", str(out_up)])
    if ok:
        f = _newest(str(out_up / "uptrend_analysis_*.json"))
        uptrend = _composite_score(f) if f else None
        if uptrend is None:
            notes.append("uptrend-analyzer: kein verwertbarer Report")
    else:
        notes.append(f"uptrend-analyzer fehlgeschlagen: {msg}")

    ok, msg = _run_script(skills / "market-breadth-analyzer" / "scripts" / "market_breadth_analyzer.py",
                          ["--output-dir", str(out_br)])
    if ok:
        f = _newest(str(out_br / "market_breadth_*.json"))
        breadth = _composite_score(f) if f else None
        if breadth is None:
            notes.append("market-breadth-analyzer: kein verwertbarer Report")
    else:
        notes.append(f"market-breadth-analyzer fehlgeschlagen: {msg}")
    return uptrend, breadth, notes


# ------------------------------------------------------------------ raw states
def us_raw_state(uptrend: float | None, breadth: float | None, cfg: dict) -> str | None:
    if uptrend is None or not np.isfinite(uptrend):
        return None
    if uptrend >= float(cfg.get("green_min", 60)):
        state = "GREEN"
    elif uptrend >= float(cfg.get("yellow_min", 40)):
        state = "YELLOW"
    else:
        state = "RED"
    if state == "GREEN" and breadth is not None and np.isfinite(breadth) and breadth < float(cfg.get("veto_below", 40)):
        state = "YELLOW"
    return state


def eu_raw_state(p200: float | None, p50: float | None, idx_above: bool | None, cfg: dict) -> str | None:
    if p200 is None or not np.isfinite(p200):
        return None
    if p200 < float(cfg.get("red_p200", 0.40)):
        return "RED"
    if idx_above is False and p50 is not None and p50 < float(cfg.get("red_p50", 0.40)):
        return "RED"
    if p200 >= float(cfg.get("green_p200", 0.55)) and idx_above is True:
        return "GREEN"
    return "YELLOW"


def eu_breadth(frames: dict[str, pd.DataFrame], eu_symbols: list[str], index_symbol: str | None,
               as_of: date, sma_fast: int = 50, sma_slow: int = 200) -> tuple[float | None, float | None, bool | None, int]:
    above200 = above50 = counted = 0
    for s in eu_symbols:
        df = frames.get(s)
        if df is None or len(df) < sma_slow:
            continue
        df = df[df.index.date <= as_of]
        if len(df) < sma_slow:
            continue
        close = df["close"]
        last = close.iloc[-1]
        counted += 1
        if last > ind.sma(close, sma_slow).iloc[-1]:
            above200 += 1
        if last > ind.sma(close, sma_fast).iloc[-1]:
            above50 += 1
    p200 = above200 / counted if counted else None
    p50 = above50 / counted if counted else None
    idx_above: bool | None = None
    if index_symbol and index_symbol in frames and len(frames[index_symbol]) >= sma_slow:
        idf = frames[index_symbol]
        idf = idf[idf.index.date <= as_of]
        if len(idf) >= sma_slow:
            idx_above = bool(idf["close"].iloc[-1] > ind.sma(idf["close"], sma_slow).iloc[-1])
    return p200, p50, idx_above, counted


# ------------------------------------------------------------------ hysteresis
def apply_hysteresis(raw_history: list[str | None], previous_effective: str | None, weeks: int) -> str | None:
    """raw_history: ältere -> neuere Rohzustände inkl. aktuellem. Unbekannt (None) zählt wie ROT."""
    hist = [r if r in RANK else "RED" for r in raw_history]
    if not hist:
        return previous_effective
    raw = hist[-1]
    if previous_effective not in RANK:
        # Kein Vorzustand (erster Lauf): erst hochstufen, wenn `weeks` Messungen vorliegen;
        # dann gilt der schwächste Zustand dieser Wochen. Vorher konservativ ROT.
        recent = hist[-weeks:]
        if len(recent) < weeks:
            return "RED"
        return min(recent, key=lambda s: RANK[s])
    if RANK[raw] <= RANK[previous_effective]:
        return raw                       # Herabstufung (oder gleich) sofort
    recent = hist[-weeks:]
    if len(recent) >= weeks and all(RANK[s] >= RANK[raw] for s in recent):
        return raw                       # Heraufstufung nach `weeks` bestätigten Wochen
    return previous_effective


# ------------------------------------------------------------------ history
HISTORY_FIELDS = ["date", "region", "raw", "effective", "uptrend", "breadth", "p200", "p50", "idx_above", "note"]


def load_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def save_history(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HISTORY_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in HISTORY_FIELDS})


def _region_rows(history: list[dict], region: str) -> list[dict]:
    return sorted([r for r in history if r.get("region") == region], key=lambda r: r["date"])


def evaluate_region(settings: Settings, region: str, as_of: date, raw: str | None, extra: dict) -> RegimeReading:
    """Rohzustand mit Historie verrechnen, Historie fortschreiben, Ergebnis zurückgeben."""
    hist_path = settings.regime_dir / "ampel_history.csv"
    history = load_history(hist_path)
    rows = [r for r in _region_rows(history, region) if r["date"] != as_of.isoformat()]
    prev_eff = rows[-1]["effective"] if rows else None
    prev_eff = prev_eff if prev_eff in RANK else None
    weeks = int(settings.get(f"regime.{region.lower()}.hysteresis_weeks", 2))
    raw_hist = [r["raw"] or None for r in rows[-(weeks - 1):]] + [raw] if weeks > 1 else [raw]
    effective = apply_hysteresis(raw_hist, prev_eff, weeks)
    note = extra.pop("note", "")
    if raw is None:
        note = (note + "; " if note else "") + "Rohzustand unbekannt -> wie ROT behandelt"
    if prev_eff is None and len(rows) + 1 < weeks:
        note = (note + "; " if note else "") + f"Hysterese-Aufbau: Lauf {len(rows) + 1}/{weeks}, Freigabe frühestens nächste Woche"
    reading = RegimeReading(date=as_of.isoformat(), region=region, raw=raw, effective=effective, note=note, **extra)
    others = [r for r in history if not (r.get("region") == region and r.get("date") == as_of.isoformat())]
    others.append({k: v for k, v in asdict(reading).items() if k in HISTORY_FIELDS})
    save_history(hist_path, sorted(others, key=lambda r: (r["date"], r["region"])))
    return reading


def last_known(settings: Settings, region: str) -> dict | None:
    rows = _region_rows(load_history(settings.regime_dir / "ampel_history.csv"), region)
    return rows[-1] if rows else None

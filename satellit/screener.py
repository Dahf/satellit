"""Screener: Trendfilter, relative Stärke, Ausbruch, Liquiditäts-/Preis-/Volatilitätsfilter.

Ergebnis ist eine Tabelle über alle bewerteten Titel mit Kennzahlen und Flags;
die Auswahl der tatsächlichen Einstiege (Ampel, Sektor-/Positionslimits) macht `pipeline`.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from . import indicators as ind
from .config import Settings
from .fx import FxTable
from .universe import Constituent

log = logging.getLogger(__name__)

RESULT_COLUMNS = [
    "region", "symbol", "isin", "name", "sector", "currency", "last_date", "close", "close_eur",
    "sma50", "sma200", "trend_ok", "rs_score", "rs_rank_pct", "rs_top", "weekly_close",
    "breakout_level", "extension", "breakout", "atr", "atr_pct", "initial_stop", "avg_turnover_eur",
    "liquidity_ok", "vol_ok", "price_ok", "target_value_eur", "candidate", "watchlist", "reason",
]


@dataclass
class ScreenerContext:
    satellite_equity_eur: float | None      # None -> Preisfilter wird übersprungen
    risk_pct: float                         # effektives Risiko je Trade in %
    as_of: date


def evaluate_symbol(c: Constituent, df: pd.DataFrame, settings: Settings, fx: FxTable,
                    ctx: ScreenerContext) -> dict:
    row: dict = {k: np.nan for k in RESULT_COLUMNS}
    row.update({"region": c.region, "symbol": c.symbol, "isin": c.isin, "name": c.name,
                "sector": c.sector or "Unknown", "currency": c.currency, "trend_ok": False,
                "rs_top": False, "breakout": False, "liquidity_ok": False, "vol_ok": False,
                "price_ok": True, "candidate": False, "watchlist": False, "reason": ""})
    min_hist = int(settings.get("universe.min_history_days", 260))
    if df is None or len(df) < min_hist:
        row["reason"] = f"zu wenig Historie ({0 if df is None else len(df)} < {min_hist})"
        return row
    df = df[df.index.date <= ctx.as_of]
    if len(df) < min_hist:
        row["reason"] = "zu wenig Historie bis Stichtag"
        return row

    close = df["close"]
    fast = int(settings.get("signal.sma_fast", 50))
    slow = int(settings.get("signal.sma_slow", 200))
    sma_f = ind.sma(close, fast).iloc[-1]
    sma_s = ind.sma(close, slow).iloc[-1]
    last = float(close.iloc[-1])
    row["last_date"] = df.index[-1].date().isoformat()
    row["close"] = last
    row["close_eur"] = fx.to_eur(last, c.currency)
    row["sma50"], row["sma200"] = float(sma_f), float(sma_s)
    row["trend_ok"] = bool(np.isfinite(sma_f) and np.isfinite(sma_s) and last > sma_s and sma_f > sma_s)

    rs = ind.rs_score(close, list(settings.get("signal.rs_lookbacks", [126, 252])),
                      int(settings.get("signal.rs_skip", 21))).iloc[-1]
    row["rs_score"] = float(rs) if np.isfinite(rs) else np.nan

    weekly = ind.weekly_closes(df)
    weeks = int(settings.get("signal.breakout_weeks", 20))
    level = ind.breakout_level(weekly, weeks)
    wclose = float(weekly.iloc[-1]) if len(weekly) else np.nan
    row["weekly_close"], row["breakout_level"] = wclose, level
    if np.isfinite(level) and level > 0:
        ext = wclose / level - 1.0
        row["extension"] = ext
        max_ext = float(settings.get("signal.max_extension", 0.05))
        row["breakout"] = bool(ext >= 0.0 and ext <= max_ext)
        below = float(settings.get("signal.watchlist_below_breakout", 0.03))
        row["watchlist"] = bool(-below <= ext < 0.0)

    atr_n = int(settings.get("risk.atr_period", 20))
    a = ind.atr(df, atr_n).iloc[-1]
    row["atr"] = float(a) if np.isfinite(a) else np.nan
    row["atr_pct"] = float(a / last) if np.isfinite(a) and last > 0 else np.nan
    mult = float(settings.get("risk.atr_stop_mult", 3.0))
    row["initial_stop"] = float(last - mult * a) if np.isfinite(a) else np.nan
    row["vol_ok"] = bool(np.isfinite(row["atr_pct"]) and row["atr_pct"] <= float(settings.get("universe.max_atr_pct", 0.06)))

    turnover = ind.avg_turnover(df, 20).iloc[-1]
    turnover_eur = fx.to_eur(float(turnover), c.currency) if np.isfinite(turnover) else np.nan
    row["avg_turnover_eur"] = turnover_eur
    min_turn = fx.to_eur(float(settings.get("universe.min_avg_turnover", 5_000_000)), "EUR")
    row["liquidity_ok"] = bool(np.isfinite(turnover_eur) and turnover_eur >= min_turn)

    # Zielposition (EUR) aus Risiko und Stopabstand, gedeckelt auf max_position_pct
    if ctx.satellite_equity_eur and np.isfinite(row["initial_stop"]) and last > row["initial_stop"]:
        risk_eur = ctx.satellite_equity_eur * ctx.risk_pct / 100.0
        stop_dist_eur = fx.to_eur(last - row["initial_stop"], c.currency)
        shares = math.floor(risk_eur / stop_dist_eur) if stop_dist_eur > 0 else 0
        max_value = ctx.satellite_equity_eur * float(settings.get("risk.max_position_pct", 25)) / 100.0
        target = min(shares * row["close_eur"], max_value)
        row["target_value_eur"] = target
        max_price_pct = float(settings.get("universe.max_price_pct_of_target", 0.40))
        row["price_ok"] = bool(target > 0 and row["close_eur"] <= max_price_pct * target)
    return row


def run_screener(constituents: list[Constituent], frames: dict[str, pd.DataFrame], settings: Settings,
                 fx: FxTable, ctx: ScreenerContext) -> pd.DataFrame:
    rows = [evaluate_symbol(c, frames.get(c.symbol), settings, fx, ctx) for c in constituents]
    table = pd.DataFrame(rows, columns=RESULT_COLUMNS)
    if table.empty:
        return table

    # RS-Rang je Region über alle Titel mit gültigem Score (1.0 = stärkster)
    top_frac = float(settings.get("signal.rs_top_fraction", 0.10))
    table["rs_rank_pct"] = table.groupby("region")["rs_score"].rank(ascending=False, pct=True, method="min")
    table["rs_top"] = table["rs_rank_pct"] <= top_frac

    table["candidate"] = (table["trend_ok"] & table["rs_top"] & table["breakout"] & table["liquidity_ok"]
                          & table["vol_ok"] & table["price_ok"])
    table["watchlist"] = table["watchlist"] & table["trend_ok"] & table["rs_top"] & table["liquidity_ok"] & table["vol_ok"]

    def _why(r) -> str:
        if r["candidate"]:
            return "Kandidat"
        if r["reason"]:
            return r["reason"]
        bits = []
        if not r["trend_ok"]:
            bits.append("Trend")
        if not r["rs_top"]:
            bits.append("RS")
        if not r["breakout"]:
            bits.append("kein Ausbruch" if not (isinstance(r["extension"], float) and r["extension"] > 0) else "zu weit gelaufen")
        if not r["liquidity_ok"]:
            bits.append("Liquidität")
        if not r["vol_ok"]:
            bits.append("Volatilität")
        if not r["price_ok"]:
            bits.append("Stückpreis")
        return ", ".join(bits)

    table["reason"] = table.apply(_why, axis=1)
    table = table.sort_values(["candidate", "rs_score"], ascending=[False, False]).reset_index(drop=True)
    log.info("Screener: %d Titel, %d Kandidaten, %d Watchlist", len(table), int(table["candidate"].sum()),
             int(table["watchlist"].sum()))
    return table

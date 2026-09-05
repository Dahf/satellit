"""Technische Kennzahlen auf Tages- und Wochenbasis (reines pandas)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=n).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """Average True Range als einfacher Mittelwert der True Range über n Tage."""
    return true_range(df).rolling(n, min_periods=n).mean()


def momentum(close: pd.Series, lookback: int, skip: int) -> pd.Series:
    """Rendite von t-lookback bis t-skip (z. B. 12-1-Momentum: lookback=252, skip=21)."""
    return close.shift(skip) / close.shift(lookback) - 1.0


def rs_score(close: pd.Series, lookbacks: list[int], skip: int) -> pd.Series:
    parts = [momentum(close, lb, skip) for lb in lookbacks]
    return pd.concat(parts, axis=1).mean(axis=1)


def weekly_closes(df: pd.DataFrame) -> pd.Series:
    """Wochenschlusskurse (Freitag). Die letzte Woche kann unvollständig sein — das ist gewollt,
    weil der Lauf am Samstag den Freitagsschluss als Wochenschluss verwendet."""
    return df["close"].resample("W-FRI").last().dropna()


def avg_turnover(df: pd.DataFrame, n: int = 20) -> pd.Series:
    return (df["close"] * df["volume"]).rolling(n, min_periods=n).mean()


def breakout_level(weekly: pd.Series, weeks: int) -> float:
    """Höchster Wochenschluss der `weeks` vorangegangenen Wochen (aktuelle Woche ausgenommen)."""
    if len(weekly) < weeks + 1:
        return float("nan")
    return float(weekly.iloc[-(weeks + 1):-1].max())


def drawdown(equity: pd.Series) -> pd.Series:
    peak = equity.cummax()
    return equity / peak - 1.0


def safe_float(x) -> float:
    try:
        v = float(x)
        return v if np.isfinite(v) else float("nan")
    except (TypeError, ValueError):
        return float("nan")

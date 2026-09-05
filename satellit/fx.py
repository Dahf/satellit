"""Wechselkurse nach EUR — für Umsatzfilter, Positionsgrößen und Berichte."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from .data import PriceSource

log = logging.getLogger(__name__)

# Yahoo-Symbole: EURUSD=X = USD je EUR
FX_SYMBOLS = {"USD": "EURUSD=X", "GBP": "EURGBP=X", "CHF": "EURCHF=X", "SEK": "EURSEK=X",
              "DKK": "EURDKK=X", "NOK": "EURNOK=X", "PLN": "EURPLN=X", "CZK": "EURCZK=X",
              "HUF": "EURHUF=X", "CAD": "EURCAD=X"}

# Notfall-Näherungen (EUR je Einheit Fremdwährung), falls kein Kurs geladen werden kann.
FALLBACK_TO_EUR = {"EUR": 1.0, "USD": 0.86, "GBP": 1.16, "CHF": 1.07, "SEK": 0.090, "DKK": 0.134,
                   "NOK": 0.086, "PLN": 0.235, "CZK": 0.041, "HUF": 0.0025, "CAD": 0.63, "GBX": 0.0116}


class FxTable:
    def __init__(self, rates_to_eur: dict[str, float], source_note: str = "fallback"):
        self.rates = dict(FALLBACK_TO_EUR)
        self.rates.update({k: v for k, v in rates_to_eur.items() if v and v > 0})
        self.note = source_note

    def to_eur(self, amount: float, currency: str) -> float:
        cur = (currency or "EUR").upper()
        if cur == "GBX":
            return amount * self.rates.get("GBP", FALLBACK_TO_EUR["GBP"]) / 100.0
        rate = self.rates.get(cur)
        if rate is None:
            log.warning("Unbekannte Währung %s — 1:1 zu EUR angenommen", cur)
            return amount
        return amount * rate

    def from_eur(self, amount_eur: float, currency: str) -> float:
        cur = (currency or "EUR").upper()
        rate = self.rates.get(cur, 1.0)
        return amount_eur / rate if rate else amount_eur


def load_fx(source: PriceSource, currencies: set[str], today: date | None = None) -> FxTable:
    """Aktuelle Kurse per Kursquelle laden; bei Fehlern Fallback-Näherungen."""
    needed = {c for c in currencies if c in FX_SYMBOLS}
    if not needed:
        return FxTable({}, "nur EUR")
    symbols = [FX_SYMBOLS[c] for c in sorted(needed)]
    today = today or date.today()
    try:
        res = source.fetch(symbols, start=today - pd.Timedelta(days=14).to_pytimedelta(), end=today)
    except Exception as exc:  # noqa: BLE001
        log.warning("FX-Kurse nicht ladbar (%s) — Fallback", exc)
        return FxTable({}, f"fallback ({exc})")
    rates: dict[str, float] = {}
    for cur in needed:
        df = res.frames.get(FX_SYMBOLS[cur])
        if df is not None and not df.empty:
            per_eur = float(df["close"].iloc[-1])      # Fremdwährung je EUR
            if per_eur > 0:
                rates[cur] = 1.0 / per_eur
    missing = needed - set(rates)
    note = "live" if not missing else f"live, Fallback für {', '.join(sorted(missing))}"
    return FxTable(rates, note)

"""Wochenlauf: Universum -> Kurse -> Ampel -> Screener -> Positionen/Stops -> Vorschläge -> Bericht."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import indicators as ind
from . import journal, regime
from .config import Settings
from .data import PriceSource, SyntheticSource, build_source, update_prices
from .fx import FxTable, load_fx
from .screener import ScreenerContext, run_screener
from .universe import Constituent, load_universe, save_universe_snapshot

log = logging.getLogger(__name__)


@dataclass
class PositionView:
    thesis_id: str
    symbol: str
    name: str
    region: str
    currency: str
    sector: str
    shares: float
    entry: float
    entry_date: str
    stop: float
    close: float | None
    week_low: float | None
    new_stop: float | None
    stop_raised: bool
    soft_exit: bool
    hard_stop_hit: bool
    pnl_pct: float | None
    open_risk_eur: float
    note: str = ""


@dataclass
class Proposal:
    symbol: str
    isin: str
    name: str
    region: str
    currency: str
    sector: str
    close: float
    breakout_level: float
    initial_stop: float
    atr: float
    rs_rank_pct: float
    shares: int
    value_eur: float
    risk_eur: float
    risk_pct: float
    limit_price: float
    ampel: str


@dataclass
class WeeklyResult:
    as_of: date
    readings: dict[str, regime.RegimeReading]
    account: journal.Account
    kill_active: bool
    kill_reason: str
    dry_run: bool
    risk_pct_by_region: dict[str, float]
    table: pd.DataFrame
    proposals: list[Proposal]
    skipped: list[str]
    positions: list[PositionView]
    open_risk_pct: float | None
    universe_size: dict[str, int]
    universe_warnings: list[str]
    data_failed: dict[str, str]
    data_notes: list[str]
    fx_note: str
    regime_notes: list[str]
    digest_md: str | None = None
    report_path: str | None = None
    demo: bool = False


# ---------------------------------------------------------------------- helpers
def last_friday(today: date | None = None) -> date:
    today = today or date.today()
    offset = (today.weekday() - 4) % 7
    return today - timedelta(days=offset)


def demo_universe(n_us: int = 60, n_eu: int = 60) -> list[Constituent]:
    sectors = ["Informationstechnologie", "Industrie", "Gesundheit", "Finanzen", "Konsum", "Energie", "Grundstoffe"]
    cons = []
    for i in range(n_us):
        cons.append(Constituent("US", f"US{i:04d}0001", f"DEMOU{i}", f"Demo US Corp {i}", sectors[i % len(sectors)],
                                "NASDAQ", "USD", 0.2, f"DEMOU{i}", 1.0))
    for i in range(n_eu):
        cons.append(Constituent("EU", f"DE{i:04d}0002", f"DEMOE{i}", f"Demo EU AG {i}", sectors[(i + 2) % len(sectors)],
                                "Xetra", "EUR", 0.15, f"DEMOE{i}.DE", 1.0))
    return cons


# ---------------------------------------------------------------------- positions
def review_positions(settings: Settings, frames: dict[str, pd.DataFrame], fx: FxTable, as_of: date,
                     equity_eur: float | None) -> list[PositionView]:
    out: list[PositionView] = []
    mult = float(settings.get("risk.atr_stop_mult", 3.0))
    atr_n = int(settings.get("risk.atr_period", 20))
    soft_weeks = int(settings.get("risk.soft_exit_weeks", 10))
    for t in journal.open_positions(settings):
        prov = journal.provenance(t)
        symbol = prov.get("symbol") or t["ticker"]
        currency = prov.get("currency") or "EUR"
        region = prov.get("region") or ("US" if "." not in symbol else "EU")
        pos = t.get("position") or {}
        shares = float(pos.get("shares_remaining") or pos.get("shares") or 0)
        entry = float((t.get("entry") or {}).get("actual_price") or prov.get("planned_entry") or 0)
        entry_date = str((t.get("entry") or {}).get("actual_date") or "")[:10]
        stop = float((t.get("exit") or {}).get("stop_loss") or 0)
        sector = ((t.get("market_context") or {}).get("sector")) or "Unknown"
        df = frames.get(symbol)
        view = PositionView(t["thesis_id"], symbol, t.get("thesis_statement", "")[:40], region, currency, sector,
                            shares, entry, entry_date, stop, None, None, None, False, False, False, None, 0.0)
        if df is None or df.empty:
            view.note = "keine Kursdaten"
            out.append(view)
            continue
        df = df[df.index.date <= as_of]
        if df.empty:
            view.note = "keine Kursdaten bis Stichtag"
            out.append(view)
            continue
        close = float(df["close"].iloc[-1])
        week = df[df.index.date > as_of - timedelta(days=7)]
        week_low = float(week["low"].min()) if not week.empty else None
        a = ind.atr(df, atr_n).iloc[-1]
        new_stop = stop
        if np.isfinite(a):
            new_stop = max(stop, close - mult * float(a))
        weekly = ind.weekly_closes(df)
        soft = False
        if len(weekly) >= soft_weeks:
            soft = bool(weekly.iloc[-1] < weekly.rolling(soft_weeks).mean().iloc[-1])
        risk_eur = max(0.0, fx.to_eur((close - new_stop) * shares, currency))
        view.close, view.week_low, view.new_stop = close, week_low, float(new_stop)
        view.stop_raised = bool(new_stop > stop + 1e-9)
        view.soft_exit = soft
        view.hard_stop_hit = bool(week_low is not None and stop > 0 and week_low <= stop)
        view.pnl_pct = (close / entry - 1.0) if entry else None
        view.open_risk_eur = risk_eur
        out.append(view)
    return out


# ---------------------------------------------------------------------- selection
def select_entries(settings: Settings, table: pd.DataFrame, readings: dict[str, regime.RegimeReading],
                   positions: list[PositionView], account: journal.Account, fx: FxTable,
                   risk_pct_by_region: dict[str, float], blocked: bool) -> tuple[list[Proposal], list[str]]:
    proposals: list[Proposal] = []
    skipped: list[str] = []
    if table.empty:
        return proposals, skipped
    cands = table[table["candidate"]].sort_values("rs_score", ascending=False)
    if cands.empty:
        return proposals, skipped
    equity = account.satellite_equity_eur
    if not equity:
        skipped.append("Kein Satelliten-Kapital hinterlegt (`satellit account set --equity ...`) — keine Positionsgrößen")
        return proposals, skipped
    if blocked:
        skipped.append("Keine neuen Einstiege (Kill-Switch aktiv)")
        return proposals, skipped

    max_positions = int(settings.get("risk.max_positions", 5))
    max_sector = int(settings.get("risk.max_per_sector", 2))
    max_open_risk = float(settings.get("risk.max_open_risk_pct", 5.0)) / 100.0 * equity
    max_value = float(settings.get("risk.max_position_pct", 25)) / 100.0 * equity
    limits = settings.get("signal.max_new_entries", {"GREEN": 2, "YELLOW": 1, "RED": 0})

    n_open = len(positions)
    sector_count: dict[str, int] = {}
    for p in positions:
        sector_count[p.sector] = sector_count.get(p.sector, 0) + 1
    open_risk = sum(p.open_risk_eur for p in positions)
    held = {p.symbol for p in positions}
    per_region_left = {r: int(limits.get(rd.effective or "RED", 0)) for r, rd in readings.items()}

    for _, r in cands.iterrows():
        region = r["region"]
        state = readings[region].effective if region in readings else None
        if r["symbol"] in held:
            continue
        if per_region_left.get(region, 0) <= 0:
            skipped.append(f"{r['symbol']}: Ampel {region} = {regime.LABEL.get(state)} — Limit neue Einstiege erreicht")
            continue
        if n_open + len(proposals) >= max_positions:
            skipped.append(f"{r['symbol']}: max. {max_positions} Positionen erreicht")
            continue
        if sector_count.get(r["sector"], 0) >= max_sector:
            skipped.append(f"{r['symbol']}: Sektor {r['sector']} bereits {max_sector}x belegt")
            continue
        risk_pct = risk_pct_by_region.get(region, float(settings.get("risk.risk_pct", 1.0)))
        risk_eur = equity * risk_pct / 100.0
        stop_dist_eur = fx.to_eur(float(r["close"] - r["initial_stop"]), r["currency"])
        if not (stop_dist_eur > 0):
            skipped.append(f"{r['symbol']}: ungültiger Stopabstand")
            continue
        shares = math.floor(risk_eur / stop_dist_eur)
        price_eur = fx.to_eur(float(r["close"]), r["currency"])
        shares = min(shares, math.floor(max_value / price_eur)) if price_eur > 0 else 0
        if shares < 1:
            skipped.append(f"{r['symbol']}: Positionsgröße < 1 Stück (Stückpreis {price_eur:.0f} EUR)")
            continue
        new_risk = shares * stop_dist_eur
        if open_risk + new_risk > max_open_risk:
            skipped.append(f"{r['symbol']}: offenes Gesamtrisiko würde {max_open_risk:.0f} EUR überschreiten")
            continue
        proposals.append(Proposal(
            symbol=r["symbol"], isin=r["isin"], name=r["name"], region=region, currency=r["currency"],
            sector=r["sector"], close=float(r["close"]), breakout_level=float(r["breakout_level"]),
            initial_stop=float(r["initial_stop"]), atr=float(r["atr"]), rs_rank_pct=float(r["rs_rank_pct"]),
            shares=int(shares), value_eur=shares * price_eur, risk_eur=new_risk, risk_pct=risk_pct,
            limit_price=float(r["close"]) * 1.01, ampel=regime.LABEL.get(state, "UNBEKANNT"),
        ))
        per_region_left[region] -= 1
        sector_count[r["sector"]] = sector_count.get(r["sector"], 0) + 1
        open_risk += new_risk
    return proposals, skipped


# ---------------------------------------------------------------------- main run
def run_weekly(settings: Settings, as_of: date | None = None, source: PriceSource | None = None,
               fallback: PriceSource | None = None, demo: bool = False, skip_us_scripts: bool = False,
               us_scores: tuple[float | None, float | None] | None = None) -> WeeklyResult:
    settings.ensure_dirs()
    today = date.today()
    as_of = as_of or last_friday(today)
    log.info("Wochenlauf, Stichtag %s (demo=%s)", as_of, demo)

    # 1. Universum
    if demo:
        cons, uni_warn = demo_universe(), ["DEMO-Modus: synthetisches Universum und synthetische Kurse"]
        source = source or SyntheticSource(days=int(settings.get("data.history_days", 420)))
    else:
        cons, uni_warn = load_universe(settings)
        source = source or build_source(settings)
        if fallback is None and settings.get("data.fallback") and settings.get("data.fallback") != settings.get("data.primary"):
            try:
                fallback = build_source(settings, settings.get("data.fallback"))
            except ValueError:
                fallback = None
    save_universe_snapshot(cons, settings.universe_dir / "universe_snapshot.csv")
    universe_size = {}
    for c in cons:
        universe_size[c.region] = universe_size.get(c.region, 0) + 1

    # 2. Kurse (Konstituenten + offene Positionen + Index-Proxys)
    symbols = [c.symbol for c in cons]
    scales = {c.symbol: c.price_scale for c in cons}
    for t in journal.open_positions(settings):
        s = journal.provenance(t).get("symbol") or t["ticker"]
        if s not in scales:
            symbols.append(s)
            scales[s] = 1.0
    index_symbols = {}
    for region, cfg in settings.get("universe.regions", {}).items():
        if cfg.get("index_symbol") and not demo:
            index_symbols[region] = cfg["index_symbol"]
            if cfg["index_symbol"] not in scales:
                symbols.append(cfg["index_symbol"])
                scales[cfg["index_symbol"]] = 1.0
    frames, failed, notes = update_prices(settings, symbols, scales, source=source, fallback=fallback, today=today)
    currencies = {c.currency for c in cons}
    fx = FxTable({}, "demo") if demo else load_fx(source, currencies, today)

    # 3. Ampel
    regime_notes: list[str] = []
    if demo:
        uptrend, breadth = us_scores or (66.0, 58.0)
    elif skip_us_scripts:
        uptrend, breadth = us_scores or (None, None)
    else:
        uptrend, breadth, regime_notes = regime.run_us_scores(settings)
    if uptrend is None:
        prev = regime.last_known(settings, "US")
        if prev and prev.get("uptrend"):
            uptrend = float(prev["uptrend"])
            breadth = float(prev["breadth"]) if prev.get("breadth") else None
            regime_notes.append(f"US-Ampel nutzt letzten bekannten Stand vom {prev['date']}")
    us_raw = regime.us_raw_state(uptrend, breadth, settings.get("regime.us", {}))
    eu_syms = [c.symbol for c in cons if c.region == "EU"]
    p200, p50, idx_above, counted = regime.eu_breadth(frames, eu_syms, index_symbols.get("EU"), as_of,
                                                      int(settings.get("signal.sma_fast", 50)),
                                                      int(settings.get("signal.sma_slow", 200)))
    if demo and idx_above is None:
        idx_above = True
    eu_raw = regime.eu_raw_state(p200, p50, idx_above, settings.get("regime.eu", {}))
    readings = {
        "US": regime.evaluate_region(settings, "US", as_of, us_raw, {"uptrend": uptrend, "breadth": breadth}),
        "EU": regime.evaluate_region(settings, "EU", as_of, eu_raw,
                                     {"p200": p200, "p50": p50, "idx_above": idx_above,
                                      "note": f"{counted} Titel bewertet" + ("" if idx_above is not None else "; Index-Proxy fehlt")}),
    }

    # 4. Konto, Kill-Switch, Risiko
    account = journal.Account.load(settings)
    kill_active, kill_reason = journal.kill_switch_status(settings, account)
    if kill_active and not account.kill_switch_active:
        account.kill_switch_active, account.kill_switch_reason = True, kill_reason
        account.save(settings)
    blocked = account.kill_switch_active
    dry_run = bool(account.dry_run_until and date.fromisoformat(account.dry_run_until) >= as_of)
    risk_by_region = {r: journal.effective_risk_pct(settings, rd.effective) for r, rd in readings.items()}

    # 5. Screener
    ctx = ScreenerContext(satellite_equity_eur=account.satellite_equity_eur,
                          risk_pct=max(risk_by_region.values()) if risk_by_region else 1.0, as_of=as_of)
    table = run_screener(cons, frames, settings, fx, ctx)
    if not table.empty:
        table.to_csv(settings.reports_dir / f"screener_{as_of.isoformat()}.csv", index=False, float_format="%.4f")

    # 6. Positionen
    positions = review_positions(settings, frames, fx, as_of, account.satellite_equity_eur)
    open_risk_pct = None
    if account.satellite_equity_eur:
        open_risk_pct = sum(p.open_risk_eur for p in positions) / account.satellite_equity_eur * 100.0

    # 7. Auswahl
    proposals, skipped = select_entries(settings, table, readings, positions, account, fx, risk_by_region, blocked)

    # 8. Digest
    digest_md = journal.run_weekly_digest(settings, as_of)

    return WeeklyResult(
        as_of=as_of, readings=readings, account=account, kill_active=blocked, kill_reason=account.kill_switch_reason,
        dry_run=dry_run, risk_pct_by_region=risk_by_region, table=table, proposals=proposals, skipped=skipped,
        positions=positions, open_risk_pct=open_risk_pct, universe_size=universe_size, universe_warnings=uni_warn,
        data_failed=failed, data_notes=notes, fx_note=fx.note, regime_notes=regime_notes, digest_md=digest_md,
        demo=demo,
    )

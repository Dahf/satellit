"""Wochenlauf: Universum -> Kurse -> Ampel -> Screener -> Positionen/Stops -> Vorschläge -> Bericht."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable

import numpy as np
import pandas as pd

from . import decisions as dec
from . import indicators as ind
from . import journal, portfolio, regime
from .config import Settings, risikoprofil
from .decisions import Decision, Kontext, SkipInfo
from .data import NullSource, PriceSource, SyntheticSource, build_source, update_prices
from .fx import FxTable, load_fx
from .screener import ScreenerContext, run_screener
from .universe import Constituent, load_universe, snapshot_aktualisieren

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
    # EUR-Sicht: bis hierher gab es je Position nur Lokalwährungskurse, also keine Antwort
    # auf "wie viel ist das in Euro" und "wie viel habe ich damit verdient".
    wert_eur: float | None = None
    einstand_eur: float | None = None
    gewinn_eur: float | None = None


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
    shares: float          # Bruchstücke möglich (risk.bruchstuecke), sonst ganzzahlig
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
    skipped: list[SkipInfo]
    positions: list[PositionView]
    open_risk_pct: float | None
    universe_size: dict[str, int]
    universe_warnings: list[str]
    universum_status: dict[str, dict]     # je Region: quelle, alter_tage, anzahl, ok
    data_failed: dict[str, str]
    data_notes: list[str]
    fx_note: str
    regime_notes: list[str]
    # Ergebnis des Entscheidungsmodells — die einzige Quelle für "was ist zu tun".
    entscheidungen: list[Decision] = field(default_factory=list)
    abgelehnt: list[Decision] = field(default_factory=list)
    fx_kurse: dict[str, float] = field(default_factory=dict)
    kern: dict = field(default_factory=dict)      # Werte, Monat, Gewinn, Band, Kauffenster
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
        view = PositionView(t["thesis_id"], symbol, _firmenname(t, symbol), region, currency, sector,
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
        view.wert_eur = fx.to_eur(close * shares, currency)
        view.einstand_eur = fx.to_eur(entry * shares, currency) if entry else None
        view.gewinn_eur = (view.wert_eur - view.einstand_eur) if view.einstand_eur is not None else None
        out.append(view)
    return out


def _kern_zusammenfassung(settings: Settings, ctx: Kontext, as_of: date) -> dict:
    """Kernzahlen für das Anzeige-Payload. Leer, solange nichts eingerichtet ist."""
    if ctx.kern_plan is None or ctx.kern_werte is None:
        return {}
    w = ctx.kern_werte
    buchungen = portfolio.lies_ledger(settings)
    return {
        "eingerichtet": True,
        "werte": {
            "gesamt_eur": w.gesamt_eur, "kern_eur": w.kern_eur, "kern_etf_eur": w.kern_etf_eur,
            "kern_aktien_eur": w.kern_aktien_eur, "satellit_eur": w.satellit_eur,
            "cash_eur": w.cash_eur, "cash_je_topf": w.cash_je_topf,
            "kern_pct": w.kern_pct, "satellit_pct": w.satellit_pct,
            "kern_aktien_cash_eur": w.kern_aktien_cash_eur,
            "nicht_bewertbar": w.nicht_bewertbar,
        },
        "monat": ctx.kern_monat,
        "gewinn": portfolio.performance(w, buchungen, as_of),
        "band": ctx.band,
        "kauffenster": ctx.kauffenster,
        "sparplan": {"tag": ctx.kern_plan.sparplan_tag, "offen": ctx.sparplan_offen,
                     "rate_eur": ctx.kern_plan.monatsrate_eur},
        "etf": ctx.kern_plan.etf,
    }


def _kern_symbole(settings: Settings) -> list[str]:
    """ETF und Kern-Aktien — sie brauchen Kurse, stehen aber nicht im Screener-Universum."""
    out: list[str] = []
    plan = portfolio.lade_plan(settings)
    if plan.etf_symbol:
        out.append(plan.etf_symbol)
    for t in journal.core_positions(settings):
        s = journal.provenance(t).get("symbol") or t.get("ticker")
        if s:
            out.append(s)
    return out


def _kern_kontext(settings: Settings, ctx: Kontext, frames: dict[str, pd.DataFrame],
                  positionen: list[PositionView], as_of: date) -> None:
    """Kern-Teil des Entscheidungskontexts füllen. Ohne eingerichteten Plan passiert nichts."""
    plan = portfolio.lade_plan(settings)
    if not plan.onboarding_erledigt:
        return
    buchungen = portfolio.lies_ledger(settings)

    kurse: dict[str, float] = {}
    for symbol in set(_kern_symbole(settings)):
        df = frames.get(symbol)
        if df is not None and not df.empty:
            reihe = df[df.index.date <= as_of]
            if not reihe.empty:
                kurse[symbol] = float(reihe["close"].iloc[-1])

    sat_wert = sum(p.wert_eur or 0.0 for p in positionen)
    werte = portfolio.bewerte(settings, plan, buchungen, kurse, satellit_positionen_eur=sat_wert)
    band = portfolio.band_pruefung(werte, settings)

    monat = as_of.strftime("%Y-%m")
    besitz = portfolio.bestaende(buchungen)
    etf_gekauft = any(b.topf == "kern_etf" for b in besitz.values())
    startbetrag = plan.startbetrag or {}
    etf_soll = float(startbetrag.get("kern_eur") or 0.0) * plan.etf_anteil
    aktien_soll = float(startbetrag.get("kern_eur") or 0.0) - etf_soll

    thesen = []
    for t in journal.core_positions(settings):
        prov = journal.provenance(t)
        symbol = prov.get("symbol") or t.get("ticker") or ""
        pos = besitz.get(f"kern_aktie:{prov.get('isin') or symbol}")
        wert = None
        if pos and symbol in kurse:
            wert = pos.stueck * kurse[symbol]
        faellig_am = ((t.get("monitoring") or {}).get("next_review_date") or "")[:10]
        faellig = bool(faellig_am and faellig_am <= as_of.isoformat())
        thesen.append((t, wert, faellig))

    letzter = (plan.depotwert_abgleich or {}).get("datum")
    abgleich_faellig = not letzter or (as_of - date.fromisoformat(letzter)).days >= 30

    ctx.kern_plan = plan
    ctx.kern_werte = werte
    ctx.band = band
    ctx.kauffenster = portfolio.kern_kauffenster(as_of, plan)
    ctx.kern_monat = portfolio.monatsausgaben(buchungen, monat, plan)
    ctx.sparplan_offen = (bool(plan.monatsrate_eur) and as_of.day >= int(plan.sparplan_tag or 1)
                          and not portfolio.sparplan_gelaufen(buchungen, monat, plan.etf_isin)
                          and etf_gekauft)
    ctx.startbetrag_offen = {
        "etf_eur": 0.0 if etf_gekauft else etf_soll,
        "aktien_eur": aktien_soll if plan.ersteinstieg_offen else 0.0,
    }
    ctx.kern_thesen = thesen
    ctx.depot_abgleich_faellig = abgleich_faellig
    # Kandidaten kommen aus dem letzten Kern-Scan, der eigenständig und selten läuft. Der
    # Wochenlauf löst ihn nicht aus: er würde je Titel Jahresabschlüsse abrufen und damit
    # Minuten kosten, um eine Frage zu beantworten, die viermal im Jahr gestellt wird.
    from . import kern_scan

    kandidaten, kopf = kern_scan.kandidaten_aus_stand(settings)
    # Nur Titel ohne bestehende These — was schon im Depot liegt, ist Bestand, kein Kandidat.
    schon_da = set()
    for these, _wert, _faellig in thesen:
        prov = (these.get("origin") or {}).get("raw_provenance") or {}
        schon_da.add(str(prov.get("symbol") or these.get("ticker") or "").upper())
    ctx.kern_kandidaten = [k for k in kandidaten if k.symbol.upper() not in schon_da]
    ctx.kern_scan_stand = kopf.get("as_of")


def _firmenname(t: dict, symbol: str) -> str:
    """Firmenname aus der These. Die Thesen beginnen mit '<Name> (<Symbol>): …'.

    Vorher standen hier die ersten 40 Zeichen des Thesensatzes — in einer Liste, die
    Titel benennt, liest sich das als abgeschnittener Satz statt als Name.
    """
    satz = str(t.get("thesis_statement") or "").strip()
    if not satz:
        return symbol
    kopf = satz.split(":", 1)[0]
    name = kopf.split(" (", 1)[0].strip()
    return name or symbol


def _wochenpunkte(df: pd.DataFrame, soft_weeks: int, anzahl: int = 60) -> list[dict]:
    """Wochenschlüsse + gleitender Schnitt für den Mini-Chart in der Begründung.

    Der Chart zeigt genau die Regel, nach der verkauft wird: Kurs gegen SMA10W.
    """
    weekly = ind.weekly_closes(df)
    if weekly.empty:
        return []
    sma = weekly.rolling(soft_weeks).mean()
    punkte = []
    for stichtag, kurs in list(weekly.items())[-anzahl:]:
        s = sma.get(stichtag)
        punkte.append({
            "d": stichtag.date().isoformat() if hasattr(stichtag, "date") else str(stichtag)[:10],
            "kurs": round(float(kurs), 4),
            "sma10w": round(float(s), 4) if s is not None and np.isfinite(s) else None,
        })
    return punkte


def mindestkapital(settings: Settings, table: pd.DataFrame, fx: FxTable, risk_pct: float,
                   equity_eur: float | None) -> float | None:
    """Wie viel Satelliten-Kapital braucht es, damit überhaupt ein Titel kaufbar wäre?

    Gibt None zurück, sobald das vorhandene Kapital reicht — die Zahl ist nur interessant,
    wenn sie eine Sperre erklärt. Sonst der kleinste Betrag, mit dem mindestens ein Titel
    des aktuellen Universums alle Größenfilter passiert.

    Ohne diese Rechnung meldet der Screener wochenlang nur ZU_TEUER, und der Grund — das
    Depot ist schlicht zu klein — steht nirgends. Geraten wird nichts: gerechnet wird gegen
    die tatsächlichen Kurse und Stopabstände des Universums.

    Zur Drei im Ganzstück-Fall: der Preisfilter verlangt Kurs <= 40 % der Zielposition. Bei
    einem Stück wäre die Zielposition genau ein Kurs, die Bedingung also nie erfüllbar; erst
    ab drei Stück geht die Ungleichung auf.
    """
    if table.empty or risk_pct <= 0:
        return None
    profil = risikoprofil(settings, equity_eur)
    max_pct = profil["max_position_pct"]
    # Titel, die nur noch an der Größe scheitern könnten — Trend, RS, Liquidität, Volatilität
    # sind Eigenschaften des Titels und ändern sich nicht dadurch, dass mehr Geld da ist.
    brauchbar = table[table["trend_ok"] & table["rs_top"] & table["liquidity_ok"] & table["vol_ok"]]
    noetig: list[float] = []
    for _, r in brauchbar.iterrows():
        close_eur = r["close_eur"]
        if not (pd.notna(close_eur) and close_eur > 0 and pd.notna(r["initial_stop"])):
            continue
        stop_dist_eur = fx.to_eur(float(r["close"] - r["initial_stop"]), r["currency"])
        if not (stop_dist_eur > 0):
            continue
        if profil["bruchstuecke"]:
            # Es genügt, die Mindestordergröße zu erreichen.
            noetig.append(profil["min_order_eur"] * 100.0 / max_pct)
        else:
            aus_risiko = 3.0 * stop_dist_eur * 100.0 / risk_pct
            aus_deckel = 3.0 * float(close_eur) * 100.0 / max_pct
            noetig.append(max(aus_risiko, aus_deckel))
    if not noetig:
        return None
    schwelle = min(noetig)
    if equity_eur and equity_eur >= schwelle:
        return None
    return round(schwelle, 2)


# ---------------------------------------------------------------------- selection
def select_entries(settings: Settings, table: pd.DataFrame, readings: dict[str, regime.RegimeReading],
                   positions: list[PositionView], account: journal.Account, fx: FxTable,
                   risk_pct_by_region: dict[str, float], blocked: bool) -> tuple[list[Proposal], list[SkipInfo]]:
    """Kandidaten in Vorschläge übersetzen.

    Ablehnungen kommen als strukturierte SkipInfo zurück, nicht als fertige Sätze — die
    Formulierung entsteht in decisions.py. Vorher wurden die Sätze hier gebaut und beim
    Schreiben des Berichts wieder weggeworfen, sodass der Nutzer nie erfuhr, warum nichts
    vorgeschlagen wurde.
    """
    proposals: list[Proposal] = []
    skipped: list[SkipInfo] = []
    if table.empty:
        return proposals, skipped
    cands = table[table["candidate"]].sort_values("rs_score", ascending=False)
    if cands.empty:
        return proposals, skipped
    equity = account.satellite_equity_eur
    if not equity:
        skipped.append(SkipInfo(symbol="", code="KEIN_KAPITAL"))
        return proposals, skipped
    if blocked:
        skipped.append(SkipInfo(symbol="", code="KILL_SWITCH"))
        return proposals, skipped

    profil = risikoprofil(settings, equity)
    max_positions = profil["max_positions"]
    max_sector = profil["max_per_sector"]
    max_open_risk = float(settings.get("risk.max_open_risk_pct", 5.0)) / 100.0 * equity
    max_value = profil["max_position_pct"] / 100.0 * equity
    limits = settings.get("signal.max_new_entries", {"GREEN": 2, "YELLOW": 1, "RED": 0})

    n_open = len(positions)
    sector_count: dict[str, int] = {}
    for p in positions:
        sector_count[p.sector] = sector_count.get(p.sector, 0) + 1
    open_risk = sum(p.open_risk_eur for p in positions)
    held = {p.symbol for p in positions}
    per_region_left = {r: int(limits.get(rd.effective or "RED", 0)) for r, rd in readings.items()}

    def _skip(r, code: str, **params) -> SkipInfo:
        return SkipInfo(symbol=r["symbol"], name=r["name"], region=r["region"], sektor=r["sector"],
                        code=code, params=params,
                        rs_rank_pct=float(r["rs_rank_pct"]) if pd.notna(r["rs_rank_pct"]) else None)

    for _, r in cands.iterrows():
        region = r["region"]
        state = readings[region].effective if region in readings else None
        if r["symbol"] in held:
            # Lief bisher wortlos ins Leere — der Nutzer sah nie, dass der Titel schon liegt.
            skipped.append(_skip(r, "BEREITS_GEHALTEN"))
            continue
        if per_region_left.get(region, 0) <= 0:
            skipped.append(_skip(r, "AMPEL_LIMIT", ampel=state, ampel_label=regime.LABEL.get(state, "UNBEKANNT"),
                                 limit=int(limits.get(state or "RED", 0))))
            continue
        if n_open + len(proposals) >= max_positions:
            skipped.append(_skip(r, "MAX_POSITIONEN", max=max_positions))
            continue
        if sector_count.get(r["sector"], 0) >= max_sector:
            skipped.append(_skip(r, "MAX_SEKTOR", max=max_sector))
            continue
        risk_pct = risk_pct_by_region.get(region, float(settings.get("risk.risk_pct", 1.0)))
        risk_eur = equity * risk_pct / 100.0
        stop_dist_eur = fx.to_eur(float(r["close"] - r["initial_stop"]), r["currency"])
        if not (stop_dist_eur > 0):
            skipped.append(_skip(r, "STOP_UNGUELTIG"))
            continue
        price_eur = fx.to_eur(float(r["close"]), r["currency"])
        shares = risk_eur / stop_dist_eur
        deckel = (max_value / price_eur) if price_eur > 0 else 0.0
        if profil["bruchstuecke"]:
            # Auf 4 Nachkommastellen, weil Broker Bruchstücke so ausweisen. Untergrenze ist
            # nicht mehr „eine ganze Aktie“, sondern die kleinste sinnvolle Order.
            shares = round(min(shares, deckel), 4)
            if shares * price_eur < profil["min_order_eur"]:
                skipped.append(_skip(r, "UNTER_MINDESTORDER", preis_eur=price_eur,
                                     wert_eur=shares * price_eur, min_eur=profil["min_order_eur"]))
                continue
        else:
            shares = math.floor(min(math.floor(shares), math.floor(deckel)))
            if shares < 1:
                skipped.append(_skip(r, "ZU_TEUER", preis_eur=price_eur))
                continue
        new_risk = shares * stop_dist_eur
        if open_risk + new_risk > max_open_risk:
            skipped.append(_skip(r, "GESAMTRISIKO", grenze_eur=max_open_risk))
            continue
        proposals.append(Proposal(
            symbol=r["symbol"], isin=r["isin"], name=r["name"], region=region, currency=r["currency"],
            sector=r["sector"], close=float(r["close"]), breakout_level=float(r["breakout_level"]),
            initial_stop=float(r["initial_stop"]), atr=float(r["atr"]), rs_rank_pct=float(r["rs_rank_pct"]),
            shares=float(shares), value_eur=shares * price_eur, risk_eur=new_risk, risk_pct=risk_pct,
            limit_price=float(r["close"]) * 1.01, ampel=regime.LABEL.get(state, "UNBEKANNT"),
        ))
        per_region_left[region] -= 1
        sector_count[r["sector"]] = sector_count.get(r["sector"], 0) + 1
        open_risk += new_risk
    return proposals, skipped


# ---------------------------------------------------------------------- main run
def run_weekly(settings: Settings, as_of: date | None = None, source: PriceSource | None = None,
               fallback: PriceSource | None = None, demo: bool = False, skip_us_scripts: bool = False,
               us_scores: tuple[float | None, float | None] | None = None,
               progress: Callable[[int, int], None] | None = None,
               offline: bool = False) -> WeeklyResult:
    """Wochenlauf. `offline=True` rechnet nur aus dem Kurs-Cache, ohne Netz und ohne
    Unterprozesse — dafür in Sekunden statt Minuten (siehe view.neu_rechnen)."""
    if offline:
        # Wirklich kein Netz: keine Kursquelle, kein Fallback (der würde sonst für jedes
        # gescheiterte Symbol einzeln anfragen — bei 1.100 Titeln minutenlang), keine
        # Unterprozesse und kein Konstituenten-Download.
        source = source or NullSource()
        fallback = None
        skip_us_scripts = True
    settings.ensure_dirs()
    today = date.today()
    as_of = as_of or last_friday(today)
    log.info("Wochenlauf, Stichtag %s (demo=%s)", as_of, demo)

    # 1. Universum
    if demo:
        cons, uni_warn = demo_universe(), ["DEMO-Modus: synthetisches Universum und synthetische Kurse"]
        uni_status = {c.region: {"quelle": "demo", "alter_tage": 0, "anzahl": 0, "ok": True} for c in cons}
        source = source or SyntheticSource(days=int(settings.get("data.history_days", 420)))
    else:
        cons, uni_warn, uni_status = load_universe(settings, offline=offline)
        source = source or build_source(settings)
        if (not offline and fallback is None and settings.get("data.fallback")
                and settings.get("data.fallback") != settings.get("data.primary")):
            try:
                fallback = build_source(settings, settings.get("data.fallback"))
            except ValueError:
                fallback = None
    if not demo and not offline:
        # Im Offline-Modus nicht schreiben: die Daten kämen aus dem Cache, und das
        # Neuschreiben würde nur das Alter des Snapshots zurücksetzen.
        snapshot_aktualisieren(cons, uni_status, settings.universe_dir / "universe_snapshot.csv")
    universe_size = {}
    for c in cons:
        universe_size[c.region] = universe_size.get(c.region, 0) + 1
    # anzahl auf den Stand nach der Dublettenbereinigung bringen — das ist die Zahl, mit der
    # anschließend wirklich gerechnet wird.
    for region, n in universe_size.items():
        uni_status.setdefault(region, {"quelle": None, "alter_tage": None, "ok": True})["anzahl"] = n

    # 2. Kurse (Konstituenten + offene Positionen + Index-Proxys)
    symbols = [c.symbol for c in cons]
    scales = {c.symbol: c.price_scale for c in cons}
    for t in journal.open_positions(settings):
        s = journal.provenance(t).get("symbol") or t["ticker"]
        if s not in scales:
            symbols.append(s)
            scales[s] = 1.0
    # Kern-Titel mit abrufen: ETF und Kern-Aktien stehen nicht im Screener-Universum,
    # ohne Kurse ließe sich der Kern nicht bewerten. Im Demo-Modus bleibt das aus — die
    # synthetische Quelle erfindet Kurse für jedes Symbol, und ein frei erfundener
    # ETF-Kurs erzeugt einen frei erfundenen Gewinn.
    if not demo:
        for kern_symbol in _kern_symbole(settings):
            if kern_symbol not in scales:
                symbols.append(kern_symbol)
                scales[kern_symbol] = 1.0
    index_symbols = {}
    for region, cfg in settings.get("universe.regions", {}).items():
        if cfg.get("index_symbol") and not demo:
            index_symbols[region] = cfg["index_symbol"]
            if cfg["index_symbol"] not in scales:
                symbols.append(cfg["index_symbol"])
                scales[cfg["index_symbol"]] = 1.0
    frames, failed, notes = update_prices(settings, symbols, scales, source=source, fallback=fallback,
                                          today=today, progress=progress)
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
                          risk_pct=max(risk_by_region.values()) if risk_by_region else 1.0, as_of=as_of,
                          profil=risikoprofil(settings, account.satellite_equity_eur))
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

    # 8. Digest — ein Unterprozess, im Offline-Modus übersprungen
    digest_md = None if offline else journal.run_weekly_digest(settings, as_of)

    # 9. Entscheidungen — hier und nur hier wird geurteilt.
    # Die Mindestgröße nur rechnen, wenn nichts vorgeschlagen wurde: liegt ein Vorschlag vor,
    # ist das Kapital offensichtlich ausreichend und die Zahl wäre nur Lärm.
    mindest = None if proposals else mindestkapital(
        settings, table, fx, ctx.risk_pct, account.satellite_equity_eur)
    d_ctx = _entscheidungs_kontext(settings, as_of, readings, risk_by_region, account, blocked, dry_run,
                                   frames, positions, proposals, mindestkapital_eur=mindest)
    _kern_kontext(settings, d_ctx, frames, positions, as_of)
    entscheidungen, abgelehnt = dec.alle_urteile(positions, proposals, skipped, d_ctx)
    kern = _kern_zusammenfassung(settings, d_ctx, as_of)

    return WeeklyResult(
        as_of=as_of, readings=readings, account=account, kill_active=blocked, kill_reason=account.kill_switch_reason,
        dry_run=dry_run, risk_pct_by_region=risk_by_region, table=table, proposals=proposals, skipped=skipped,
        positions=positions, open_risk_pct=open_risk_pct, universe_size=universe_size, universe_warnings=uni_warn,
        universum_status=uni_status,
        data_failed=failed, data_notes=notes, fx_note=fx.note, regime_notes=regime_notes,
        entscheidungen=entscheidungen, abgelehnt=abgelehnt, fx_kurse=dict(fx.rates), kern=kern,
        digest_md=digest_md,
        demo=demo,
    )


def _entscheidungs_kontext(settings: Settings, as_of: date, readings: dict[str, regime.RegimeReading],
                           risk_by_region: dict[str, float], account: journal.Account,
                           blocked: bool, dry_run: bool, frames: dict[str, pd.DataFrame],
                           positions: list[PositionView], proposals: list[Proposal],
                           mindestkapital_eur: float | None = None) -> Kontext:
    """Rohwerte für das Entscheidungsmodell einsammeln — ohne Pipeline-Typen weiterzureichen."""
    limits = settings.get("signal.max_new_entries", {"GREEN": 2, "YELLOW": 1, "RED": 0})
    soft_weeks = int(settings.get("risk.soft_exit_weeks", 10))
    detail, ampel_note = {}, {}
    for r, rd in readings.items():
        if r == "US":
            detail[r] = f"Uptrend {dec.zahl(rd.uptrend, 0)} · Breadth {dec.zahl(rd.breadth, 0)}"
        else:
            detail[r] = f"P200 {dec.prozent(rd.p200, 0)} · P50 {dec.prozent(rd.p50, 0)}"
        # Gute Rohwerte bei roter Ampel sehen wie ein Fehler aus. Es ist die Hysterese:
        # die Ampel schaltet erst nach mehreren Lesungen in Folge um.
        if rd.raw != rd.effective:
            wochen = int(settings.get(f"regime.{r.lower()}.hysteresis_weeks", 2))
            ampel_note[r] = (f"Die Rohwerte stehen bereits auf {regime.LABEL.get(rd.raw)}, die Ampel schaltet aber "
                             f"erst nach {wochen} Wochen in Folge um — damit nicht auf jede Zuckung reagiert wird.")

    # Chartpunkte nur für Zeilen, die auch angezeigt werden — sonst bläht der Payload auf.
    wochenkurse = {}
    for symbol in {p.symbol for p in positions} | {p.symbol for p in proposals}:
        df = frames.get(symbol)
        if df is not None and not df.empty:
            wochenkurse[symbol] = _wochenpunkte(df, soft_weeks)

    gebunden = sum(p.wert_eur or 0.0 for p in positions)
    equity = account.satellite_equity_eur
    profil = risikoprofil(settings, equity)
    return Kontext(
        as_of=as_of,
        ampel={r: rd.effective for r, rd in readings.items()},
        ampel_label={r: rd.label for r, rd in readings.items()},
        ampel_detail=detail,
        ampel_note=ampel_note,
        risk_pct=dict(risk_by_region),
        max_neue_einstiege={r: int(limits.get(rd.effective or "RED", 0)) for r, rd in readings.items()},
        wochenkurse=wochenkurse,
        equity_eur=equity,
        cash_eur=max(0.0, equity - gebunden) if equity else None,
        kill_aktiv=blocked, kill_grund=account.kill_switch_reason,
        trockenlauf_bis=account.dry_run_until if dry_run else None,
        soft_exit_wochen=soft_weeks,
        max_positionen=profil["max_positions"],
        kleines_depot=profil["klein"],
        mindestkapital_eur=mindestkapital_eur,
        startphase=len(journal.closed_theses(settings)) < int(settings.get("risk.start_trades", 20)),
    )

"""Wochenbericht (Markdown) und Kurzfassung für die Push-Nachricht."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date

import numpy as np
import pandas as pd

from . import regime
from .config import Settings
from .pipeline import WeeklyResult


def _f(x, digits: int = 2, suffix: str = "") -> str:
    try:
        if x is None or (isinstance(x, float) and not np.isfinite(x)):
            return "–"
        return f"{float(x):,.{digits}f}{suffix}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "–"


def _pct(x, digits: int = 1) -> str:
    return "–" if x is None or (isinstance(x, float) and not np.isfinite(x)) else _f(float(x) * 100, digits, " %")


def ampel_line(r: regime.RegimeReading) -> str:
    if r.region == "US":
        detail = f"Uptrend {_f(r.uptrend, 0)} · Breadth {_f(r.breadth, 0)}"
    else:
        idx = "über" if r.idx_above else ("unter" if r.idx_above is False else "?")
        detail = f"P200 {_pct(r.p200, 0)} · P50 {_pct(r.p50, 0)} · Index {idx} SMA200"
    raw = f" (roh: {regime.LABEL.get(r.raw)})" if r.raw != r.effective else ""
    return f"**{r.region}: {r.label}**{raw} — {detail}"


def build_markdown(res: WeeklyResult, settings: Settings) -> str:
    L: list[str] = []
    L.append(f"# Wochenbericht Satellit — Stichtag {res.as_of.isoformat()}" + (" (DEMO)" if res.demo else ""))
    L.append("")
    if res.kill_active:
        L.append(f"> ⛔ **KILL-SWITCH AKTIV** — {res.kill_reason}. Keine neuen Einstiege. Bestehende Positionen laufen nach Abschnitt 7 aus.")
        L.append("")
    if res.dry_run:
        L.append(f"> 🧪 **Trockenlauf** bis {res.account.dry_run_until} — Bericht lesen, keine Orders aufgeben.")
        L.append("")

    # Ampel
    L.append("## 1. Ampel")
    for r in res.readings.values():
        L.append(f"- {ampel_line(r)}" + (f" — _{r.note}_" if r.note else ""))
    limits = settings.get("signal.max_new_entries", {})
    L.append(f"- Neue Einstiege erlaubt: " + ", ".join(
        f"{reg} {limits.get(rd.effective or 'RED', 0)}" for reg, rd in res.readings.items()))
    L.append(f"- Risiko je Trade: " + ", ".join(f"{reg} {_f(v, 2)} %" for reg, v in res.risk_pct_by_region.items()))
    for n in res.regime_notes:
        L.append(f"- ⚠️ {n}")
    L.append("")

    # Konto
    acc = res.account
    L.append("## 2. Satellit-Konto")
    if acc.satellite_equity_eur:
        dd = acc.drawdown
        L.append(f"- Kapital: **{_f(acc.satellite_equity_eur, 0)} EUR** (Stand {acc.updated}) · Hoch {_f(acc.high_water_mark, 0)} EUR · Drawdown {_pct(dd)}")
        L.append(f"- Offenes Risiko: {_f(res.open_risk_pct, 2)} % (Limit {settings.get('risk.max_open_risk_pct')} %) · Positionen {len(res.positions)}/{settings.get('risk.max_positions')}")
    else:
        L.append("- ⚠️ Kein Kapital hinterlegt: `satellit account set --equity <EUR>` — ohne Kapital keine Positionsgrößen.")
    L.append("")

    # Positionen
    L.append("## 3. Offene Positionen — Montag erledigen")
    if not res.positions:
        L.append("- keine")
    else:
        L.append("| Symbol | Stücke | Einstieg | Kurs | P&L | Stop alt | Stop neu | Aktion |")
        L.append("|---|---|---|---|---|---|---|---|")
        for p in res.positions:
            actions = []
            if p.hard_stop_hit:
                actions.append("⚠️ Wochentief ≤ Stop — im Depot prüfen, ob Stop ausgelöst wurde; falls ja `journal close --reason stop`")
            if p.soft_exit:
                actions.append("🔻 **VERKAUFEN** (Wochenschluss < SMA10W) — Market-Order Montag, dann `journal close --reason trend`")
            if p.stop_raised and not p.soft_exit:
                actions.append(f"⬆️ Stop-Order auf **{_f(p.new_stop)}** anheben, dann `journal stop {p.thesis_id} --stop {p.new_stop:.2f}`")
            if not actions:
                actions.append("halten" if not p.note else p.note)
            L.append(f"| {p.symbol} | {_f(p.shares, 0)} | {_f(p.entry)} | {_f(p.close)} | {_pct(p.pnl_pct)} | {_f(p.stop)} | {_f(p.new_stop)} | {'; '.join(actions)} |")
    L.append("")

    # Vorschläge
    L.append("## 4. Neue Einstiege (Vorschlag — Sichtkontrolle Sonntag, Orders Montag)")
    if res.proposals:
        L.append("| Symbol | Name | Region | Sektor | Kurs | Ausbruch | Stop | Stücke | Wert EUR | Risiko EUR | Limit |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for p in res.proposals:
            L.append(f"| **{p.symbol}** | {p.name[:28]} | {p.region} ({p.ampel}) | {p.sector} | {_f(p.close)} {p.currency} | {_f(p.breakout_level)} | {_f(p.initial_stop)} | {p.shares} | {_f(p.value_eur, 0)} | {_f(p.risk_eur, 0)} ({_f(p.risk_pct, 2)} %) | ≤ {_f(p.limit_price)} |")
        L.append("")
        L.append("Ablauf je Einstieg: Chart prüfen (Base ≥ 4 Wochen?) → `satellit journal new --symbol … --entry … --stop …` → Montag Limit-Order (tagesgültig) → bei Ausführung `satellit journal open <id> --price … --shares …` → Stop-Market-Order (360 Tage) auf den Initialstop.")
    else:
        L.append("- keine Kandidaten, die alle Regeln erfüllen")
    if res.skipped:
        L.append("")
        L.append("<details><summary>Übersprungen / begrenzt</summary>")
        L.append("")
        for s in res.skipped[:25]:
            L.append(f"- {s}")
        L.append("")
        L.append("</details>")
    L.append("")

    # Watchlist + Screener-Statistik
    t = res.table
    if not t.empty:
        L.append("## 5. Watchlist (Top-RS, Trend intakt, bis 3 % unter Ausbruch)")
        w = t[t["watchlist"]].head(10)
        if w.empty:
            L.append("- keine")
        else:
            L.append("| Symbol | Name | Region | Kurs | Ausbruch bei | Abstand |")
            L.append("|---|---|---|---|---|---|")
            for _, r in w.iterrows():
                L.append(f"| {r['symbol']} | {str(r['name'])[:28]} | {r['region']} | {_f(r['close'])} | {_f(r['breakout_level'])} | {_pct(r['extension'])} |")
        L.append("")
        L.append("## 6. Screener-Statistik")
        for reg, grp in t.groupby("region"):
            L.append(f"- {reg}: {len(grp)} Titel · Trend ok {int(grp['trend_ok'].sum())} · Top-RS {int(grp['rs_top'].sum())} · Ausbruch {int(grp['breakout'].sum())} · **Kandidaten {int(grp['candidate'].sum())}**")
        L.append("")

    # Datenqualität
    L.append("## 7. Datenqualität")
    for reg, n in res.universe_size.items():
        L.append(f"- Universum {reg}: {n} Titel")
    for wmsg in res.universe_warnings:
        L.append(f"- ⚠️ {wmsg}")
    L.append(f"- Wechselkurse: {res.fx_note}")
    for n in res.data_notes:
        L.append(f"- ⚠️ {n}")
    if res.data_failed:
        L.append(f"- ⚠️ {len(res.data_failed)} Symbole ohne Kurse (Korrektur in config/symbol_overrides.yaml): "
                 + ", ".join(f"{s} ({why})" for s, why in list(res.data_failed.items())[:12])
                 + (" …" if len(res.data_failed) > 12 else ""))
    L.append("")

    if res.digest_md:
        L.append("## 8. Wochen-Digest (geschlossene Trades)")
        L.append("")
        L.append(res.digest_md.strip())
        L.append("")
    return "\n".join(L)


def build_push(res: WeeklyResult, settings: Settings) -> tuple[str, str]:
    """(Titel, Nachricht ≤ 1024 Zeichen)"""
    title = f"Satellit {res.as_of.strftime('%d.%m.')}: " + " · ".join(f"{r.region} {r.label}" for r in res.readings.values())
    lines = []
    if res.kill_active:
        lines.append("⛔ KILL-SWITCH AKTIV — keine Einstiege")
    if res.dry_run:
        lines.append("🧪 Trockenlauf — keine Orders")
    sells = [p.symbol for p in res.positions if p.soft_exit]
    stops = [f"{p.symbol}→{p.new_stop:.2f}" for p in res.positions if p.stop_raised and not p.soft_exit]
    hits = [p.symbol for p in res.positions if p.hard_stop_hit]
    if sells:
        lines.append("🔻 Verkaufen: " + ", ".join(sells))
    if hits:
        lines.append("⚠️ Stop evtl. ausgelöst: " + ", ".join(hits))
    if stops:
        lines.append("⬆️ Stops: " + ", ".join(stops))
    if res.proposals:
        lines.append("🟢 Kandidaten: " + ", ".join(f"{p.symbol} ({p.shares} Stk, Stop {p.initial_stop:.2f})" for p in res.proposals))
    else:
        lines.append("Keine neuen Kandidaten")
    if res.data_failed:
        lines.append(f"⚠️ {len(res.data_failed)} Symbole ohne Kurse")
    if res.report_path:
        lines.append(f"Bericht: {res.report_path}")
    msg = "\n".join(lines)
    return title, msg[:1024]


def write_report(res: WeeklyResult, settings: Settings) -> str:
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    path = settings.reports_dir / f"weekly_{res.as_of.isoformat()}.md"
    res.report_path = str(path)
    path.write_text(build_markdown(res, settings), encoding="utf-8")
    summary = {
        "as_of": res.as_of.isoformat(),
        "readings": {k: asdict(v) for k, v in res.readings.items()},
        "kill_active": res.kill_active, "dry_run": res.dry_run,
        "proposals": [asdict(p) for p in res.proposals],
        "positions": [asdict(p) for p in res.positions],
        "data_failed": res.data_failed, "notes": res.data_notes + res.regime_notes + res.universe_warnings,
    }
    (settings.reports_dir / f"weekly_{res.as_of.isoformat()}.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return str(path)

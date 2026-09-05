"""Wochenbericht (Markdown) und Kurzfassung für die Push-Nachricht."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date

import numpy as np
import pandas as pd

from . import decisions as dec
from . import regime
from .config import Settings, risikoprofil
from .pipeline import WeeklyResult

# Eine Quelle für die Zahlenformatierung — decisions.py formuliert dieselben Werte für die
# Oberfläche, und zwei Formatierer driften erfahrungsgemäß auseinander.
_f = dec.zahl
_pct = dec.prozent
_stueck = dec.stueck

_ZEICHEN = {dec.KAUFEN: "🟢", dec.VERKAUFEN: "🔻", dec.STOP_ANHEBEN: "⬆️", dec.PRUEFEN: "⚠️",
            dec.HALTEN: "·", dec.WARTEN: "⏸", dec.NICHT_KAUFEN: "–", dec.NACHKAUFEN: "➕"}


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
        # Die Grenzen aus dem wirksamen Profil, nicht aus den Regelwerten — bei kleinem
        # Satelliten gelten andere, und eine falsche Zahl im Bericht ist schlimmer als keine.
        profil = risikoprofil(settings, res.account.satellite_equity_eur)
        L.append(f"- Offenes Risiko: {_f(res.open_risk_pct, 2)} % (Limit {settings.get('risk.max_open_risk_pct')} %) · Positionen {len(res.positions)}/{profil['max_positions']}")
        if profil["klein"]:
            L.append(f"- Kleines Depot: höchstens {profil['max_positions']} Positionen à "
                     f"{_f(profil['max_position_pct'], 0)} % (Trading-Plan 6.1)")
    else:
        L.append("- ⚠️ Kein Kapital hinterlegt: `satellit account set --equity <EUR>` — ohne Kapital keine Positionsgrößen.")
    L.append("")

    # Positionen — Urteil und Begründung kommen aus decisions.py, hier wird nur gerendert.
    L.append("## 3. Offene Positionen — Montag erledigen")
    if not res.positions:
        L.append("- keine")
    else:
        urteil = {d.schluessel: d for d in res.entscheidungen}
        L.append("| Symbol | Stücke | Einstieg | Kurs | P&L | Wert EUR | Stop alt | Stop neu | Aktion |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for p in res.positions:
            d = urteil.get(f"TH:{p.thesis_id}")
            aktion = f"{_ZEICHEN.get(d.verdikt, '')} **{d.verdikt_label}** — {d.begruendung}" if d else "–"
            L.append(f"| {p.symbol} | {_f(p.shares, 0)} | {_f(p.entry)} | {_f(p.close)} | {_pct(p.pnl_pct)} | "
                     f"{_f(p.wert_eur, 0)} | {_f(p.stop)} | {_f(p.new_stop)} | {aktion} |")
    L.append("")

    # Vorschläge
    L.append("## 4. Neue Einstiege (Vorschlag — Sichtkontrolle Sonntag, Orders Montag)")
    if res.proposals:
        L.append("| Symbol | Name | Region | Sektor | Kurs | Ausbruch | Stop | Stücke | Wert EUR | Risiko EUR | Limit |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for p in res.proposals:
            L.append(f"| **{p.symbol}** | {p.name[:28]} | {p.region} ({p.ampel}) | {p.sector} | {_f(p.close)} {p.currency} | {_f(p.breakout_level)} | {_f(p.initial_stop)} | {_stueck(p.shares)} | {_f(p.value_eur, 0)} | {_f(p.risk_eur, 0)} ({_f(p.risk_pct, 2)} %) | ≤ {_f(p.limit_price)} |")
        L.append("")
        L.append("Ablauf je Einstieg: Chart prüfen (Base ≥ 4 Wochen?) → `satellit journal new --symbol … --entry … --stop …` → Montag Limit-Order (tagesgültig) → bei Ausführung `satellit journal open <id> --price … --shares …` → Stop-Market-Order (360 Tage) auf den Initialstop.")
    else:
        L.append("- keine Kandidaten, die alle Regeln erfüllen")
    if res.abgelehnt:
        L.append("")
        L.append("<details><summary>Warum wurde sonst nichts gekauft?</summary>")
        L.append("")
        for d in res.abgelehnt[:25]:
            L.append(f"- {d.begruendung}")
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
    # Auch die Push-Nachricht liest die Urteile, statt sie erneut abzuleiten.
    def _mit(verdikt: str) -> list:
        return [d for d in res.entscheidungen if d.verdikt == verdikt]

    if sells := _mit(dec.VERKAUFEN):
        lines.append("🔻 Verkaufen: " + ", ".join(d.symbol for d in sells))
    if hits := [d for d in _mit(dec.PRUEFEN) if d.art == "satellit_position"]:
        lines.append("⚠️ Prüfen: " + ", ".join(d.symbol for d in hits))
    if stops := _mit(dec.STOP_ANHEBEN):
        lines.append("⬆️ Stops: " + ", ".join(f"{d.symbol}→{_f(d.neuer_stop)}" for d in stops))
    if kaeufe := _mit(dec.KAUFEN):
        lines.append("🟢 Kandidaten: " + ", ".join(
            f"{d.symbol} ({_f(d.stueck, 0)} Stk, Stop {_f(d.stop_kurs)})" for d in kaeufe))
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

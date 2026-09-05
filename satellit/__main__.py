"""CLI: python -m satellit <befehl> [optionen]"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from . import journal, regime
from .api import run_weekly_job, serve_api, write_run_status
from .config import Settings, load_settings
from .data import build_source, update_prices
from .fx import FxTable, load_fx
from .notify import send_pushover
from .pipeline import last_friday, run_weekly
from .report import build_push, write_report
from .universe import import_holdings, load_universe, snapshot_aktualisieren

log = logging.getLogger("satellit")


def _setup_logging(settings: Settings, verbose: bool) -> None:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    handlers = [logging.StreamHandler(sys.stderr), logging.FileHandler(settings.state_dir / "satellit.log", encoding="utf-8")]
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)


# ------------------------------------------------------------------ commands
def cmd_weekly(a, s: Settings) -> int:
    as_of = date.fromisoformat(a.as_of) if a.as_of else None
    source = build_source(s, a.source) if a.source else None
    write_run_status(s, running=True, started=datetime.now().isoformat(timespec="seconds"), error=None)
    try:
        res = run_weekly(s, as_of=as_of, source=source, demo=a.demo, skip_us_scripts=a.skip_us_scripts)
        path = write_report(res, s)
    except Exception as exc:  # noqa: BLE001
        write_run_status(s, running=False, ok=False, error=str(exc), finished=datetime.now().isoformat(timespec="seconds"))
        raise
    title, msg = build_push(res, s)
    print(Path(path).read_text(encoding="utf-8"))
    print(f"\n--- Bericht gespeichert: {path}", file=sys.stderr)
    pushed = False
    if not a.no_push:
        pushed = send_pushover(title, msg, priority=1 if (res.kill_active or any(p.soft_exit or p.hard_stop_hit for p in res.positions)) else 0,
                               url=os.environ.get("DASHBOARD_URL") or None)
        print(f"--- Pushover: {'gesendet' if pushed else 'nicht gesendet'}", file=sys.stderr)
    write_run_status(s, running=False, ok=True, finished=datetime.now().isoformat(timespec="seconds"),
                     as_of=res.as_of.isoformat(), report=path, pushed=pushed, candidates=len(res.proposals),
                     failed_symbols=len(res.data_failed), demo=a.demo)
    return 0


def _universe_import(a, s: Settings) -> int:
    """Von Hand heruntergeladene iShares-Holdings-CSV übernehmen."""
    pfad = Path(a.import_file)
    if not pfad.exists():
        print(f"Datei nicht gefunden: {pfad}")
        return 1
    if not a.region:
        print("--region fehlt (z. B. --region US)")
        return 1
    try:
        anzahl, ziel = import_holdings(s, a.region, pfad.read_text(encoding="utf-8", errors="replace"))
    except ValueError as exc:
        print(f"Import fehlgeschlagen: {exc}")
        return 1
    print(f"{a.region}: {anzahl} Titel gelesen -> {ziel}")
    return 0


def cmd_universe(a, s: Settings) -> int:
    if getattr(a, "import_file", None):
        return _universe_import(a, s)
    cons, warnings, status = load_universe(s, force=a.force)
    snapshot_aktualisieren(cons, status, s.universe_dir / "universe_snapshot.csv")
    by_region: dict[str, int] = {}
    for c in cons:
        by_region[c.region] = by_region.get(c.region, 0) + 1
    print("Universum:", ", ".join(f"{k} {v}" for k, v in by_region.items()) or "(leer)")
    for region, st in status.items():
        herkunft = st["quelle"] or "keine Quelle"
        alter = "" if st["alter_tage"] in (None, 0) else f", {st['alter_tage']} Tage alt"
        print(f"  {region}: {'ok' if st['ok'] else 'FEHLT'} — {herkunft}{alter}")
    for w in warnings:
        print("⚠️", w)
    if a.check:
        print("\nStichprobe (Symbol | Name | Börse | Währung | Sektor):")
        for c in cons[:8] + cons[-8:]:
            print(f"  {c.symbol:14} | {c.name[:30]:30} | {c.exchange[:22]:22} | {c.currency:4} | {c.sector}")
        unknown = [c for c in cons if c.region == "EU" and "." not in c.symbol]
        if unknown:
            print(f"\n⚠️ {len(unknown)} EU-Titel ohne Börsensuffix (Börse nicht erkannt): "
                  + ", ".join(f"{c.ticker}@{c.exchange}" for c in unknown[:10]))
    return 0


def cmd_prices(a, s: Settings) -> int:
    if a.symbols:
        symbols, scales = [x.strip() for x in a.symbols.split(",")], {}
    else:
        cons, _, _ = load_universe(s)
        symbols, scales = [c.symbol for c in cons], {c.symbol: c.price_scale for c in cons}
    source = build_source(s, a.source) if a.source else None
    frames, failed, notes = update_prices(s, symbols, scales, source=source)
    print(f"{len(frames)} Kursreihen im Cache, {len(failed)} fehlgeschlagen")
    for n in notes:
        print("⚠️", n)
    for sym, why in list(failed.items())[:30]:
        print(f"  ✗ {sym}: {why}")
    return 0


def cmd_regime(a, s: Settings) -> int:
    up, br, notes = regime.run_us_scores(s)
    print(f"US: uptrend={up} breadth={br} -> roh {regime.us_raw_state(up, br, s.get('regime.us', {}))}")
    for n in notes:
        print("⚠️", n)
    for row in regime.load_history(s.regime_dir / "ampel_history.csv")[-6:]:
        print("  ", {k: row[k] for k in ("date", "region", "raw", "effective")})
    return 0


def cmd_account(a, s: Settings) -> int:
    acc = journal.Account.load(s)
    if a.sub == "set":
        acc.set_equity(a.equity)
        acc.save(s)
    elif a.sub == "dry-run":
        acc.dry_run_until = a.until
        acc.save(s)
    elif a.sub == "reset-kill":
        acc.kill_switch_active, acc.kill_switch_reason = False, ""
        acc.save(s)
        print("Kill-Switch zurückgesetzt — Neustart nur nach schriftlicher Analyse (Trading-Plan 10.2).")
    active, why = journal.kill_switch_status(s, acc)
    exp, n, wr = journal.expectancy(journal.closed_theses(s))
    print(f"Satellit-Kapital: {acc.satellite_equity_eur} EUR (Stand {acc.updated}), Hoch {acc.high_water_mark}, "
          f"Drawdown {None if acc.drawdown is None else f'{acc.drawdown:.1%}'}")
    print(f"Geschlossene Trades: {n} · Expectancy {exp if exp is None else f'{exp:.2f} R'} · Trefferquote {wr if wr is None else f'{wr:.0%}'}")
    print(f"Kill-Switch: {'AKTIV — ' + acc.kill_switch_reason if acc.kill_switch_active else ('würde greifen: ' + why if active else 'inaktiv')}")
    print(f"Trockenlauf bis: {acc.dry_run_until or '–'}")
    return 0


def _latest_screener_row(s: Settings, symbol: str) -> dict | None:
    files = sorted(glob.glob(str(s.reports_dir / "screener_*.csv")))
    if not files:
        return None
    df = pd.read_csv(files[-1])
    hit = df[df["symbol"].str.upper() == symbol.upper()]
    return None if hit.empty else hit.iloc[0].to_dict()


def cmd_journal(a, s: Settings) -> int:
    if a.sub == "new":
        row = _latest_screener_row(s, a.symbol) or {}
        entry = a.entry if a.entry is not None else row.get("close")
        stop = a.stop if a.stop is not None else (0.0 if a.core else row.get("initial_stop"))
        if entry is None or stop is None:
            print("Einstieg/Stop unbekannt — --entry und --stop angeben (Symbol nicht im letzten Screener-Lauf).")
            return 2
        region = a.region or row.get("region") or ("US" if "." not in a.symbol else "EU")
        currency = a.currency or row.get("currency") or ("USD" if region == "US" else "EUR")
        sector = a.sector or row.get("sector") or "Unknown"
        reading = regime.last_known(s, region) or {}
        ampel = reading.get("effective")
        report_file = sorted(glob.glob(str(s.reports_dir / "weekly_*.md")))[-1:] or ["manual"]
        tid = journal.new_thesis(
            s, symbol=a.symbol.upper(), isin=a.isin or row.get("isin") or "", name=a.name or row.get("name") or a.symbol,
            region=region, currency=currency, sector=sector, entry=float(entry), stop=float(stop),
            breakout_level=row.get("breakout_level"), rs_rank_pct=row.get("rs_rank_pct"), ampel=ampel,
            report_file=os.path.basename(report_file[0]), statement=a.statement,
            setup_type="core_holding" if a.core else "trendfolge_20w", review_days=180 if a.core else 7,
        )
        print(f"These angelegt: {tid} (ENTRY_READY)")
        acc = journal.Account.load(s)
        if not a.core and acc.satellite_equity_eur:
            fx = FxTable({}, "fallback") if a.no_fx else load_fx(build_source(s), {currency})
            risk = journal.effective_risk_pct(s, ampel)
            try:
                report, path = journal.size_position(s, entry=float(entry), stop=float(stop), currency=currency, fx=fx,
                                                     equity_eur=acc.satellite_equity_eur, risk_pct=risk, sector=sector)
                journal.attach_sizing(s, tid, path)
                print(f"Positionsgröße: {report.get('final_recommended_shares')} Stück · Wert {report.get('final_position_value'):.0f} EUR "
                      f"· Risiko {report.get('final_risk_dollars'):.0f} EUR ({risk:.2f} %) · Stop {float(stop):.2f} {currency}")
            except Exception as exc:  # noqa: BLE001
                print(f"⚠️ Positionsgröße nicht berechnet: {exc}")
        return 0
    if a.sub == "open":
        when = a.date or date.today().isoformat()
        t = journal.open_position(s, a.id, a.price, journal.now_iso(date.fromisoformat(when)), a.shares)
        print(f"{a.id}: ACTIVE — {t['position']['shares']} Stück zu {a.price}")
        return 0
    if a.sub == "close":
        when = a.date or date.today().isoformat()
        t = journal.close_position(s, a.id, a.price, journal.now_iso(date.fromisoformat(when)), a.reason)
        o = t.get("outcome") or {}
        print(f"{a.id}: CLOSED — P&L {o.get('pnl_dollars')} ({o.get('pnl_pct')} %), R = {journal.r_multiple(t)}")
        if a.reason == "manual":
            print("⚠️ Exit-Grund 'manual' = Regelbruch. Im Monatsreview begründen.")
        return 0
    if a.sub == "stop":
        journal.update_stop(s, a.id, a.stop, a.note or "wöchentlicher Trailing-Stop")
        print(f"{a.id}: Stop auf {a.stop} gesetzt (Stop-Order beim Broker entsprechend anpassen!)")
        return 0
    if a.sub == "list":
        theses = journal.list_theses(s, a.status)
        for t in sorted(theses, key=lambda x: x.get("created_at", "")):
            ex = t.get("exit") or {}
            print(f"{t['thesis_id']:34} {t['status']:16} {t['ticker']:12} stop={ex.get('stop_loss')}  {t.get('setup_type')}")
        return 0
    if a.sub in ("review-due", "summary"):
        return journal.review_cli(s, [a.sub])
    if a.sub == "postmortem":
        return journal.review_cli(s, ["postmortem", a.id])
    if a.sub == "monthly":
        out = s.reports_dir / f"monthly_{a.month}.md"
        return journal.review_cli(s, ["monthly-report", "--month", a.month, "--output", str(out)])
    return 1


def cmd_push_test(a, s: Settings) -> int:
    ok = send_pushover("Satellit Test", "Pushover funktioniert. 🟢")
    print("gesendet" if ok else "fehlgeschlagen (Token/User prüfen)")
    return 0 if ok else 1


def cmd_api(a, s: Settings) -> int:
    serve_api(s, port=int(os.environ.get("SATELLIT_API_PORT", a.port)), block=True)
    return 0


def cmd_serve(a, s: Settings) -> int:
    """Scheduler: wartet bis zum nächsten Termin (Samstag 08:00 Europe/Berlin) und läuft dann. Startet die API mit."""
    tz = ZoneInfo(os.environ.get("SATELLIT_TZ") or s.get("schedule.timezone", "Europe/Berlin"))
    weekday, hour, minute = int(s.get("schedule.weekday", 5)), int(s.get("schedule.hour", 8)), int(s.get("schedule.minute", 0))
    if not a.no_api:
        serve_api(s, port=int(os.environ.get("SATELLIT_API_PORT", 8787)), block=False)
    while True:
        now = datetime.now(tz)
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (weekday - now.weekday()) % 7
        target = target + timedelta(days=days_ahead)
        if target <= now:
            target += timedelta(days=7)
        wait = (target - now).total_seconds()
        log.info("Nächster Lauf: %s (in %.1f h)", target.isoformat(), wait / 3600)
        time.sleep(max(60, min(wait, 3600)))
        if datetime.now(tz) >= target:
            result = run_weekly_job(s, push=True)
            log.info("Wochenlauf: %s", result)
            time.sleep(120)


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="satellit", description="Core-Satellite Trading-Pipeline")
    p.add_argument("--settings", default=None, help="Pfad zu settings.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("weekly", help="Kompletter Wochenlauf + Bericht + Push")
    w.add_argument("--as-of", default=None, help="Stichtag YYYY-MM-DD (Standard: letzter Freitag)")
    w.add_argument("--source", default=None, choices=["yfinance", "stooq", "fixture", "synthetic"])
    w.add_argument("--demo", action="store_true", help="synthetisches Universum + Kurse, ohne Netz")
    w.add_argument("--skip-us-scripts", action="store_true", help="US-Skills nicht ausführen (letzten Stand nutzen)")
    w.add_argument("--no-push", action="store_true")
    w.set_defaults(func=cmd_weekly)

    u = sub.add_parser("universe", help="Konstituenten laden/prüfen/importieren")
    u.add_argument("--force", action="store_true")
    u.add_argument("--check", action="store_true")
    u.add_argument("--import-file", dest="import_file", default=None,
                   help="Von Hand heruntergeladene iShares-Holdings-CSV übernehmen (mit --region)")
    u.add_argument("--region", default=None, help="Region für --import-file, z. B. US oder EU")
    u.set_defaults(func=cmd_universe)

    pr = sub.add_parser("prices", help="Kurs-Cache aktualisieren")
    pr.add_argument("--symbols", default=None)
    pr.add_argument("--source", default=None, choices=["yfinance", "stooq", "fixture", "synthetic"])
    pr.set_defaults(func=cmd_prices)

    r = sub.add_parser("regime", help="US-Ampel-Skills ausführen")
    r.set_defaults(func=cmd_regime)

    ac = sub.add_parser("account", help="Satelliten-Kapital, Kill-Switch, Trockenlauf")
    acs = ac.add_subparsers(dest="sub", required=True)
    a1 = acs.add_parser("set"); a1.add_argument("--equity", type=float, required=True)
    acs.add_parser("show")
    a3 = acs.add_parser("dry-run"); a3.add_argument("--until", required=True, help="YYYY-MM-DD")
    acs.add_parser("reset-kill")
    ac.set_defaults(func=cmd_account)

    j = sub.add_parser("journal", help="Thesen/Positionen (trader-memory-core)")
    js = j.add_subparsers(dest="sub", required=True)
    n = js.add_parser("new")
    n.add_argument("--symbol", required=True)
    n.add_argument("--entry", type=float); n.add_argument("--stop", type=float)
    n.add_argument("--isin"); n.add_argument("--name"); n.add_argument("--region"); n.add_argument("--currency")
    n.add_argument("--sector"); n.add_argument("--statement"); n.add_argument("--core", action="store_true")
    n.add_argument("--no-fx", action="store_true", help="keine FX-Abfrage (Fallback-Kurse)")
    o = js.add_parser("open"); o.add_argument("id"); o.add_argument("--price", type=float, required=True)
    o.add_argument("--shares", type=float, required=True); o.add_argument("--date")
    c = js.add_parser("close"); c.add_argument("id"); c.add_argument("--price", type=float, required=True)
    c.add_argument("--reason", choices=["stop", "trend", "manual", "invalidated"], required=True); c.add_argument("--date")
    st = js.add_parser("stop"); st.add_argument("id"); st.add_argument("--stop", type=float, required=True); st.add_argument("--note")
    ls = js.add_parser("list"); ls.add_argument("--status")
    js.add_parser("review-due"); js.add_parser("summary")
    pm = js.add_parser("postmortem"); pm.add_argument("id")
    mo = js.add_parser("monthly"); mo.add_argument("--month", required=True)
    j.set_defaults(func=cmd_journal)

    sub.add_parser("push-test").set_defaults(func=cmd_push_test)
    sv = sub.add_parser("serve", help="Scheduler-Schleife + Dashboard-API (Docker)")
    sv.add_argument("--no-api", action="store_true")
    sv.set_defaults(func=cmd_serve)
    ap = sub.add_parser("api", help="nur die Dashboard-API starten")
    ap.add_argument("--port", type=int, default=8787)
    ap.set_defaults(func=cmd_api)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings(args.settings)
    _setup_logging(settings, args.verbose)
    return args.func(args, settings)


if __name__ == "__main__":
    sys.exit(main())

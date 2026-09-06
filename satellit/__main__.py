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

from . import decisions as dec
from . import journal, portfolio, regime, view
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
        view.schreiben(view.bauen(res, s), s)
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


def cmd_kern_scan(a, s: Settings) -> int:
    """Kandidaten für den Kern-Aktienteil gegen KERN.md 6 prüfen."""
    from .kern_scan import run_kern_scan, stand_uebernehmen

    def fortschritt(fertig: int, gesamt: int) -> None:
        print(f"\r  {fertig}/{gesamt} Titel …", end="", file=sys.stderr, flush=True)

    res = run_kern_scan(s, nur_watchlist=a.watchlist, demo=a.demo, offline=a.offline,
                        progress=fortschritt, max_titel=a.max_titel)
    stand_uebernehmen(s, res)
    print(file=sys.stderr)
    for h in res.hinweise:
        print(f"  {h}", file=sys.stderr)

    if res.fehler:
        # Ein Fehlschlag ist kein leeres Ergebnis — auch der Rückgabewert muss das sagen,
        # damit ein Cronjob oder ein Skript daran scheitert statt weiterzulaufen.
        print(f"\nKern-Scan fehlgeschlagen: {res.fehler}", file=sys.stderr)
        return 1

    t = res.trichter
    print(f"\nKern-Scan {res.as_of} ({res.quelle}) — {res.geprueft} geprüft, "
          f"{res.vorgefiltert} vorgefiltert")
    print(f"  bestanden: {t.get('bestanden', 0)} · ausgeschlossen: {t.get('ausgeschlossen', 0)}")
    for nummer in range(1, 8):
        n = t.get(f"kriterium_{nummer}", 0)
        if n:
            print(f"  an Kriterium {nummer} gescheitert: {n}")
    if res.daten_fehlt:
        print(f"  ohne Kennzahlen: {len(res.daten_fehlt)}")

    if not res.bestanden:
        print("\nKein Titel besteht den Katalog. Das ist ein gültiges Ergebnis, kein Fehler.")
        return 0
    print("\nBestanden (die offenen Kriterien beantwortest du beim Anlegen der These):")
    for k in res.bestanden:
        offen = f" · {len(k.ungeprueft)} offen" if k.ungeprueft else ""
        print(f"  {k.symbol:<12} {k.name[:34]:<34} Soll {k.erfuellte_soll}"
              f" · {k.jahre_abgedeckt} Jahre Daten{offen}")
    print(f"\n  python -m satellit journal new --symbol <SYMBOL> --core --entry <Kurs> --stop 0")
    return 0


def cmd_portfolio(a, s: Settings) -> int:
    """Kern-Portfolio anzeigen oder einrichten."""
    if a.unterbefehl == "setup":
        # Bewusst dieselbe Funktion wie das Dashboard: zwei Einrichtungswege, die
        # unterschiedlich viel tun, sind eine Fehlerquelle, die niemand bemerkt.
        from .api import action_portfolio_setup
        try:
            r = action_portfolio_setup(s, {"start_eur": a.start, "rate_eur": a.rate,
                                           "sparplan_tag": a.sparplan_tag, "etf_isin": a.etf,
                                           "etf_anteil": a.etf_anteil, "force": a.force})
        except ValueError as exc:
            print(f"Einrichtung nicht möglich: {exc}")
            if "ISIN" in str(exc):
                for e in portfolio.lade_etf_katalog(s):
                    print(f"  {e['isin']}  {e['name']}")
            return 1
        print(f"Eingerichtet: {r['etf']} · Kern {dec.zahl(r['kern_eur'])} EUR · "
              f"Satellit {dec.zahl(r['satellit_eur'])} EUR · {r['buchungen']} Eröffnungsbuchungen")
        print(f"Trockenlauf bis {r['trockenlauf_bis']} — bis dahin nur mitlesen (Trading-Plan 10.1).")
        return 0

    z = portfolio.zusammenfassung(s)
    w, plan = z["werte"], z["plan"]
    if not plan.onboarding_erledigt:
        print("Noch nicht eingerichtet — `satellit portfolio setup --start … --rate … --etf <ISIN>`")
        return 0
    e = lambda x: f"{dec.zahl(x, 2):>14} EUR"
    print(f"Gesamtwert   {e(w.gesamt_eur)}")
    print(f"  Kern       {e(w.kern_eur)}  ({dec.prozent(w.kern_pct)})")
    print(f"    ETF      {e(w.kern_etf_eur)}")
    print(f"    Aktien   {e(w.kern_aktien_eur)}  (+ {dec.zahl(w.kern_aktien_cash_eur)} EUR Cash bereit)")
    # Der Kern trägt sein Cash schon in kern_eur; beim Satelliten muss es dazu, sonst
    # steht eine 0 neben einem Anteil von 10 %.
    sat_gesamt = w.satellit_eur + w.cash_je_topf.get("satellit", 0.0)
    print(f"  Satellit   {e(sat_gesamt)}  ({dec.prozent(w.satellit_pct)})")
    print(f"  Frei       {e(w.cash_je_topf.get('cash', 0.0))}")
    g = z["gewinn"]
    print(f"\nEingezahlt   {e(g['eingezahlt_netto_eur'])}")
    print(f"Gewinn       {e(g['gewinn_eur'])}"
          + (f"  ({dec.prozent(g['xirr_pct'])} p. a.)" if g["xirr_pct"] is not None else ""))
    m = z["monat"]
    print(f"\n{m['monat']}: {dec.zahl(m['ausgegeben_eur'])} EUR ausgegeben"
          + (f", {dec.zahl(m['offen_eur'])} EUR offen" if m["offen_eur"] else ""))
    f = z["kauffenster"]
    print("Kauffenster Kern-Aktien: " + (f"offen ({f['grund']})" if f["offen"]
                                         else f"geschlossen, nächstes {f['naechstes']}"))
    print(f"Band Kern/Satellit: {z['band']['status']}")
    if w.nicht_bewertbar:
        print(f"⚠️ ohne Kurs bewertet: {', '.join(w.nicht_bewertbar)}")
    return 0


def cmd_ledger(a, s: Settings) -> int:
    """Kassenbuch anzeigen oder ergänzen."""
    if a.unterbefehl == "add":
        b = portfolio.Buchung(datum=a.datum or date.today().isoformat(), typ=a.typ, topf=a.topf,
                              betrag_eur=float(a.betrag), isin=a.isin or "", symbol=a.symbol or "",
                              stueck=float(a.stueck or 0), kurs=float(a.kurs or 0),
                              gebuehr_eur=float(a.gebuehr or 0), notiz=a.notiz or "", quelle="cli")
        portfolio.schreibe_buchung(s, b)
        print(f"gebucht: {b.datum} {b.typ} {b.topf} {b.betrag_eur:.2f} EUR  [{b.quelle_id}]")
        return 0
    if a.unterbefehl == "storno":
        g = portfolio.storniere(s, a.schluessel, a.notiz or "manuell")
        print(f"storniert: {a.schluessel} -> Gegenbuchung {g.quelle_id}")
        return 0
    buchungen = portfolio.lies_ledger(s)
    if a.monat:
        buchungen = [b for b in buchungen if b.datum[:7] == a.monat]
    for b in buchungen:
        print(f"{b.datum}  {b.typ:16} {b.topf:10} {dec.zahl(b.betrag_eur):>12}"
              + f"  {b.symbol or b.isin:12} {b.notiz[:30]:30} [{b.quelle_id}]")
    print(f"\n{len(buchungen)} Buchungen · Cash je Topf: "
          + ", ".join(f"{k} {dec.zahl(v)}" for k, v in portfolio.cash_je_topf(buchungen).items()))
    return 0


def cmd_tr_import(a, s: Settings) -> int:
    """Umsatzliste aus Trade Republic übernehmen — erst zeigen, dann buchen."""
    from . import tr_import

    pfad = Path(a.datei)
    if not pfad.exists():
        print(f"Datei nicht gefunden: {pfad}")
        return 1
    text = pfad.read_text(encoding="utf-8", errors="replace")
    try:
        v = tr_import.vorschau(s, text, a.mit_geld, a.ab)
    except ValueError as exc:
        print(f"Nicht lesbar: {exc}")
        return 1
    print(f"{v['gelesen']} Zeilen gelesen · {v['neu']} neu · {v['bereits_gebucht']} schon gebucht")
    if v["zeitraum"][0]:
        print(f"Zeitraum: {v['zeitraum'][0]} bis {v['zeitraum'][1]}")
    for typ, n in sorted(v["nach_typ"].items()):
        print(f"  {n:4}x {typ}")
    for w in v["warnungen"]:
        print(f"  ⚠️ {w}")
    if a.vorschau:
        print("\nNur Vorschau — ohne --vorschau wird gebucht.")
        return 0
    if not v["neu"]:
        return 0
    r = tr_import.uebernehmen(s, text, a.mit_geld, a.ab)
    print(f"\n{r['gebucht']} Buchungen übernommen.")
    return 0


def cmd_view(a, s: Settings) -> int:
    """Ansicht ohne Netz neu bauen — zum Prüfen und nach manuellen Journal-Änderungen."""
    ziel = view.neu_rechnen(s)
    payload = view.lesen(s) or {}
    n = len(payload.get("entscheidungen") or [])
    dringend = sum(1 for d in payload.get("entscheidungen") or [] if d.get("dringlichkeit", 0) >= 1)
    print(f"{ziel} geschrieben — {n} Entscheidungen, davon {dringend} zu erledigen")
    for d in (payload.get("entscheidungen") or [])[:10]:
        if d.get("dringlichkeit", 0) >= 1:
            print(f"  [{d['verdikt_label']}] {d.get('symbol') or d.get('name')}: {d['begruendung']}")
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

    ks = sub.add_parser("kern-scan", help="Kern-Aktien gegen den Kriterienkatalog prüfen (KERN.md 6)")
    ks.add_argument("--watchlist", action="store_true",
                    help="nur die eigenen Titel aus state/kern_watchlist.yaml — in Sekunden statt Minuten")
    ks.add_argument("--demo", action="store_true", help="synthetisches Universum + erfundene Kennzahlen")
    ks.add_argument("--offline", action="store_true", help="nur aus dem Cache, ohne Netz")
    ks.add_argument("--max", type=int, default=None, dest="max_titel",
                    help="höchstens N Titel prüfen (zum Ausprobieren)")
    ks.set_defaults(func=cmd_kern_scan)

    v = sub.add_parser("view", help="Ansicht (state/view_latest.json) ohne Netz neu bauen")
    v.set_defaults(func=cmd_view)

    pf_ = sub.add_parser("portfolio", help="Kern-Portfolio anzeigen/einrichten")
    pfs = pf_.add_subparsers(dest="unterbefehl")
    pfs.add_parser("show")
    setup = pfs.add_parser("setup", help="Ersteinrichtung")
    setup.add_argument("--start", type=float, required=True, help="Startbetrag gesamt in EUR")
    setup.add_argument("--rate", type=float, required=True, help="Monatsrate in EUR")
    setup.add_argument("--etf", required=True, help="ISIN aus config/etf_universe.yaml")
    setup.add_argument("--etf-anteil", dest="etf_anteil", type=float, default=0.8,
                       help="Anteil des Kerns im ETF (>= 0.8, KERN.md 1)")
    setup.add_argument("--sparplan-tag", dest="sparplan_tag", type=int, default=1)
    setup.add_argument("--force", action="store_true")
    pf_.set_defaults(func=cmd_portfolio, unterbefehl="show")

    tr = sub.add_parser("tr-import", help="Umsatzliste aus Trade Republic übernehmen (pytr-CSV)")
    tr.add_argument("datei")
    tr.add_argument("--vorschau", action="store_true", help="nur zeigen, nichts buchen")
    tr.add_argument("--mit-geld", dest="mit_geld", action="store_true",
                    help="Ein- und Auszahlungen mitbuchen (Standard: aus, das Verrechnungskonto "
                         "ist kein Depot)")
    tr.add_argument("--ab", default=None, help="nur Buchungen ab diesem Datum (JJJJ-MM-TT)")
    tr.set_defaults(func=cmd_tr_import)

    lg = sub.add_parser("ledger", help="Kassenbuch anzeigen/ergänzen")
    lgs = lg.add_subparsers(dest="unterbefehl")
    lst = lgs.add_parser("list"); lst.add_argument("--monat", default=None)
    add = lgs.add_parser("add")
    add.add_argument("--typ", required=True, choices=sorted(portfolio.TYPEN))
    add.add_argument("--topf", required=True, choices=sorted(portfolio.TOEPFE))
    add.add_argument("--betrag", type=float, required=True)
    add.add_argument("--datum", default=None)
    add.add_argument("--isin", default=None); add.add_argument("--symbol", default=None)
    add.add_argument("--stueck", type=float, default=0); add.add_argument("--kurs", type=float, default=0)
    add.add_argument("--gebuehr", type=float, default=0); add.add_argument("--notiz", default=None)
    sto = lgs.add_parser("storno")
    sto.add_argument("schluessel"); sto.add_argument("--notiz", default=None)
    lg.set_defaults(func=cmd_ledger, unterbefehl="list", monat=None)

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

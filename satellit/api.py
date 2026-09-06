"""Kleine HTTP-API (Standardbibliothek) für das Dashboard: Journal-Aktionen, Kontostand, Wochenlauf auslösen.

Nur im Docker-Netz erreichbar (Port 8787), geschützt über den Header X-Satellit-Token (SATELLIT_API_TOKEN).
Alle schreibenden Operationen laufen über dieselben Funktionen wie die CLI.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import threading
import time
import traceback
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import journal, portfolio, regime, universe, view
from .config import Settings
from .data import build_source
from .fx import FxTable, load_fx
from .notify import send_pushover

log = logging.getLogger(__name__)

_RUN_LOCK = threading.Lock()


def _status_path(settings: Settings) -> Path:
    return settings.state_dir / "run_status.json"


def write_run_status(settings: Settings, **fields) -> None:
    p = _status_path(settings)
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = {}
    data.update(fields)
    data["updated"] = datetime.now().isoformat(timespec="seconds")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def write_kern_status(settings: Settings, **fields) -> None:
    """Laufstatus des Kern-Scans — verschachtelt unter `kern` in derselben Datei.

    Eigener Schlüssel statt eigener Datei: das Dashboard liest `run_status.json` ohnehin.
    Flach geschrieben würden `ok`, `error` und `finished` aber die Felder des Wochenlaufs
    überschreiben, und die Oberfläche behauptete nach einem Kern-Scan Dinge über den
    letzten Wochenlauf. Beide teilen sich `_RUN_LOCK` und laufen nie gleichzeitig — ihre
    Statusfelder dürfen sich trotzdem nicht überschreiben.
    """
    p = _status_path(settings)
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = {}
    vorher = data.get("kern")
    data["kern"] = {**(vorher if isinstance(vorher, dict) else {}), **fields,
                    "updated": datetime.now().isoformat(timespec="seconds")}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _demo_modus(settings: Settings) -> bool:
    """War der letzte Wochenlauf ein Demo-Lauf?

    Der Kern-Scan hat keinen eigenen Schalter, und das Dashboard bietet keinen an. Lief der
    Rest des Systems auf synthetischen Daten, muss er das auch: sonst prüft er ein echtes
    Index-Universum, das im Demo-Modus nie heruntergeladen wurde, findet nichts und meldet
    einen Fehlschlag, den niemand einordnen kann.
    """
    p = _status_path(settings)
    if not p.exists():
        return False
    try:
        return bool(json.loads(p.read_text(encoding="utf-8")).get("demo"))
    except Exception:  # noqa: BLE001
        return False


def run_weekly_job(settings: Settings, push: bool = True, as_of: date | None = None, demo: bool = False) -> dict:
    """Wochenlauf mit Statusdatei; wird von CLI, Scheduler und API benutzt."""
    from .pipeline import run_weekly
    from .report import build_push, write_report

    if not _RUN_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "Ein Lauf ist bereits aktiv"}

    letzte_meldung = [0.0]

    def fortschritt(fertig: int, gesamt: int) -> None:
        # Höchstens alle 5 s schreiben — der Erstlauf meldet sonst hunderte Male.
        jetzt = time.monotonic()
        if fertig < gesamt and jetzt - letzte_meldung[0] < 5.0:
            return
        letzte_meldung[0] = jetzt
        write_run_status(settings, fortschritt={"geladen": fertig, "gesamt": gesamt})

    try:
        write_run_status(settings, running=True, started=datetime.now().isoformat(timespec="seconds"),
                         error=None, fortschritt=None)
        res = run_weekly(settings, as_of=as_of, demo=demo, progress=fortschritt)
        path = write_report(res, settings)
        view.schreiben(view.bauen(res, settings), settings)
        title, msg = build_push(res, settings)
        pushed = False
        if push:
            urgent = res.kill_active or any(p.soft_exit or p.hard_stop_hit for p in res.positions)
            pushed = send_pushover(title, msg, priority=1 if urgent else 0,
                                   url=os.environ.get("DASHBOARD_URL") or None)
        write_run_status(settings, running=False, finished=datetime.now().isoformat(timespec="seconds"),
                         ok=True, as_of=res.as_of.isoformat(), report=path, pushed=pushed, demo=demo,
                         candidates=len(res.proposals), failed_symbols=len(res.data_failed))
        return {"ok": True, "report": path, "as_of": res.as_of.isoformat(), "pushed": pushed}
    except Exception as exc:  # noqa: BLE001
        log.exception("Wochenlauf fehlgeschlagen")
        write_run_status(settings, running=False, finished=datetime.now().isoformat(timespec="seconds"),
                         ok=False, error=f"{exc}", trace=traceback.format_exc()[-2000:])
        if push:
            send_pushover("Satellit: Wochenlauf FEHLGESCHLAGEN", f"{exc}"[:900], priority=1)
        return {"ok": False, "error": str(exc)}
    finally:
        _RUN_LOCK.release()


# ---------------------------------------------------------------------- actions
def _latest_screener_row(settings: Settings, symbol: str) -> dict:
    import pandas as pd

    files = sorted(glob.glob(str(settings.reports_dir / "screener_*.csv")))
    if not files:
        return {}
    df = pd.read_csv(files[-1])
    hit = df[df["symbol"].str.upper() == symbol.upper()]
    if hit.empty:
        return {}
    row = hit.iloc[0].to_dict()
    return {k: (None if isinstance(v, float) and v != v else v) for k, v in row.items()}


def _latest_kern_row(settings: Settings, symbol: str) -> dict:
    """Zeile aus dem letzten Kern-Scan. Kern-Titel stehen nicht zwingend im Screener-Universum,
    und ohne diese Rückfallquelle scheiterte das Anlegen einer Kern-These an fehlendem Kurs."""
    import pandas as pd

    files = sorted(glob.glob(str(settings.reports_dir / "kern_*.csv")))
    if not files:
        return {}
    try:
        df = pd.read_csv(files[-1])
    except Exception:  # noqa: BLE001
        return {}
    hit = df[df["symbol"].astype(str).str.upper() == symbol.upper()]
    if hit.empty:
        return {}
    row = hit.iloc[0].to_dict()
    return {k: (None if isinstance(v, float) and v != v else v) for k, v in row.items()}


def _kern_ausschluss_ergaenzen(settings: Settings, symbol: str, isin: str, name: str) -> bool:
    """ISIN/Symbol unter `core_holdings` in config/exclusions.yaml eintragen.

    Scheitert das (Datei schreibgeschützt im Container), ist das kein Grund, die These zu
    verwerfen — der Doppelhalten-Schutz fehlt dann, die These ist aber angelegt. Deshalb
    Rückgabewert statt Ausnahme: der Aufrufer kann es melden.
    """
    import yaml

    pfad = settings.path("exclusions_file")
    try:
        daten = yaml.safe_load(pfad.read_text(encoding="utf-8")) if pfad.exists() else {}
        daten = daten if isinstance(daten, dict) else {}
        gruppe = daten.setdefault("core_holdings", []) or []
        for e in gruppe:
            if isinstance(e, dict) and (
                    (isin and str(e.get("isin", "")).upper() == isin.upper())
                    or (symbol and str(e.get("symbol", "")).upper() == symbol.upper())):
                return True
        eintrag = {"note": f"Kern-Aktie {name} (automatisch beim Anlegen der These)"}
        if isin:
            eintrag["isin"] = isin
        if symbol:
            eintrag["symbol"] = symbol
        gruppe.append(eintrag)
        daten["core_holdings"] = gruppe
        pfad.write_text(yaml.safe_dump(daten, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Ausschlussliste nicht schreibbar (%s) — %s bitte von Hand eintragen", exc, symbol)
        return False


def action_journal_new(settings: Settings, body: dict) -> dict:
    symbol = str(body.get("symbol", "")).strip().upper()
    if not symbol:
        raise ValueError("symbol fehlt")
    core = bool(body.get("core", False))
    row = _latest_screener_row(settings, symbol)
    kern_row = _latest_kern_row(settings, symbol) if core else {}

    # KERN.md 6, Kriterien 1 und 7 — die beiden, die kein Code beantworten kann. Ohne sie
    # entsteht keine These, und ohne These kein Kauf (Trading-Plan 3.2).
    kill: list[str] = []
    statement = body.get("statement")
    if core:
        geschaeftsmodell = str(body.get("geschaeftsmodell") or "").strip()
        kill = [str(body.get(f"kill_{i}") or "").strip() for i in (1, 2)]
        kill = [k for k in kill if k] + [str(k).strip() for k in (body.get("kill_criteria") or [])]
        if not geschaeftsmodell:
            raise ValueError("Kriterium 1: Beschreib das Geschäftsmodell in zwei Sätzen — womit "
                             "verdient das Unternehmen Geld, und warum kauft der Kunde dort?")
        if len(kill) < 2:
            raise ValueError("Kriterium 7: Zwei konkrete Kill-Kriterien sind Pflicht — Ereignisse, "
                             "bei denen du verkaufst (Trading-Plan 3.2).")
        statement = statement or f"{body.get('name') or symbol} ({symbol}): {geschaeftsmodell}"

    entry = body.get("entry", kern_row.get("kurs_eur") or row.get("close"))
    stop = body.get("stop", 0.0 if core else row.get("initial_stop"))
    if core and entry is None:
        # Der Kurs ist bei einer Kern-These reine Dokumentation — es gibt keinen Stop und
        # keine Positionsgröße, die davon abhinge. Er darf das Anlegen nicht verhindern.
        entry = 0.0
    if entry is None or stop is None:
        raise ValueError("entry/stop fehlen (Symbol nicht im letzten Screener-Lauf)")
    region = body.get("region") or row.get("region") or kern_row.get("region") or ("US" if "." not in symbol else "EU")
    currency = body.get("currency") or row.get("currency") or ("USD" if region == "US" else "EUR")
    sector = body.get("sector") or row.get("sector") or kern_row.get("sektor") or "Unknown"
    isin = body.get("isin") or row.get("isin") or kern_row.get("isin") or ""
    # Der Kern kennt keine Ampel (Trading-Plan 2) — sie würde in der These nur so aussehen,
    # als hätte sie beim Kauf eine Rolle gespielt.
    ampel = None if core else (regime.last_known(settings, region) or {}).get("effective")
    reports = sorted(glob.glob(str(settings.reports_dir / "weekly_*.md")))
    tid = journal.new_thesis(
        settings, symbol=symbol, isin=isin,
        name=body.get("name") or row.get("name") or kern_row.get("name") or symbol,
        region=region, currency=currency, sector=sector, entry=float(entry), stop=float(stop),
        breakout_level=row.get("breakout_level"), rs_rank_pct=row.get("rs_rank_pct"), ampel=ampel,
        report_file=os.path.basename(reports[-1]) if reports else "dashboard", statement=statement,
        setup_type="core_holding" if core else "trendfolge_20w", review_days=180 if core else 7,
        kill_criteria=kill or None,
    )
    out = {"thesis_id": tid, "symbol": symbol, "entry": float(entry), "stop": float(stop), "ampel": ampel}
    if core:
        # KERN.md 6, Ablauf Schritt 3: die ISIN gehört in die Ausschlussliste, damit der
        # Screener den Titel nicht zusätzlich im Satelliten vorschlägt (Regel 3.5, kein
        # Doppelhalten). Bisher war das ein Handgriff, den nichts erzwang und nichts prüfte.
        out["ausgeschlossen"] = _kern_ausschluss_ergaenzen(settings, symbol, isin,
                                                           body.get("name") or symbol)
    acc = journal.Account.load(settings)
    if not core and acc.satellite_equity_eur:
        try:
            fx = load_fx(build_source(settings), {currency}) if not body.get("no_fx") else FxTable({}, "fallback")
            risk = journal.effective_risk_pct(settings, ampel)
            report, path = journal.size_position(settings, entry=float(entry), stop=float(stop), currency=currency, fx=fx,
                                                 equity_eur=acc.satellite_equity_eur, risk_pct=risk, sector=sector)
            journal.attach_sizing(settings, tid, path)
            out.update({"shares": report.get("final_recommended_shares"), "value_eur": report.get("final_position_value"),
                        "risk_eur": report.get("final_risk_dollars"), "risk_pct": risk})
        except Exception as exc:  # noqa: BLE001
            out["sizing_error"] = str(exc)
    return out


def action_journal_open(settings: Settings, body: dict) -> dict:
    when = body.get("date") or date.today().isoformat()
    t = journal.open_position(settings, body["id"], float(body["price"]), journal.now_iso(date.fromisoformat(when)),
                              float(body["shares"]) if body.get("shares") is not None else None)
    return {"thesis_id": t["thesis_id"], "status": t["status"], "shares": (t.get("position") or {}).get("shares")}


def action_journal_close(settings: Settings, body: dict) -> dict:
    when = body.get("date") or date.today().isoformat()
    t = journal.close_position(settings, body["id"], float(body["price"]), journal.now_iso(date.fromisoformat(when)),
                               body.get("reason", "manual"))
    o = t.get("outcome") or {}
    return {"thesis_id": t["thesis_id"], "status": t["status"], "pnl": o.get("pnl_dollars"), "pnl_pct": o.get("pnl_pct"),
            "r": journal.r_multiple(t), "rule_break": body.get("reason") == "manual"}


def action_journal_stop(settings: Settings, body: dict) -> dict:
    t = journal.update_stop(settings, body["id"], float(body["stop"]), body.get("note") or "Trailing-Stop (Dashboard)")
    return {"thesis_id": t["thesis_id"], "stop": (t.get("exit") or {}).get("stop_loss")}


def action_account(settings: Settings, body: dict) -> dict:
    acc = journal.Account.load(settings)
    if body.get("equity") is not None:
        acc.set_equity(float(body["equity"]))
    if "dry_run_until" in body:
        acc.dry_run_until = body["dry_run_until"] or None
    if body.get("reset_kill"):
        acc.kill_switch_active, acc.kill_switch_reason = False, ""
    acc.save(settings)
    return acc.__dict__


MAX_IMPORT_BYTES = 5 * 1024 * 1024


def action_universe_import(settings: Settings, body: dict) -> dict:
    """Holdings-CSV aus dem Dashboard übernehmen.

    Das Dashboard mountet state/ nur lesend, deshalb schickt der Browser den Dateiinhalt
    hierher statt ihn selbst abzulegen.
    """
    inhalt = body.get("inhalt") or ""
    if not inhalt.strip():
        raise ValueError("Kein Dateiinhalt übermittelt")
    if len(inhalt.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ValueError(f"Datei zu groß (Grenze {MAX_IMPORT_BYTES // 1024 // 1024} MB)")
    anzahl, ziel = universe.import_holdings(settings, str(body.get("region") or "").upper(), inhalt)
    return {"region": body.get("region"), "titel": anzahl, "datei": ziel.name}


def action_ledger_add(settings: Settings, body: dict) -> dict:
    """Eine Geldbewegung buchen. Die Prüfung steckt im Buchungstyp selbst."""
    b = portfolio.Buchung(
        datum=str(body.get("datum") or date.today().isoformat()),
        typ=str(body["typ"]), topf=str(body["topf"]),
        betrag_eur=float(body.get("betrag_eur") or 0), isin=str(body.get("isin") or ""),
        symbol=str(body.get("symbol") or ""), waehrung=str(body.get("waehrung") or "EUR"),
        stueck=float(body.get("stueck") or 0), kurs=float(body.get("kurs") or 0),
        gebuehr_eur=float(body.get("gebuehr_eur") or 0), thesis_id=str(body.get("thesis_id") or ""),
        notiz=str(body.get("notiz") or ""), quelle="dashboard",
    )
    if date.fromisoformat(b.datum) > date.today():
        raise ValueError("Das Datum liegt in der Zukunft.")
    if b.topf == "kern_aktie" and b.betrag_eur > 0:
        # Trading-Plan 3.3 und KERN.md 1: höchstens 5 % je Titel, höchstens 20 % des Kerns in
        # Einzelaktien. Die Prüfung existierte seit Langem als portfolio.kern_grenze_ok, wurde
        # aber von nirgendwo aufgerufen — CHANGELOG_REGELN behauptete trotzdem, das Dashboard
        # erzwinge die Grenzen. Hier wird das eingelöst.
        z = portfolio.zusammenfassung(settings)
        ok, grund = portfolio.kern_grenze_ok(z["werte"], settings, b.isin, b.betrag_eur)
        if not ok:
            raise ValueError(grund)
        if not b.thesis_id and not _hat_kern_these(settings, b.symbol, b.isin):
            raise ValueError("Vor dem Kauf braucht jede Kern-Aktie eine schriftliche These mit "
                             "Kill-Kriterien (Trading-Plan 3.2). Lege sie zuerst an.")
    portfolio.schreibe_buchung(settings, b)
    return {"gebucht": b.quelle_id, "typ": b.typ, "topf": b.topf, "betrag_eur": b.betrag_eur}


def _hat_kern_these(settings: Settings, symbol: str, isin: str) -> bool:
    """„Ohne These kein Kauf" (Trading-Plan 3.2) — hier durchgesetzt statt nur behauptet."""
    symbol, isin = (symbol or "").upper(), (isin or "").upper()
    for these in journal.core_positions(settings):
        prov = (these.get("origin") or {}).get("raw_provenance") or {}
        kandidaten = {str(prov.get("symbol") or "").upper(), str(these.get("ticker") or "").upper(),
                      str(prov.get("isin") or "").upper()}
        if (symbol and symbol in kandidaten) or (isin and isin in kandidaten):
            return True
    return False


def action_kern_watchlist(settings: Settings, body: dict) -> dict:
    """Eigene Kern-Kandidaten pflegen. `entfernen=true` nimmt einen Titel wieder heraus."""
    from . import kern_scan

    symbol = str(body.get("symbol") or "").strip().upper()
    if body.get("entfernen"):
        return {"titel": kern_scan.watchlist_entfernen(settings, symbol)}
    return {"titel": kern_scan.watchlist_ergaenzen(
        settings, symbol, name=str(body.get("name") or ""), isin=str(body.get("isin") or ""),
        notiz=str(body.get("notiz") or ""))}


def action_kern_scan(settings: Settings, body: dict) -> dict:
    """Kern-Kandidaten prüfen.

    Der volle Universumslauf ruft je Titel Jahresabschlüsse ab und dauert rund eine Stunde
    — deshalb läuft er wie der Wochenlauf im Hintergrund und meldet seinen Fortschritt über
    `run_status.json`. `nur_watchlist=true` prüft nur die eigenen Titel und ist in Sekunden
    fertig, läuft deshalb direkt in der Anfrage.
    """
    from . import kern_scan as ks_modul

    nur_watchlist = bool(body.get("nur_watchlist", False))
    # Der Modus folgt dem letzten Wochenlauf, lässt sich für die CLI aber überschreiben.
    demo = bool(body["demo"]) if "demo" in body else _demo_modus(settings)
    if not nur_watchlist:
        if _RUN_LOCK.locked():
            raise ValueError("Es läuft bereits ein Lauf. Bitte abwarten.")
        threading.Thread(target=_kern_scan_job, args=(settings,), kwargs={"demo": demo},
                         daemon=True).start()
        return {"gestartet": True, "umfang": "universum", "demo": demo}
    res = ks_modul.run_kern_scan(settings, nur_watchlist=True, demo=demo)
    ks_modul.stand_uebernehmen(settings, res)
    if res.fehler:
        # Als Ausnahme, nicht als leeres Ergebnis: die Oberfläche zeigt Fehler rot an, ein
        # „0 geprüft" dagegen als gültiges Prüfergebnis.
        raise ValueError(res.fehler)
    return {"gestartet": False, "umfang": "watchlist", "geprueft": res.geprueft,
            "bestanden": len(res.bestanden), "trichter": res.trichter}


def _kern_scan_job(settings: Settings, demo: bool = False) -> None:
    """Der volle Universumslauf im Hintergrund — mit Fortschritt und sichtbarem Fehlschlag.

    Ohne Statusschreiben waren „läuft noch", „lief ins Leere" und „abgestürzt" für den
    Nutzer nicht unterscheidbar: die Oberfläche sagte in allen drei Fällen dasselbe.
    """
    from . import kern_scan as ks_modul

    letzte_meldung = [0.0]

    def fortschritt(fertig: int, gesamt: int) -> None:
        # Gedrosselt wie beim Wochenlauf — sonst schreibt ein Lauf über 1.100 Titel die
        # Statusdatei 1.100-mal.
        jetzt = time.monotonic()
        if fertig < gesamt and jetzt - letzte_meldung[0] < 5.0:
            return
        letzte_meldung[0] = jetzt
        write_kern_status(settings, fortschritt={"geprueft": fertig, "gesamt": gesamt})

    with _RUN_LOCK:
        write_kern_status(settings, running=True, ok=None, error=None, fortschritt=None,
                          demo=demo, started=datetime.now().isoformat(timespec="seconds"))
        try:
            res = ks_modul.run_kern_scan(settings, demo=demo, progress=fortschritt)
            ks_modul.stand_uebernehmen(settings, res)
        except Exception as exc:  # noqa: BLE001
            log.exception("Kern-Scan fehlgeschlagen: %s", exc)
            write_kern_status(settings, running=False, ok=False, error=f"{exc}",
                              trace=traceback.format_exc()[-2000:], fortschritt=None,
                              finished=datetime.now().isoformat(timespec="seconds"))
        else:
            log.info("Kern-Scan fertig: %d geprüft, %d bestanden", res.geprueft, len(res.bestanden))
            write_kern_status(settings, running=False, ok=not res.fehler, error=res.fehler,
                              geprueft=res.geprueft, bestanden=len(res.bestanden),
                              fortschritt=None,
                              finished=datetime.now().isoformat(timespec="seconds"))
    ansicht_auffrischen(settings)


def action_ledger_storno(settings: Settings, body: dict) -> dict:
    g = portfolio.storniere(settings, str(body["quelle_id"]), str(body.get("notiz") or "Korrektur"))
    return {"storno": g.quelle_id, "hebt_auf": g.thesis_id}


def action_depot_abgleich(settings: Settings, body: dict) -> dict:
    """Differenz zwischen gerechnetem und tatsächlichem Depotwert als Korrektur buchen.

    Die Gegenmaßnahme gegen vergessene Buchungen: ohne sie driftet das Kassenbuch still
    vom echten Depot weg, und alle abgeleiteten Zahlen mit ihm.
    """
    ist = float(body["wert_eur"])
    plan = portfolio.lade_plan(settings)
    z = portfolio.zusammenfassung(settings)
    soll = z["werte"].gesamt_eur
    diff = round(ist - soll, 2)
    heute = date.today().isoformat()
    if abs(diff) >= 0.01:
        portfolio.schreibe_buchung(settings, portfolio.Buchung(
            datum=heute, typ="korrektur", topf="cash", betrag_eur=abs(diff),
            notiz=f"Depotabgleich: {'Fehlbetrag' if diff > 0 else 'Überhang'} {abs(diff):.2f} EUR",
            quelle="dashboard"))
    plan.depotwert_abgleich = {"datum": heute, "wert_eur": ist}
    portfolio.speichere_plan(settings, plan)
    return {"gerechnet_eur": soll, "app_eur": ist, "differenz_eur": diff}


def action_portfolio_katalog(settings: Settings, body: dict) -> dict:
    """ETF-Auswahlliste direkt liefern.

    Das Onboarding bekommt den Katalog sonst nur über state/view_latest.json — und genau
    dort ist er veraltet, solange kein Lauf stattgefunden hat. Im Onboarding gibt es aber
    noch keine Aktion, die eine Auffrischung auslösen könnte. Also holt es ihn direkt.
    """
    return {"etfs": portfolio.lade_etf_katalog(settings)}


def action_portfolio_setup(settings: Settings, body: dict) -> dict:
    """Ersteinrichtung aus dem Onboarding."""
    plan = portfolio.lade_plan(settings)
    if plan.onboarding_erledigt and not body.get("force"):
        raise ValueError("Das Portfolio ist bereits eingerichtet.")
    eingabe = str(body.get("etf_isin") or "").strip().upper()
    katalog = {e["isin"]: e for e in portfolio.lade_etf_katalog(settings)}
    if katalog:
        etf = katalog.get(eingabe)
        if etf is None:
            raise ValueError("Unbekannte ETF-ISIN — bitte aus der Liste wählen.")
    else:
        # Ohne Katalog (config/etf_universe.yaml fehlt) darf die Einrichtung nicht scheitern.
        # Streng prüfen, wo geprüft werden kann; sonst die Eingabe übernehmen und den
        # fehlenden Kurs-Symbolnamen ehrlich offen lassen — die Bewertung fällt dann auf
        # den Einstand zurück und meldet das.
        if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", eingabe):
            raise ValueError("Das sieht nicht nach einer ISIN aus (12 Zeichen, z. B. IE00BK5BQT80).")
        etf = {"isin": eingabe, "symbol": str(body.get("etf_symbol") or ""),
               "name": str(body.get("etf_name") or eingabe)}
    anteil = float(body.get("etf_anteil", 0.8))
    if anteil < 0.8:
        raise ValueError("Mindestens 80 % des Kerns gehören in den ETF (KERN.md 1).")
    start = float(body["start_eur"])
    kern = round(start * float(settings.get("portfolio.core_share", 0.90)), 2)
    heute = date.today()
    plan = portfolio.Plan(
        start_datum=heute.isoformat(), monatsrate_eur=float(body.get("rate_eur") or 0),
        sparplan_tag=int(body.get("sparplan_tag") or 1),
        etf={"isin": etf["isin"], "symbol": etf["symbol"], "name": etf["name"], "anteil_kern": anteil},
        startbetrag={"modus": "einmalkauf", "kern_eur": kern, "satellit_eur": round(start - kern, 2),
                     "ersteinstieg_aktien_offen": anteil < 1.0},
        onboarding_erledigt=True,
    )
    portfolio.speichere_plan(settings, plan)
    n = portfolio.schreibe_buchungen(settings, portfolio.startbetrag_buchungen(plan, heute))
    # Trading-Plan 10.1: Vorgabe sind zwei Wochenenden Trockenlauf, bevor Orders zulässig sind.
    # Abwählbar, weil es eine Datenprüfung ist und keine Marktregel — wer die erste Ampel-
    # Auswertung von Hand gegenliest, braucht die Frist nicht. Der Kern ist ohnehin nie gesperrt.
    tage = int(body.get("trockenlauf_tage", settings.get("start.trockenlauf_tage", 14)))
    if tage < 0:
        raise ValueError("Der Trockenlauf kann nicht negativ sein.")
    acc = journal.Account.load(settings)
    acc.dry_run_until = (heute + timedelta(days=tage)).isoformat() if tage > 0 else None
    acc.set_equity(round(start - kern, 2), heute)
    acc.save(settings)
    return {"etf": etf["name"], "kern_eur": kern, "satellit_eur": round(start - kern, 2),
            "buchungen": n, "trockenlauf_bis": acc.dry_run_until}


def action_portfolio_reset(settings: Settings, body: dict) -> dict:
    """Die Einrichtung rückgängig machen, damit das Onboarding erneut läuft.

    Nicht gelöscht, sondern storniert: das Kassenbuch kennt nur Gegenbuchungen, und die
    Historie bleibt nachvollziehbar (portfolio.storniere). Betroffen sind ausschließlich die
    Eröffnungsbuchungen der Einrichtung — spätere Käufe, Sparplan-Ausführungen und Importe
    bleiben unangetastet, sonst würde ein „Neu einrichten" stillschweigend Geschichte tilgen.

    Offene Satelliten-Positionen blockieren den Reset: Kapital und Journal liefen danach
    auseinander, und der Kill-Switch misst gegen einen Hochstand, den es nicht mehr gibt.
    `force=true` überstimmt das ausdrücklich.
    """
    offen = journal.open_positions(settings)
    if offen and not body.get("force"):
        symbole = ", ".join(sorted(journal.provenance(t).get("symbol") or t.get("ticker", "?")
                                   for t in offen))
        raise ValueError(f"Es sind noch {len(offen)} Satelliten-Positionen offen ({symbole}). "
                         f"Schließ sie zuerst im Journal — sonst rechnet das System danach mit "
                         f"Kapital, das im Journal noch gebunden ist.")

    buchungen = portfolio.lies_ledger(settings)
    wirksam = {b.quelle_id for b in portfolio._wirksame(buchungen)}
    storniert = 0
    for b in buchungen:
        if b.quelle_id in wirksam and str(b.notiz or "").startswith("Startbetrag"):
            portfolio.storniere(settings, b.quelle_id, "Einrichtung zurückgesetzt")
            storniert += 1

    plan = portfolio.lade_plan(settings)
    plan.onboarding_erledigt = False
    plan.startbetrag = {}
    portfolio.speichere_plan(settings, plan)

    acc = journal.Account.load(settings)
    acc.satellite_equity_eur = None
    acc.high_water_mark = None
    acc.dry_run_until = None
    acc.kill_switch_active = False
    acc.kill_switch_reason = ""
    acc.save(settings)
    return {"storniert": storniert, "offene_positionen": len(offen),
            "hinweis": "Beim nächsten Laden erscheint wieder die Einrichtung."}


def action_portfolio_import(settings: Settings, body: dict) -> dict:
    """Umsatzliste aus Trade Republic übernehmen — zweistufig.

    Ohne `uebernehmen=true` wird nur gezeigt, was gebucht würde. Das Format stammt aus
    einem inoffiziellen Werkzeug und ist nirgends dokumentiert; blind zu schreiben wäre
    unverantwortlich.
    """
    from . import tr_import

    inhalt = body.get("inhalt") or ""
    if not inhalt.strip():
        raise ValueError("Kein Dateiinhalt übermittelt")
    if len(inhalt.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ValueError(f"Datei zu groß (Grenze {MAX_IMPORT_BYTES // 1024 // 1024} MB)")
    optionen = {"mit_geldbewegungen": bool(body.get("mit_geldbewegungen")),
                "ab": str(body["ab"]) if body.get("ab") else None}
    if body.get("uebernehmen"):
        return tr_import.uebernehmen(settings, inhalt, **optionen)
    return tr_import.vorschau(settings, inhalt, **optionen)


ACTIONS = {
    "/journal/new": action_journal_new,
    "/journal/open": action_journal_open,
    "/journal/close": action_journal_close,
    "/journal/stop": action_journal_stop,
    "/account": action_account,
    "/universe/import": action_universe_import,
    "/ledger/add": action_ledger_add,
    "/ledger/storno": action_ledger_storno,
    "/depot/abgleich": action_depot_abgleich,
    "/portfolio/setup": action_portfolio_setup,
    "/portfolio/katalog": action_portfolio_katalog,
    "/portfolio/import": action_portfolio_import,
    "/portfolio/reset": action_portfolio_reset,
    "/kern/scan": action_kern_scan,
    "/kern/watchlist": action_kern_watchlist,
}


# ---------------------------------------------------------------------- server
def ansicht_auffrischen(settings: Settings) -> bool:
    """view_latest.json nach einer schreibenden Aktion neu bauen.

    Läuft gerade ein Wochenlauf, wird übersprungen: er schreibt die Ansicht am Ende ohnehin,
    und zwei gleichzeitige Schreiber auf dieselbe Datei sind der sichere Weg zu halbem JSON.
    Ein Fehlschlag darf die Aktion nie scheitern lassen — die Buchung ist schon passiert.
    """
    if _RUN_LOCK.locked():
        log.info("Ansicht nicht aufgefrischt: Wochenlauf aktiv")
        return False
    try:
        view.neu_rechnen(settings)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Ansicht konnte nicht aufgefrischt werden: %s", exc)
        return False


def make_handler(settings: Settings, token: str):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            return bool(token) and self.headers.get("X-Satellit-Token", "") == token

        def log_message(self, fmt, *args):  # noqa: D401
            log.info("api %s", fmt % args)

        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                st = _status_path(settings)
                status = json.loads(st.read_text(encoding="utf-8")) if st.exists() else {}
                self._send(200, {"ok": True, "run_status": status})
                return
            self._send(404, {"ok": False, "error": "not found"})

        def do_POST(self):  # noqa: N802
            if not self._authorized():
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._send(400, {"ok": False, "error": "invalid json"})
                return
            if self.path == "/run/weekly":
                if _RUN_LOCK.locked():
                    self._send(409, {"ok": False, "error": "Ein Lauf ist bereits aktiv"})
                    return
                threading.Thread(target=run_weekly_job, args=(settings,),
                                 kwargs={"push": bool(body.get("push", True)), "demo": bool(body.get("demo", False))},
                                 daemon=True).start()
                self._send(202, {"ok": True, "started": True})
                return
            fn = ACTIONS.get(self.path)
            if fn is None:
                self._send(404, {"ok": False, "error": "not found"})
                return
            try:
                ergebnis = fn(settings, body)
            except Exception as exc:  # noqa: BLE001
                log.warning("API %s fehlgeschlagen: %s", self.path, exc)
                self._send(400, {"ok": False, "error": str(exc)})
                return
            ansicht_auffrischen(settings)
            self._send(200, {"ok": True, "result": ergebnis})

    return Handler


def serve_api(settings: Settings, host: str = "0.0.0.0", port: int = 8787, block: bool = True) -> ThreadingHTTPServer:
    token = os.environ.get("SATELLIT_API_TOKEN", "")
    if not token:
        log.warning("SATELLIT_API_TOKEN nicht gesetzt — schreibende API-Aufrufe werden abgelehnt")
    server = ThreadingHTTPServer((host, port), make_handler(settings, token))
    log.info("API lauscht auf %s:%d", host, port)
    if block:
        server.serve_forever()
    else:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    return server

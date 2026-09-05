"""Kleine HTTP-API (Standardbibliothek) für das Dashboard: Journal-Aktionen, Kontostand, Wochenlauf auslösen.

Nur im Docker-Netz erreichbar (Port 8787), geschützt über den Header X-Satellit-Token (SATELLIT_API_TOKEN).
Alle schreibenden Operationen laufen über dieselben Funktionen wie die CLI.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import threading
import traceback
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import journal, regime
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


def run_weekly_job(settings: Settings, push: bool = True, as_of: date | None = None, demo: bool = False) -> dict:
    """Wochenlauf mit Statusdatei; wird von CLI, Scheduler und API benutzt."""
    from .pipeline import run_weekly
    from .report import build_push, write_report

    if not _RUN_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "Ein Lauf ist bereits aktiv"}
    try:
        write_run_status(settings, running=True, started=datetime.now().isoformat(timespec="seconds"), error=None)
        res = run_weekly(settings, as_of=as_of, demo=demo)
        path = write_report(res, settings)
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


def action_journal_new(settings: Settings, body: dict) -> dict:
    symbol = str(body.get("symbol", "")).strip().upper()
    if not symbol:
        raise ValueError("symbol fehlt")
    core = bool(body.get("core", False))
    row = _latest_screener_row(settings, symbol)
    entry = body.get("entry", row.get("close"))
    stop = body.get("stop", 0.0 if core else row.get("initial_stop"))
    if entry is None or stop is None:
        raise ValueError("entry/stop fehlen (Symbol nicht im letzten Screener-Lauf)")
    region = body.get("region") or row.get("region") or ("US" if "." not in symbol else "EU")
    currency = body.get("currency") or row.get("currency") or ("USD" if region == "US" else "EUR")
    sector = body.get("sector") or row.get("sector") or "Unknown"
    ampel = (regime.last_known(settings, region) or {}).get("effective")
    reports = sorted(glob.glob(str(settings.reports_dir / "weekly_*.md")))
    tid = journal.new_thesis(
        settings, symbol=symbol, isin=body.get("isin") or row.get("isin") or "", name=body.get("name") or row.get("name") or symbol,
        region=region, currency=currency, sector=sector, entry=float(entry), stop=float(stop),
        breakout_level=row.get("breakout_level"), rs_rank_pct=row.get("rs_rank_pct"), ampel=ampel,
        report_file=os.path.basename(reports[-1]) if reports else "dashboard", statement=body.get("statement"),
        setup_type="core_holding" if core else "trendfolge_20w", review_days=180 if core else 7,
    )
    out = {"thesis_id": tid, "symbol": symbol, "entry": float(entry), "stop": float(stop), "ampel": ampel}
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


ACTIONS = {
    "/journal/new": action_journal_new,
    "/journal/open": action_journal_open,
    "/journal/close": action_journal_close,
    "/journal/stop": action_journal_stop,
    "/account": action_account,
}


# ---------------------------------------------------------------------- server
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
                self._send(200, {"ok": True, "result": fn(settings, body)})
            except Exception as exc:  # noqa: BLE001
                log.warning("API %s fehlgeschlagen: %s", self.path, exc)
                self._send(400, {"ok": False, "error": str(exc)})

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

"""Journal-Anbindung an trader-memory-core (vendored) + Kontostand, Positionen, Kill-Switch.

Konventionen (siehe Trading-Plan, Abschnitt 11):
- thesis_type = pivot_breakout, setup_type = "trendfolge_20w" (Satellit) bzw. "core_holding" (Kern)
- exit_reason: stop_hit = harter Stop, time_stop = weicher Exit (Trendbruch; das Schema kennt
  keinen Trend-Exit), manual = Regelbruch
- origin.raw_provenance trägt ISIN, Region, Währung, Ausbruchsniveau, RS-Rang, Ampelstand
"""

from __future__ import annotations

import glob
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml

from .config import Settings
from .fx import FxTable

log = logging.getLogger(__name__)

EXIT_REASONS = {"stop": "stop_hit", "trend": "time_stop", "manual": "manual", "invalidated": "invalidated"}


def journal_ticker(symbol: str) -> str:
    """trader-memory-core erlaubt im Ticker nur [A-Za-z0-9]: 'SAP.DE' -> 'SAPDE', 'ERIC-B.ST' -> 'ERICBST'.
    Das echte Yahoo-Symbol steht in origin.raw_provenance.symbol."""
    import re
    return re.sub(r"[^A-Za-z0-9]", "", symbol).upper()


def _store(settings: Settings):
    scripts = settings.vendor_skills_dir / "trader-memory-core" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import thesis_store  # noqa: WPS433
    return thesis_store


# ------------------------------------------------------------------ account state
@dataclass
class Account:
    satellite_equity_eur: float | None = None
    updated: str | None = None
    high_water_mark: float | None = None
    kill_switch_active: bool = False
    kill_switch_reason: str = ""
    dry_run_until: str | None = None      # ISO-Datum: bis dahin keine Orders (Trockenlauf)

    @classmethod
    def load(cls, settings: Settings) -> "Account":
        p = settings.state_dir / "account.yaml"
        if not p.exists():
            return cls()
        with open(p, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls(**{k: data.get(k) for k in cls.__dataclass_fields__ if k in data})

    def save(self, settings: Settings) -> None:
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        with open(settings.state_dir / "account.yaml", "w", encoding="utf-8") as fh:
            yaml.safe_dump(self.__dict__, fh, sort_keys=False, allow_unicode=True)

    def set_equity(self, value: float, today: date | None = None) -> None:
        today = today or date.today()
        self.satellite_equity_eur = float(value)
        self.updated = today.isoformat()
        if self.high_water_mark is None or value > self.high_water_mark:
            self.high_water_mark = float(value)

    @property
    def drawdown(self) -> float | None:
        if not self.satellite_equity_eur or not self.high_water_mark:
            return None
        return 1.0 - self.satellite_equity_eur / self.high_water_mark


# ------------------------------------------------------------------ theses
def list_theses(settings: Settings, status: str | None = None) -> list[dict]:
    store = _store(settings)
    ids = store.query(settings.theses_dir, status=status)
    out = []
    for entry in ids:
        tid = entry["thesis_id"] if isinstance(entry, dict) else entry
        try:
            out.append(store.get(settings.theses_dir, tid))
        except Exception as exc:  # noqa: BLE001
            log.warning("These %s nicht lesbar: %s", tid, exc)
    return out


def open_positions(settings: Settings) -> list[dict]:
    """ACTIVE + PARTIALLY_CLOSED Satelliten-Thesen (Kern-Holdings ausgenommen)."""
    theses = list_theses(settings, "ACTIVE") + list_theses(settings, "PARTIALLY_CLOSED")
    return [t for t in theses if (t.get("setup_type") or "") != "core_holding"]


def closed_theses(settings: Settings) -> list[dict]:
    return [t for t in list_theses(settings, "CLOSED") if (t.get("setup_type") or "") != "core_holding"]


def provenance(thesis: dict) -> dict:
    return ((thesis.get("origin") or {}).get("raw_provenance") or {})


def new_thesis(settings: Settings, *, symbol: str, isin: str, name: str, region: str, currency: str,
               sector: str, entry: float, stop: float, breakout_level: float | None, rs_rank_pct: float | None,
               ampel: str | None, report_file: str, statement: str | None = None,
               setup_type: str = "trendfolge_20w", thesis_type: str = "pivot_breakout",
               review_days: int = 7, kill_criteria: list[str] | None = None) -> str:
    store = _store(settings)
    stop_pct = (entry - stop) / entry * 100.0 if entry else None
    data = {
        "ticker": journal_ticker(symbol),
        "thesis_type": thesis_type,
        "setup_type": setup_type,
        "thesis_statement": statement or (
            f"{name} ({symbol}): Ausbruch auf 20-Wochen-Hoch bei intaktem Trend, RS-Rang "
            f"{(rs_rank_pct or 0) * 100:.0f} % in {region}. Initialstop {stop:.2f} {currency}."),
        "mechanism_tag": "behavior",
        "evidence": [
            f"Close > SMA200, SMA50 > SMA200",
            f"Ausbruchsniveau {breakout_level:.2f} {currency}" if breakout_level else "Ausbruch",
            f"Ampel {region}: {ampel or 'n/a'}",
        ],
        "kill_criteria": kill_criteria or [
            "Harter Stop (Stop-Market beim Broker) ausgelöst",
            "Wochenschluss unter SMA(10 Wochen) -> Verkauf Montag",
        ],
        "exit": {"stop_loss": float(stop), "stop_loss_pct": float(stop_pct) if stop_pct else None},
        "market_context": {"regime": ampel, "sector": sector},
        "monitoring": {"review_interval_days": int(review_days)},
        "origin": {
            "skill": "satellit-screener",
            "output_file": report_file,
            "raw_provenance": {
                "isin": isin, "region": region, "currency": currency, "symbol": symbol,
                "breakout_level": breakout_level, "rs_rank_pct": rs_rank_pct, "ampel": ampel,
                "initial_stop": float(stop), "planned_entry": float(entry),
            },
        },
    }
    tid = store.register(settings.theses_dir, data)
    store.transition(settings.theses_dir, tid, "ENTRY_READY", reason="Kandidat bestätigt (Sichtkontrolle)")
    return tid


def size_position(settings: Settings, *, entry: float, stop: float, currency: str, fx: FxTable,
                  equity_eur: float, risk_pct: float, sector: str | None = None,
                  current_sector_pct: float | None = None) -> tuple[dict, str]:
    """position-sizer (vendored) in EUR aufrufen. Gibt (Report-Dict, JSON-Pfad) zurück."""
    script = settings.vendor_skills_dir / "position-sizer" / "scripts" / "position_sizer.py"
    out_dir = settings.reports_dir / "sizing"
    out_dir.mkdir(parents=True, exist_ok=True)
    entry_eur = fx.to_eur(entry, currency)
    stop_eur = fx.to_eur(stop, currency)
    args = [sys.executable, str(script), "--account-size", f"{equity_eur:.2f}", "--entry", f"{entry_eur:.4f}",
            "--stop", f"{stop_eur:.4f}", "--risk-pct", f"{risk_pct:.2f}",
            "--max-position-pct", str(settings.get("risk.max_position_pct", 25)), "--output-dir", str(out_dir)]
    if sector:
        args += ["--sector", sector]
    if current_sector_pct is not None:
        args += ["--current-sector-exposure", f"{current_sector_pct:.2f}", "--max-sector-pct",
                 str(2 * float(settings.get("risk.max_position_pct", 25)))]
    before = set(glob.glob(str(out_dir / "position_sizer_*.json")))
    proc = subprocess.run(args, capture_output=True, text=True, timeout=120, cwd=str(script.parent))
    if proc.returncode != 0:
        raise RuntimeError(f"position-sizer fehlgeschlagen: {(proc.stderr or proc.stdout)[-300:]}")
    new = set(glob.glob(str(out_dir / "position_sizer_*.json"))) - before
    path = max(new, key=os.path.getmtime) if new else max(glob.glob(str(out_dir / "position_sizer_*.json")), key=os.path.getmtime)
    with open(path, encoding="utf-8") as fh:
        report = json.load(fh)
    return report, path


def attach_sizing(settings: Settings, thesis_id: str, report_path: str) -> dict:
    return _store(settings).attach_position(settings.theses_dir, thesis_id, report_path)


def open_position(settings: Settings, thesis_id: str, price: float, when: str, shares: float | None) -> dict:
    return _store(settings).open_position(settings.theses_dir, thesis_id, price, when, shares=shares)


def close_position(settings: Settings, thesis_id: str, price: float, when: str, reason_key: str) -> dict:
    reason = EXIT_REASONS.get(reason_key, reason_key)
    return _store(settings).close(settings.theses_dir, thesis_id, reason, price, when)


def update_stop(settings: Settings, thesis_id: str, new_stop: float, note: str) -> dict:
    store = _store(settings)
    thesis = store.get(settings.theses_dir, thesis_id)
    old = (thesis.get("exit") or {}).get("stop_loss")
    if old is not None and new_stop < float(old):
        raise ValueError(f"Stop darf nicht gesenkt werden ({old} -> {new_stop})")
    prov = dict(provenance(thesis))
    ledger = list(prov.get("stop_ledger", []))
    ledger.append({"date": date.today().isoformat(), "old": old, "new": float(new_stop), "note": note})
    prov["stop_ledger"] = ledger
    origin = dict(thesis.get("origin") or {})
    origin["raw_provenance"] = prov
    return store.update(settings.theses_dir, thesis_id, {"exit": {"stop_loss": float(new_stop)}, "origin": origin})


# ------------------------------------------------------------------ kill switch / statistics
def r_multiple(thesis: dict) -> float | None:
    """Ergebnis in R: realisiertes P&L / anfängliches Risiko (Stopabstand × Stücke)."""
    outcome = thesis.get("outcome") or {}
    pnl = outcome.get("pnl_dollars")
    pos = thesis.get("position") or {}
    entry = (thesis.get("entry") or {}).get("actual_price")
    stop = provenance(thesis).get("initial_stop") or (thesis.get("exit") or {}).get("stop_loss")
    shares = pos.get("shares")
    if pnl is None or entry is None or stop is None or not shares:
        risk = pos.get("risk_dollars")
        return float(pnl) / float(risk) if (pnl is not None and risk) else None
    risk = (float(entry) - float(stop)) * float(shares)
    return float(pnl) / risk if risk > 0 else None


def expectancy(theses: list[dict]) -> tuple[float | None, int, float | None]:
    rs = [r for r in (r_multiple(t) for t in theses) if r is not None]
    if not rs:
        return None, 0, None
    wins = [r for r in rs if r > 0]
    win_rate = len(wins) / len(rs)
    return sum(rs) / len(rs), len(rs), win_rate


def kill_switch_status(settings: Settings, account: Account) -> tuple[bool, str]:
    max_dd = float(settings.get("kill_switch.max_drawdown", 0.25))
    min_trades = int(settings.get("kill_switch.min_trades", 30))
    reasons = []
    dd = account.drawdown
    if dd is not None and dd >= max_dd:
        reasons.append(f"Drawdown {dd:.1%} >= {max_dd:.0%}")
    exp, n, _ = expectancy(closed_theses(settings))
    if exp is not None and n >= min_trades and exp <= 0:
        reasons.append(f"Expectancy {exp:.2f} R nach {n} Trades")
    return bool(reasons), "; ".join(reasons)


def effective_risk_pct(settings: Settings, ampel: str | None) -> float:
    closed = len(closed_theses(settings))
    risk = float(settings.get("risk.risk_pct", 1.0))
    if closed < int(settings.get("risk.start_trades", 20)):
        risk = float(settings.get("risk.risk_pct_start", 0.5))
    if ampel == "YELLOW":
        risk *= float(settings.get("risk.yellow_risk_factor", 0.5))
    return risk


# ------------------------------------------------------------------ digest & reviews (vendored CLIs)
def run_weekly_digest(settings: Settings, to_date: date) -> str | None:
    script = settings.vendor_skills_dir / "weekly-performance-digest" / "scripts" / "generate_weekly_digest.py"
    out = settings.reports_dir / "digest"
    out.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([sys.executable, str(script), "--state-dir", str(settings.theses_dir),
                           "--to-date", to_date.isoformat(), "--output-dir", str(out)],
                          capture_output=True, text=True, timeout=120, cwd=str(script.parent))
    if proc.returncode != 0:
        log.warning("weekly digest fehlgeschlagen: %s", (proc.stderr or proc.stdout)[-300:])
        return None
    md = out / f"weekly_digest_{to_date.isoformat()}.md"
    return md.read_text(encoding="utf-8") if md.exists() else None


def review_cli(settings: Settings, args: list[str]) -> int:
    script = settings.vendor_skills_dir / "trader-memory-core" / "scripts" / "thesis_review.py"
    return subprocess.call([sys.executable, str(script), "--state-dir", str(settings.theses_dir), *args],
                           cwd=str(script.parent))


def now_iso(d: date | None = None) -> str:
    d = d or date.today()
    return datetime(d.year, d.month, d.day).isoformat() + "+00:00"

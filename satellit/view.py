"""Das Anzeige-Artefakt: state/view_latest.json.

Der Wochenbericht ist ein Dokument, dieses Payload ist die Datenquelle der Oberfläche.
Bisher serialisierte report.write_report acht von einundzwanzig Feldern des WeeklyResult —
alle Begründungen, das Konto, der offene Risikoanteil und der Wechselkurs fielen dabei weg.
Hier kommt alles an, was die Ansicht braucht, in einer Datei ohne Namensmuster: das
Dashboard mountet state/ nur lesend und soll nicht nach Dateien suchen müssen.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import portfolio
from .config import Settings

log = logging.getLogger(__name__)

SCHEMA = 1


def _sauber(x: Any) -> Any:
    """NaN und Inf zu None, Datumswerte zu ISO-Strings, Dataclasses zu Dicts.

    Pflicht, kein Feinschliff: der Screener erzeugt np.nan, und json.dumps schreibt daraus
    das Literal NaN. Nodes JSON.parse wirft darauf eine Ausnahme — die Seite bliebe leer,
    ohne dass irgendwo ein Fehler sichtbar wird.
    """
    if x is None or isinstance(x, (str, bool, int)):
        return x
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    if is_dataclass(x) and not isinstance(x, type):
        return _sauber(asdict(x))
    if isinstance(x, dict):
        return {str(k): _sauber(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [_sauber(v) for v in x]
    # numpy-Skalare und alles Übrige: über float/str retten
    for wandler in (lambda v: _sauber(float(v)), str):
        try:
            return wandler(x)
        except (TypeError, ValueError):
            continue
    return None


def _kursalter(res) -> int | None:
    """Wie alt sind die jüngsten Kurse? Ab einer Woche werden keine Käufe mehr vorgeschlagen."""
    juengste = None
    for p in res.positions:
        if p.close is not None:
            juengste = res.as_of
            break
    return (date.today() - (juengste or res.as_of)).days


def bauen(res, settings: Settings) -> dict:
    """WeeklyResult -> Payload. Reines Umsortieren, keine neue Rechnung."""
    acc = res.account
    equity = acc.satellite_equity_eur
    gebunden = sum(p.wert_eur or 0.0 for p in res.positions)
    kw = ((res.kern or {}).get("werte") or {})       # leer, solange nichts eingerichtet ist
    trichter = {}
    if res.table is not None and not res.table.empty:
        t = res.table
        trichter = {
            "gesamt": int(len(t)),
            "kein_trend": int((~t["trend_ok"]).sum()),
            "keine_top_rs": int((t["trend_ok"] & ~t["rs_top"]).sum()),
            "kein_ausbruch": int((t["trend_ok"] & t["rs_top"] & ~t["breakout"]).sum()),
            "kandidaten": int(t["candidate"].sum()),
            "watchlist": int(t["watchlist"].sum()),
        }

    payload = {
        "schema": SCHEMA,
        "as_of": res.as_of.isoformat(),
        "erzeugt": datetime.now().isoformat(timespec="seconds"),
        "demo": res.demo,
        # Phase 2 füllt Kern, Monatsbudget und Gewinn. Die Schlüssel stehen schon hier,
        # damit die Oberfläche nicht später ihre Form ändern muss.
        "onboarding_noetig": not bool((res.kern or {}).get("eingerichtet")),
        "portfolio": {
            "satellit_eur": kw.get("satellit_eur", equity),
            "gebunden_eur": gebunden,
            "cash_eur": kw.get("cash_eur", max(0.0, equity - gebunden) if equity else None),
            "cash_je_topf": kw.get("cash_je_topf") or {},
            "hoch_eur": acc.high_water_mark,
            "drawdown": acc.drawdown,
            "positionen": {"offen": len(res.positions),
                           "max": int(settings.get("risk.max_positions", 5))},
            "offenes_risiko_pct": res.open_risk_pct,
            "offenes_risiko_max_pct": float(settings.get("risk.max_open_risk_pct", 5.0)),
            "kern_eur": kw.get("kern_eur"),
            "kern_etf_eur": kw.get("kern_etf_eur"),
            "kern_aktien_eur": kw.get("kern_aktien_eur"),
            "kern_aktien_cash_eur": kw.get("kern_aktien_cash_eur"),
            "gesamt_eur": kw.get("gesamt_eur"),
            "kern_pct": kw.get("kern_pct"),
            "satellit_pct": kw.get("satellit_pct"),
            "band": (res.kern or {}).get("band") or {},
            "kauffenster": (res.kern or {}).get("kauffenster") or {},
        },
        "monat": (res.kern or {}).get("monat"),
        "gewinn": (res.kern or {}).get("gewinn"),
        "sparplan": (res.kern or {}).get("sparplan"),
        "etf": (res.kern or {}).get("etf"),
        # Nur für die Ersteinrichtung: das Dashboard hat keinen Zugriff auf config/,
        # es mountet ausschließlich state/. Danach ist der Katalog überflüssig.
        "etf_katalog": [] if (res.kern or {}).get("eingerichtet") else portfolio.lade_etf_katalog(settings),
        "ampel": {r: {**asdict(rd), "label": rd.label} for r, rd in res.readings.items()},
        "entscheidungen": [asdict(d) for d in res.entscheidungen],
        "abgelehnt": [asdict(d) for d in res.abgelehnt],
        "screener_trichter": trichter,
        "sperren": {
            "kill_switch": {"aktiv": res.kill_active, "grund": res.kill_reason},
            "trockenlauf": {"aktiv": res.dry_run, "bis": acc.dry_run_until},
        },
        "daten": {
            "fx": {"kurse": res.fx_kurse, "quelle": res.fx_note},
            "universum": res.universum_status,
            "universum_warnungen": res.universe_warnings,
            "fehlende_symbole": res.data_failed,
            "hinweise": res.data_notes + res.regime_notes,
            "kurse_alter_tage": _kursalter(res),
            "letzter_lauf": datetime.now().isoformat(timespec="seconds"),
            "bericht": res.report_path,
        },
    }
    return _sauber(payload)


def schreiben(payload: dict, settings: Settings) -> Path:
    """Archivfassung je Stichtag + die feste Datei, die das Dashboard liest."""
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
    (settings.reports_dir / f"view_{payload['as_of']}.json").write_text(text, encoding="utf-8")
    ziel = settings.state_dir / "view_latest.json"
    ziel.write_text(text, encoding="utf-8")
    return ziel


def lesen(settings: Settings) -> dict | None:
    p = settings.state_dir / "view_latest.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("view_latest.json nicht lesbar: %s", exc)
        return None


def neu_rechnen(settings: Settings) -> Path:
    """Ansicht ohne Netz neu bauen — nach jeder schreibenden Aktion.

    Ein Wochenlauf dauert Minuten; ein Klick im Dashboard darf das nicht. Deshalb wird
    hier ausschließlich aus dem Kurs-Cache, dem Journal und der letzten Ampel gerechnet.
    """
    from .pipeline import run_weekly
    res = run_weekly(settings, offline=True)
    return schreiben(bauen(res, settings), settings)

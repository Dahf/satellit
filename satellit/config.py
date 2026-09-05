"""Konfiguration laden (config/settings.yaml) und Pfade auflösen."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(os.environ.get("SATELLIT_ROOT", Path(__file__).resolve().parent.parent))
DEFAULT_SETTINGS = PROJECT_ROOT / "config" / "settings.yaml"


@dataclass
class Settings:
    raw: dict[str, Any]
    root: Path

    # ------------------------------------------------------------------ access
    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, dotted: str, default: Any = None) -> Any:
        """settings.get("risk.risk_pct") -> 1.0"""
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    # ------------------------------------------------------------------- paths
    def path(self, key: str) -> Path:
        """Pfad aus paths.<key>, relativ zum Projekt-Root."""
        value = self.get(f"paths.{key}")
        if value is None:
            raise KeyError(f"paths.{key} fehlt in settings.yaml")
        return self._resolve(value)

    def _resolve(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else self.root / p

    @property
    def state_dir(self) -> Path:
        return self.path("state_dir")

    @property
    def theses_dir(self) -> Path:
        return self.path("theses_dir")

    @property
    def reports_dir(self) -> Path:
        return self.path("reports_dir")

    @property
    def regime_dir(self) -> Path:
        return self.path("regime_dir")

    @property
    def universe_dir(self) -> Path:
        return self.path("universe_dir")

    @property
    def cache_dir(self) -> Path:
        return self._resolve(self.get("data.cache_dir", "state/prices"))

    @property
    def vendor_skills_dir(self) -> Path:
        return self.path("vendor_skills_dir")

    def ensure_dirs(self) -> None:
        for p in (self.state_dir, self.theses_dir, self.reports_dir, self.regime_dir,
                  self.universe_dir, self.cache_dir):
            p.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- yaml files
    def load_yaml(self, key: str, default: Any) -> Any:
        p = self.path(key)
        if not p.exists():
            return default
        with open(p, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return default if data is None else data


def risikoprofil(settings: Settings, equity_eur: float | None) -> dict[str, Any]:
    """Die effektiven Risiko-Grenzen für ein Satelliten-Kapital.

    Unterhalb von risk.kleines_depot_unter_eur gelten die Werte aus risk.klein: wenige,
    größere Positionen. Grund ist Arithmetik, keine Meinung — bei 250 EUR Kapital und
    0,5 % Risiko je Trade sind fünf Positionen à 25 % rechnerisch nicht darstellbar, und
    der Screener meldete dafür bisher nur ZU_TEUER, ohne den Grund zu nennen.

    Wächst der Satellit über die Schwelle, gelten wieder die Regelwerte — ohne Zutun.
    max_open_risk_pct steht bewusst nicht hier: es begrenzt das Klumpenrisiko und gilt
    unverändert (Trading-Plan 6).

    Aufgelöst an genau einer Stelle, weil Screener und Auswahl dieselben Zahlen brauchen —
    liefen sie auseinander, würde der Screener Titel durchlassen, die die Auswahl verwirft.
    """
    schwelle = float(settings.get("risk.kleines_depot_unter_eur", 0) or 0)
    klein = bool(equity_eur is not None and schwelle > 0 and equity_eur < schwelle)
    quelle = "risk.klein." if klein else "risk."

    def _wert(name: str, default: Any) -> Any:
        # Fehlt ein Wert unter risk.klein, gilt der Regelwert — kein stilles Auffüllen mit 0.
        return settings.get(f"{quelle}{name}", settings.get(f"risk.{name}", default))

    return {
        "klein": klein,
        "max_positions": int(_wert("max_positions", 5)),
        "max_position_pct": float(_wert("max_position_pct", 25)),
        "max_per_sector": int(_wert("max_per_sector", 2)),
        "bruchstuecke": bool(settings.get("risk.bruchstuecke", False)),
        "min_order_eur": float(settings.get("risk.min_order_eur", 1.0)),
    }


def load_settings(path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> Settings:
    p = Path(path) if path else DEFAULT_SETTINGS
    with open(p, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    root = p.resolve().parent.parent if p.name == "settings.yaml" else PROJECT_ROOT
    if overrides:
        _deep_merge(raw, overrides)
    return Settings(raw=raw, root=root)


def _deep_merge(base: dict, extra: dict) -> None:
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v

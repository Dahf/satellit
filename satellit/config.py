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

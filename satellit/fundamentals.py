"""Fundamentaldaten je Titel: austauschbare Quellen + lokaler JSON-Cache.

Gebaut nach dem Muster von `data.py` — dieselbe Dreiteilung aus Quelle, Ergebnis und Cache,
weil sie sich dort bewährt hat und weil Offline- und Demo-Läufe sonst nicht möglich wären.

Datenmodell je Symbol: `Fundamentals`. Jahreswerte stehen als {Jahr: Wert}, nicht als Liste —
die Quelle liefert unterschiedlich viele Jahre, und eine Liste ohne Jahreszahl verleitet dazu,
Lücken zu übersehen.

**Die wichtigste Eigenschaft dieses Moduls ist `jahre_abgedeckt`.** Der Kriterienkatalog in
docs/KERN.md fragt nach 5–10 Jahren (Kriterium 2) und nach 8 von 10 Jahren positivem Free
Cashflow (Kriterium 5). Yahoo liefert typischerweise vier Jahresabschlüsse. Ein Kriterium, das
über vier Jahre hält, ist damit *nicht* geprüft — es ist ungeprüft. Wer das zu „erfüllt“
rundet, baut sich eine Qualitätsprüfung, die keine ist. Deshalb wird die Abdeckung überall
mitgeführt und in `kern_screener` zu `erfuellt=None` statt `True`.
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)


@dataclass
class Fundamentals:
    """Was der Kriterienkatalog braucht — nicht mehr.

    Alle Geldbeträge in `waehrung`, außer `marktkap_eur`. Die Kriterien 3 bis 5 sind
    Verhältnisse bzw. Vorzeichen und damit währungsunabhängig; nur die Marktkapitalisierung
    wird gegen eine EUR-Schwelle geprüft und deshalb umgerechnet.
    """

    symbol: str
    waehrung: str = ""
    marktkap_eur: float | None = None
    erstnotiz: str | None = None            # ISO-Datum, aus der Länge der Kursreihe oder der Quelle
    umsatz: dict[int, float] = field(default_factory=dict)
    eps: dict[int, float] = field(default_factory=dict)
    roe: dict[int, float] = field(default_factory=dict)          # Anteil, nicht Prozent
    roic: dict[int, float] = field(default_factory=dict)
    nettoschulden: float | None = None
    ebitda: float | None = None
    fcf: dict[int, float] = field(default_factory=dict)
    dividende: dict[int, float] = field(default_factory=dict)    # Summe je Jahr je Aktie
    aktienzahl: dict[int, float] = field(default_factory=dict)
    quelle: str = ""
    abgerufen_am: str | None = None
    hinweise: list[str] = field(default_factory=list)

    @property
    def jahre_abgedeckt(self) -> int:
        """Wie viele Geschäftsjahre die Quelle tatsächlich hergibt.

        Maßgeblich ist die längste der Jahresreihen: fehlt eine einzelne Kennzahl, ist das
        eine Lücke in dieser Kennzahl, nicht eine kürzere Historie des Unternehmens.
        """
        return max((len(r) for r in (self.umsatz, self.eps, self.fcf, self.roe, self.roic)),
                   default=0)

    @property
    def vollstaendig(self) -> bool:
        """Reicht die Datenlage, um überhaupt eine Aussage zu versuchen?"""
        return bool(self.umsatz or self.eps or self.fcf)


@dataclass
class FundamentalsResult:
    daten: dict[str, Fundamentals] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)       # Symbol -> Grund
    notes: list[str] = field(default_factory=list)


class FundamentalsSource(ABC):
    name = "abstract"
    progress: Callable[[int, int], None] | None = None         # (fertig, gesamt)

    def _melde(self, fertig: int, gesamt: int) -> None:
        if self.progress:
            try:
                self.progress(fertig, gesamt)
            except Exception:  # noqa: BLE001  # pragma: no cover
                pass

    @abstractmethod
    def fetch(self, symbols: list[str]) -> FundamentalsResult:
        """Jahreskennzahlen für Symbole."""


# --------------------------------------------------------------------------- Hilfen
def _jahr(spalte) -> int | None:
    """Spaltenkopf eines yfinance-Abschlusses -> Geschäftsjahr."""
    try:
        return int(getattr(spalte, "year", None) or str(spalte)[:4])
    except (TypeError, ValueError):
        return None


def _reihe(frame, *namen: str) -> dict[int, float]:
    """Eine Zeile aus einem yfinance-Abschluss als {Jahr: Wert}.

    Yahoo benennt dieselbe Position je nach Titel unterschiedlich, deshalb mehrere Namen der
    Reihe nach. Nicht endliche Werte fallen weg — eine NaN-Lücke ist eine Lücke, keine Null.
    """
    if frame is None or getattr(frame, "empty", True):
        return {}
    for name in namen:
        if name not in frame.index:
            continue
        out: dict[int, float] = {}
        for spalte, wert in frame.loc[name].items():
            j = _jahr(spalte)
            try:
                f = float(wert)
            except (TypeError, ValueError):
                continue
            if j is not None and f == f:                        # NaN ohne numpy
                out[j] = f
        if out:
            return out
    return {}


def _erste(info: dict, *namen: str) -> float | None:
    for name in namen:
        wert = info.get(name)
        try:
            f = float(wert)
        except (TypeError, ValueError):
            continue
        if f == f:
            return f
    return None


# --------------------------------------------------------------------------- Quellen
class YFinanceFundamentals(FundamentalsSource):
    """Primärquelle. Dieselbe inoffizielle Schnittstelle wie die Kurse, aber je Titel ein
    eigener Abruf — es gibt keinen Batch-Endpunkt für Abschlüsse. Ein Lauf über ein volles
    Indexuniversum dauert deshalb Minuten bis Viertelstunden; darum der lange Cache.
    """

    name = "yfinance"

    def __init__(self, pause: float = 0.6, retries: int = 2):
        self.pause = pause
        self.retries = retries

    def fetch(self, symbols: list[str]) -> FundamentalsResult:
        res = FundamentalsResult()
        try:
            import yfinance as yf  # noqa: WPS433
        except ImportError as exc:  # pragma: no cover
            res.notes.append(f"yfinance nicht installiert: {exc}")
            for s in symbols:
                res.failed[s] = "yfinance fehlt"
            return res

        heute = date.today().isoformat()
        for i, symbol in enumerate(symbols, start=1):
            f = None
            for versuch in range(self.retries + 1):
                try:
                    f = self._einer(yf, symbol, heute)
                    break
                except Exception as exc:  # noqa: BLE001
                    wait = 30 * (versuch + 1)
                    log.warning("Fundamentaldaten %s fehlgeschlagen (%s) — warte %ds", symbol, exc, wait)
                    if versuch == self.retries:
                        res.failed[symbol] = f"Abruf fehlgeschlagen: {exc}"
                    else:
                        time.sleep(wait)
            if f is not None:
                if f.vollstaendig:
                    res.daten[symbol] = f
                else:
                    # Ein leerer Datensatz ist kein Datensatz. Würde er im Cache landen,
                    # gälte der Titel 90 Tage lang als geprüft und durchgefallen.
                    res.failed[symbol] = "keine Jahresabschlüsse (yfinance)"
            self._melde(i, len(symbols))
            if i < len(symbols):
                time.sleep(self.pause)
        return res

    def _einer(self, yf, symbol: str, heute: str) -> Fundamentals:
        t = yf.Ticker(symbol)
        info = {}
        try:
            info = t.info or {}
        except Exception as exc:  # noqa: BLE001
            log.debug("info für %s nicht verfügbar: %s", symbol, exc)

        guv = getattr(t, "income_stmt", None)
        bilanz = getattr(t, "balance_sheet", None)
        cash = getattr(t, "cashflow", None)

        umsatz = _reihe(guv, "Total Revenue", "Operating Revenue")
        eps = _reihe(guv, "Diluted EPS", "Basic EPS")
        nettogewinn = _reihe(guv, "Net Income", "Net Income Common Stockholders")
        ebit = _reihe(guv, "EBIT", "Operating Income")
        ebitda_reihe = _reihe(guv, "EBITDA", "Normalized EBITDA")

        eigenkapital = _reihe(bilanz, "Stockholders Equity", "Total Equity Gross Minority Interest")
        schulden = _reihe(bilanz, "Total Debt")
        liquide = _reihe(bilanz, "Cash And Cash Equivalents",
                         "Cash Cash Equivalents And Short Term Investments")
        aktien = _reihe(bilanz, "Share Issued", "Ordinary Shares Number")

        operativ = _reihe(cash, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
        investitionen = _reihe(cash, "Capital Expenditure")
        fcf = _reihe(cash, "Free Cash Flow")
        if not fcf and operativ:
            # Capital Expenditure kommt bei Yahoo negativ — deshalb addieren, nicht abziehen.
            fcf = {j: operativ[j] + investitionen.get(j, 0.0) for j in operativ}

        roe = {j: nettogewinn[j] / eigenkapital[j]
               for j in nettogewinn if eigenkapital.get(j)}
        # ROIC als EBIT / (Eigenkapital + Nettoschulden). Eine Näherung: ohne Steuerquote und
        # ohne Bereinigung um nicht betriebsnotwendige Mittel. Sie taugt für einen Filter bei
        # 10 %, nicht für einen Vergleich zweier Titel auf den Punkt.
        roic = {}
        for j in ebit:
            basis = eigenkapital.get(j)
            if basis:
                netto = schulden.get(j, 0.0) - liquide.get(j, 0.0)
                nenner = basis + max(netto, 0.0)
                if nenner:
                    roic[j] = ebit[j] / nenner

        dividende: dict[int, float] = {}
        try:
            for stichtag, betrag in (t.dividends or {}).items():
                j = _jahr(stichtag)
                if j is not None:
                    dividende[j] = dividende.get(j, 0.0) + float(betrag)
        except Exception as exc:  # noqa: BLE001
            log.debug("Dividenden für %s nicht verfügbar: %s", symbol, exc)

        letztes = max(schulden) if schulden else (max(liquide) if liquide else None)
        nettoschulden = None
        if letztes is not None:
            nettoschulden = schulden.get(letztes, 0.0) - liquide.get(letztes, 0.0)

        hinweise = []
        marktkap = _erste(info, "marketCap")
        waehrung = str(info.get("financialCurrency") or info.get("currency") or "")
        if marktkap is not None and waehrung and waehrung != "EUR":
            # Umrechnung passiert beim Aufrufer, der die FX-Tabelle hat.
            hinweise.append(f"Marktkapitalisierung in {waehrung}")

        erstnotiz = None
        gruendung = info.get("firstTradeDateEpochUtc") or info.get("firstTradeDateMilliseconds")
        if gruendung:
            try:
                sek = float(gruendung)
                if sek > 1e11:            # Millisekunden
                    sek /= 1000.0
                erstnotiz = datetime.utcfromtimestamp(sek).date().isoformat()
            except (TypeError, ValueError, OverflowError, OSError):
                erstnotiz = None

        return Fundamentals(
            symbol=symbol, waehrung=waehrung, marktkap_eur=marktkap, erstnotiz=erstnotiz,
            umsatz=umsatz, eps=eps, roe=roe, roic=roic,
            nettoschulden=nettoschulden,
            ebitda=ebitda_reihe.get(max(ebitda_reihe)) if ebitda_reihe else None,
            fcf=fcf, dividende=dividende, aktienzahl=aktien,
            quelle=self.name, abgerufen_am=heute, hinweise=hinweise,
        )


class NullFundamentals(FundamentalsSource):
    """Offline: nichts abrufen. Der Cache trägt, was er trägt."""

    name = "cache"

    def fetch(self, symbols: list[str]) -> FundamentalsResult:
        res = FundamentalsResult()
        for s in symbols:
            res.failed[s] = "offline (nur Cache)"
        if symbols:
            res.notes.append(f"Offline-Modus: {len(symbols)} Titel ohne frische Fundamentaldaten")
        return res


class FixtureFundamentals(FundamentalsSource):
    """Aus einem Verzeichnis mit <symbol>.json — für Tests mit bekannten Zahlen."""

    name = "fixture"

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def fetch(self, symbols: list[str]) -> FundamentalsResult:
        res = FundamentalsResult()
        for s in symbols:
            p = self.directory / f"{s}.json"
            if not p.exists():
                res.failed[s] = "keine Fixture"
                continue
            try:
                res.daten[s] = von_dict(json.loads(p.read_text(encoding="utf-8")))
            except Exception as exc:  # noqa: BLE001
                res.failed[s] = f"Fixture unlesbar: {exc}"
        return res


class SyntheticFundamentals(FundamentalsSource):
    """Erfundene, aber in sich stimmige Zahlen für `--demo` und Tests.

    Deterministisch aus dem Symbol abgeleitet, damit derselbe Titel im Demo-Lauf immer
    dieselben Kennzahlen hat. Etwa jeder dritte Titel fällt absichtlich durch — ein Demo,
    in dem alles besteht, zeigt den Filter nicht.
    """

    name = "synthetic"

    def __init__(self, jahre: int = 5):
        self.jahre = jahre

    def fetch(self, symbols: list[str]) -> FundamentalsResult:
        res = FundamentalsResult()
        heute = date.today()
        for s in symbols:
            saat = sum(ord(c) for c in s)
            gut = saat % 3 != 0
            jahre = list(range(heute.year - self.jahre, heute.year))
            wachstum = 1.08 if gut else 0.97
            umsatz = {j: 1_000_000_000.0 * (wachstum ** i) for i, j in enumerate(jahre)}
            eps = {j: 5.0 * (wachstum ** i) for i, j in enumerate(jahre)}
            marge = 0.16 if gut else 0.05
            res.daten[s] = Fundamentals(
                symbol=s, waehrung="EUR",
                marktkap_eur=(20e9 if gut else 3e9),
                erstnotiz=date(heute.year - (12 if gut else 3), 1, 1).isoformat(),
                umsatz=umsatz, eps=eps,
                roe={j: marge for j in jahre}, roic={j: marge for j in jahre},
                nettoschulden=(1.5e9 if gut else 9e9), ebitda=1.0e9,
                fcf={j: (2e8 if gut else -1e8 * ((i % 2) or -1)) for i, j in enumerate(jahre)},
                dividende={j: 1.0 for j in jahre}, aktienzahl={j: 1e9 for j in jahre},
                quelle=self.name, abgerufen_am=heute.isoformat(),
            )
        return res


def build_source(settings, which: str | None = None) -> FundamentalsSource:
    kind = (which or settings.get("fundamentals.primary", "yfinance")).lower()
    if kind == "yfinance":
        return YFinanceFundamentals(pause=float(settings.get("fundamentals.pause_seconds", 0.6)))
    if kind == "synthetic":
        return SyntheticFundamentals()
    if kind == "fixture":
        d = settings.get("fundamentals.fixture_dir") or settings.get("data.fixture_dir")
        if not d:
            raise ValueError("fundamentals.fixture_dir fehlt in settings.yaml")
        return FixtureFundamentals(d)
    if kind in ("null", "cache", "offline"):
        return NullFundamentals()
    raise ValueError(f"Unbekannte Fundamentaldaten-Quelle: {kind}")


# --------------------------------------------------------------------------- Cache
def zu_dict(f: Fundamentals) -> dict:
    """Jahreszahlen werden als Text geschrieben — JSON kennt keine Zahl als Schlüssel."""
    d = asdict(f)
    for feld in ("umsatz", "eps", "roe", "roic", "fcf", "dividende", "aktienzahl"):
        d[feld] = {str(k): v for k, v in (d[feld] or {}).items()}
    return d


def von_dict(d: dict) -> Fundamentals:
    kopie = dict(d)
    for feld in ("umsatz", "eps", "roe", "roic", "fcf", "dividende", "aktienzahl"):
        roh = kopie.get(feld) or {}
        kopie[feld] = {int(k): float(v) for k, v in roh.items()}
    erlaubt = {f for f in Fundamentals.__dataclass_fields__}
    return Fundamentals(**{k: v for k, v in kopie.items() if k in erlaubt})


class FundamentalsCache:
    """Eine JSON je Symbol. Symbol-Sanitizing wie im Kurs-Cache, damit '^' und '=' in
    Dateinamen nicht auf Windows scheitern."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        safe = symbol.replace("^", "_idx_").replace("=", "_eq_").replace("/", "_")
        return self.directory / f"{safe}.json"

    def load(self, symbol: str) -> Fundamentals | None:
        p = self._path(symbol)
        if not p.exists():
            return None
        try:
            return von_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            log.warning("Fundamentaldaten-Cache für %s unlesbar (%s) — wird neu geladen", symbol, exc)
            return None

    def save(self, f: Fundamentals) -> None:
        self._path(f.symbol).write_text(
            json.dumps(zu_dict(f), ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")

    def alter_tage(self, f: Fundamentals, heute: date) -> int | None:
        if not f.abgerufen_am:
            return None
        try:
            return (heute - date.fromisoformat(f.abgerufen_am)).days
        except ValueError:
            return None


def update_fundamentals(settings, symbols: list[str], source: FundamentalsSource | None = None,
                        today: date | None = None,
                        progress: Callable[[int, int], None] | None = None,
                        ) -> tuple[dict[str, Fundamentals], dict[str, str], list[str]]:
    """Cache auffrischen und alle bekannten Kennzahlen zurückgeben.

    Returns: (daten, failed, notes). `failed` enthält nur Symbole, für die auch im Cache
    nichts liegt — ein veralteter Datensatz ist besser als keiner, solange sein Alter
    sichtbar bleibt.
    """
    heute = today or date.today()
    cache = FundamentalsCache(settings.state_dir / "fundamentals")
    frist = int(settings.get("fundamentals.refresh_days", 90))

    daten: dict[str, Fundamentals] = {}
    holen: list[str] = []
    for s in symbols:
        vorhanden = cache.load(s)
        alter = cache.alter_tage(vorhanden, heute) if vorhanden else None
        if vorhanden is not None and alter is not None and alter <= frist:
            daten[s] = vorhanden
        else:
            holen.append(s)
            if vorhanden is not None:
                daten[s] = vorhanden          # als Rückfall, falls der Abruf scheitert

    notes: list[str] = []
    failed: dict[str, str] = {}
    if holen:
        src = source or build_source(settings)
        if progress:
            src.progress = progress
        log.info("Fundamentaldaten: %d von %d Titeln werden geladen (%s)", len(holen), len(symbols), src.name)
        res = src.fetch(holen)
        notes.extend(res.notes)
        for s, f in res.daten.items():
            f.abgerufen_am = f.abgerufen_am or heute.isoformat()
            cache.save(f)
            daten[s] = f
        for s, grund in res.failed.items():
            if s not in daten:
                failed[s] = grund
        veraltet = [s for s in holen if s in daten and s not in res.daten]
        if veraltet:
            notes.append(f"{len(veraltet)} Titel mit veralteten Fundamentaldaten (Abruf fehlgeschlagen)")
    return daten, failed, notes

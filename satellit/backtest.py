"""Backtest — das Gate aus Trading-Plan 10.3.

Die Frage ist nicht „wie viel hätte es gebracht", sondern eine einzige, vorab
festgeschriebene: **schlägt der Satellit nach Kosten und nach Steuern den Kern-ETF?**
Fällt die Antwort nein aus, wird der Satellit gestrichen und die 10 % gehen in den Kern.

Damit das Urteil trägt, ruft der Motor dieselben Funktionen wie der Wochenlauf —
`screener.run_screener`, `regime.marktbreite` / `breite_raw_state` / `apply_hysteresis`,
`pipeline.select_entries` und `sizing.positionsgroesse`. Nichts davon ist hier nachgebaut.
Ein Backtest mit eigener Regelimplementierung prüft eine Fantasie, nicht das System, das
später Geld bewegt; genau deshalb wurde die Positionsgröße vorher nach `sizing` gezogen.

**Was modelliert ist**
  * Wochenrhythmus mit Stichtag Freitag, wie im Wochenlauf.
  * Punkt-in-Zeit-Mitgliedschaft für die USA, soweit Stammdaten vorliegen
    (`universe_history` — die verbleibende Lücke steht als `abdeckung` im Bericht).
  * Kurslücken am Stop: gefüllt wird zur Eröffnung, nicht am Stop.
  * 1,00 € je Order plus Spread, Sparplan kostenlos.
  * Deutsche Kapitalertragsteuer mit Verlustverrechnung, Teilfreistellung, Pauschbetrag
    und Vorabpauschale.
  * Historische Wechselkurse — der Euro-Wert einer USD-Position ändert sich über die
    Haltedauer, und diese Bewegung war bisher nirgends im System abgebildet.

**Was nicht modelliert ist** (und deshalb nicht behauptet wird)
  * Dividenden auf Einzelaktien. Sie fehlen auf der Satellitenseite und begünstigen damit
    den ETF, für den der Kurs total-return-bereinigt vorliegt — die sichere Richtung, weil
    der Satellit die Beweislast trägt.
  * Intraday-Slippage jenseits der Kurslücke, Teilausführungen, Handelsaussetzungen.
  * Delistete Titel, für die keine Kurse mehr vorliegen. Siehe `universe_history`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from . import journal, regime, sizing
from .config import Settings, risikoprofil
from .kosten import Kostenmodell, stop_fuellkurs
from .pipeline import PositionView, last_friday, select_entries
from .screener import ScreenerContext, run_screener
from .steuern import TEILFREISTELLUNG_AKTIENFONDS, Steuerkonto, Steuersatz, basiszins_tabelle
from .universe import Constituent
from .universe_history import Universumshistorie

log = logging.getLogger(__name__)


class FxHistorie:
    """Wechselkurse zum jeweiligen Stichtag statt eines Kurses für alle Zeiten.

    Der Wochenlauf rechnet mit dem Tageskurs — für eine Momentaufnahme richtig. Über einen
    mehrjährigen Test wäre derselbe Kurs für 2019 und 2026 grob falsch: bei einer
    USD-Position ist die Wechselkursbewegung über die Haltedauer in der Größenordnung des
    Positionsrisikos selbst.
    """

    FALLBACK = {"EUR": 1.0}

    def __init__(self, frames: dict[str, pd.DataFrame], stichtag: date | None = None):
        self.frames = frames
        self.stichtag = stichtag
        self.note = "historisch"
        self._cache: dict[tuple[str, date], float] = {}

    def setze_stichtag(self, tag: date) -> None:
        self.stichtag = tag

    def _kurs(self, waehrung: str) -> float | None:
        tag = self.stichtag
        if tag is None:
            return None
        schluessel = (waehrung, tag)
        if schluessel in self._cache:
            return self._cache[schluessel]
        df = self.frames.get(f"EUR{waehrung}=X")
        if df is None or df.empty:
            return None
        bis = df[df.index.date <= tag]
        if bis.empty:
            return None
        # EURUSD=X notiert USD je EUR; für die Umrechnung nach EUR wird der Kehrwert gebraucht.
        kurs = float(bis["close"].iloc[-1])
        wert = (1.0 / kurs) if kurs > 0 else None
        self._cache[schluessel] = wert
        return wert

    def to_eur(self, amount: float, currency: str) -> float:
        cur = (currency or "EUR").upper()
        if cur == "EUR":
            return amount
        if cur == "GBX":
            k = self._kurs("GBP")
            return amount * k / 100.0 if k else amount / 100.0
        k = self._kurs(cur)
        if k is None:
            # Keine stille 1:1-Annahme wie im Live-Pfad: im Backtest ist ein fehlender
            # Kurs ein Datenproblem, das sich über Jahre aufsummiert.
            raise LookupError(f"Kein Wechselkurs für {cur} zum {self.stichtag}")
        return amount * k

    @property
    def rates(self) -> dict[str, float]:
        return {}


@dataclass
class Position:
    symbol: str
    name: str
    region: str
    currency: str
    sector: str
    stueck: float
    einstand: float                 # Lokalwährung
    einstand_eur: float
    stop: float
    eroeffnet: date
    kosten_eur: float
    # Das Risiko beim Einstieg — 1R. Muss beim Einstieg festgehalten werden: der Stop wird
    # nachgezogen, und sobald er über den Einstand wandert, ist der Abstand zum Kurs der
    # gesicherte Gewinn, nicht mehr das eingegangene Risiko. Gegen ihn zu messen machte
    # jedes ausgewiesene R bedeutungslos.
    risiko_eur: float = 0.0
    thesis_id: str = ""


@dataclass
class Trade:
    symbol: str
    region: str
    eintritt: date
    austritt: date
    einstand_eur: float
    erloes_eur: float
    kosten_eur: float
    grund: str
    r_geplant_eur: float            # das Risiko, das beim Einstieg angesetzt war (1R)

    @property
    def gewinn_eur(self) -> float:
        return self.erloes_eur - self.einstand_eur - self.kosten_eur

    @property
    def r_multiple(self) -> float | None:
        """Tatsächliches R — nicht das geplante. Genau hier zeigt sich die Kurslücke."""
        if self.r_geplant_eur <= 0:
            return None
        return self.gewinn_eur / self.r_geplant_eur


@dataclass
class Ergebnis:
    von: date
    bis: date
    trades: list[Trade] = field(default_factory=list)
    equity: list[tuple[date, float]] = field(default_factory=list)
    startkapital_eur: float = 0.0
    endkapital_eur: float = 0.0
    kosten_eur: float = 0.0
    steuer_eur: float = 0.0
    benchmark: dict = field(default_factory=dict)
    abdeckung: dict = field(default_factory=dict)
    hinweise: list[str] = field(default_factory=list)

    @property
    def treffer(self) -> float | None:
        gezaehlt = [t for t in self.trades if t.r_multiple is not None]
        if not gezaehlt:
            return None
        return sum(1 for t in gezaehlt if t.gewinn_eur > 0) / len(gezaehlt)

    @property
    def expectancy_r(self) -> float | None:
        werte = [t.r_multiple for t in self.trades if t.r_multiple is not None]
        return sum(werte) / len(werte) if werte else None

    @property
    def max_drawdown(self) -> float | None:
        if not self.equity:
            return None
        hoch, tief = self.equity[0][1], 0.0
        for _, wert in self.equity:
            hoch = max(hoch, wert)
            if hoch > 0:
                tief = max(tief, 1.0 - wert / hoch)
        return tief

    @property
    def netto_eur(self) -> float:
        """Endkapital nach Steuern — die Zahl, die gegen den ETF antritt."""
        return self.endkapital_eur - self.steuer_eur

    def besteht(self) -> bool | None:
        """Das Urteil aus Trading-Plan 10.3. None, wenn es nicht bewertbar ist."""
        ref = self.benchmark.get("netto_eur")
        if ref is None or not self.trades:
            return None
        return self.netto_eur > ref


def _freitage(von: date, bis: date) -> list[date]:
    tag = last_friday(von + timedelta(days=6))
    out = []
    while tag <= bis:
        out.append(tag)
        tag += timedelta(days=7)
    return out


def _woche(df: pd.DataFrame, von: date, bis: date) -> pd.DataFrame:
    return df[(df.index.date > von) & (df.index.date <= bis)]


class Backtest:
    """Wochenschleife durch die Historie. Ein Objekt je Lauf, kein geteilter Zustand."""

    def __init__(self, settings: Settings, frames: dict[str, pd.DataFrame],
                 konstituenten: list[Constituent], historie: Universumshistorie,
                 startkapital_eur: float, *, index_symbols: dict[str, str] | None = None):
        self.s = settings
        self.frames = frames
        self.konstituenten = konstituenten
        self.historie = historie
        self.startkapital = startkapital_eur
        self.index_symbols = index_symbols or {}
        self.kosten = Kostenmodell.aus_settings(settings)
        self.steuer = Steuerkonto(
            satz=Steuersatz.aus_settings(settings),
            pauschbetrag_eur=float(settings.get("backtest.steuer.pauschbetrag_eur", 1000)))
        self.fx = FxHistorie(frames)
        self.positionen: dict[str, Position] = {}
        self.kasse = startkapital_eur
        self.trades: list[Trade] = []
        self.kosten_summe = 0.0
        self.roh_historie: dict[str, list[str | None]] = {"US": [], "EU": []}
        self.wirksam: dict[str, str | None] = {"US": None, "EU": None}

    # ------------------------------------------------------------------ Ampel
    def _ampel(self, as_of: date) -> dict[str, regime.RegimeReading]:
        sma_fast = int(self.s.get("signal.sma_fast", 50))
        sma_slow = int(self.s.get("signal.sma_slow", 200))
        cfg = {"US": self.s.get("regime.us_breite", {}), "EU": self.s.get("regime.eu", {})}
        readings = {}
        for region in ("US", "EU"):
            syms = [c.symbol for c in self.konstituenten if c.region == region]
            p200, p50, idx, _ = regime.marktbreite(self.frames, syms, self.index_symbols.get(region),
                                                   as_of, sma_fast, sma_slow)
            roh = regime.breite_raw_state(p200, p50, idx, cfg[region])
            self.roh_historie[region].append(roh)
            wochen = int(self.s.get(f"regime.{region.lower()}.hysteresis_weeks", 2))
            # Dieselbe reine Funktion wie im Wochenlauf; nur die Historie liegt im Speicher
            # statt in state/regime/ampel_history.csv.
            eff = regime.apply_hysteresis(self.roh_historie[region][-wochen:],
                                          self.wirksam[region], wochen)
            self.wirksam[region] = eff
            readings[region] = regime.RegimeReading(as_of.isoformat(), region, roh, eff,
                                                    p200=p200, p50=p50, idx_above=idx)
        return readings

    # ------------------------------------------------------------------ Exits
    def _exits(self, as_of: date, vorwoche: date) -> None:
        mult = float(self.s.get("risk.atr_stop_mult", 3.0))
        atr_n = int(self.s.get("risk.atr_period", 20))
        soft_weeks = int(self.s.get("risk.soft_exit_weeks", 10))
        from . import indicators as ind

        for symbol, pos in list(self.positionen.items()):
            df = self.frames.get(symbol)
            if df is None:
                continue
            bis_heute = df[df.index.date <= as_of]
            if bis_heute.empty:
                continue
            woche = _woche(df, vorwoche, as_of)

            # 1. Harter Stop, Tag für Tag — die Kurslücke entscheidet den Füllkurs.
            for tag, zeile in woche.iterrows():
                fill = stop_fuellkurs(stop=pos.stop, eroeffnung=float(zeile["open"]),
                                      tief=float(zeile["low"]))
                if fill is not None:
                    self._schliessen(pos, tag.date(), fill,
                                     "kurslücke" if fill < pos.stop else "stop")
                    break
            if symbol not in self.positionen:
                continue

            schluss = float(bis_heute["close"].iloc[-1])

            # 2. Weicher Exit: Wochenschluss unter dem 10-Wochen-Schnitt.
            weekly = ind.weekly_closes(bis_heute)
            if len(weekly) >= soft_weeks:
                if float(weekly.iloc[-1]) < float(weekly.rolling(soft_weeks).mean().iloc[-1]):
                    self._schliessen(pos, as_of, schluss, "weicher_exit")
                    continue

            # 3. Stop nachziehen — nie senken.
            a = ind.atr(bis_heute, atr_n).iloc[-1]
            if pd.notna(a):
                pos.stop = max(pos.stop, schluss - mult * float(a))

    def _schliessen(self, pos: Position, tag: date, kurs: float, grund: str) -> None:
        self.fx.setze_stichtag(tag)
        try:
            erloes_eur = self.fx.to_eur(kurs * pos.stueck, pos.currency)
        except LookupError:
            return
        gebuehr = self.kosten.order(erloes_eur)
        self.kasse += erloes_eur - gebuehr
        self.kosten_summe += gebuehr
        trade = Trade(pos.symbol, pos.region, pos.eroeffnet, tag, pos.einstand_eur, erloes_eur,
                      pos.kosten_eur + gebuehr, grund, pos.risiko_eur)
        self.trades.append(trade)
        self.steuer.realisiere(tag.year, trade.gewinn_eur)
        del self.positionen[pos.symbol]

    # ------------------------------------------------------------------ Entries
    def _entries(self, as_of: date, readings: dict, cons: list[Constituent]) -> None:
        equity = self.bewertung(as_of)
        if equity <= 0:
            return
        profil = risikoprofil(self.s, equity)
        risk_pct = float(self.s.get("risk.risk_pct", 1.0))
        if len(self.trades) < int(self.s.get("risk.start_trades", 20)):
            risk_pct = float(self.s.get("risk.risk_pct_start", risk_pct))
        ctx = ScreenerContext(satellite_equity_eur=equity, risk_pct=risk_pct, as_of=as_of,
                              profil=profil)
        tabelle = run_screener(cons, self.frames, self.s, self.fx, ctx)
        if tabelle.empty:
            return
        konto = journal.Account(satellite_equity_eur=equity, high_water_mark=equity)
        sichten = [PositionView(p.thesis_id, p.symbol, p.name, p.region, p.currency, p.sector,
                                p.stueck, p.einstand, p.eroeffnet.isoformat(), p.stop,
                                None, None, None, False, False, False, None,
                                max(0.0, self.fx.to_eur((p.einstand - p.stop) * p.stueck, p.currency)))
                    for p in self.positionen.values()]
        risk_by_region = {r: risk_pct for r in readings}
        vorschlaege, _ = select_entries(self.s, tabelle, readings, sichten, konto, self.fx,
                                        risk_by_region, blocked=False)
        for v in vorschlaege:
            if v.symbol in self.positionen:
                continue
            gebuehr = self.kosten.order(v.value_eur)
            if v.value_eur + gebuehr > self.kasse:
                continue
            self.kasse -= v.value_eur + gebuehr
            self.kosten_summe += gebuehr
            self.positionen[v.symbol] = Position(
                v.symbol, v.name, v.region, v.currency, v.sector, v.shares, v.close,
                v.value_eur, v.initial_stop, as_of, gebuehr, risiko_eur=v.risk_eur)

    # ------------------------------------------------------------------ Bewertung
    def bewertung(self, as_of: date) -> float:
        wert = self.kasse
        self.fx.setze_stichtag(as_of)
        for pos in self.positionen.values():
            df = self.frames.get(pos.symbol)
            if df is None:
                continue
            bis = df[df.index.date <= as_of]
            if bis.empty:
                continue
            try:
                wert += self.fx.to_eur(float(bis["close"].iloc[-1]) * pos.stueck, pos.currency)
            except LookupError:
                continue
        return wert

    # ------------------------------------------------------------------ Lauf
    def fehlende_wechselkurse(self) -> list[str]:
        """Währungen ohne Kursreihe — vor dem Lauf zu prüfen, nicht mittendrin.

        Ein fehlender Wechselkurs ist im Backtest kein Randfall: er beträfe jeden Titel
        dieser Währung über den ganzen Zeitraum. Der Live-Pfad nimmt in diesem Fall 1:1 an
        und warnt; über Jahre wäre das eine erfundene Rendite. Hier bricht der Lauf lieber
        ab — aber mit einer Ansage statt mit einer Ausnahme mitten in Woche 34.
        """
        gebraucht = {c.currency.upper() for c in self.konstituenten
                     if c.currency and c.currency.upper() not in ("EUR", "GBX")}
        if any(c.currency and c.currency.upper() == "GBX" for c in self.konstituenten):
            gebraucht.add("GBP")
        return sorted(w for w in gebraucht
                      if self.frames.get(f"EUR{w}=X") is None or self.frames[f"EUR{w}=X"].empty)

    def run(self, von: date, bis: date) -> Ergebnis:
        erg = Ergebnis(von=von, bis=bis, startkapital_eur=self.startkapital)
        freitage = _freitage(von, bis)
        if not freitage:
            erg.hinweise.append("Kein vollständiger Wochenstichtag im Zeitraum.")
            return erg
        fehlt = self.fehlende_wechselkurse()
        if fehlt:
            erg.hinweise.append(
                "Abbruch: keine Wechselkursreihen für " + ", ".join(fehlt) +
                f" (erwartet als EUR{fehlt[0]}=X im Kurs-Cache). Ohne sie wäre der "
                "Euro-Wert jeder Position dieser Währung über den ganzen Zeitraum geraten.")
            return erg
        vorwoche = freitage[0] - timedelta(days=7)
        for as_of in freitage:
            self.fx.setze_stichtag(as_of)
            self._exits(as_of, vorwoche)
            readings = self._ampel(as_of)
            cons = self.historie.am(as_of)
            self._entries(as_of, readings, cons)
            erg.equity.append((as_of, self.bewertung(as_of)))
            vorwoche = as_of

        # Offene Positionen zum Schlusskurs auflösen — sonst hinge das Urteil an Papiergewinnen.
        for pos in list(self.positionen.values()):
            df = self.frames.get(pos.symbol)
            if df is None or df[df.index.date <= bis].empty:
                continue
            self._schliessen(pos, bis, float(df[df.index.date <= bis]["close"].iloc[-1]), "ende")

        erg.trades = self.trades
        erg.endkapital_eur = self.bewertung(bis)
        erg.kosten_eur = self.kosten_summe
        abrechnung = self.steuer.abrechnung()
        erg.steuer_eur = abrechnung["steuer_eur"]
        erg.hinweise.extend(abrechnung["hinweise"])
        erg.abdeckung = self.historie.abdeckung(von)
        erg.hinweise.extend(self.historie.hinweise)
        return erg


def bericht(erg: Ergebnis) -> str:
    """Der Bericht muss das Urteil tragen — und seine Grenzen mit ausweisen.

    Deshalb stehen Abdeckung und Hinweise nicht im Anhang, sondern über dem Ergebnis: ein
    Backtest, der seine Datenlücken verschweigt, behauptet mehr, als er geprüft hat.
    """
    def z(x, n=2):
        return "–" if x is None else f"{x:,.{n}f}".replace(",", " ").replace(".", ",")

    L = [f"# Backtest {erg.von.isoformat()} bis {erg.bis.isoformat()}", ""]

    urteil = erg.besteht()
    b = erg.benchmark or {}
    if not erg.equity:
        # Abgebrochen, bevor eine Woche gerechnet wurde. Dann Nullen als Ergebnis
        # auszuweisen wäre falsch — es gibt keins.
        L += ["## Lauf nicht durchgeführt", ""]
        for h in erg.hinweise:
            L.append(f"- {h}")
        L += ["", "Solange das nicht behoben ist, gibt es kein Urteil nach Trading-Plan 10.3."]
        return "\n".join(L) + "\n"

    if urteil is None:
        L.append("## Kein Urteil möglich")
        L.append("")
        L.append("Es fehlen Trades oder eine Vergleichsreihe. Trading-Plan 10.3 verlangt einen "
                 "Vergleich gegen den Kern-ETF; ohne ihn ist die Latte nicht messbar.")
    else:
        L.append(f"## Urteil: {'BESTANDEN' if urteil else 'NICHT BESTANDEN'}")
        L.append("")
        L.append(f"Satellit netto **{z(erg.netto_eur)} EUR** gegen Kern-ETF netto "
                 f"**{z(b.get('netto_eur'))} EUR** — beides nach Kosten und nach Steuern.")
        if not urteil:
            L.append("")
            L.append("Nach Trading-Plan 10.3 wird der Satellit damit gestrichen und die 10 % "
                     "gehen in den Kern. Parameter zu ändern und erneut zu messen ist eine "
                     "**neue** Entscheidung und braucht einen eigenen Eintrag im "
                     "Änderungsprotokoll — sonst ist der Backtest keine Evidenz, sondern "
                     "eine Rechtfertigung.")

    L += ["", "## Datenlage — vor dem Ergebnis zu lesen", ""]
    a = erg.abdeckung or {}
    if a.get("anteil") is None:
        grund = a.get("hinweis") or ("keine Änderungshistorie hinterlegt "
                                     "(state/universe/sp500_changes.csv)")
        L.append(f"- ⚠️ **US-Universum voll überlebensverzerrt** — {grund}")
    else:
        L.append(f"- US-Universum: {a['geprueft']} von {a['mitglieder']} damaligen Mitgliedern "
                 f"geprüft (**{a['anteil']:.0%}**). Die fehlenden {a['fehlend']} sind die "
                 f"zwischenzeitlich entfernten Titel — der Rest der Verzerrung.")
    for h in erg.hinweise:
        L.append(f"- {h}")

    L += ["", "## Satellit", "",
          f"- Startkapital: {z(erg.startkapital_eur)} EUR",
          f"- Endkapital vor Steuern: {z(erg.endkapital_eur)} EUR",
          f"- Steuern: {z(erg.steuer_eur)} EUR · Transaktionskosten: {z(erg.kosten_eur)} EUR",
          f"- Trades: {len(erg.trades)} · Trefferquote: "
          f"{'–' if erg.treffer is None else f'{erg.treffer:.0%}'} · Expectancy: "
          f"{z(erg.expectancy_r)} R",
          f"- Maximaler Drawdown: {'–' if erg.max_drawdown is None else f'{erg.max_drawdown:.1%}'}"]

    luecken = [t for t in erg.trades if t.grund == "kurslücke"]
    if luecken:
        schlimmste = min(t.r_multiple for t in luecken if t.r_multiple is not None)
        L.append(f"- **{len(luecken)} Exits durch Kurslücke**, schlimmster {z(schlimmste)} R — "
                 f"so viel kostet ein Stop-Market wirklich, wenn der Kurs darunter eröffnet.")

    if b and "netto_eur" in b:
        L += ["", "## Kern-ETF zum Vergleich", "",
              f"- Symbol: {b.get('symbol')}",
              f"- Brutto: {z(b.get('brutto_eur'))} EUR · Steuern: {z(b.get('steuer_eur'))} EUR "
              f"· Kosten: {z(b.get('kosten_eur'))} EUR",
              f"- Netto: **{z(b.get('netto_eur'))} EUR**"]
        for h in b.get("hinweise") or []:
            L.append(f"- {h}")
    elif b.get("fehler"):
        L += ["", f"## Kern-ETF zum Vergleich", "", f"- ⚠️ {b['fehler']}"]

    return "\n".join(L) + "\n"


def kern_etf_referenz(settings: Settings, frames: dict[str, pd.DataFrame], symbol: str,
                      von: date, bis: date, startkapital_eur: float) -> dict:
    """Dieselbe Summe in den Kern-ETF, gehalten bis zum Ende.

    Die Vergleichsgröße aus Trading-Plan 10.3. Bewusst mit allen Vorteilen, die der ETF
    wirklich hat: kostenlose Ausführung, 30 % Teilfreistellung, Steuerstundung bis zum
    Verkauf — und mit dem Nachteil, den er wirklich hat, der Vorabpauschale.
    """
    df = frames.get(symbol)
    if df is None or df.empty:
        return {"fehler": f"Keine Kursreihe für {symbol}"}
    zeitraum = df[(df.index.date >= von) & (df.index.date <= bis)]
    if len(zeitraum) < 2:
        return {"fehler": f"Zu wenig Kurshistorie für {symbol} im Zeitraum"}

    kosten = Kostenmodell.aus_settings(settings)
    steuer = Steuerkonto(satz=Steuersatz.aus_settings(settings),
                         pauschbetrag_eur=float(settings.get("backtest.steuer.pauschbetrag_eur", 1000)))
    zins = basiszins_tabelle(settings)

    start = float(zeitraum["close"].iloc[0])
    gebuehr = kosten.order(startkapital_eur, sparplan=True)
    stueck = (startkapital_eur - gebuehr) / start

    # Vorabpauschale je Kalenderjahr auf den tatsächlichen Jahresverlauf.
    for jahr in range(von.year, bis.year + 1):
        im_jahr = zeitraum[[d.year == jahr for d in zeitraum.index.date]]
        if im_jahr.empty:
            continue
        steuer.vorabpauschale(jahr,
                              wert_anfang=float(im_jahr["close"].iloc[0]) * stueck,
                              wert_ende=float(im_jahr["close"].iloc[-1]) * stueck,
                              basiszins=zins.get(jahr))

    ende = float(zeitraum["close"].iloc[-1])
    brutto = stueck * ende
    verkauf_gebuehr = kosten.order(brutto, sparplan=True)
    gewinn = brutto - verkauf_gebuehr - (startkapital_eur - gebuehr)
    steuer.verkauf_fonds(bis.year, gewinn, teilfreistellung=TEILFREISTELLUNG_AKTIENFONDS)
    abrechnung = steuer.abrechnung()
    return {
        "symbol": symbol,
        "brutto_eur": brutto - verkauf_gebuehr,
        "steuer_eur": abrechnung["steuer_eur"],
        "netto_eur": brutto - verkauf_gebuehr - abrechnung["steuer_eur"],
        "kosten_eur": gebuehr + verkauf_gebuehr,
        "hinweise": abrechnung["hinweise"],
    }

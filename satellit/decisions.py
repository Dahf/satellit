"""Entscheidungen: aus Rohwerten wird genau einmal ein Urteil.

Bis hierher wurde "halten / Stop anheben / verkaufen" an zwei Stellen getrennt abgeleitet —
in report.py für den Bericht und in positions-table.tsx im Dashboard. Zwei Ableitungen
derselben Regel laufen früher oder später auseinander. Hier entsteht das Urteil ein einziges
Mal; Bericht, Push-Nachricht und Oberfläche rendern nur noch, was hier herauskommt.

Das Modul kommt bewusst ohne pandas aus und importiert zur Laufzeit nichts aus pipeline:
so bleibt es ohne Kursdaten und ohne Netz testbar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:                                  # nur für Typprüfer, kein Laufzeit-Import
    from .pipeline import PositionView, Proposal

# --------------------------------------------------------------------------- Verdikte
KAUFEN = "KAUFEN"
VERKAUFEN = "VERKAUFEN"
HALTEN = "HALTEN"
STOP_ANHEBEN = "STOP_ANHEBEN"
NACHKAUFEN = "NACHKAUFEN"          # ausschließlich Kern — im Satelliten verboten (Plan 7)
WARTEN = "WARTEN"
NICHT_KAUFEN = "NICHT_KAUFEN"
PRUEFEN = "PRUEFEN"

VERDIKT_LABEL = {
    KAUFEN: "Kaufen", VERKAUFEN: "Verkaufen", HALTEN: "Halten", STOP_ANHEBEN: "Stop anheben",
    NACHKAUFEN: "Nachkaufen", WARTEN: "Warten", NICHT_KAUFEN: "Nicht kaufen", PRUEFEN: "Prüfen",
}

# Dringlichkeit steuert, was auf der Startseite unter "Das ist zu tun" landet.
SOFORT = 2          # Montag zwingend
DIESE_WOCHE = 1
INFO = 0


# --------------------------------------------------------------------------- Formatierung
def zahl(x: Any, stellen: int = 2, einheit: str = "") -> str:
    """Deutsche Schreibweise: 1.234,56. None und NaN werden zu '–'."""
    try:
        if x is None:
            return "–"
        f = float(x)
        if f != f or f in (float("inf"), float("-inf")):     # NaN/Inf ohne numpy
            return "–"
        return f"{f:,.{stellen}f}{einheit}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "–"


def prozent(x: Any, stellen: int = 1) -> str:
    """Anteil (0,057) -> '5,7 %'."""
    try:
        if x is None:
            return "–"
        f = float(x)
        if f != f:
            return "–"
        return zahl(f * 100, stellen, " %")
    except (TypeError, ValueError):
        return "–"


# --------------------------------------------------------------------------- Bausteine
@dataclass
class Beleg:
    """Eine Zeile der Begründung — erscheint im Aufklapp-Panel als ✓/✗-Liste."""
    label: str
    wert: str
    erfuellt: bool | None = None       # True ✓, False ✗, None = neutrale Information
    regel: str = ""                    # z. B. "Trading-Plan 5.1"


@dataclass
class ChartSpec:
    """Ein Bild statt Kennzahlen — für jemanden, der Kennzahlen (noch) nicht liest."""
    typ: str                           # "kurs"
    punkte: list[dict] = field(default_factory=list)     # [{"d": "2026-03-06", "kurs": …, "sma10w": …}]
    linien: list[dict] = field(default_factory=list)     # [{"y": 148.2, "label": "Stop", "ton": "verkauf"}]
    hinweis: str = ""                  # ein Satz, der das Bild erklärt


@dataclass
class AktionSpec:
    """Was der Nutzer anschließend eintragen kann. Ohne AktionSpec gibt es keinen Knopf."""
    aktion: str                        # Schlüssel der /api/action-Whitelist
    label: str
    felder: list[dict] = field(default_factory=list)     # {"name","label","typ","wert","pflicht"}
    body: dict = field(default_factory=dict)             # feste Vorbelegung, nicht änderbar
    bestaetigung: str = ""             # Satz, den der Nutzer bestätigt


@dataclass
class Decision:
    schluessel: str                    # "TH:th_…" | "PROP:AAPL" | "CASH:satellit"
    art: str                           # satellit_position | satellit_kandidat | satellit_abgelehnt | cash
    topf: str                          # KERN | SATELLIT | GESAMT
    verdikt: str
    verdikt_label: str
    dringlichkeit: int
    begruendung: str                   # EIN deutscher Satz — die Hauptanzeige
    symbol: str = ""
    isin: str = ""
    name: str = ""
    region: str | None = None
    waehrung: str | None = None
    sektor: str | None = None
    hinweise: list[str] = field(default_factory=list)
    belege: list[Beleg] = field(default_factory=list)
    regeln: list[str] = field(default_factory=list)
    chart: ChartSpec | None = None
    # Menge
    stueck: float | None = None
    betrag_eur: float | None = None
    limit_kurs: float | None = None
    stop_kurs: float | None = None
    neuer_stop: float | None = None
    # Bestand
    kurs: float | None = None
    wert_eur: float | None = None
    einstand_eur: float | None = None
    gewinn_eur: float | None = None
    gewinn_pct: float | None = None
    ampel: str | None = None
    ampel_label: str | None = None
    aktion: AktionSpec | None = None
    gesperrt_weil: str | None = None   # gesetzt -> Knopf deaktiviert, Grund im Klartext


@dataclass
class SkipInfo:
    """Warum ein Screener-Kandidat nicht vorgeschlagen wurde — strukturiert, nicht als Satz.

    Die Formulierung entsteht erst hier im Modul. In der Pipeline hat sie nichts zu suchen,
    sonst landet Textgestaltung in der Rechenschicht.
    """
    symbol: str
    name: str = ""
    region: str = ""
    sektor: str = ""
    code: str = ""                     # siehe SKIP_TEXTE
    params: dict = field(default_factory=dict)
    rs_rank_pct: float | None = None


@dataclass
class Kontext:
    """Alles, was die Urteile brauchen — bewusst als einfache Werte, nicht als Pipeline-Objekte."""
    as_of: date
    ampel: dict[str, str | None] = field(default_factory=dict)          # Region -> GREEN/YELLOW/RED/None
    ampel_label: dict[str, str] = field(default_factory=dict)
    ampel_detail: dict[str, str] = field(default_factory=dict)          # Region -> "Uptrend 52 · Breadth 61"
    ampel_note: dict[str, str] = field(default_factory=dict)            # Region -> Grund, falls roh != wirksam
    risk_pct: dict[str, float] = field(default_factory=dict)            # Region -> Risiko je Trade in %
    max_neue_einstiege: dict[str, int] = field(default_factory=dict)
    wochenkurse: dict[str, list[dict]] = field(default_factory=dict)    # Symbol -> Chartpunkte
    equity_eur: float | None = None
    cash_eur: float | None = None
    kill_aktiv: bool = False
    kill_grund: str = ""
    trockenlauf_bis: str | None = None
    soft_exit_wochen: int = 10
    max_positionen: int = 5
    startphase: bool = False           # < risk.start_trades abgeschlossene Trades


# --------------------------------------------------------------------------- Hilfen
def _sperre(ctx: Kontext) -> str | None:
    """Gründe, die jede Order verbieten — gelten für alle Kauf-Urteile gleichermaßen."""
    if ctx.kill_aktiv:
        return f"Kill-Switch aktiv: {ctx.kill_grund or 'siehe Konto'}. Keine neuen Einstiege (Trading-Plan 10)."
    if ctx.trockenlauf_bis:
        return f"Trockenlauf bis {ctx.trockenlauf_bis} — bis dahin nur mitlesen, keine Orders (Trading-Plan 10.1)."
    return None


def _ampel_beleg(ctx: Kontext, region: str | None) -> Beleg | None:
    if not region or region not in ctx.ampel:
        return None
    zustand = ctx.ampel.get(region)
    label = ctx.ampel_label.get(region, "UNBEKANNT")
    detail = ctx.ampel_detail.get(region, "")
    erlaubt = ctx.max_neue_einstiege.get(region)
    risiko = ctx.risk_pct.get(region)
    text = f"{label}"
    if detail:
        text += f" ({detail})"
    if erlaubt is not None and risiko is not None:
        text += f" — höchstens {erlaubt} neue Einstiege, Risiko {zahl(risiko, 2)} % je Trade"
    # Ohne diesen Zusatz wirkt "Uptrend 66, trotzdem ROT" wie ein Fehler des Systems.
    if note := ctx.ampel_note.get(region):
        text += f". {note}"
    return Beleg(f"Ampel {region}", text, erfuellt=(zustand == "GREEN") if zustand else None,
                 regel="Trading-Plan 8")


def _kurschart(ctx: Kontext, symbol: str, linien: list[dict], hinweis: str) -> ChartSpec | None:
    punkte = ctx.wochenkurse.get(symbol)
    if not punkte:
        return None
    return ChartSpec(typ="kurs", punkte=punkte, linien=linien, hinweis=hinweis)


# --------------------------------------------------------------------------- Positionen
def urteil_satellit_position(p: PositionView, ctx: Kontext) -> Decision:
    """Genau ein Urteil je offener Position. Das erste zutreffende gewinnt, der Rest wird Hinweis."""
    belege: list[Beleg] = []
    if p.close is not None:
        belege.append(Beleg("Kurs", f"{zahl(p.close)} {p.currency}"))
    if p.entry:
        belege.append(Beleg("Einstieg", f"{zahl(p.entry)} am {p.entry_date or '?'}"))
    if p.pnl_pct is not None:
        belege.append(Beleg("Gewinn/Verlust", f"{prozent(p.pnl_pct)}"
                            + (f" ({zahl(p.gewinn_eur, 0)} EUR)" if p.gewinn_eur is not None else ""),
                            erfuellt=p.pnl_pct >= 0))
    belege.append(Beleg("Stop", f"{zahl(p.stop)}"
                        + (f" → neu {zahl(p.new_stop)}" if p.stop_raised else " (unverändert)"),
                        regel="Trading-Plan 7"))
    if p.close is not None and p.stop:
        belege.append(Beleg("Abstand zum Stop", prozent(p.close / p.stop - 1.0) if p.stop else "–",
                            regel="Trading-Plan 6"))
    a = _ampel_beleg(ctx, p.region)
    if a:
        belege.append(a)

    gemeinsam = dict(
        schluessel=f"TH:{p.thesis_id}", art="satellit_position", topf="SATELLIT",
        symbol=p.symbol, name=p.name, region=p.region, waehrung=p.currency, sektor=p.sector,
        stueck=p.shares, kurs=p.close, wert_eur=p.wert_eur, einstand_eur=p.einstand_eur,
        gewinn_eur=p.gewinn_eur, gewinn_pct=p.pnl_pct, stop_kurs=p.stop, neuer_stop=p.new_stop,
        belege=belege, ampel=ctx.ampel.get(p.region or ""), ampel_label=ctx.ampel_label.get(p.region or ""),
    )

    linien = [{"y": p.stop, "label": "Stop", "ton": "verkauf"}]
    if p.entry:
        linien.append({"y": p.entry, "label": "Einstieg", "ton": "neutral"})

    # 1. Stop möglicherweise im Depot ausgelöst
    if p.hard_stop_hit:
        return Decision(
            verdikt=PRUEFEN, verdikt_label=VERDIKT_LABEL[PRUEFEN], dringlichkeit=SOFORT,
            begruendung=(f"Das Wochentief lag bei {zahl(p.week_low)} und damit auf oder unter deinem Stop von "
                         f"{zahl(p.stop)} — sieh im Depot nach, ob die Stop-Order ausgeführt wurde."),
            hinweise=(["Falls sie ausgelöst hat, hier den Verkaufskurs eintragen. Falls nicht, nichts tun."]),
            regeln=["Trading-Plan 7"],
            chart=_kurschart(ctx, p.symbol, linien,
                             "Die rote Linie ist dein Stop. Der Kurs hat sie diese Woche berührt."),
            aktion=AktionSpec(
                aktion="journal.close", label="Verkauf eintragen",
                felder=[_feld("price", "Verkaufskurs", "dezimal", p.stop, True),
                        _feld("date", "Datum", "datum", ctx.as_of.isoformat(), True)],
                body={"id": p.thesis_id, "reason": "stop"},
                bestaetigung="Die Stop-Order wurde im Depot ausgeführt.",
            ),
            **gemeinsam)

    # 2. Trend gebrochen -> verkaufen
    if p.soft_exit:
        return Decision(
            verdikt=VERKAUFEN, verdikt_label=VERDIKT_LABEL[VERKAUFEN], dringlichkeit=SOFORT,
            begruendung=(f"Der Wochenschluss liegt unter dem Durchschnitt der letzten {ctx.soft_exit_wochen} Wochen — "
                         f"der Trend ist gebrochen. Alle {zahl(p.shares, 0)} Stück am Montag verkaufen."),
            hinweise=["Bestpreis-Market-Order: Europa 9:05–17:30, USA ab 15:35."],
            regeln=["Trading-Plan 7"],
            chart=_kurschart(ctx, p.symbol, linien,
                             "Die blaue Linie (Kurs) ist unter die graue (Schnitt der letzten 10 Wochen) "
                             "gefallen. Genau das ist die Verkaufsregel."),
            aktion=AktionSpec(
                aktion="journal.close", label="Verkauft",
                felder=[_feld("price", "Verkaufskurs", "dezimal", p.close, True),
                        _feld("date", "Datum", "datum", ctx.as_of.isoformat(), True)],
                # Grund fest vorbelegt: ein Regel-Exit darf nicht versehentlich als
                # "manual" (= Regelbruch) im Journal landen.
                body={"id": p.thesis_id, "reason": "trend"},
                bestaetigung="Ich habe die Position im Depot verkauft.",
            ),
            **gemeinsam)

    # 3. Stop wandert mit
    if p.stop_raised:
        return Decision(
            verdikt=STOP_ANHEBEN, verdikt_label=VERDIKT_LABEL[STOP_ANHEBEN], dringlichkeit=SOFORT,
            begruendung=(f"Der Kurs ist gestiegen, dein Stop wandert von {zahl(p.stop)} auf {zahl(p.new_stop)} mit. "
                         f"Stop-Order im Depot anpassen."),
            hinweise=["Stops werden nur angehoben, nie gesenkt."],
            regeln=["Trading-Plan 7", "Leitsatz 2"],
            chart=_kurschart(ctx, p.symbol,
                             linien + [{"y": p.new_stop, "label": "neuer Stop", "ton": "kaufen"}],
                             "Der Stop rückt dem Kurs nach und sichert einen Teil des Gewinns."),
            aktion=AktionSpec(
                aktion="journal.stop", label=f"Stop auf {zahl(p.new_stop)} gesetzt",
                felder=[_feld("stop", "Neuer Stop", "dezimal", p.new_stop, True)],
                body={"id": p.thesis_id, "note": "Trailing-Stop (Wochenlauf)"},
                bestaetigung="Ich habe die Stop-Order im Depot angepasst.",
            ),
            **gemeinsam)

    # 4. Keine Kursdaten
    if p.note:
        return Decision(
            verdikt=PRUEFEN, verdikt_label=VERDIKT_LABEL[PRUEFEN], dringlichkeit=DIESE_WOCHE,
            begruendung=f"Für {p.symbol} liegen keine aktuellen Kurse vor ({p.note}) — die Position wird gerade nicht überwacht.",
            hinweise=["Symbol in config/symbol_overrides.yaml prüfen."],
            regeln=[], **gemeinsam)

    # 5. Nichts zu tun
    return Decision(
        verdikt=HALTEN, verdikt_label=VERDIKT_LABEL[HALTEN], dringlichkeit=INFO,
        begruendung=f"Trend intakt, Stop unverändert bei {zahl(p.stop)}. Nichts tun.",
        regeln=["Trading-Plan 7"],
        chart=_kurschart(ctx, p.symbol, linien, "Solange die blaue Linie über der grauen bleibt, wird gehalten."),
        **gemeinsam)


# --------------------------------------------------------------------------- Kandidaten
def urteil_satellit_kandidat(p: Proposal, ctx: Kontext) -> Decision:
    sperre = _sperre(ctx)
    rs = f"Top {zahl((p.rs_rank_pct or 0) * 100, 0)} %" if p.rs_rank_pct is not None else "–"
    belege = [
        Beleg("Trend intakt", "Kurs über SMA200 und SMA50 über SMA200", True, "Trading-Plan 5.1"),
        Beleg("Relative Stärke", f"{rs} in {p.region}", True, "Trading-Plan 5.2"),
        Beleg("Ausbruch", f"Wochenschluss {zahl(p.close)} ≥ 20-Wochen-Hoch {zahl(p.breakout_level)}",
              True, "Trading-Plan 5.3"),
        Beleg("Positionsgröße", f"{p.shares} Stück ≈ {zahl(p.value_eur, 0)} EUR", None, "Trading-Plan 6"),
        Beleg("Risiko", f"{zahl(p.risk_eur, 0)} EUR ({zahl(p.risk_pct, 2)} % des Satelliten)", None,
              "Trading-Plan 6"),
        Beleg("Initialstop", f"{zahl(p.initial_stop)} = Einstieg − 3 × ATR(20)", None, "Trading-Plan 6"),
    ]
    if ctx.startphase:
        belege.append(Beleg("Startphase", "Erste 20 Trades: halbes Risiko (0,5 %)", None, "Trading-Plan 6"))
    a = _ampel_beleg(ctx, p.region)
    if a:
        belege.append(a)

    return Decision(
        schluessel=f"PROP:{p.symbol}", art="satellit_kandidat", topf="SATELLIT",
        verdikt=KAUFEN, verdikt_label=VERDIKT_LABEL[KAUFEN], dringlichkeit=DIESE_WOCHE,
        symbol=p.symbol, isin=p.isin, name=p.name, region=p.region, waehrung=p.currency, sektor=p.sector,
        begruendung=(f"Neues 20-Wochen-Hoch bei intaktem Aufwärtstrend, relative Stärke {rs} in {p.region}. "
                     f"{p.shares} Stück ≈ {zahl(p.value_eur, 0)} EUR mit Stop bei {zahl(p.initial_stop)} — "
                     f"dein Verlust ist auf {zahl(p.risk_eur, 0)} EUR begrenzt."),
        hinweise=["Vor der Order: Chart ansehen. Kommt der Ausbruch aus einer ruhigen Seitwärtsphase "
                  "von mindestens vier Wochen? Wenn nicht, Kandidaten streichen."],
        belege=belege, regeln=["Trading-Plan 5", "Trading-Plan 6"],
        stueck=p.shares, betrag_eur=p.value_eur, kurs=p.close, limit_kurs=p.limit_price,
        stop_kurs=p.initial_stop,
        chart=_kurschart(ctx, p.symbol,
                         [{"y": p.breakout_level, "label": "Ausbruch", "ton": "kaufen"},
                          {"y": p.initial_stop, "label": "Stop", "ton": "verkauf"}],
                         "Der Kurs hat das Hoch der letzten 20 Wochen überschritten. Die rote Linie "
                         "begrenzt deinen Verlust, falls es doch nicht aufgeht."),
        ampel=ctx.ampel.get(p.region), ampel_label=p.ampel,
        gesperrt_weil=sperre,
        aktion=None if sperre else AktionSpec(
            aktion="journal.new", label="These anlegen",
            felder=[_feld("entry", "Geplanter Einstieg", "dezimal", p.close, True),
                    _feld("stop", "Initialstop", "dezimal", p.initial_stop, True)],
            body={"symbol": p.symbol},
            bestaetigung="Ich habe den Chart geprüft: der Ausbruch kommt aus einer Base von mindestens vier Wochen.",
        ),
    )


# --------------------------------------------------------------------------- Ablehnungen
SKIP_TEXTE = {
    "BEREITS_GEHALTEN": lambda s: f"{s.symbol} liegt bereits im Depot — ein Titel wird nicht doppelt gekauft.",
    "AMPEL_LIMIT": lambda s: (
        f"Die Ampel {s.region} steht auf {s.params.get('ampel_label', '?')} — bei diesem Stand sind gar keine "
        f"neuen Einstiege erlaubt."
        if not s.params.get("limit") else
        f"Die Ampel {s.region} steht auf {s.params.get('ampel_label', '?')}. Damit sind höchstens "
        f"{s.params['limit']} neue Einstiege je Woche erlaubt, und die sind bereits vergeben."),
    "MAX_POSITIONEN": lambda s: (f"Du hast bereits {s.params.get('max', 5)} offene Positionen — mehr lässt der "
                                 f"Plan nicht zu, damit du den Überblick behältst."),
    "MAX_SEKTOR": lambda s: (f"Im Sektor {s.sektor} liegen schon {s.params.get('max', 2)} Positionen. Mehr wäre "
                             f"ein Klumpenrisiko."),
    "STOP_UNGUELTIG": lambda s: f"Für {s.symbol} lässt sich kein sinnvoller Stop berechnen — deshalb kein Einstieg.",
    "ZU_TEUER": lambda s: (f"Eine einzelne Aktie kostet {zahl(s.params.get('preis_eur'), 0)} EUR. Bei deinem "
                           f"Risiko je Trade käme weniger als ein ganzes Stück heraus, und Bruchstücke lassen "
                           f"keine Stop-Order zu."),
    "GESAMTRISIKO": lambda s: (f"Das offene Gesamtrisiko würde über {zahl(s.params.get('grenze_eur'), 0)} EUR "
                               f"steigen. Erst wenn Stops nachgezogen sind, ist wieder Platz."),
    "KILL_SWITCH": lambda s: "Der Kill-Switch ist aktiv — diese Woche keine neuen Einstiege.",
    "KEIN_KAPITAL": lambda s: "Für den Satelliten ist noch kein Kapital hinterlegt, deshalb keine Positionsgrößen.",
}


def urteil_abgelehnt(s: SkipInfo, ctx: Kontext) -> Decision:
    macher = SKIP_TEXTE.get(s.code)
    text = macher(s) if macher else f"{s.symbol}: {s.code}"
    # Bei roter Ampel trotz guter Rohwerte gehört der Grund dazu, sonst wirkt es wie ein Fehler.
    if s.code == "AMPEL_LIMIT" and (note := ctx.ampel_note.get(s.region or "")):
        text += f" {note}"
    verdikt = WARTEN if s.code in ("AMPEL_LIMIT", "MAX_POSITIONEN", "MAX_SEKTOR", "GESAMTRISIKO") else NICHT_KAUFEN
    return Decision(
        schluessel=f"SKIP:{s.symbol or s.code}", art="satellit_abgelehnt", topf="SATELLIT",
        verdikt=verdikt, verdikt_label=VERDIKT_LABEL[verdikt], dringlichkeit=INFO,
        symbol=s.symbol, name=s.name, region=s.region or None, sektor=s.sektor or None,
        begruendung=text, regeln=["Trading-Plan 5", "Trading-Plan 6"],
        ampel=ctx.ampel.get(s.region or ""), ampel_label=ctx.ampel_label.get(s.region or ""),
    )


# --------------------------------------------------------------------------- Cash
def urteil_cash(ctx: Kontext) -> Decision | None:
    """Warten ist eine Position. Ohne diese Zeile fehlt dem Anfänger die Erlaubnis, nichts zu tun."""
    if ctx.cash_eur is None:
        return None
    return Decision(
        schluessel="CASH:satellit", art="cash", topf="SATELLIT",
        verdikt=HALTEN, verdikt_label=VERDIKT_LABEL[HALTEN], dringlichkeit=INFO,
        name="Freies Satelliten-Kapital", betrag_eur=ctx.cash_eur, wert_eur=ctx.cash_eur,
        begruendung=(f"{zahl(ctx.cash_eur, 0)} EUR liegen bereit. Sie bleiben liegen, bis das System ein Signal "
                     f"gibt — Warten ist eine Position, kein Versäumnis."),
        regeln=["Leitsatz 1"],
    )


# --------------------------------------------------------------------------- Zusammenbau
def urteil_einrichtung(ctx: Kontext) -> Decision | None:
    """Ohne hinterlegtes Kapital rechnet das System keine Positionsgrößen.

    Ohne diese Zeile bliebe die Ansicht komplett leer und der Grund stünde nur versteckt
    unter den Ablehnungen — der Nutzer sähe eine leere Seite und wüsste nicht, warum.
    """
    if ctx.equity_eur:
        return None
    return Decision(
        schluessel="SETUP:kapital", art="einrichtung", topf="SATELLIT",
        verdikt=PRUEFEN, verdikt_label="Einrichten", dringlichkeit=SOFORT,
        name="Satelliten-Kapital hinterlegen",
        begruendung=("Ohne Kapitalbetrag kann das System keine Stückzahlen berechnen — deshalb gibt es "
                     "noch keine Kaufvorschläge. Trag ein, wie viel Geld im Satelliten steckt."),
        hinweise=["Laut Plan sind das rund 10 % deines Gesamtportfolios."],
        regeln=["Trading-Plan 1", "Trading-Plan 6"],
        aktion=AktionSpec(
            aktion="account", label="Kapital eintragen",
            felder=[_feld("equity", "Satelliten-Kapital in EUR", "dezimal", None, True)],
            bestaetigung="",
        ),
    )


def alle_urteile(positionen: list[PositionView], kandidaten: list[Proposal],
                 abgelehnt: list[SkipInfo], ctx: Kontext) -> tuple[list[Decision], list[Decision]]:
    """(Entscheidungen, Ablehnungen). Sortiert nach Dringlichkeit, innerhalb davon stabil."""
    out = [urteil_satellit_position(p, ctx) for p in positionen]
    out += [urteil_satellit_kandidat(p, ctx) for p in kandidaten]
    if einrichtung := urteil_einrichtung(ctx):
        out.append(einrichtung)
    cash = urteil_cash(ctx)
    if cash:
        out.append(cash)
    out.sort(key=lambda d: -d.dringlichkeit)

    # Trading-Plan 7 kennt im Satelliten keine Nachkäufe. Das wird hier strukturell
    # sichergestellt und nicht bloß dadurch, dass niemand ein solches Urteil erzeugt.
    verstoss = [d.schluessel for d in out if d.topf == "SATELLIT" and d.verdikt == NACHKAUFEN]
    if verstoss:
        raise AssertionError(f"Nachkaufen im Satelliten ist verboten (Trading-Plan 7): {verstoss}")

    return out, [urteil_abgelehnt(s, ctx) for s in abgelehnt]


def _feld(name: str, label: str, typ: str, wert: Any = None, pflicht: bool = False) -> dict:
    return {"name": name, "label": label, "typ": typ, "wert": wert, "pflicht": pflicht}

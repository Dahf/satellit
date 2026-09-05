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
    # --- Kern (Phase 2). Ohne Plan bleibt alles davon leer und es entstehen keine Kern-Zeilen.
    kern_plan: Any = None              # portfolio.Plan
    kern_werte: Any = None             # portfolio.Werte
    kern_monat: dict = field(default_factory=dict)
    kauffenster: dict = field(default_factory=dict)
    sparplan_offen: bool = False       # Ausführung dieses Monats fehlt noch
    startbetrag_offen: dict = field(default_factory=dict)   # {etf_eur, aktien_eur}
    kern_thesen: list = field(default_factory=list)         # offene core_holding-Thesen
    depot_abgleich_faellig: bool = False
    band: dict = field(default_factory=dict)


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


# --------------------------------------------------------------------------- Kern
# Der Kern kennt keine Ampel. Trading-Plan 2: "Es wird nicht getimt. Sparplan läuft
# unabhängig von Ampel, Nachrichten und Kursniveau." Deshalb taucht hier nirgends ein
# Ampel-Beleg auf — er wäre schlicht ohne Bedeutung.

def urteil_kern_startbetrag(ctx: Kontext) -> list[Decision]:
    """Der Ersteinstieg — die Antwort auf 'irgendwann muss ich doch mal anfangen'."""
    offen = ctx.startbetrag_offen or {}
    plan = ctx.kern_plan
    out: list[Decision] = []

    etf_eur = float(offen.get("etf_eur") or 0.0)
    if etf_eur > 0 and plan is not None:
        out.append(Decision(
            schluessel="KERN:startbetrag_etf", art="kern_startbetrag", topf="KERN",
            verdikt=KAUFEN, verdikt_label=VERDIKT_LABEL[KAUFEN], dringlichkeit=SOFORT,
            isin=plan.etf_isin, symbol=plan.etf_symbol, name=plan.etf.get("name") or "Welt-ETF",
            betrag_eur=etf_eur,
            begruendung=(f"Leg deinen Kern-Startbetrag an: {zahl(etf_eur, 0)} EUR in "
                         f"{plan.etf.get('name') or plan.etf_symbol}. Das ist unabhängig von der "
                         f"Marktlage — der Kern wird nicht getimt."),
            hinweise=["In der Trade-Republic-App als Einmalkauf, danach hier eintragen.",
                      "Einmal entscheiden, dann nicht mehr ändern (KERN.md 5.3)."],
            belege=[
                Beleg("Warum jetzt", "Der Kern folgt keiner Ampel und keinem Kauffenster.", True,
                      "Trading-Plan 2"),
                Beleg("Modus", "Einmalkauf statt gestreckt — so festgelegt.", None, "KERN.md 5.3"),
            ],
            regeln=["Trading-Plan 2", "KERN.md 5.3"],
            aktion=AktionSpec(
                aktion="ledger.add", label="Kauf eintragen",
                felder=[_feld("betrag_eur", "Bezahlt (EUR)", "dezimal", round(etf_eur, 2), True),
                        _feld("stueck", "Anteile laut App", "dezimal", None, True),
                        _feld("kurs", "Kurs", "dezimal", None, False),
                        _feld("datum", "Datum", "datum", ctx.as_of.isoformat(), True)],
                body={"typ": "sparplan", "topf": "kern_etf", "isin": plan.etf_isin,
                      "symbol": plan.etf_symbol, "notiz": "Startbetrag Kern-ETF"},
                bestaetigung="Ich habe den Kauf in der App ausgeführt.",
            ),
        ))

    aktien_eur = float(offen.get("aktien_eur") or 0.0)
    if aktien_eur > 0:
        fenster = ctx.kauffenster or {}
        hat_these = bool(ctx.kern_thesen)
        gesperrt = None
        if not fenster.get("offen"):
            gesperrt = (f"Kern-Aktien werden nur in der ersten Handelswoche von Januar, April, Juli "
                        f"und Oktober gekauft. Nächstes Fenster: {fenster.get('naechstes') or '?'}.")
        elif not hat_these:
            gesperrt = ("Vor dem Kauf braucht jede Kern-Aktie eine schriftliche These mit "
                        "Kill-Kriterien (Trading-Plan 3.2). Lege sie zuerst an.")
        out.append(Decision(
            schluessel="KERN:startbetrag_aktien", art="kern_startbetrag", topf="KERN",
            verdikt=KAUFEN if not gesperrt else WARTEN,
            verdikt_label=VERDIKT_LABEL[KAUFEN if not gesperrt else WARTEN],
            dringlichkeit=DIESE_WOCHE if not gesperrt else INFO,
            name="Kern-Aktien aus dem Startbetrag", betrag_eur=aktien_eur,
            begruendung=(f"{zahl(aktien_eur, 0)} EUR sind für einzelne Kern-Aktien vorgesehen und liegen "
                         f"bereit." + ("" if gesperrt else " Das Fenster ist offen.")),
            hinweise=["Je Titel höchstens 5 % des Gesamtportfolios, Einzelaktien höchstens 20 % des Kerns.",
                      "KERN.md 6 listet sieben Muss-Kriterien, die jeder Titel erfüllen muss."],
            belege=[
                Beleg("Kauffenster", {"quartal": "reguläres Quartalsfenster",
                                      "ersteinstieg": "einmaliger Ersteinstieg (Startbetrag)",
                                      "geschlossen": f"geschlossen bis {fenster.get('naechstes') or '?'}"}
                      .get(fenster.get("grund", ""), "unbekannt"),
                      bool(fenster.get("offen")), "Trading-Plan 3.4"),
                Beleg("These vorhanden", "ja" if hat_these else "nein — Pflicht vor jedem Kauf",
                      hat_these, "Trading-Plan 3.2"),
            ],
            regeln=["Trading-Plan 3.2", "Trading-Plan 3.3", "Trading-Plan 3.4"],
            gesperrt_weil=gesperrt,
        ))
    return out


def urteil_kern_etf(ctx: Kontext) -> Decision | None:
    """Der monatliche Sparplan — der einzige Automatismus im ganzen System."""
    plan = ctx.kern_plan
    if plan is None or not plan.etf_symbol:
        return None
    rate = float(plan.monatsrate_eur or 0.0) * plan.etf_anteil
    monat = ctx.as_of.strftime("%Y-%m")
    if ctx.sparplan_offen and rate > 0:
        return Decision(
            schluessel="KERN:sparplan", art="kern_etf", topf="KERN",
            verdikt=NACHKAUFEN, verdikt_label=VERDIKT_LABEL[NACHKAUFEN], dringlichkeit=DIESE_WOCHE,
            isin=plan.etf_isin, symbol=plan.etf_symbol, name=plan.etf.get("name") or "Welt-ETF",
            betrag_eur=rate,
            begruendung=(f"Die Sparplan-Ausführung für {monat} fehlt noch: {zahl(rate, 0)} EUR in "
                         f"{plan.etf_symbol}. Sobald sie in der App gelaufen ist, hier eintragen."),
            hinweise=["Der Sparplan wird nie wegen der Marktlage pausiert (Trading-Plan 2)."],
            belege=[Beleg("Ausführungstag", f"{plan.sparplan_tag}. des Monats", None, "KERN.md 5.1"),
                    Beleg("Anteil des Kerns im ETF", prozent(plan.etf_anteil), None, "KERN.md 1")],
            regeln=["Trading-Plan 2", "KERN.md 5"],
            aktion=AktionSpec(
                aktion="ledger.add", label="Ausführung eintragen",
                felder=[_feld("betrag_eur", "Bezahlt (EUR)", "dezimal", round(rate, 2), True),
                        _feld("stueck", "Anteile laut App", "dezimal", None, True),
                        _feld("datum", "Datum", "datum", ctx.as_of.isoformat(), True)],
                body={"typ": "sparplan", "topf": "kern_etf", "isin": plan.etf_isin,
                      "symbol": plan.etf_symbol, "notiz": f"Sparplan {monat}"},
                bestaetigung="Die Ausführung steht in der App.",
            ),
        )
    werte = ctx.kern_werte
    wert = getattr(werte, "kern_etf_eur", None) if werte else None
    if not wert:
        return None
    return Decision(
        schluessel="KERN:etf", art="kern_etf", topf="KERN",
        verdikt=HALTEN, verdikt_label=VERDIKT_LABEL[HALTEN], dringlichkeit=INFO,
        isin=plan.etf_isin, symbol=plan.etf_symbol, name=plan.etf.get("name") or "Welt-ETF",
        wert_eur=wert,
        begruendung=("Der Sparplan läuft. Der Kern wird nicht wegen der Marktlage angefasst — "
                     "auch nicht bei roter Ampel."),
        regeln=["Trading-Plan 2"],
    )


def urteil_kern_aktie(these: dict, wert_eur: float | None, faellig: bool, ctx: Kontext) -> Decision:
    """Kern-Aktien werden gehalten. Verkauft wird nur bei Thesenbruch, nie wegen des Kurses."""
    prov = (these.get("origin") or {}).get("raw_provenance") or {}
    symbol = prov.get("symbol") or these.get("ticker") or ""
    name = str(these.get("thesis_statement") or "").split(" (")[0] or symbol
    review = ((these.get("monitoring") or {}).get("next_review_date") or "")[:10]
    kill = these.get("kill_criteria") or []
    belege = [Beleg("Halteabsicht", "mindestens drei Jahre, kein Stop", None, "Trading-Plan 3.1"),
              Beleg("Nächster Review", review or "offen", None, "KERN.md 6")]
    belege += [Beleg("Kill-Kriterium", k, None, "Trading-Plan 3.2") for k in kill[:4]]

    if faellig:
        return Decision(
            schluessel=f"KERN:{these['thesis_id']}", art="kern_aktie", topf="KERN",
            verdikt=PRUEFEN, verdikt_label=VERDIKT_LABEL[PRUEFEN], dringlichkeit=DIESE_WOCHE,
            symbol=symbol, isin=prov.get("isin", ""), name=name, wert_eur=wert_eur,
            begruendung=(f"Halbjahres-Review für {name} ist fällig. Geh die Kill-Kriterien durch — "
                         f"nur ein Thesenbruch rechtfertigt einen Verkauf, kein Kursrückgang."),
            belege=belege, regeln=["Trading-Plan 3.1", "KERN.md 6"],
        )
    return Decision(
        schluessel=f"KERN:{these['thesis_id']}", art="kern_aktie", topf="KERN",
        verdikt=HALTEN, verdikt_label=VERDIKT_LABEL[HALTEN], dringlichkeit=INFO,
        symbol=symbol, isin=prov.get("isin", ""), name=name, wert_eur=wert_eur,
        begruendung=(f"Kern-Aktie, Halteabsicht mindestens drei Jahre. Ein Kursrückgang ist kein "
                     f"Verkaufsgrund." + (f" Nächster Review: {review}." if review else "")),
        belege=belege, regeln=["Trading-Plan 3.1"],
    )


def urteil_rebalance(ctx: Kontext) -> Decision | None:
    """Nur in der ersten Januarwoche und nur außerhalb des Bandes (Trading-Plan 1)."""
    band = ctx.band or {}
    if band.get("status") in (None, "ok", "unbekannt"):
        return None
    if ctx.as_of.month != 1 or ctx.as_of.day > 7:
        return None
    zu_wenig = band["status"] == "unter"
    gesperrt = None
    if zu_wenig and ctx.kill_aktiv:
        gesperrt = "Bei aktivem Kill-Switch wird der Satellit nicht aufgefüllt (Trading-Plan 1)."
    return Decision(
        schluessel="KERN:rebalance", art="rebalance", topf="GESAMT",
        verdikt=PRUEFEN, verdikt_label=VERDIKT_LABEL[PRUEFEN], dringlichkeit=DIESE_WOCHE,
        name="Kern und Satellit ausgleichen",
        begruendung=(f"Der Satellit liegt bei {prozent(band.get('anteil'))} und damit "
                     + ("unter" if zu_wenig else "über")
                     + f" dem Band von {prozent(band.get('low'))} bis {prozent(band.get('high'))}. "
                     + ("Aus dem Kern auffüllen." if zu_wenig else "Den Überschuss in den Kern übertragen.")),
        belege=[Beleg("Zielanteil", prozent(band.get("ziel")), None, "Trading-Plan 1")],
        regeln=["Trading-Plan 1"], gesperrt_weil=gesperrt,
    )


def urteil_depotabgleich(ctx: Kontext) -> Decision | None:
    """Die Gegenmaßnahme gegen vergessene Buchungen.

    Jede Zahl im Dashboard hängt daran, dass das Kassenbuch vollständig ist. Ohne einen
    regelmäßigen Abgleich mit der App fällt eine fehlende Zeile nie auf.
    """
    if not ctx.depot_abgleich_faellig or ctx.kern_werte is None:
        return None
    gesamt = getattr(ctx.kern_werte, "gesamt_eur", 0.0)
    return Decision(
        schluessel="KERN:abgleich", art="abgleich", topf="GESAMT",
        verdikt=PRUEFEN, verdikt_label=VERDIKT_LABEL[PRUEFEN], dringlichkeit=DIESE_WOCHE,
        name="Depotwert abgleichen", wert_eur=gesamt,
        begruendung=(f"Das System rechnet mit {zahl(gesamt, 0)} EUR. Vergleich das mit der "
                     f"Trade-Republic-App — weicht es ab, fehlt hier eine Buchung."),
        hinweise=["Einmal im Monat genügt. Die Differenz wird als Korrektur gebucht."],
        regeln=[],
        aktion=AktionSpec(
            aktion="depot.abgleich", label="Wert aus der App eintragen",
            felder=[_feld("wert_eur", "Depotwert laut App (EUR)", "dezimal", None, True)],
            body={}, bestaetigung="",
        ),
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
    # Kern zuerst in der Liste erzeugen — er ist der größere Teil des Depots und braucht
    # weder Ampel noch Kapitalfreigabe.
    if ctx.kern_plan is not None:
        out += urteil_kern_startbetrag(ctx)
        if etf := urteil_kern_etf(ctx):
            out.append(etf)
        for these, wert, faellig in ctx.kern_thesen:
            out.append(urteil_kern_aktie(these, wert, faellig, ctx))
        if reb := urteil_rebalance(ctx):
            out.append(reb)
        if abgleich := urteil_depotabgleich(ctx):
            out.append(abgleich)
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

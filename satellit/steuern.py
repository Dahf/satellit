"""Deutsche Kapitalertragsbesteuerung — so weit, wie der Vergleich sie braucht.

Der Backtest misst den Satelliten gegen den Kern-ETF (Trading-Plan 10.3). Ohne Steuermodell
wäre dieser Vergleich zugunsten des Satelliten verfälscht, und zwar in drei Richtungen:

1. **Teilfreistellung.** Beim Aktienfonds sind 30 % des Ertrags steuerfrei (InvStG § 20),
   bei Einzelaktien nichts. Wer beide mit demselben Satz rechnet, benachteiligt den ETF.
2. **Stundung.** Der Satellit realisiert Gewinne bei jedem Exit und versteuert sie sofort;
   der ETF stundet sie bis zum Verkauf. Bei Trendfolge mit Haltedauern von Wochen ist das
   der größere Effekt als der Steuersatz selbst.
3. **Vorabpauschale.** Sie belastet den thesaurierenden ETF laufend (InvStG § 18) und ist
   der einzige Posten, der in die *andere* Richtung wirkt. Sie wegzulassen würde den ETF zu
   gut aussehen lassen — was die Latte für den Satelliten zu niedrig setzte.

**Verlustverrechnung ist kein Detail.** Trendfolge erzeugt viele kleine Verluste und wenige
große Gewinne. Ein Modell, das nur Gewinne besteuert und Verluste ignoriert, überzeichnet
die Steuerlast des Satelliten grob. Verluste werden deshalb im Jahr verrechnet und
unbegrenzt vorgetragen.

**Getrennte Verlustverrechnungstöpfe.** Verluste aus Aktienveräußerungen dürfen nur mit
Gewinnen aus Aktienveräußerungen verrechnet werden (§ 20 Abs. 6 EStG); Fondserträge liegen
im allgemeinen Topf. Im Backtest laufen Satellit und ETF ohnehin als getrennte Szenarien,
die Trennung ist hier also vor allem Dokumentation der Regel — sie verhindert aber, dass
ein späteres gemischtes Szenario still falsch rechnet.

**Was dieses Modul nicht kann und nicht vorgibt zu können:** Kirchensteuer ist abschaltbar
und standardmäßig aus; die Günstigerprüfung, gesonderte Verlustbescheinigungen und die
Sonderregeln für Alt-Anteile fehlen. Für einen Vergleich zweier Anlagewege reicht das; für
eine Steuererklärung nicht.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# InvStG § 20 Abs. 1: Aktienfonds (Aktienquote >= 51 %), Privatanleger.
TEILFREISTELLUNG_AKTIENFONDS = 0.30

# § 20 Abs. 6 EStG: Aktienveräußerungsverluste sind ein eigener Topf.
TOPF_AKTIEN = "aktien"
TOPF_SONSTIGE = "sonstige"


@dataclass(frozen=True)
class Steuersatz:
    """Abgeltungsteuer plus Zuschläge. `kirche` ist 0, solange nichts anderes gesetzt ist."""

    abgeltung: float = 0.25
    soli: float = 0.055
    kirche: float = 0.0

    @property
    def effektiv(self) -> float:
        """0,26375 ohne Kirchensteuer — 25 % zuzüglich 5,5 % Solidaritätszuschlag darauf."""
        return self.abgeltung * (1.0 + self.soli + self.kirche)

    @classmethod
    def aus_settings(cls, settings) -> "Steuersatz":
        return cls(
            abgeltung=float(settings.get("backtest.steuer.abgeltung", 0.25)),
            soli=float(settings.get("backtest.steuer.soli", 0.055)),
            kirche=float(settings.get("backtest.steuer.kirche", 0.0)),
        )


@dataclass
class Jahr:
    """Ein Steuerjahr je Topf: was angefallen ist, bevor verrechnet wird."""

    ertrag_eur: float = 0.0            # bereits um die Teilfreistellung gekürzt
    vorabpauschale_eur: float = 0.0    # ebenfalls gekürzt; mindert später den Veräußerungsgewinn


@dataclass
class Steuerkonto:
    """Führt Erträge, Verlustvorträge, Pauschbetrag und Vorabpauschale über die Jahre.

    Beträge werden **nach** Teilfreistellung eingebucht; wer einbucht, sagt über
    `teilfreistellung`, welcher Anteil steuerfrei bleibt.
    """

    satz: Steuersatz = field(default_factory=Steuersatz)
    pauschbetrag_eur: float = 1000.0
    buch: dict[tuple[int, str], Jahr] = field(default_factory=dict)
    # Je Anteil vorab versteuerte Beträge. Sie mindern den Gewinn beim späteren Verkauf —
    # ohne das würde derselbe Ertrag zweimal besteuert und der ETF zu schlecht dargestellt.
    vorab_versteuert_eur: float = 0.0
    hinweise: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ Einbuchen
    def _jahr(self, jahr: int, topf: str) -> Jahr:
        return self.buch.setdefault((jahr, topf), Jahr())

    def realisiere(self, jahr: int, gewinn_eur: float, *, teilfreistellung: float = 0.0,
                   topf: str = TOPF_AKTIEN) -> None:
        """Einen realisierten Gewinn oder Verlust einbuchen. Verluste gehen negativ ein."""
        self._jahr(jahr, topf).ertrag_eur += gewinn_eur * (1.0 - teilfreistellung)

    def verkauf_fonds(self, jahr: int, gewinn_eur: float, *,
                      teilfreistellung: float = TEILFREISTELLUNG_AKTIENFONDS) -> None:
        """Fondsverkauf: der Gewinn wird um bereits versteuerte Vorabpauschalen gemindert."""
        anrechnung = min(self.vorab_versteuert_eur, max(gewinn_eur, 0.0))
        self.vorab_versteuert_eur -= anrechnung
        self.realisiere(jahr, gewinn_eur - anrechnung, teilfreistellung=teilfreistellung,
                        topf=TOPF_SONSTIGE)

    def vorabpauschale(self, jahr: int, *, wert_anfang: float, wert_ende: float,
                       basiszins: float | None, ausschuettung_eur: float = 0.0,
                       teilfreistellung: float = TEILFREISTELLUNG_AKTIENFONDS) -> float:
        """Vorabpauschale nach InvStG § 18 für ein thesaurierendes Jahr.

        Basisertrag = Wert am Jahresanfang × Basiszins × 0,7, gemindert um Ausschüttungen,
        gedeckelt auf die tatsächliche Wertsteigerung des Jahres, mindestens null.

        `basiszins` veröffentlicht das BMF jährlich. Fehlt er, wird **nicht geschätzt**: die
        Pauschale entfällt für dieses Jahr und ein Hinweis wandert in `hinweise`. Das
        verzerrt zugunsten des ETF und damit gegen den Satelliten — die sichere Richtung,
        weil der Satellit die Beweislast trägt (Trading-Plan 10.3).
        """
        if basiszins is None:
            self.hinweise.append(
                f"{jahr}: keine Vorabpauschale gerechnet — Basiszins des BMF nicht hinterlegt "
                f"(config: backtest.steuer.basiszins). Der ETF ist damit leicht zu gut gestellt.")
            return 0.0
        basisertrag = max(wert_anfang, 0.0) * basiszins * 0.7
        wertsteigerung = max(wert_ende - wert_anfang, 0.0)
        pauschale = max(min(basisertrag - ausschuettung_eur, wertsteigerung), 0.0)
        if pauschale <= 0:
            return 0.0
        steuerpflichtig = pauschale * (1.0 - teilfreistellung)
        self._jahr(jahr, TOPF_SONSTIGE).vorabpauschale_eur += steuerpflichtig
        self.vorab_versteuert_eur += pauschale
        return pauschale

    # ------------------------------------------------------------------ Abrechnen
    def abrechnung(self) -> dict:
        """Steuer je Jahr, mit Verlustvortrag und Pauschbetrag. Reine Auswertung.

        Der Pauschbetrag wird je Jahr über beide Töpfe gemeinsam vergeben — er gilt für alle
        Kapitalerträge zusammen, nicht je Topf. Nicht genutzter Pauschbetrag verfällt;
        Verluste dagegen werden unbegrenzt vorgetragen.
        """
        vortrag = {TOPF_AKTIEN: 0.0, TOPF_SONSTIGE: 0.0}
        je_jahr: dict[int, dict] = {}
        for jahr in sorted({j for j, _ in self.buch}):
            frei = self.pauschbetrag_eur
            steuer_jahr = 0.0
            bemessung_jahr = 0.0
            for topf in (TOPF_AKTIEN, TOPF_SONSTIGE):
                b = self.buch.get((jahr, topf))
                if b is None:
                    continue
                roh = b.ertrag_eur + b.vorabpauschale_eur
                roh -= vortrag[topf]
                if roh < 0:
                    vortrag[topf] = -roh          # bleibt als Verlust stehen
                    continue
                vortrag[topf] = 0.0
                genutzt = min(frei, roh)
                frei -= genutzt
                bemessung = roh - genutzt
                bemessung_jahr += bemessung
                steuer_jahr += bemessung * self.satz.effektiv
            je_jahr[jahr] = {"bemessung_eur": bemessung_jahr, "steuer_eur": steuer_jahr}
        return {
            "je_jahr": je_jahr,
            "steuer_eur": sum(v["steuer_eur"] for v in je_jahr.values()),
            "verlustvortrag_eur": dict(vortrag),
            "satz": self.satz.effektiv,
            "hinweise": list(self.hinweise),
        }


def basiszins_tabelle(settings) -> dict[int, float]:
    """Basiszins je Jahr aus der Konfiguration.

    Bewusst **leer** ausgeliefert: die Werte veröffentlicht das Bundesfinanzministerium
    jedes Jahr im Januar per BMF-Schreiben. Sie hier zu raten hieße, eine Steuerrechnung mit
    erfundenen Zahlen zu füttern und das Ergebnis dann als Entscheidungsgrundlage zu
    verwenden. Fehlende Jahre meldet `Steuerkonto.vorabpauschale` als Hinweis.
    """
    roh = settings.get("backtest.steuer.basiszins", {}) or {}
    return {int(j): float(z) for j, z in roh.items()}

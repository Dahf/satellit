"""Positionsgröße — die eine Stelle, an der aus Risiko und Stopabstand eine Stückzahl wird.

Bis hierher stand dieselbe Rechnung dreimal im Code: in `pipeline.select_entries` (für die
tatsächliche Order), in `screener.evaluate_symbol` (für `target_value_eur` und `price_ok`)
und invertiert in `pipeline.mindestkapital`. Ein Backtest wäre die vierte Stelle geworden —
und ein Backtest, der eine andere Größe rechnet als der Wochenlauf, prüft ein anderes
System als das, das später Geld bewegt. Genau deshalb liegt die Rechnung jetzt hier.

Zwei Größenbegriffe, die sich wirklich unterscheiden und deshalb verschieden heißen:

* `stueck` / `wert_eur` — die **ausführbare Order**. Die Stückzahl ist auf den
  Positionsdeckel begrenzt und im Ganzstück-Fall abgerundet; `wert_eur` ist das, was
  tatsächlich gekauft würde.
* `zielwert_eur` — der **Screening-Wert**. Er deckelt den Wert statt der Stückzahl und ist
  deshalb im Ganzstück-Fall kein Vielfaches des Kurses. Er beantwortet „wie groß wäre die
  Position ungefähr", nicht „was wird geordert", und dient nur den Filtern des Screeners.

Beide fallen bei aktiven Bruchstücken zusammen. Getrennt gehalten werden sie, weil der
Ganzstück-Pfad (`risk.bruchstuecke: false`) weiterhin getestet ist und sein Verhalten
unverändert bleiben muss.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol


class NachEuro(Protocol):
    """Alles, was Beträge in Euro umrechnen kann — in der Praxis `fx.FxTable`."""

    def to_eur(self, amount: float, currency: str) -> float: ...


# Ablehnungsgründe. Es sind dieselben Schlüssel wie in `decisions.SKIP_TEXTE`, damit der
# Aufrufer sie unverändert in eine SkipInfo geben kann und der Nutzer einen ganzen Satz sieht.
STOP_UNGUELTIG = "STOP_UNGUELTIG"
UNTER_MINDESTORDER = "UNTER_MINDESTORDER"
ZU_TEUER = "ZU_TEUER"


@dataclass(frozen=True)
class Groesse:
    """Ergebnis der Größenrechnung. `ablehnung` ist gesetzt, wenn keine Order möglich ist."""

    stueck: float = 0.0
    wert_eur: float = 0.0
    risiko_eur: float = 0.0
    preis_eur: float = 0.0
    stop_abstand_eur: float = 0.0
    zielwert_eur: float = 0.0
    ablehnung: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def moeglich(self) -> bool:
        return self.ablehnung is None


def positionsgroesse(*, equity_eur: float | None, risk_pct: float, close: float,
                     initial_stop: float, currency: str, fx: NachEuro,
                     profil: dict[str, Any],
                     max_price_pct_of_target: float | None = None) -> Groesse:
    """Wie viele Stücke, wie viel Geld, wie viel Risiko — und wenn nichts, warum nicht.

    `profil` ist das Ergebnis von `config.risikoprofil()`; es trägt bereits die Auflösung
    zwischen normalem und `risk.klein`-Profil, damit hier keine zweite Fallunterscheidung
    entsteht.

    `max_price_pct_of_target` ist der alte Preisfilter des Screeners („eine einzelne Aktie
    darf höchstens 40 % der Zielposition ausmachen"). Er gilt ausschließlich im
    Ganzstück-Fall und nur, wenn ein Wert übergeben wird — die Order-Rechnung braucht ihn
    nicht, weil sie dieselbe Frage schon über `stueck < 1` beantwortet.
    """
    if not equity_eur or risk_pct <= 0:
        return Groesse(ablehnung=ZU_TEUER, params={"preis_eur": 0.0})

    stop_abstand_eur = fx.to_eur(float(close) - float(initial_stop), currency)
    if not (stop_abstand_eur > 0):
        return Groesse(stop_abstand_eur=stop_abstand_eur, ablehnung=STOP_UNGUELTIG)

    preis_eur = fx.to_eur(float(close), currency)
    risiko_budget = equity_eur * risk_pct / 100.0
    roh = risiko_budget / stop_abstand_eur

    max_pct = float(profil.get("max_position_pct", 25))
    max_wert = equity_eur * max_pct / 100.0
    deckel = (max_wert / preis_eur) if preis_eur > 0 else 0.0

    # Screening-Wert: Deckel auf den Wert, nicht auf die Stückzahl. Siehe Modul-Docstring.
    # Im Ganzstück-Fall geht die abgerundete Stückzahl ein — sonst fiele der Zielwert höher
    # aus als jede Order, die daraus je würde, und der Preisfilter unten würde zu milde.
    zielwert_eur = min((roh if profil.get("bruchstuecke") else math.floor(roh)) * preis_eur, max_wert)

    basis = dict(preis_eur=preis_eur, stop_abstand_eur=stop_abstand_eur, zielwert_eur=zielwert_eur)

    if profil.get("bruchstuecke"):
        # Auf 4 Nachkommastellen, weil Broker Bruchstücke so ausweisen. Untergrenze ist
        # nicht „eine ganze Aktie", sondern die kleinste sinnvolle Order.
        stueck = round(min(roh, deckel), 4)
        wert_eur = stueck * preis_eur
        min_order = float(profil.get("min_order_eur", 1.0))
        if wert_eur < min_order:
            return Groesse(**basis, stueck=stueck, wert_eur=wert_eur, ablehnung=UNTER_MINDESTORDER,
                           params={"preis_eur": preis_eur, "wert_eur": wert_eur, "min_eur": min_order})
        return Groesse(**basis, stueck=stueck, wert_eur=wert_eur,
                       risiko_eur=stueck * stop_abstand_eur)

    stueck = float(math.floor(min(math.floor(roh), math.floor(deckel))))
    if stueck < 1:
        return Groesse(**basis, ablehnung=ZU_TEUER, params={"preis_eur": preis_eur})
    if max_price_pct_of_target is not None and not (
            zielwert_eur > 0 and preis_eur <= max_price_pct_of_target * zielwert_eur):
        return Groesse(**basis, ablehnung=ZU_TEUER, params={"preis_eur": preis_eur})
    return Groesse(**basis, stueck=stueck, wert_eur=stueck * preis_eur,
                   risiko_eur=stueck * stop_abstand_eur)


def mindestkapital_je_titel(*, stop_abstand_eur: float, preis_eur: float, risk_pct: float,
                            profil: dict[str, Any]) -> float:
    """Die Umkehrung: welches Satelliten-Kapital macht *diesen* Titel gerade kaufbar?

    Gehört hierher und nicht in die Pipeline, weil sie exakt die Grenzen invertiert, die
    `positionsgroesse` anlegt — stehen beide auseinander, laufen sie irgendwann auseinander.

    Zur Drei im Ganzstück-Fall: der Preisfilter verlangt Kurs ≤ 40 % der Zielposition. Bei
    einem Stück wäre die Zielposition genau ein Kurs, die Bedingung also nie erfüllbar;
    erst ab drei Stück geht die Ungleichung auf.
    """
    max_pct = float(profil.get("max_position_pct", 25))
    if profil.get("bruchstuecke"):
        # Es genügt, die Mindestordergröße zu erreichen.
        return float(profil.get("min_order_eur", 1.0)) * 100.0 / max_pct
    aus_risiko = 3.0 * stop_abstand_eur * 100.0 / risk_pct
    aus_deckel = 3.0 * preis_eur * 100.0 / max_pct
    return max(aus_risiko, aus_deckel)

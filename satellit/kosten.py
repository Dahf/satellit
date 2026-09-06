"""Transaktionskosten — die Posten, die einen kleinen Satelliten entscheiden.

Die Zahlen sind nicht geschätzt. Aus 49 eigenen Trade-Republic-Orders
(`account_transactions.csv`, 2024-12 bis 2026-05):

* **1,00 € pauschal je manueller Order**, Kauf wie Verkauf, ohne jede Varianz — 41 von 41
  gebührenpflichtigen Orders exakt 1,00 €, unabhängig von der Ordergröße.
* **Sparplan-Ausführungen kostenlos** (8 von 8). Das begünstigt den Kern-ETF gegenüber dem
  Satelliten und gehört genau deshalb ins Modell.
* Tatsächliche Kostenquote der manuellen Orders: 1,80 % im Mittel, 4,79 % im schlechtesten
  Fall (Verkauf über 20,88 € mit 1,00 € Gebühr).

Warum das trägt: eine Pauschale ist bei kleinen Positionen keine Nebensache, sondern der
dominante Posten. Bei 83 € Position sind 2,00 € Roundtrip 2,4 % — gegen einen Bruttoedge
von rund 2,7 % bei 0,3R und 9 % Stopabstand. Ein Backtest ohne diesen Posten prüft nicht
die Strategie, sondern eine Fantasie.

Der Spread ist der unsichere Teil: Trade Republic weist ihn nirgends strukturiert aus (auch
nicht in `all_events.json`; er steckt nur in den MiFID-PDFs). Er ist deshalb eine **gesetzte
Annahme** aus der Konfiguration und keine Messung — und als solche im Bericht auszuweisen.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Kostenmodell:
    """Was eine Order kostet. Alle Angaben in EUR bzw. als Anteil des Ordervolumens."""

    order_gebuehr_eur: float = 1.00
    """Pauschale je manueller Order. Belegt, nicht geschätzt."""

    spread_pct: float = 0.001
    """Halber Geld-Brief-Spread **je Seite**, als Anteil. Annahme, keine Messung."""

    sparplan_gebuehr_eur: float = 0.0
    """Sparplan-Ausführungen sind kostenlos — der strukturelle Vorteil des Kerns."""

    @classmethod
    def aus_settings(cls, settings) -> "Kostenmodell":
        return cls(
            order_gebuehr_eur=float(settings.get("backtest.order_gebuehr_eur", 1.00)),
            spread_pct=float(settings.get("backtest.spread_pct", 0.001)),
            sparplan_gebuehr_eur=float(settings.get("backtest.sparplan_gebuehr_eur", 0.0)),
        )

    def order(self, wert_eur: float, *, sparplan: bool = False) -> float:
        """Kosten einer Seite: Pauschale plus Spread auf das Volumen."""
        gebuehr = self.sparplan_gebuehr_eur if sparplan else self.order_gebuehr_eur
        return gebuehr + abs(wert_eur) * self.spread_pct

    def roundtrip(self, wert_eur: float) -> float:
        """Kauf und Verkauf zusammen — die Zahl, gegen die ein Edge bestehen muss."""
        return self.order(wert_eur) * 2.0

    def anteil_am_edge(self, wert_eur: float, edge_r: float, stop_abstand_pct: float) -> float | None:
        """Welcher Anteil eines Bruttoedges geht für Kosten drauf?

        Die Kennzahl, an der die Positionsgröße hängt: ein Edge von `edge_r` R entspricht bei
        einem Stopabstand von `stop_abstand_pct` genau `edge_r * stop_abstand_pct` des
        Positionswerts. Liegt der Roundtrip in derselben Größenordnung, ist die Strategie
        eine Gebührenumleitung zum Broker, unabhängig davon, wie gut die Signale sind.
        """
        brutto = abs(wert_eur) * edge_r * stop_abstand_pct
        if brutto <= 0:
            return None
        return self.roundtrip(wert_eur) / brutto


def stop_fuellkurs(*, stop: float, eroeffnung: float, tief: float) -> float | None:
    """Zu welchem Kurs füllt ein ruhender Stop-Market tatsächlich?

    Ein Stop-Market wird zur Market-Order, sobald der Kurs den Stop berührt. Drei Fälle:

    * Der Kurs eröffnet **unter** dem Stop (Kurslücke): die Order wird sofort zur
      Market-Order und füllt zur Eröffnung — **nicht** am Stop. Genau hier entsteht der
      Verlust jenseits von 1R, den ein Backtest verschweigt, der immer am Stop füllt.
    * Der Kurs eröffnet darüber und fällt im Tagesverlauf auf oder unter den Stop: Fill am
      Stop. Slippage innerhalb des Tages wird nicht modelliert — sie ist klein gegen die
      Kurslücke und wäre geraten.
    * Der Stop wird nicht berührt: kein Fill.

    Ohne diesen Fall ist jedes ausgewiesene R eine Behauptung statt einer Messung: das
    Risikomodell des Trading-Plans unterstellt, ein Stop koste genau 1R.
    """
    if eroeffnung <= stop:
        return eroeffnung
    if tief <= stop:
        return stop
    return None

"""Kriterienkatalog für Kern-Aktien (docs/KERN.md 6) als Code.

Ein **Filter, kein Score** — KERN.md 6: „ein Titel muss *alle* Muss-Kriterien erfüllen."
Deshalb gibt es hier keine gewichtete Punktzahl, die ein schwaches Kriterium durch ein
starkes ausgleicht. Sortiert wird erst unter den Bestandenen, und nur nach den
Soll-Kriterien, die der Katalog ausdrücklich als Tiebreaker bezeichnet.

Drei der sieben Kriterien kann Code nicht beantworten:

* **1 — Geschäftsmodell in zwei Sätzen erklärbar.** Das ist eine Aussage über den Leser,
  nicht über die Firma.
* **7 — Kill-Kriterien schriftlich.** Existiert erst, wenn jemand sie geschrieben hat.
* Teile von **2 und 5**, wenn die Quelle nicht weit genug zurückreicht.

Sie bleiben `erfuellt=None` und werden über Pflichtfelder beim Anlegen der These erzwungen
(siehe `decisions.urteil_kern_kandidat`). `None` heißt „ungeprüft", nicht „erfüllt" — die
Unterscheidung ist der ganze Zweck der Übung, denn ein Katalog, der Unbekanntes durchwinkt,
prüft nichts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from .config import Settings
from .fundamentals import Fundamentals

log = logging.getLogger(__name__)

# Die Nummern sind die aus docs/KERN.md 6 — sie stehen im Beleg und müssen dort wiedererkennbar sein.
MUSS = (1, 2, 3, 4, 5, 6, 7)


@dataclass
class Kriterium:
    nummer: int
    label: str
    erfuellt: bool | None          # None = Datenlage reicht nicht oder menschliches Urteil
    wert: str
    regel: str = "KERN.md 6"

    @property
    def gescheitert(self) -> bool:
        return self.erfuellt is False


@dataclass
class KernKandidat:
    symbol: str
    isin: str = ""
    name: str = ""
    sektor: str = ""
    waehrung: str = ""
    region: str = ""
    kurs_eur: float | None = None
    kriterien: list[Kriterium] = field(default_factory=list)
    soll: list[Kriterium] = field(default_factory=list)
    ausschluss: str = ""                    # gesetzt -> raus, unabhängig von den Kriterien
    jahre_abgedeckt: int = 0
    daten_stand: str | None = None

    @property
    def durchgefallen(self) -> list[Kriterium]:
        return [k for k in self.kriterien if k.gescheitert]

    @property
    def ungeprueft(self) -> list[Kriterium]:
        return [k for k in self.kriterien if k.erfuellt is None]

    @property
    def bestanden(self) -> bool:
        """Kein Muss-Kriterium verletzt und kein Ausschlussgrund.

        Ungeprüfte Kriterien verhindern das Bestehen nicht — sonst käme nie ein Titel durch,
        weil 1 und 7 grundsätzlich offen sind. Sie bleiben aber sichtbar: die Entscheidung
        trifft der Mensch, und er sieht, was offen ist.
        """
        return not self.ausschluss and not self.durchgefallen

    @property
    def erfuellte_soll(self) -> int:
        return sum(1 for k in self.soll if k.erfuellt)


def _trend_steigend(reihe: dict[int, float], jahre: int) -> tuple[bool | None, str]:
    """Kriterium 2: „über 5–10 Jahre gestiegen (nicht jedes Jahr, aber der Trend)".

    Verglichen wird der Mittelwert der ersten Hälfte mit dem der zweiten — ein Vergleich nur
    von Anfangs- und Endjahr würde an einem einzelnen schwachen Jahr hängen, und genau das
    schließt der Katalog aus.
    """
    if len(reihe) < 3:
        return None, f"nur {len(reihe)} Jahre bekannt"
    jahre_sortiert = sorted(reihe)[-jahre * 2:]
    if len(jahre_sortiert) < 3:
        return None, f"nur {len(jahre_sortiert)} Jahre bekannt"
    mitte = len(jahre_sortiert) // 2
    frueh = [reihe[j] for j in jahre_sortiert[:mitte]]
    spaet = [reihe[j] for j in jahre_sortiert[-mitte:]]
    a, b = sum(frueh) / len(frueh), sum(spaet) / len(spaet)
    gestiegen = b > a
    text = f"{jahre_sortiert[0]}–{jahre_sortiert[-1]}: {'steigend' if gestiegen else 'nicht steigend'}"
    if len(jahre_sortiert) < jahre:
        # Der Trend über drei Jahre ist nicht der Trend über den Zyklus, nach dem der
        # Katalog fragt. Er darf nicht als solcher durchgehen.
        return None, text + f" (nur {len(jahre_sortiert)} von {jahre} Jahren)"
    return gestiegen, text


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x * 100:.1f} %".replace(".", ",")


def pruefe(f: Fundamentals, settings: Settings, *, isin: str = "", name: str = "",
           sektor: str = "", region: str = "", kurs_eur: float | None = None,
           jahre_notiert: float | None = None, im_satelliten: bool = False,
           auf_watchlist: bool = False, as_of: date | None = None) -> KernKandidat:
    """Einen Titel gegen den Katalog prüfen.

    `jahre_notiert` kommt vom Aufrufer, weil die Kurshistorie im Kurs-Cache liegt und nicht
    in den Fundamentaldaten — Kriterium 6 lässt sich damit ohne zusätzlichen Abruf belegen.
    """
    as_of = as_of or date.today()
    k = KernKandidat(symbol=f.symbol, isin=isin, name=name or f.symbol, sektor=sektor,
                     waehrung=f.waehrung, region=region, kurs_eur=kurs_eur,
                     jahre_abgedeckt=f.jahre_abgedeckt, daten_stand=f.abgerufen_am)

    # --- Ausschlusskriterien (KERN.md 6, „Ausschlusskriterien") --------------------
    if im_satelliten:
        k.ausschluss = ("Der Titel läuft im Satelliten. Kein Doppelhalten — sonst hängt an einer "
                        "Firma zweimal Geld mit gegensätzlichen Regeln.")
    elif auf_watchlist:
        k.ausschluss = "Der Titel steht auf der Screener-Watchlist des Satelliten. Kein Doppelhalten."

    # --- 1: Geschäftsmodell — menschliches Urteil ---------------------------------
    k.kriterien.append(Kriterium(
        1, "Geschäftsmodell in zwei Sätzen erklärbar", None,
        "beim Anlegen der These zu beantworten"))

    # --- 2: Wachstum über den Zyklus ----------------------------------------------
    jahre = int(settings.get("kern.wachstum_jahre", 5))
    umsatz_ok, umsatz_text = _trend_steigend(f.umsatz, jahre)
    eps_ok, eps_text = _trend_steigend(f.eps, jahre)
    if umsatz_ok is False or eps_ok is False:
        zusammen: bool | None = False
    elif umsatz_ok is None or eps_ok is None:
        zusammen = None
    else:
        zusammen = True
    k.kriterien.append(Kriterium(
        2, "Umsatz und Gewinn je Aktie über den Zyklus gestiegen", zusammen,
        f"Umsatz {umsatz_text} · EPS {eps_text}"))

    # --- 3: Kapitalrendite über Kapitalkosten -------------------------------------
    schwelle = float(settings.get("kern.min_roic", 0.10))
    fenster = int(settings.get("kern.roic_jahre", 5))
    reihe = f.roic or f.roe
    quelle = "ROIC" if f.roic else "ROE"
    werte = [reihe[j] for j in sorted(reihe)[-fenster:]]
    if not werte:
        k.kriterien.append(Kriterium(3, "Kapitalrendite nachhaltig über 10 %", None,
                                     "keine Renditekennzahl in der Quelle"))
    else:
        schnitt = sum(werte) / len(werte)
        text = f"{quelle} {_pct(schnitt)} im Schnitt über {len(werte)} Jahre (nötig > {_pct(schwelle)})"
        if len(werte) < fenster:
            # Zwei gute Jahre sind kein Fünfjahresschnitt.
            k.kriterien.append(Kriterium(3, "Kapitalrendite nachhaltig über 10 %", None,
                                         text + f" — {fenster} Jahre gefordert"))
        else:
            k.kriterien.append(Kriterium(3, "Kapitalrendite nachhaltig über 10 %",
                                         schnitt > schwelle, text))

    # --- 4: Bilanz ----------------------------------------------------------------
    max_verschuldung = float(settings.get("kern.max_net_debt_ebitda", 2.5))
    if f.nettoschulden is None or not f.ebitda:
        k.kriterien.append(Kriterium(4, "Nettoverschuldung / EBITDA unter 2,5", None,
                                     "Nettoverschuldung oder EBITDA fehlt in der Quelle"))
    elif f.nettoschulden <= 0:
        k.kriterien.append(Kriterium(4, "Nettoverschuldung / EBITDA unter 2,5", True,
                                     "Nettoliquidität statt Nettoschulden"))
    else:
        quote = f.nettoschulden / f.ebitda
        k.kriterien.append(Kriterium(
            4, "Nettoverschuldung / EBITDA unter 2,5", quote < max_verschuldung,
            f"{quote:.2f}".replace(".", ",") + f" (Grenze {max_verschuldung})".replace(".", ",")))

    # --- 5: Free Cashflow ---------------------------------------------------------
    fenster_fcf = int(settings.get("kern.fcf_fenster", 10))
    noetig = int(settings.get("kern.fcf_mindestens", 8))
    jahre_fcf = sorted(f.fcf)[-fenster_fcf:]
    positiv = sum(1 for j in jahre_fcf if f.fcf[j] > 0)
    if not jahre_fcf:
        k.kriterien.append(Kriterium(5, "Free Cashflow in 8 von 10 Jahren positiv", None,
                                     "keine Cashflow-Rechnung in der Quelle"))
    elif len(jahre_fcf) < fenster_fcf:
        # Der entscheidende Fall: 4 von 4 positiven Jahren beantworten die Frage nach
        # 8 von 10 nicht. Als „erfüllt" gezählt, wäre der Katalog eine Attrappe.
        negativ = len(jahre_fcf) - positiv
        erfuellt = False if negativ > (fenster_fcf - noetig) else None
        k.kriterien.append(Kriterium(
            5, "Free Cashflow in 8 von 10 Jahren positiv", erfuellt,
            f"{positiv} von {len(jahre_fcf)} bekannten Jahren positiv — "
            f"{fenster_fcf}-Jahres-Fenster nicht abgedeckt"))
    else:
        k.kriterien.append(Kriterium(
            5, "Free Cashflow in 8 von 10 Jahren positiv", positiv >= noetig,
            f"{positiv} von {len(jahre_fcf)} Jahren positiv (nötig {noetig})"))

    # --- 6: Größe und Historie ----------------------------------------------------
    # Zur Notierungsdauer zwei Quellen mit ungleichem Gewicht: die Erstnotiz der Quelle ist
    # eine Aussage über die Firma; die Länge der Kursreihe ist eine Aussage über den Cache.
    # Letztere kann Alter nur *belegen*, nie widerlegen — der Cache wird mit 420 Tagen
    # gefüllt, also ist jede Reihe anfangs kurz, auch bei hundertjährigen Konzernen.
    min_jahre = float(settings.get("kern.min_jahre_notiert", 5))
    min_kap = float(settings.get("kern.min_marktkap_eur", 5e9))
    teile: list[str] = []
    sechs: bool | None = True

    alter = None
    if f.erstnotiz:
        try:
            alter = (as_of - date.fromisoformat(f.erstnotiz)).days / 365.25
            teile.append(f"seit {alter:.0f} Jahren notiert ({f.erstnotiz[:4]})")
        except ValueError:
            alter = None
    if alter is None and jahre_notiert is not None and jahre_notiert >= min_jahre:
        alter = jahre_notiert
        teile.append(f"mindestens {jahre_notiert:.0f} Jahre Kurshistorie")
    if alter is None:
        sechs = None
        teile.append("Notierungsdauer unbekannt")
    elif alter < min_jahre:
        sechs = False

    if f.marktkap_eur is None:
        if sechs is not False:
            sechs = None
        teile.append("Marktkapitalisierung unbekannt")
    else:
        teile.append(f"{f.marktkap_eur / 1e9:.1f}".replace(".", ",") + " Mrd. EUR")
        if f.marktkap_eur < min_kap:
            sechs = False
    k.kriterien.append(Kriterium(6, "Über 5 Jahre notiert, über 5 Mrd. EUR schwer", sechs,
                                 " · ".join(teile)))

    # --- 7: Kill-Kriterien — menschliches Urteil ----------------------------------
    k.kriterien.append(Kriterium(
        7, "Mindestens zwei Kill-Kriterien schriftlich", None,
        "beim Anlegen der These zu benennen", "Trading-Plan 3.2"))

    # --- Soll-Kriterien (Tiebreaker, kein Muss) -----------------------------------
    if f.dividende:
        jahre_div = sorted(f.dividende)
        gekuerzt = [j for i, j in enumerate(jahre_div[1:], start=1)
                    if f.dividende[j] < f.dividende[jahre_div[i - 1]] * 0.99]
        k.soll.append(Kriterium(0, "Dividende nicht gekürzt", not gekuerzt,
                                f"{len(jahre_div)} Jahre bekannt"
                                + (f", zuletzt gekürzt {max(gekuerzt)}" if gekuerzt else ", keine Kürzung")))
    if len(f.aktienzahl) >= 2:
        jahre_a = sorted(f.aktienzahl)
        sinkt = f.aktienzahl[jahre_a[-1]] < f.aktienzahl[jahre_a[0]]
        k.soll.append(Kriterium(0, "Aktienzahl sinkt (Rückkäufe wirken)", sinkt,
                                f"{f.aktienzahl[jahre_a[0]] / 1e6:.0f} → "
                                f"{f.aktienzahl[jahre_a[-1]] / 1e6:.0f} Mio. Stück"))
    return k


def rangfolge(kandidaten: list[KernKandidat]) -> list[KernKandidat]:
    """Bestandene zuerst, darunter nach erfüllten Soll-Kriterien, dann nach Datenabdeckung.

    Die Abdeckung als letztes Kriterium ist Absicht: bei sonst gleichem Bild ist der Titel
    vorzuziehen, über den mehr bekannt ist.
    """
    return sorted(kandidaten, key=lambda k: (
        not k.bestanden, -k.erfuellte_soll, len(k.ungeprueft), -k.jahre_abgedeckt, k.symbol))


def trichter(kandidaten: list[KernKandidat]) -> dict[str, int]:
    """Wo die Titel hängen bleiben — nach dem Vorbild des Screener-Trichters.

    Gezählt wird je Titel das *erste* verletzte Kriterium, damit sich die Zahlen zur
    Gesamtzahl addieren und niemand versucht, aus überlappenden Mengen etwas abzuleiten.
    """
    out = {"gesamt": len(kandidaten), "ausgeschlossen": 0, "bestanden": 0}
    for nummer in MUSS:
        out[f"kriterium_{nummer}"] = 0
    for k in kandidaten:
        if k.ausschluss:
            out["ausgeschlossen"] += 1
        elif k.bestanden:
            out["bestanden"] += 1
        else:
            out[f"kriterium_{k.durchgefallen[0].nummer}"] += 1
    return out

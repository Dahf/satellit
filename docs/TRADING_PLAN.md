# Trading-Plan — Core-Satellite-Portfolio

**Version 1.0 · Stand 2026-09-05 · Verbindliches Regelwerk**

> Dieses Dokument ist die einzige Quelle für alle Regeln. Was hier nicht steht, ist nicht erlaubt.
> Regeln werden nur nach dem Verfahren in Abschnitt 12 geändert — nie während der Handelszeit, nie für einen laufenden Trade.
>
> Dies ist ein selbst gegebenes Regelwerk, keine Anlageberatung. Jede Kauf- und Verkaufsentscheidung liegt beim Depotinhaber.

---

## 0. Leitsätze (in Woche 7 zuerst lesen)

1. **Das System entscheidet, nicht die Meinung.** Ein Trade ohne Signal ist ein Regelbruch, auch wenn er gewinnt.
2. **Stops werden nie gesenkt.** Nie. Aus keinem Grund.
3. **Kern ist kein Chart, Satellit ist nur Chart.** Kern-Positionen werden nicht getradet, Satelliten-Positionen nicht "gehalten, weil das Unternehmen gut ist".
4. **Keine Order ohne Journaleintrag.** These zuerst, Order danach.
5. **Verluste sind Betriebskosten.** Eine Serie von fünf kleinen Verlusten ist bei Trendfolge normal und kein Grund, das System zu ändern. Der Kill-Switch (Abschnitt 10) definiert, was *nicht* normal ist.

---

## 1. Portfolio-Architektur

| Baustein | Anteil | Zweck | Zeithorizont |
|---|---|---|---|
| **Kern** | ~90 % | Vermögensaufbau, Marktrendite | Jahre bis Jahrzehnte |
| **Satellit** | ~10 % | Systematisches Positions-Trading, Lernen mit echtem Geld | Wochen bis Monate pro Trade |

- **Broker:** Trade Republic. Ordermodell seit 02.07.2026: *Bestpreis-Order* (1 € Abwicklungspauschale, 07:30–23:00 Uhr, Ausführung über mehrere Referenzbörsen) und *Direktpreis-Order* (2 €, freie Börsenwahl). Sparpläne kostenlos.
- **Kapitalzufluss:** Startbetrag wird 90/10 verteilt. Der monatliche Sparplan fließt **vollständig in den Kern**.
- **Rebalancing Kern/Satellit:** Einmal jährlich in der ersten Handelswoche im Januar.
  - Satellit > 15 % des Gesamtportfolios → Überschuss über 10 % in den Kern übertragen.
  - Satellit < 7 % → aus dem Kern auf 10 % auffüllen — **nur wenn der Kill-Switch (Abschnitt 10) nicht ausgelöst ist.**
  - Dazwischen: nichts tun.

---

## 2. Kern — ETF-Teil (≥ 80 % des Kerns)

- Ein oder wenige breit gestreute Welt-ETFs per Sparplan (Auswahlkriterien und Kandidaten: `docs/KERN.md`).
- **Es wird nicht getimt.** Sparplan läuft unabhängig von Ampel, Nachrichten und Kursniveau.
- Verkauf aus dem ETF-Teil nur für das jährliche Rebalancing oder bei geändertem Lebensziel — nie wegen Marktlage.
- Im Januar liegt Cash für die Vorabpauschale auf dem Verrechnungskonto (Basiszins 2026: 3,20 %).

## 3. Kern — Einzelaktien-Teil (≤ 20 % des Kerns)

**Abgrenzungsregel — was eine Kern-Aktie ist:**

1. **Halteabsicht ≥ 3 Jahre, kein Stop.** Verkauf nur bei *Thesenbruch* (Geschäftsmodell, Bilanz, Management), nie wegen Kursverlauf. Ein Kursrückgang von −40 % ist kein Thesenbruch.
2. **Schriftliche These vor dem Kauf** im Journal (`trader-memory-core`, Typ `core_holding` im Feld `setup_type`, Review-Datum +6 Monate). Ohne These kein Kauf. Die These benennt explizit die **Kill-Kriterien** (was müsste passieren, damit ich verkaufe).
3. **Max. 5 % des Gesamtportfolios pro Titel** (zum Kaufzeitpunkt). Bei 20 % des Kerns sind das 4–6 Titel. Keine Ausnahme.
4. **Kauf nur an festen Terminen:** erste Handelswoche im Januar, April, Juli, Oktober. Zwischen den Terminen werden Kandidaten nur notiert, nie gekauft.
   *Ausnahme Depotaufbau:* Der **einmalige** Kern-Startbetrag nach `docs/KERN.md` Abschnitt 5.3 darf beim Aufbau des Depots in einem Zug investiert werden — er ist Einrichtung, keine Timing-Entscheidung. Die Regeln 3.2 (schriftliche These mit Kill-Kriterien) und 3.3 (5 % je Titel) gelten unverändert. Ab dem zweiten Kauf gelten ausschließlich die vier Termine. Siehe `docs/CHANGELOG_REGELN.md`, Eintrag 2026-09-05.
5. **Kein Doppelhalten.** Ein Titel ist entweder Kern oder Satellit. Ein Satelliten-Trade in einer Kern-Aktie ist verboten, eine Kern-Position in einem Satelliten-Titel ebenfalls (Prüfung: der Screener blendet Kern-Titel aus).

Kriterienkatalog für Kern-Aktien: `docs/KERN.md`, Abschnitt 4.

---

## 4. Satellit — Universum und Instrumente

| Regel | Festlegung |
|---|---|
| Universum | Konstituenten S&P 500 + STOXX Europe 600 (Quelle: iShares-Holdings-Dateien, monatlich aktualisiert) |
| Instrumente | Nur Long-Aktien. Keine Hebelprodukte, keine Optionen, kein Krypto, keine Leerverkäufe |
| Stückelung | **Nur ganze Stücke.** Bruchstück-Orders bei Trade Republic sind nur als Market-Order möglich und lassen keine Stop-Orders auf den Bruchstück-Anteil zu — deshalb ausgeschlossen |
| Liquidität | Durchschnittlicher Tagesumsatz (20 Tage) ≥ 5 Mio. € bzw. USD |
| Preisfilter | Stückpreis ≤ 40 % der Zielpositionsgröße (damit mindestens 2–3 Stücke gehen und das Risiko sauber abbildbar ist) |
| Volatilitätsfilter | ATR(20) / Kurs ≤ 6 % — Titel darüber sind für Wochenkadenz zu nervös |
| Ausschlüsse | Kern-Aktien (Regel 3.5); Titel ohne 12 Monate Kurshistorie; Titel, die bei Trade Republic nicht handelbar sind |

---

## 5. Satellit — Signal-Regeln (wöchentliche Trendfolge auf relative Stärke)

Alle Berechnungen auf **Tagesschlusskursen bis einschließlich Freitag**; Wochenwerte = Freitagsschluss. Rechnung pro Region (USA / Europa) getrennt.

### 5.1 Vorfilter — Trend intakt
- Schlusskurs > SMA(200 Tage)
- SMA(50 Tage) > SMA(200 Tage)

### 5.2 Ranking — relative Stärke
- RS-Score = Mittelwert aus 6-Monats-Rendite (ohne letzten Monat) und 12-Monats-Rendite (ohne letzten Monat), also `(R_126−21 + R_252−21) / 2` in Handelstagen.
- Rang innerhalb der Region. **Nur das oberste Zehntel** (Top 10 %) kommt weiter.

### 5.3 Trigger — Ausbruch
- Freitagsschluss ≥ höchster Wochenschluss der **vorangegangenen 20 Wochen** (aktuelle Woche nicht mitgezählt).
- Freitagsschluss ≤ 105 % dieses Hochs (kein Nachjagen: ist der Kurs schon > 5 % über dem Ausbruchsniveau, ist der Zug abgefahren).

### 5.4 Kandidatenliste
- Alle Titel, die 5.1–5.3 und die Filter aus Abschnitt 4 erfüllen, sortiert nach RS-Score.
- **Max. 2 neue Einstiege pro Woche** (bei Ampel Gelb: max. 1). Es werden die höchstplatzierten genommen, die nicht gegen Sektor- und Positionslimits verstoßen.
- Sichtkontrolle am Sonntag: Chart öffnen, prüfen, ob der Ausbruch aus einer erkennbaren Base kommt (mind. 4 Wochen Seitwärtsphase) und nicht aus einem V-förmigen Spike. Bei Zweifel: kein Trade. Sichtkontrolle darf einen Kandidaten **streichen**, nie einen hinzufügen.

### 5.5 Bekannte Lücke — Earnings
Es gibt keine kostenlose, zuverlässige Quelle für Earnings-Termine im Universum. Regel: **Sofern der Termin bekannt ist** (Trade-Republic-App, Unternehmensseite): kein neuer Einstieg, wenn Earnings in den nächsten 5 Handelstagen liegen. Bestehende Positionen werden durch Earnings gehalten — der Stop regelt das Risiko.

---

## 6. Satellit — Risiko und Positionsgröße

Alle Prozentwerte beziehen sich auf das **aktuelle Satelliten-Kapital** (Cash + Positionen zu Freitagskursen).

| Regel | Wert | Anmerkung |
|---|---|---|
| Risiko pro Trade | **1,0 %** | Startphase (erste 20 Trades): **0,5 %** |
| Positionsgröße | Stücke = ⌊ Risiko € ÷ (Einstieg − Initialstop) ⌋ | Berechnung mit `position-sizer` (Fixed Fractional), Report wird an die These angehängt |
| Max. Positionsgröße | **25 %** des Satelliten | Positionsgröße wird gedeckelt, nicht das Risiko erhöht |
| Max. offene Positionen | **5** | |
| Max. je Sektor (GICS) | **2** Positionen | Sektor laut iShares-Holdings |
| Max. offenes Gesamtrisiko | **5 %** (Summe der Abstände zum aktuellen Stop) | Bei gestiegenen Stops sinkt das offene Risiko — dann sind weitere Einstiege möglich |
| Ampel Gelb | halbe Positionsgröße (0,5 % Risiko), max. 1 Einstieg/Woche | |
| Ampel Rot | keine neuen Einstiege | bestehende Positionen laufen mit Stop weiter |

**Initialstop:** Einstiegskurs − 3 × ATR(20 Tage). Wird vor der Order berechnet, im Journal notiert und **am Montag als Stop-Market-Order (Gültigkeit 360 Tage) bei Trade Republic eingestellt.**

---

## 7. Satellit — Exits

Es gibt genau drei Wege aus einem Trade. Kursziele, Teilverkäufe und Nachkäufe existieren nicht (Version 1.0).

| Exit | Regel | Ausführung |
|---|---|---|
| **Harter Stop** (Broker) | Stop-Market bei Trade Republic auf dem aktuellen Stop-Niveau | Automatisch, intraday |
| **Trailing** (wöchentlich) | Neuer Stop = max(bisheriger Stop, Freitagsschluss − 3 × ATR(20)). Stops werden **nur angehoben, nie gesenkt** | Montag: Stop-Order bei Trade Republic anpassen |
| **Weicher Exit** (Trend gebrochen) | Freitagsschluss < SMA(10 Wochen) → Position wird geschlossen | Montag: Verkauf als Bestpreis-Market-Order in der Xetra-Kernzeit (EU 09:05–17:30) bzw. nach US-Eröffnung (ab 15:35) |

Nach dem Exit: Journal schließen (`close` mit Exit-Grund `stop_hit` / `trend_break`), Postmortem im nächsten Monatsreview.

---

## 8. Regime-Ampel

### 8.1 USA (steuert Einstiege in US-Titel)
- **Primärsignal:** `uptrend-analyzer` Composite-Score (0–100).
- **Veto:** `market-breadth-analyzer` Composite-Score.

| Ampel | Bedingung |
|---|---|
| **Grün** | Uptrend ≥ 60 |
| **Gelb** | Uptrend 40–59 — *oder* Uptrend ≥ 60 bei Breadth-Veto < 40 (eine Stufe herabgestuft) |
| **Rot** | Uptrend < 40 |

**Hysterese:** Herabstufung gilt sofort. **Heraufstufung erst, wenn die Bedingung zwei Wochen in Folge erfüllt ist.** (Vorsichtig raus, vorsichtig rein.)

### 8.2 Europa (steuert Einstiege in EU-Titel)
Eigener Breadth-Proxy, jede Woche aus den STOXX-600-Kursen des Screeners berechnet:
- `P200` = Anteil der STOXX-600-Titel über SMA(200)
- `P50` = Anteil über SMA(50)
- `IDX` = Index-Proxy (STOXX Europe 600 bzw. dessen ETF) über/unter SMA(200)

| Ampel | Bedingung (Startkalibrierung) |
|---|---|
| **Grün** | P200 ≥ 55 % **und** IDX über SMA(200) |
| **Rot** | P200 < 40 % **oder** (IDX unter SMA(200) **und** P50 < 40 %) |
| **Gelb** | alles andere |

Gleiche Hysterese wie USA. Die Schwellen sind eine Startkalibrierung; die Pipeline protokolliert P200/P50/IDX jede Woche, nach 6 Monaten werden sie im Review gegen die US-Werte geprüft (Abschnitt 12).

### 8.3 Was die Ampel *nicht* tut
Sie verkauft nichts. Bestehende Positionen werden ausschließlich über Abschnitt 7 beendet.

---

## 9. Wochenablauf (Zeitbudget ~1 Stunde)

| Wann | Was | Werkzeug |
|---|---|---|
| **Samstag 08:00** (automatisch) | Pipeline: Konstituenten prüfen → Kurse aktualisieren → Ampel USA/EU → Screener → Stop-Nachzüge für offene Positionen → Bericht → Push aufs Handy | Docker-Container auf dem vServer, Pushover |
| **Sonntag** (45 min) | 1. Bericht lesen: Ampel, Kandidaten, Stop-Nachzüge, weiche Exits.<br>2. Kandidaten-Sichtkontrolle (Abschnitt 5.4).<br>3. Für jeden Einstieg: These im Journal anlegen (`satellit journal new`), Positionsgröße rechnen, Report anhängen.<br>4. Orderzettel für Montag notieren (Ticker, Stücke, Limit, Stop). | Bericht, Trade-Republic-App (Chart), `satellit`-CLI |
| **Montag** (15 min) | **09:05–09:30** EU-Orders, **15:35–16:00** US-Orders:<br>· Einstiege als **Limit-Order, Limit = letzter Kurs + max. 1 %, tagesgültig.** Nicht ausgeführt = kein Trade, kein Nachfassen.<br>· Weiche Exits als Market-Order.<br>· Stop-Market-Orders neu einstellen bzw. anheben (360 Tage).<br>· Journal: `open-position` für gefüllte Orders, `close` für Exits. | Trade-Republic-App, `satellit`-CLI |
| **Samstag** (automatisch) | Wochen-Digest der geschlossenen Trades wird an den Bericht angehängt | `weekly-performance-digest` |
| **Erster Sonntag im Monat** (+30 min) | Monatsreview: Postmortems der im Vormonat geschlossenen Trades, Monatsbericht, Kill-Switch-Prüfung, Änderungsprotokoll | `trader-memory-core review postmortem / monthly-report` |
| **Erste Januarwoche** | Jahresreview: Rebalancing Kern/Satellit, Kern-Aktien-Reviews, Kalibrierung EU-Ampel, Regelrevision | |

Fällt der Sonntags-Slot aus, werden **keine neuen Einstiege** gemacht. Stop-Nachzüge und weiche Exits werden am nächstmöglichen Tag nachgeholt — die haben Vorrang vor allem anderen.

---

## 10. Start- und Abbruchregeln

### 10.1 Start
1. **Trockenlauf:** Die Pipeline läuft mindestens **2 Wochenenden** nur mit Bericht, ohne Orders. Ziel: Datenfehler, falsche Ticker-Zuordnungen, Ampel-Plausibilität prüfen.
2. **Halbes Risiko:** Die ersten **20 abgeschlossenen Trades** mit 0,5 % Risiko pro Trade. Danach 1,0 % — sofern der Kill-Switch nicht ausgelöst ist.
3. Kern-Sparplan startet sofort, unabhängig vom Satelliten.

### 10.2 Kill-Switch (mechanisch, kein Ermessen)
Der Satellit stoppt **neue Einstiege** sofort, wenn eine der Bedingungen eintritt:
- **Drawdown ≥ 25 %** vom bisherigen Höchststand des Satelliten-Kapitals (wöchentlich zu Freitagskursen gemessen, inkl. offener Positionen). *Einlagenbereinigt:* Bei Ein- und Auszahlungen wandert der Höchststand um denselben Betrag mit — gemessen wird die Kursentwicklung, nicht der Kapitalzufluss. Ohne diese Bereinigung machte eine Einzahlung einen laufenden Verlust unsichtbar (`docs/CHANGELOG_REGELN.md`, Eintrag 2026-09-05).
- **Expectancy ≤ 0** nach **30 abgeschlossenen Trades** (Expectancy = Ø Gewinn × Trefferquote − Ø Verlust × (1 − Trefferquote), in R).

Danach: bestehende Positionen laufen nach Abschnitt 7 aus. Vor einem Neustart: schriftliche Analyse aller Trades, Ursachenhypothese, Regeländerung nach Abschnitt 12, dann Neustart mit 0,5 % Risiko und neuem 20-Trade-Zähler. Der Satellit wird währenddessen **nicht** aus dem Kern aufgefüllt.

---

## 11. Journal und Review

- **Vor jeder Order** existiert eine These im Journal (`trader-memory-core`): Ticker, Setup (`pivot_breakout`), RS-Rang, Ausbruchsniveau, Initialstop, Positionsgröße, Ampelstand, Sektor.
- **Bei Ausführung:** tatsächlicher Einstiegskurs, Datum, Stücke.
- **Bei Exit:** Exit-Kurs, Datum, Grund. Kodierung im Journal (das Schema von `trader-memory-core` kennt keinen Trend-Exit): harter Stop = `stop_hit`, weicher Exit (Trendbruch) = `time_stop`, Regelbruch = `manual`. `manual` wird im Monatsreview als Regelbruch gezählt.
- **Technische Konvention:** Ticker im Journal sind alphanumerisch (`SAP.DE` → `SAPDE`); das Handelssymbol, ISIN, Region, Währung, Ausbruchsniveau und Ampelstand stehen in `origin.raw_provenance`.
- **Wöchentlich:** Digest (Trefferquote, Expectancy, Profit-Faktor, R-Multiple).
- **Monatlich:** Postmortem je geschlossenem Trade (ohne MAE/MFE — keine bezahlte Datenquelle), Monatsbericht.
- **Regelbrüche** werden im Journal als solche protokolliert. Drei Regelbrüche in einem Monat = Satellit pausiert bis zum Monatsreview.

---

## 12. Regeländerungen

- Regeln werden **nur im Monats- oder Jahresreview** geändert, nie unter der Woche, nie mit offener Order.
- Jede Änderung wird in `docs/CHANGELOG_REGELN.md` eingetragen: Datum, alte Regel, neue Regel, Begründung, Datenbasis.
- Änderungen gelten **ab dem nächsten Montag** und nie rückwirkend für offene Trades.
- Änderungen an Signal-Logik (Abschnitt 5) oder Exits (Abschnitt 7) frühestens nach **30 abgeschlossenen Trades** — vorher ist jede Statistik Rauschen.
- Mehr als 3 Regeländerungen in 6 Monaten sind ein Warnsignal: dann wird nicht das Regelwerk, sondern die eigene Disziplin geprüft.
- Die Parameterdatei `config/settings.yaml` und dieses Dokument werden **gemeinsam** geändert. Weichen sie voneinander ab, gilt dieses Dokument.

---

## 13. Steuern und Broker-Praxis (Deutschland)

- Trade Republic führt Kapitalertragsteuer automatisch ab. **Freistellungsauftrag (1.000 €) in der App einrichten.**
- Zwei Verlustverrechnungstöpfe: *Aktien* (nur mit Aktiengewinnen verrechenbar) und *Sonstige* (ETFs, Dividenden). Satelliten-Verluste landen im Aktientopf — ein Grund mehr, warum der Satellit nur Aktien handelt.
- Aktienfonds-ETFs: 30 % Teilfreistellung; Vorabpauschale wird im Januar vom Verrechnungskonto eingezogen.
- **Nicht verifiziert** (bei erstem Trade prüfen): Handhabung der UK-Stempelsteuer (0,5 %) und der Finanztransaktionssteuern FR/IT/ES bei Bestpreis-Orders. Bis zur Klärung: Für UK-, FR-, IT-, ES-Titel die Kostenanzeige vor Orderaufgabe lesen; liegen Fremdkosten > 0,5 % des Ordervolumens, Titel überspringen.
- Direktpreis-Orders (2 €) nur, wenn die Bestpreis-Ausführung für einen Titel erkennbar schlechte Kurse liefert (Spread > 0,5 %).

---

## 14. Bekannte Annahmen und Lücken (Version 1.0)

| Thema | Status | Umgang |
|---|---|---|
| Kursdaten | yfinance (inoffiziell, Rate-Limits auf Cloud-IPs möglich), Stooq als Fallback (benötigt seit 04/2026 kostenlosen API-Key) | Lokaler Cache, inkrementelle Updates, Fehler im Bericht sichtbar. Bei wiederholtem Ausfall: bezahlte Quelle (Abschnitt 12) |
| Earnings-Termine | keine freie Quelle | Regel 5.5 |
| EU-Ampel-Schwellen | Startkalibrierung ohne Backtest | Wöchentlich protokolliert, Kalibrierung nach 6 Monaten |
| Sektorzuordnung | GICS-Sektor laut iShares-Holdings | Fehlende Sektoren → "Unknown", zählt als eigener Sektor |
| Trade-Republic-Handelbarkeit | Nicht jeder STOXX-600-Titel ist bei TR handelbar | Nicht handelbare Titel werden in `config/exclusions.yaml` gepflegt und ausgeblendet |
| Währung | US-Titel in USD, Positionsgröße in EUR-Gegenwert (Wochenendkurs EUR/USD) | Wechselkursrisiko ist Teil des Trades, nicht gehedgt |
| Backtest | Es gibt keinen Backtest des Regelwerks | Das Journal *ist* der Test. 30 Trades vor jeder Bewertung |

---

## Anhang A — Parametertabelle (Spiegel von `config/settings.yaml`)

| Parameter | Wert |
|---|---|
| Kern / Satellit | 0,90 / 0,10 |
| Rebalancing-Bänder Satellit | 0,07 – 0,15 |
| Kern-Einzelaktien | ≤ 20 % des Kerns, ≤ 5 % Gesamt je Titel |
| Kern-Kauftermine | 1. Handelswoche Jan / Apr / Jul / Okt |
| Universum | S&P 500 + STOXX Europe 600 |
| Liquidität | Ø Tagesumsatz 20 T ≥ 5.000.000 |
| Preisfilter | Stückpreis ≤ 40 % der Zielposition |
| Volatilitätsfilter | ATR(20)/Kurs ≤ 6 % |
| Trendfilter | Close > SMA200, SMA50 > SMA200 |
| RS-Score | Mittel aus R(126−21) und R(252−21), Top 10 % je Region |
| Ausbruch | Freitagsschluss ≥ Hoch der Wochenschlüsse (20 W, exkl. aktuelle); ≤ 105 % davon |
| Neue Einstiege / Woche | 2 (Gelb: 1, Rot: 0) |
| Risiko / Trade | 1,0 % (Start: 0,5 % für 20 Trades; Gelb: halb) |
| Initialstop | Einstieg − 3 × ATR(20) |
| Trailing | max(alter Stop, Close − 3 × ATR(20)), wöchentlich |
| Weicher Exit | Freitagsschluss < SMA(10 Wochen) |
| Max. Position / Anzahl / Sektor | 25 % / 5 / 2 |
| Max. offenes Gesamtrisiko | 5 % |
| Ampel USA | Grün ≥ 60, Gelb 40–59, Rot < 40; Veto Breadth < 40 → eine Stufe runter |
| Ampel EU | Grün: P200 ≥ 55 % ∧ IDX > SMA200 · Rot: P200 < 40 % ∨ (IDX < SMA200 ∧ P50 < 40 %) |
| Hysterese | Herabstufung sofort, Heraufstufung nach 2 Wochen |
| Kill-Switch | DD ≥ 25 % oder Expectancy ≤ 0 nach 30 Trades |
| Trockenlauf | ≥ 2 Wochenenden |
| Order-Limit Einstieg | letzter Kurs + 1 %, tagesgültig |
| Stop-Order | Stop-Market, 360 Tage |

## Anhang B — Glossar

- **ATR(20):** Average True Range über 20 Tage — durchschnittliche Tagesschwankung in Kurseinheiten.
- **SMA(n):** einfacher gleitender Durchschnitt über n Tage/Wochen.
- **R / R-Multiple:** Gewinn oder Verlust eines Trades geteilt durch das anfängliche Risiko (Einstieg − Initialstop) × Stücke. Ein Trade mit +2R hat das Doppelte des Risikos verdient.
- **Expectancy:** Erwartungswert je Trade in R.
- **Drawdown:** Rückgang vom bisherigen Höchststand des Satelliten-Kapitals.
- **Breadth:** Marktbreite — wie viele Aktien den Trend tragen, nicht nur der Index.
- **Base:** Seitwärtsphase vor einem Ausbruch.

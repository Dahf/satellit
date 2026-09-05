# Wochen-Checkliste (ausdrucken oder aufs Handy)

## Samstag — automatisch
- [ ] Push-Nachricht angekommen? Wenn nicht: `docker compose logs --tail=100 satellit` prüfen.

## Sonntag — 45 Minuten
1. [ ] Dashboard öffnen (Übersicht) — oder Bericht `state/reports/weekly_<Datum>.md`
2. [ ] **Abschnitt 3 zuerst:** Verkäufe (🔻) und Stop-Nachzüge (⬆️) auf den Montags-Orderzettel.
3. [ ] Abschnitt 1: Ampel gelesen. Rot = keine neuen Einstiege, Punkt 4–6 überspringen.
4. [ ] Abschnitt 4: Jeden Kandidaten im Chart ansehen (Trade-Republic-App oder TradingView):
   - Base ≥ 4 Wochen erkennbar? Kein V-Spike?
   - Earnings in den nächsten 5 Handelstagen (falls bekannt)? → streichen
   - UK/FR/IT/ES-Titel: Fremdkosten in der Kostenanzeige prüfen (> 0,5 % → streichen)
5. [ ] Für jeden verbleibenden Einstieg: Dashboard → Aktionen → „These anlegen" (oder `python -m satellit journal new --symbol <SYMBOL>`) → These + Positionsgröße
6. [ ] Orderzettel für Montag: Symbol · Stücke · Limit (Kurs + max. 1 %) · Initialstop
7. [ ] Kontostand aktualisieren: Dashboard → Aktionen → Konto (oder `python -m satellit account set --equity <EUR>`)

## Montag — 15 Minuten
**EU 09:05–09:30 · US 15:35–16:00**
- [ ] Verkäufe (weicher Exit) als Market-Order → Dashboard „Schließen" (Grund Trendbruch) bzw. `journal close … --reason trend`
- [ ] Ausgelöste Stops prüfen (Depot/Orderhistorie) → „Schließen" (Grund Stop) bzw. `journal close … --reason stop`
- [ ] Stop-Orders anheben (Stop-Market, 360 Tage) → „Stop nachziehen" bzw. `journal stop <id> --stop …`
- [ ] Einstiege als Limit-Order (tagesgültig). Nicht ausgeführt = kein Trade, kein Nachfassen.
- [ ] Ausgeführte Einstiege: „Ausführung eintragen" bzw. `journal open <id> --price … --shares …` + Stop-Market-Order auf den Initialstop

## Erster Sonntag im Monat — +30 Minuten
- [ ] `python -m satellit journal review-due`
- [ ] Für jeden im Vormonat geschlossenen Trade: `python -m satellit journal postmortem <id>`
- [ ] `python -m satellit journal monthly --month YYYY-MM`
- [ ] `python -m satellit account show` — Kill-Switch-Status, Expectancy, Trefferquote
- [ ] Regelbrüche gezählt? ≥ 3 → Satellit pausiert bis zum nächsten Monatsreview
- [ ] Regeländerungen? Nur hier, nur mit Eintrag in `docs/CHANGELOG_REGELN.md`

## Erste Januarwoche
- [ ] Rebalancing Kern/Satellit (Bänder 7–15 %)
- [ ] Kern-Aktien-Reviews (Thesen mit Kill-Kriterien abgleichen)
- [ ] EU-Ampel-Schwellen gegen `state/regime/ampel_history.csv` prüfen
- [ ] Jahresreview des Regelwerks

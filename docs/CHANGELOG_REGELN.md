# Änderungsprotokoll Regelwerk

Regeländerungen nur nach Trading-Plan Abschnitt 12: im Monats-/Jahresreview, schriftlich, mit Datenbasis,
gültig ab dem nächsten Montag, nie rückwirkend. `config/settings.yaml` und `docs/TRADING_PLAN.md` gemeinsam ändern.

| Datum | Abschnitt | Alte Regel | Neue Regel | Begründung / Datenbasis | Gültig ab |
|---|---|---|---|---|---|
| 2026-09-05 | – | – | Version 1.0 des Regelwerks | Planungsinterview | 2026-09-07 |
| 2026-09-05 | 3.4 | „Kauf nur an festen Terminen: erste Handelswoche im Januar, April, Juli, Oktober." — ohne Ausnahme | Die vier Termine regeln die **laufenden** Käufe aus dem angesparten Cash. Der **einmalige** Kern-Startbetrag nach KERN.md 5.3 ist ausgenommen und darf beim Depotaufbau in einem Zug investiert werden. Ab dem zweiten Kauf gelten ausschließlich die vier Termine. | Auflösung eines Widerspruchs im eigenen Regelwerk: 3.4 formuliert unbedingt, KERN.md 5.3 erlaubt den Startbetrag ausdrücklich als Einmalkauf, ohne den Aktienanteil auszunehmen. Die Begründung der Termine (KERN.md 5.2, „sonst entsteht Timing durch die Hintertür") bezieht sich auf die **Sparrate**, nicht auf die Einrichtung. Ein einmaliger Ersteinstieg ist keine Timing-Entscheidung. Die Grenzen aus 3.2 (schriftliche These mit Kill-Kriterien) und 3.3 (5 % je Titel, 20 % des Kerns) gelten unverändert und werden vom Dashboard erzwungen. | 2026-09-07 |
| 2026-09-05 | 10.2 | Drawdown = 1 − Kapital / bisheriger Höchststand, wobei der Höchststand bei jedem höheren eingetragenen Kapitalstand nachgezogen wurde | Der Höchststand wird bei Ein- und Auszahlungen um denselben Betrag verschoben. Gemessen wird damit nur die Kursentwicklung, nicht der Kapitalzufluss. | Fehlerkorrektur, keine Lockerung. Vorher machte eine Einzahlung einen laufenden Verlust unsichtbar: 10.000 → 8.000 (20 % Drawdown) → 2.000 € eingezahlt → Drawdown 0 %. Der Kill-Switch hätte danach an einer Marke gemessen, die nie durch Gewinne erreicht wurde. Als Regressionstest festgehalten in `tests/test_portfolio.py`. | 2026-09-07 |

> **Offen bis zum ersten Monatsreview.** Abschnitt 12 verlangt, Regeländerungen im Monats- oder
> Jahresreview zu beschließen. Beide Einträge oben entstanden während der Einrichtung, also außerhalb
> dieses Verfahrens. Sie sind im ersten Monatsreview ausdrücklich zu bestätigen oder zurückzunehmen.

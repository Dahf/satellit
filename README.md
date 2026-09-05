# satellit — Core-Satellite Trading-Pipeline

Wöchentliche Trendfolge-Pipeline für den Satelliten-Anteil eines Core-Satellite-Portfolios (Trade Republic,
S&P 500 + STOXX Europe 600, Long-only). Läuft als Docker-Container auf einem vServer, meldet sich samstags per
Pushover, führt selbst **keine** Orders aus.

- Regelwerk: [`docs/TRADING_PLAN.md`](docs/TRADING_PLAN.md) — die einzige Quelle für alle Regeln
- Wochenablauf: [`docs/WOCHEN_CHECKLISTE.md`](docs/WOCHEN_CHECKLISTE.md)
- Kern (ETF-Kriterien, Sparplan, Kern-Aktien): [`docs/KERN.md`](docs/KERN.md)
- Regeländerungen: [`docs/CHANGELOG_REGELN.md`](docs/CHANGELOG_REGELN.md)

## Was der Wochenlauf tut (`satellit weekly`)

```
iShares-Holdings (S&P 500, STOXX 600)  ──►  Universum + ISIN + Sektor + Börse
        │
        ▼
Kurse (yfinance, Fallback Stooq)  ──►  lokaler CSV-Cache (state/prices/), inkrementell
        │
        ├──►  Ampel USA:  uptrend-analyzer (primär) + market-breadth-analyzer (Veto)   [TraderMonty-Skills]
        ├──►  Ampel EU:   eigener Breadth-Proxy aus den STOXX-600-Kursen (P200, P50, Index > SMA200)
        │                 → dreistufig, Hysterese (runter sofort, hoch nach 2 Wochen)
        ├──►  Screener:   Close > SMA200, SMA50 > SMA200 · Top-10 % relative Stärke je Region ·
        │                 Ausbruch auf 20-Wochen-Hoch (≤ 5 % drüber) · Liquidität · Volatilität · Stückpreis
        ├──►  Positionen: Trailing-Stop (3×ATR), weicher Exit (Wochenschluss < SMA10W), Stop-Treffer-Hinweis
        ├──►  Auswahl:    Ampel-Limit je Region, max. 5 Positionen, max. 2 je Sektor, offenes Risiko ≤ 5 %,
        │                 Positionsgröße aus Risiko je Trade (0,5 % Start / 1 %)
        └──►  Bericht (Markdown + JSON) + Wochen-Digest der geschlossenen Trades + Pushover
```

Das Journal (`state/theses/`) ist `trader-memory-core` aus [tradermonty/claude-trading-skills](https://github.com/tradermonty/claude-trading-skills)
(MIT, gevendort unter `vendor/`). Position-Sizer, Wochen-Digest und Postmortems kommen aus demselben Repo.

## Setup auf dem vServer

```bash
git clone <dieses Repo> satellit && cd satellit
cp .env.example .env            # Pushover-Keys, DASHBOARD_PASSWORD, SESSION_SALT, SATELLIT_API_TOKEN eintragen
docker compose build
# Depot einrichten: 90/10-Aufteilung, Eröffnungsbuchungen, Trockenlauf über 2 Wochenenden
docker compose run --rm satellit portfolio setup --start 5000 --rate 500 --etf IE00BK5BQT80 --etf-anteil 0.8
docker compose run --rm satellit universe --force --check       # iShares-Download + Ticker-Zuordnung prüfen
docker compose run --rm satellit weekly                         # erster kompletter Lauf (dauert 5–15 min)
docker compose up -d                                            # Scheduler: jeden Samstag 08:00
docker compose logs -f
```

Ohne Docker: `pip install -r requirements.txt` und `python3 -m satellit …` (Python ≥ 3.11).
`scripts/smoke_live.sh` fasst die Erstprüfung zusammen.

## Trade Republic anbinden

Trade Republic hat **keine offizielle Schnittstelle**. Der einzige Weg führt über
[pytr](https://github.com/pytr-org/pytr), einen inoffiziellen Zugang zur privaten App-API.

**pytr läuft auf deinem eigenen Rechner, nicht auf dem Server** — Telefonnummer, PIN und
Geräteschlüssel kommen damit nie auf eine dauerhaft laufende Maschine.

```bash
pip install pytr
python -m pytr login                 # Bestätigungscode in der TR-App
python -m pytr export_transactions   # erzeugt account_transactions.csv
```

Die Datei anschließend im Dashboard unter *Einstellungen → Trade Republic* hochladen, oder:

```bash
docker compose run --rm satellit tr-import /pfad/account_transactions.csv --vorschau
```

Der Import ist zweistufig: erst wird gezeigt, was gebucht würde, dann bestätigst du. Weil pytr
immer die vollständige Historie exportiert, prüft der Importer auf Dubletten — ein wiederholter
Import bucht nichts doppelt. Unbekannte Umsatzarten werden gemeldet, nicht geraten; Splits und
Abspaltungen bleiben Handarbeit, weil nur du entscheiden kannst, wie der Einstand aufzuteilen ist.

Geprüft mit pytr 0.4.10 (deutsche und englische Spaltenüberschriften). Das Format ist nicht
zugesagt und kann sich ändern — deshalb die Pflicht-Vorschau.

## Dashboard (Next.js)

Zweiter Container im selben Compose-Stack (`dashboard/`): Next.js 15 (App Router), Tailwind, shadcn/ui-Komponenten, Recharts.
Liest das `state/`-Volume **read-only** und schreibt ausschließlich über die Python-API (`satellit serve` startet sie auf Port 8787
im Compose-Netz, Token `SATELLIT_API_TOKEN`).

Es gibt **eine** Seite. Sie zeigt keine Kennzahlen-Tabellen, sondern eine Handlungsliste:
was zu tun ist, wie viel, und auf Abruf warum.

| Bereich | Inhalt |
|---|---|
| Kopf | Gesamtwert · Eingezahlt · Gewinn mit Jahresrendite (XIRR) · diesen Monat ausgegeben |
| Aufteilung | Kern / Satellit / nicht zugeteilt als Balken mit dem 7–15-%-Band aus Trading-Plan 1 |
| **Das ist zu tun** | Je Zeile: Verdikt, Titel, Menge, ein Satz Begründung, „Warum?" und ein Knopf. Links steht die Fundstelle im Regelwerk (`TP 7`, `Kern 5.3`) als Marginalie |
| Dein Bestand | Was läuft, ohne Handlungsbedarf |
| Aufklappbar | „Warum wurde sonst nichts gekauft?" (alle Ablehnungsgründe + Screener-Trichter) und „Daten und Technik" |
| Einstellungen | Wochenlauf, Kapital, Trockenlauf, Kill-Switch, Trade-Republic-Import, Konstituenten-Upload |

Ist noch nichts eingerichtet, führt die Seite stattdessen durch die Ersteinrichtung.

Die Ampel ist kein eigener Reiter mehr: sie wird weiter berechnet und protokolliert, erscheint aber
dort, wo sie etwas erklärt — im Begründungs-Panel einer Entscheidung. Das Frontend enthält **keine
Regellogik**; welche Aktion möglich ist und ob sie gesperrt ist, entscheidet `satellit/decisions.py`
und liefert es im Payload `state/view_latest.json` mit.

Login per Passwort (`DASHBOARD_PASSWORD`), Session-Cookie 30 Tage. Der Port ist in `docker-compose.yml` auf `127.0.0.1:3000` gebunden —
davor gehört ein Reverse-Proxy mit HTTPS (Caddy: `satellit.example.de { reverse_proxy 127.0.0.1:3000 }`). `DASHBOARD_URL` in `.env`
landet als Link in der Push-Nachricht.

```bash
openssl rand -hex 32          # -> SATELLIT_API_TOKEN
openssl rand -hex 16          # -> SESSION_SALT
docker compose build dashboard && docker compose up -d
```

**Zum Build:** `next.config.mjs` hat `typescript.ignoreBuildErrors` an, damit ein Typ-Nit den
Container-Build nicht stoppt — `cd dashboard && npm run typecheck` zeigt vor dem Deploy, ob es welche
gibt. Der Build nutzt `npm ci` gegen das eingecheckte `package-lock.json`.

### Was beim ersten Lauf zu prüfen ist

1. **`universe --check`:** Werden für beide Regionen ~500 bzw. ~600 Titel geladen? Stimmen die Symbole in der Stichprobe
   (z. B. `SAP.DE`, `ASML.AS`, `BP.L`, `ROG.SW`, `ERIC-B.ST`)? Falls der iShares-Download scheitert: Produktseite öffnen →
   „Positionen herunterladen" → CSV nach `state/universe/<REGION>_holdings.csv` legen oder die URL in `config/settings.yaml`
   aktualisieren.
2. **Bericht, Abschnitt 7 (Datenqualität):** Symbole ohne Kurse → richtige Yahoo-Schreibweise in
   `config/symbol_overrides.yaml` (ISIN → Symbol) eintragen. Ein paar Dutzend Ausfälle in der ersten Woche sind normal
   (Dual Listings, exotische Ticker); über 10 % sind ein Zeichen für Yahoo-Rate-Limits — dann `data.batch_size` senken
   und `data.batch_pause_seconds` erhöhen.
3. **Ampel:** In den ersten zwei Läufen steht die Ampel wegen der Hysterese auf ROT („Hysterese-Aufbau: Lauf 1/2").
   Das ist gewollt und deckt sich mit dem Trockenlauf. Wer den Trockenlauf beim Einrichten abwählt, wartet trotzdem
   diese zwei Läufe — die Hysterese ist die härtere der beiden Bremsen.
4. **Satellit zu klein?** Unterhalb von rund 1.000 € Satelliten-Kapital lässt sich aus Risiko je Trade und Stopabstand
   keine handelbare Position bilden. Statt wortlos „zu teuer" zu melden, nennt die Ansicht dann die rechnerisch nötige
   Summe. Für kleine Depots greift zusätzlich das Konzentrationsprofil aus Trading-Plan 6.1 (2 Positionen statt 5).
5. **US-Skills:** `satellit regime` muss zwei Scores liefern. Scheitert ein Skill (Netz, CSV-Format), nutzt die Pipeline
   den letzten bekannten Stand und schreibt das in den Bericht.

## Befehle

| Befehl | Zweck |
|---|---|
| `weekly [--as-of DATUM] [--no-push] [--demo]` | Wochenlauf. `--demo` = synthetische Daten ohne Netz |
| `universe [--force] [--check]` | Konstituenten laden, Ticker-Zuordnung prüfen |
| `prices [--symbols A,B]` | Kurs-Cache aktualisieren |
| `regime` | US-Ampel-Skills ausführen und Historie zeigen |
| `kern-scan [--watchlist] [--demo] [--max N]` | Kern-Aktien gegen den Kriterienkatalog (KERN.md 6) prüfen. Läuft **nicht** im Wochenlauf mit: je Titel ein Fundamentaldaten-Abruf, deshalb Minuten. Ergebnis hält 90 Tage |
| `account set --equity X` / `show` / `dry-run --until D` / `reset-kill` | Satelliten-Kapital, Kill-Switch |
| `portfolio setup --start X --rate Y --etf ISIN` | Depot einrichten: 90/10-Aufteilung, Eröffnungsbuchungen, Trockenlauf |
| `portfolio show` | Gesamtwert, Kern/Satellit, Einzahlungen, Gewinn, Monatsausgabe, Kauffenster |
| `ledger add --typ … --topf … --betrag X` / `list [--monat]` / `storno <id>` | Kassenbuch: jede Geldbewegung. Korrektur nur per Gegenbuchung |
| `tr-import <datei> [--vorschau]` | Umsatzliste aus Trade Republic übernehmen (erst Vorschau, dann buchen) |
| `view` | Anzeige-Payload ohne Netz neu bauen |
| `journal new --symbol SYM [--entry --stop --core]` | These anlegen (liest Kurs/Stop/Sektor aus dem letzten Screener-Lauf) + Positionsgröße |
| `journal open <id> --price P --shares N [--date D]` | Ausführung eintragen → ACTIVE |
| `journal stop <id> --stop S` | Trailing-Stop nachziehen (nie senken — wird abgelehnt) |
| `journal close <id> --price P --reason stop\|trend\|manual` | Exit eintragen (manual = Regelbruch) |
| `journal list [--status]`, `review-due`, `summary`, `postmortem <id>`, `monthly --month YYYY-MM` | Reviews |
| `push-test` | Pushover prüfen |
| `serve [--no-api]` | Scheduler-Schleife + Dashboard-API (Standard im Container) |
| `api [--port 8787]` | nur die Dashboard-API |

## Konfiguration

- `config/settings.yaml` — alle Parameter des Regelwerks (Spiegel von Trading-Plan Anhang A). Änderungen nur mit
  Eintrag in `docs/CHANGELOG_REGELN.md`.
- `config/exclusions.yaml` — Kern-Aktien (kein Doppelhalten) und bei TR nicht handelbare Titel.
- `config/symbol_overrides.yaml` — Korrekturen der Ticker-Zuordnung (ISIN → Yahoo-Symbol).
- `.env` — Pushover-Schlüssel, Dashboard-Passwort, Session-Salt, API-Token, optional Stooq-API-Key und `DASHBOARD_URL`.

## Datenquellen und bekannte Grenzen

| Quelle | Rolle | Hinweis |
|---|---|---|
| iShares Holdings-CSV (SXR8 = S&P 500, EXSA = STOXX 600) | Konstituenten, ISIN, Sektor, Börse | monatlich neu geladen; URL-Format kann sich ändern → `local_file`-Fallback |
| yfinance | Kurse (Primärquelle) | inoffiziell; Yahoo drosselt Cloud-IPs gelegentlich. Batches à 80, Pausen, Retries, lokaler Cache. Bei Dauerproblemen: bezahlte Quelle als neuer Adapter in `satellit/data.py` |
| Stooq | Kurse (Fallback) | seit 04/2026 API-Key nötig (`STOOQ_APIKEY`, kostenlos per Captcha auf stooq.com); nur `.us/.de/.uk` verifiziert |
| TraderMonty CSVs (GitHub Pages / raw.githubusercontent) | US-Ampel | über die gevendorten Skills; Ausfall → letzter Stand |
| Yahoo FX (`EURUSD=X` …) | Umrechnung nach EUR | Fallback-Näherungen in `satellit/fx.py` |

**Nicht abgedeckt (bewusst):** Earnings-Termine (keine freie Quelle), Backtest, Orderausführung, MAE/MFE im Postmortem.

**Journal-Konventionen:** Ticker im Journal sind alphanumerisch (`SAP.DE` → `SAPDE`), das echte Symbol steht in
`origin.raw_provenance.symbol`. Exit-Gründe: `stop_hit` = harter Stop, `time_stop` = weicher Exit (Trendbruch),
`manual` = Regelbruch.

## Tests

```bash
python3 -m unittest discover -s tests -v     # 19 Offline-Tests (Parser, Indikatoren, Screener, Ampel, Auswahl, Journal-Mathe)
python3 -m satellit weekly --demo --no-push  # kompletter Lauf mit synthetischen Daten
```

Der Code wurde in einer Umgebung **ohne Zugriff auf Yahoo, iShares und GitHub-Pages** gebaut: Parser, Screener,
Ampel-Logik, Journal und Bericht sind mit synthetischen Daten und Fixtures getestet; der Live-Datenpfad
(yfinance-Download, iShares-URL, TraderMonty-CSVs) ist beim ersten Lauf auf dem vServer zu prüfen (`scripts/smoke_live.sh`).

## Lizenz

Eigener Code: MIT. `vendor/claude-trading-skills`: MIT, Copyright (c) 2026 TraderMonty (siehe `vendor/claude-trading-skills/LICENSE`).
Kein Bestandteil dieses Projekts ist Anlageberatung.

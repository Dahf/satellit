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
docker compose run --rm satellit account set --equity 5000      # Satelliten-Kapital in EUR
docker compose run --rm satellit account dry-run --until 2026-09-25   # Trockenlauf: 2 Wochenenden
docker compose run --rm satellit universe --force --check       # iShares-Download + Ticker-Zuordnung prüfen
docker compose run --rm satellit weekly                         # erster kompletter Lauf (dauert 5–15 min)
docker compose up -d                                            # Scheduler: jeden Samstag 08:00
docker compose logs -f
```

Ohne Docker: `pip install -r requirements.txt` und `python3 -m satellit …` (Python ≥ 3.11).
`scripts/smoke_live.sh` fasst die Erstprüfung zusammen.

## Dashboard (Next.js)

Zweiter Container im selben Compose-Stack (`dashboard/`): Next.js 15 (App Router), Tailwind, shadcn/ui-Komponenten, Recharts.
Liest das `state/`-Volume **read-only** und schreibt ausschließlich über die Python-API (`satellit serve` startet sie auf Port 8787
im Compose-Netz, Token `SATELLIT_API_TOKEN`).

| Seite | Inhalt |
|---|---|
| `/` Übersicht | Letzter Lauf, Ampel USA/EU, Kapital/Drawdown, **Montag erledigen** (Positionen mit Stop-Nachzug/Verkauf), Kandidaten, Watchlist, Statistik, Datenqualität |
| `/screener` | Alle Titel des letzten Laufs mit Kennzahlen und Flags, Filter nach Kandidat/Watchlist/Top-RS/Region, ältere Läufe wählbar |
| `/journal`, `/journal/<id>` | Thesen mit Status, P&L, R-Multiple, Stop-Verlauf, Statusverlauf; Kennzahlen (Trefferquote, Expectancy, Profit-Faktor) |
| `/ampel` | Verlauf der Ampel-Scores (US: Uptrend/Breadth, EU: P200/P50) mit Schwellen, Roh vs. Effektiv |
| `/aktionen` | These anlegen (mit Positionsgröße), Ausführung eintragen, Stop nachziehen, Schließen, Kapital/Trockenlauf/Kill-Switch, Wochenlauf starten |

Login per Passwort (`DASHBOARD_PASSWORD`), Session-Cookie 30 Tage. Der Port ist in `docker-compose.yml` auf `127.0.0.1:3000` gebunden —
davor gehört ein Reverse-Proxy mit HTTPS (Caddy: `satellit.example.de { reverse_proxy 127.0.0.1:3000 }`). `DASHBOARD_URL` in `.env`
landet als Link in der Push-Nachricht.

```bash
openssl rand -hex 32          # -> SATELLIT_API_TOKEN
openssl rand -hex 16          # -> SESSION_SALT
docker compose build dashboard && docker compose up -d
```

**Hinweis zum Build:** Das Dashboard wurde ohne npm-Zugang geschrieben; Syntax ist geprüft, der erste `npm run build` läuft auf
deinem Server. `next.config.mjs` hat `typescript.ignoreBuildErrors` an, damit ein Typ-Nit den Container-Build nicht stoppt —
`cd dashboard && npm install && npm run typecheck` zeigt, ob es welche gibt. Es gibt kein `package-lock.json`; der erste Build
erzeugt eines, das du einchecken solltest. Weitere shadcn-Komponenten: `npx shadcn@latest add dialog` (components.json liegt bei).

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
   Das ist gewollt und deckt sich mit dem Trockenlauf.
4. **US-Skills:** `satellit regime` muss zwei Scores liefern. Scheitert ein Skill (Netz, CSV-Format), nutzt die Pipeline
   den letzten bekannten Stand und schreibt das in den Bericht.

## Befehle

| Befehl | Zweck |
|---|---|
| `weekly [--as-of DATUM] [--no-push] [--demo]` | Wochenlauf. `--demo` = synthetische Daten ohne Netz |
| `universe [--force] [--check]` | Konstituenten laden, Ticker-Zuordnung prüfen |
| `prices [--symbols A,B]` | Kurs-Cache aktualisieren |
| `regime` | US-Ampel-Skills ausführen und Historie zeigen |
| `account set --equity X` / `show` / `dry-run --until D` / `reset-kill` | Satelliten-Kapital (wöchentlich aus der TR-App eintragen), Kill-Switch |
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

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
cp .env.example .env            # PUSHOVER_TOKEN, PUSHOVER_USER eintragen (STOOQ_APIKEY optional)
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
| `serve` | Scheduler-Schleife (Standard im Container) |

## Konfiguration

- `config/settings.yaml` — alle Parameter des Regelwerks (Spiegel von Trading-Plan Anhang A). Änderungen nur mit
  Eintrag in `docs/CHANGELOG_REGELN.md`.
- `config/exclusions.yaml` — Kern-Aktien (kein Doppelhalten) und bei TR nicht handelbare Titel.
- `config/symbol_overrides.yaml` — Korrekturen der Ticker-Zuordnung (ISIN → Yahoo-Symbol).
- `.env` — Pushover-Schlüssel, optional Stooq-API-Key.

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

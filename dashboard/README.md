# satellit-dashboard

Next.js-Oberfläche für die Pipeline im Elternverzeichnis. Läuft normalerweise als Container (`docker compose up -d`).

## Lokal entwickeln

```bash
npm install
DATA_DIR=../state SATELLIT_API_URL=http://localhost:8787 SATELLIT_API_TOKEN=dev DASHBOARD_PASSWORD=dev npm run dev
# in zweitem Terminal: SATELLIT_API_TOKEN=dev python3 -m satellit api
```

Ohne `DASHBOARD_PASSWORD` antwortet das Dashboard mit 503 — lieber gesperrt als offen.

## Aufbau

- `lib/data.ts` — liest `state/` (weekly_*.json, screener_*.csv, ampel_history.csv, account.yaml, theses/*.yaml, run_status.json)
- `lib/auth.ts`, `middleware.ts`, `app/api/login` — Passwort-Login, Session-Cookie (SHA-256 aus Passwort + Salt)
- `app/api/action` — leitet Aktionen an die Python-API weiter (Allowlist, Token serverseitig)
- `components/ui/*` — shadcn/ui-Komponenten (card, badge, button, input, label, table) ohne Radix-Abhängigkeit; `components.json` erlaubt `npx shadcn add …`
- Seiten: `/`, `/screener`, `/journal`, `/journal/[id]`, `/ampel`, `/aktionen`, `/login`

#!/usr/bin/env bash
# Erster Live-Check auf dem vServer (mit Netz). Läuft ~5–15 Minuten wegen Kursdownload.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== 1. Konstituenten (iShares)"; python3 -m satellit universe --force --check
echo "== 2. Kursdaten Stichprobe"; python3 -m satellit prices --symbols AAPL,MSFT,SAP.DE,ASML.AS,BP.L,ROG.SW,ERIC-B.ST,NOVO-B.CO,EXSA.DE
echo "== 3. US-Ampel-Skills"; python3 -m satellit regime
echo "== 4. Kompletter Wochenlauf ohne Push"; python3 -m satellit weekly --no-push
echo "== 5. Pushover"; python3 -m satellit push-test || true
echo "Fertig. Bericht: state/reports/"

import Link from "next/link";
import { AmpelBadge } from "@/components/ampel-badge";
import { CandidatesTable } from "@/components/candidates-table";
import { PositionsTable } from "@/components/positions-table";
import { Stat } from "@/components/stat";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { computeStats, drawdown, getAccount, getRunStatus, getScreener, getTheses, getWeekly, type Reading } from "@/lib/data";
import { dateDe, eur, fmt, pct } from "@/lib/utils";

export const dynamic = "force-dynamic";

function ReadingCard({ r }: { r: Reading }) {
  const detail =
    r.region === "US"
      ? `Uptrend ${fmt(r.uptrend, 0)} · Breadth ${fmt(r.breadth, 0)}`
      : `P200 ${pct(r.p200, 0)} · P50 ${pct(r.p50, 0)} · Index ${r.idx_above === null || r.idx_above === undefined ? "?" : r.idx_above ? "über" : "unter"} SMA200`;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>Ampel {r.region === "US" ? "USA" : "Europa"}</CardDescription>
        <CardTitle className="flex items-center gap-2 text-xl">
          <AmpelBadge state={r.effective} className="text-sm" />
          {r.raw !== r.effective ? <span className="text-xs font-normal text-muted-foreground">roh: <AmpelBadge state={r.raw} /></span> : null}
        </CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        <div>{detail}</div>
        {r.note ? <div className="mt-1 text-xs">{r.note}</div> : null}
      </CardContent>
    </Card>
  );
}

export default function OverviewPage() {
  const weekly = getWeekly();
  const account = getAccount();
  const status = getRunStatus();
  const theses = getTheses();
  const stats = computeStats(theses);
  const dd = drawdown(account);
  const screener = getScreener(weekly?.as_of);
  const watchlist = screener.rows.filter((r) => r.watchlist).slice(0, 10);
  const failedCount = weekly ? Object.keys(weekly.data_failed || {}).length : 0;

  return (
    <div className="space-y-6">
      {/* Statuszeile */}
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">Letzter Lauf:</span>
        {status.running ? (
          <Badge variant="yellow">läuft seit {status.started}</Badge>
        ) : status.ok === false ? (
          <Badge variant="red">Fehler: {status.error}</Badge>
        ) : status.finished ? (
          <Badge variant="secondary">{status.finished} · Stichtag {dateDe(status.as_of)}{status.demo ? " · DEMO" : ""}</Badge>
        ) : (
          <Badge variant="gray">noch kein Lauf</Badge>
        )}
        {account.kill_switch_active ? <Badge variant="red">⛔ KILL-SWITCH AKTIV — {account.kill_switch_reason}</Badge> : null}
        {weekly?.dry_run ? <Badge variant="yellow">🧪 Trockenlauf bis {dateDe(account.dry_run_until)} — keine Orders</Badge> : null}
        {weekly ? (
          <Link href={`/screener?asOf=${weekly.as_of}`} className="ml-auto text-xs underline">
            Screener vom {dateDe(weekly.as_of)}
          </Link>
        ) : null}
      </div>

      {!weekly ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            Noch kein Wochenbericht vorhanden. Erster Lauf: <code>docker compose run --rm satellit weekly</code> oder unter <Link href="/aktionen" className="underline">Aktionen</Link> starten.
          </CardContent>
        </Card>
      ) : null}

      {/* Ampel + Konto */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {weekly ? Object.values(weekly.readings).map((r) => <ReadingCard key={r.region} r={r} />) : null}
        <Stat
          label="Satellit-Kapital"
          value={eur(account.satellite_equity_eur)}
          hint={account.updated ? `Stand ${dateDe(account.updated)} · Hoch ${eur(account.high_water_mark)}` : "noch nicht hinterlegt"}
        />
        <Stat
          label="Drawdown"
          value={pct(dd)}
          hint={`Kill-Switch bei 25 % · offene Positionen ${weekly?.positions.length ?? 0}/5`}
          tone={dd !== null && dd >= 0.15 ? "bad" : "neutral"}
        />
      </div>

      {/* Montag erledigen */}
      <Card>
        <CardHeader>
          <CardTitle>Montag erledigen</CardTitle>
          <CardDescription>Offene Positionen — Verkäufe und Stop-Nachzüge haben Vorrang vor neuen Einstiegen.</CardDescription>
        </CardHeader>
        <CardContent>
          <PositionsTable positions={weekly?.positions ?? []} />
        </CardContent>
      </Card>

      {/* Kandidaten */}
      <Card>
        <CardHeader>
          <CardTitle>Neue Einstiege — Vorschlag</CardTitle>
          <CardDescription>
            Sichtkontrolle am Sonntag (Base ≥ 4 Wochen, kein V-Spike, keine Earnings in 5 Tagen), dann These anlegen. Orders Montag als Limit-Order, tagesgültig.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <CandidatesTable proposals={weekly?.proposals ?? []} />
        </CardContent>
      </Card>

      {/* Watchlist + Statistik */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Watchlist</CardTitle>
            <CardDescription>Top-RS, Trend intakt, bis 3 % unter dem Ausbruchsniveau.</CardDescription>
          </CardHeader>
          <CardContent>
            {watchlist.length === 0 ? (
              <p className="text-sm text-muted-foreground">Leer.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Region</TableHead>
                    <TableHead className="text-right">Kurs</TableHead>
                    <TableHead className="text-right">Ausbruch bei</TableHead>
                    <TableHead className="text-right">Abstand</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {watchlist.map((r) => (
                    <TableRow key={r.symbol}>
                      <TableCell className="font-medium">{r.symbol}<div className="max-w-[14rem] truncate text-xs text-muted-foreground">{r.name}</div></TableCell>
                      <TableCell>{r.region}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmt(r.close)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmt(r.breakout_level)}</TableCell>
                      <TableCell className="text-right tabular-nums">{pct(r.extension)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Statistik (geschlossene Trades)</CardTitle>
            <CardDescription>Expectancy in R = Ergebnis geteilt durch anfängliches Risiko. Aussagekräftig ab 30 Trades.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Stat label="Trades" value={String(stats.closed)} hint={`${stats.wins} W / ${stats.losses} L`} />
              <Stat label="Trefferquote" value={pct(stats.winRate, 0)} />
              <Stat label="Expectancy" value={stats.avgR === null ? "–" : `${fmt(stats.avgR)} R`} tone={stats.avgR === null ? "neutral" : stats.avgR > 0 ? "good" : "bad"} />
              <Stat label="Profit-Faktor" value={fmt(stats.profitFactor)} />
            </div>
            <div className="mt-3 text-xs text-muted-foreground">
              Realisiert gesamt: {eur(stats.sumPnl, 2)} · Kill-Switch prüft Expectancy ≤ 0 ab 30 Trades.{" "}
              <Link href="/journal" className="underline">Zum Journal</Link>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Datenqualität */}
      {weekly ? (
        <Card>
          <CardHeader>
            <CardTitle>Datenqualität</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            {(weekly.notes || []).map((n, i) => (
              <div key={i}>⚠️ {n}</div>
            ))}
            {failedCount > 0 ? (
              <details>
                <summary className="cursor-pointer">⚠️ {failedCount} Symbole ohne Kurse — Korrektur in config/symbol_overrides.yaml</summary>
                <ul className="mt-2 grid gap-1 text-xs text-muted-foreground md:grid-cols-2">
                  {Object.entries(weekly.data_failed).map(([s, why]) => (
                    <li key={s}><span className="font-mono">{s}</span> — {why}</li>
                  ))}
                </ul>
              </details>
            ) : (
              <div className="text-muted-foreground">Alle Kursreihen geladen.</div>
            )}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

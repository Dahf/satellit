import Link from "next/link";
import { AmpelBadge } from "@/components/ampel-badge";
import { Stat } from "@/components/stat";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { computeStats, getTheses, isSatellite } from "@/lib/data";
import { dateDe, eur, fmt, pct } from "@/lib/utils";

export const dynamic = "force-dynamic";

const STATUS_VARIANT: Record<string, "green" | "yellow" | "gray" | "secondary" | "red"> = {
  ACTIVE: "green",
  PARTIALLY_CLOSED: "yellow",
  ENTRY_READY: "yellow",
  IDEA: "gray",
  CLOSED: "secondary",
  INVALIDATED: "red",
};

const EXIT_LABEL: Record<string, string> = {
  stop_hit: "Stop",
  time_stop: "Trend-Exit",
  manual: "manuell (Regelbruch)",
  invalidated: "invalidiert",
  target_hit: "Ziel",
};

export default async function JournalPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const status = sp.status ?? "all";
  const all = getTheses();
  const stats = computeStats(all);
  const shown = all.filter((t) => (status === "all" ? true : status === "core" ? !isSatellite(t) : t.status === status));
  const statuses = ["all", "ACTIVE", "ENTRY_READY", "CLOSED", "INVALIDATED", "core"];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Geschlossen" value={String(stats.closed)} hint={`${stats.wins} W / ${stats.losses} L`} />
        <Stat label="Trefferquote" value={pct(stats.winRate, 0)} />
        <Stat label="Expectancy" value={stats.avgR === null ? "–" : `${fmt(stats.avgR)} R`} tone={stats.avgR === null ? "neutral" : stats.avgR > 0 ? "good" : "bad"} />
        <Stat label="Profit-Faktor" value={fmt(stats.profitFactor)} />
        <Stat label="Realisiert" value={eur(stats.sumPnl, 0)} tone={stats.sumPnl >= 0 ? "good" : "bad"} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Thesen</CardTitle>
          <CardDescription>Jeder Trade beginnt hier — vor der Order. Exit-Grund „manuell" zählt als Regelbruch.</CardDescription>
          <div className="flex flex-wrap gap-2 pt-2">
            {statuses.map((s) => (
              <Link key={s} href={`/journal?status=${s}`}>
                <Badge variant={status === s ? "default" : "outline"}>{s === "all" ? "Alle" : s === "core" ? "Kern-Aktien" : s}</Badge>
              </Link>
            ))}
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {shown.length === 0 ? (
            <p className="p-6 text-sm text-muted-foreground">Keine Thesen.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Angelegt</TableHead>
                  <TableHead className="text-right">Einstieg</TableHead>
                  <TableHead className="text-right">Stücke</TableHead>
                  <TableHead className="text-right">Stop</TableHead>
                  <TableHead className="text-right">Exit</TableHead>
                  <TableHead className="text-right">P&amp;L</TableHead>
                  <TableHead className="text-right">R</TableHead>
                  <TableHead>Ampel</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shown.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-medium">
                      <Link href={`/journal/${t.id}`} className="hover:underline">{t.symbol}</Link>
                      <div className="text-xs text-muted-foreground">{t.sector ?? "–"} · {t.setup_type ?? t.thesis_type}</div>
                    </TableCell>
                    <TableCell><Badge variant={STATUS_VARIANT[t.status] ?? "gray"}>{t.status}</Badge></TableCell>
                    <TableCell className="text-xs">{dateDe(t.created_at)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(t.entry_price)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(t.shares, 0)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(t.stop)}</TableCell>
                    <TableCell className="text-right text-xs">
                      {t.exit_price ? `${fmt(t.exit_price)} · ${EXIT_LABEL[t.exit_reason ?? ""] ?? t.exit_reason ?? ""}` : "–"}
                    </TableCell>
                    <TableCell className={"text-right tabular-nums " + ((t.pnl ?? 0) > 0 ? "text-emerald-600" : (t.pnl ?? 0) < 0 ? "text-red-600" : "")}>
                      {t.pnl === null ? "–" : `${eur(t.pnl, 2)} (${pct(t.pnl_pct, 1, false)})`}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{t.r === null ? "–" : fmt(t.r)}</TableCell>
                    <TableCell><AmpelBadge state={t.ampel} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getScreener, listWeeklyDates } from "@/lib/data";
import { cn, dateDe, eur, fmt, pct } from "@/lib/utils";

export const dynamic = "force-dynamic";

const FILTERS: Array<{ key: string; label: string }> = [
  { key: "candidate", label: "Kandidaten" },
  { key: "watchlist", label: "Watchlist" },
  { key: "rs_top", label: "Top-RS" },
  { key: "breakout", label: "Ausbruch" },
  { key: "trend_ok", label: "Trend ok" },
  { key: "all", label: "Alle" },
];

function Flag({ ok }: { ok: boolean }) {
  return <span className={cn("inline-block h-2.5 w-2.5 rounded-full", ok ? "bg-emerald-500" : "bg-zinc-300")} />;
}

export default async function ScreenerPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const filter = sp.filter ?? "candidate";
  const region = sp.region ?? "all";
  const { asOf, rows } = getScreener(sp.asOf);
  const dates = listWeeklyDates();

  let shown = rows;
  if (region !== "all") shown = shown.filter((r) => r.region === region);
  if (filter !== "all") shown = shown.filter((r) => (r as unknown as Record<string, unknown>)[filter] === true);
  shown = [...shown].sort((a, b) => (b.rs_score ?? -9) - (a.rs_score ?? -9)).slice(0, 300);

  const counts = {
    total: rows.length,
    trend: rows.filter((r) => r.trend_ok).length,
    rs: rows.filter((r) => r.rs_top).length,
    breakout: rows.filter((r) => r.breakout).length,
    candidates: rows.filter((r) => r.candidate).length,
  };

  const link = (over: Record<string, string>) => {
    const q = new URLSearchParams({ filter, region, ...(asOf ? { asOf } : {}), ...over });
    return `/screener?${q.toString()}`;
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Screener — Stichtag {dateDe(asOf)}</CardTitle>
          <CardDescription>
            {counts.total} Titel · Trend ok {counts.trend} · Top-RS {counts.rs} · Ausbruch {counts.breakout} · Kandidaten {counts.candidates}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          {FILTERS.map((f) => (
            <Link key={f.key} href={link({ filter: f.key })}>
              <Badge variant={filter === f.key ? "default" : "outline"}>{f.label}</Badge>
            </Link>
          ))}
          <span className="mx-2 text-muted-foreground">|</span>
          {["all", "US", "EU"].map((r) => (
            <Link key={r} href={link({ region: r })}>
              <Badge variant={region === r ? "default" : "outline"}>{r === "all" ? "USA + EU" : r}</Badge>
            </Link>
          ))}
          {dates.length > 1 ? (
            <form className="ml-auto" method="get">
              <input type="hidden" name="filter" value={filter} />
              <input type="hidden" name="region" value={region} />
              <select name="asOf" defaultValue={asOf ?? ""} className="h-8 rounded-md border bg-background px-2 text-sm">
                {dates.map((d) => (
                  <option key={d} value={d}>{dateDe(d)}</option>
                ))}
              </select>
              <button type="submit" className="ml-2 h-8 rounded-md border px-2 text-sm">anzeigen</button>
            </form>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {shown.length === 0 ? (
            <p className="p-6 text-sm text-muted-foreground">Keine Titel für diesen Filter.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Sektor</TableHead>
                  <TableHead className="text-right">Kurs</TableHead>
                  <TableHead className="text-right">RS-Rang</TableHead>
                  <TableHead className="text-right">Ausbruch bei</TableHead>
                  <TableHead className="text-right">Abstand</TableHead>
                  <TableHead className="text-right">ATR %</TableHead>
                  <TableHead className="text-right">Stop</TableHead>
                  <TableHead className="text-right">Umsatz/Tag</TableHead>
                  <TableHead title="Trend · RS · Ausbruch · Liquidität · Volatilität · Preis">Flags</TableHead>
                  <TableHead>Grund</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shown.map((r) => (
                  <TableRow key={r.symbol} className={r.candidate ? "bg-emerald-50" : undefined}>
                    <TableCell className="font-medium">
                      {r.symbol} <span className="text-xs text-muted-foreground">{r.region}</span>
                      <div className="max-w-[14rem] truncate text-xs text-muted-foreground">{r.name}</div>
                    </TableCell>
                    <TableCell className="text-xs">{r.sector}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(r.close)} {r.currency}</TableCell>
                    <TableCell className="text-right tabular-nums">{pct(r.rs_rank_pct, 0)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(r.breakout_level)}</TableCell>
                    <TableCell className="text-right tabular-nums">{pct(r.extension)}</TableCell>
                    <TableCell className="text-right tabular-nums">{pct(r.atr_pct)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(r.initial_stop)}</TableCell>
                    <TableCell className="text-right tabular-nums">{eur(r.avg_turnover_eur)}</TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <Flag ok={r.trend_ok} /><Flag ok={r.rs_top} /><Flag ok={r.breakout} /><Flag ok={r.liquidity_ok} /><Flag ok={r.vol_ok} /><Flag ok={r.price_ok} />
                      </div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{r.reason}</TableCell>
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

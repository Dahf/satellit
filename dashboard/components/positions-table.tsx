import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { PositionView } from "@/lib/data";
import { fmt, pct } from "@/lib/utils";

export function PositionsTable({ positions }: { positions: PositionView[] }) {
  if (positions.length === 0) return <p className="text-sm text-muted-foreground">Keine offenen Positionen.</p>;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Symbol</TableHead>
          <TableHead className="text-right">Stücke</TableHead>
          <TableHead className="text-right">Einstieg</TableHead>
          <TableHead className="text-right">Kurs</TableHead>
          <TableHead className="text-right">P&amp;L</TableHead>
          <TableHead className="text-right">Stop</TableHead>
          <TableHead className="text-right">Stop neu</TableHead>
          <TableHead>Aktion Montag</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {positions.map((p) => {
          const actions: React.ReactNode[] = [];
          if (p.hard_stop_hit) actions.push(<Badge key="hit" variant="red">Stop evtl. ausgelöst — Depot prüfen</Badge>);
          if (p.soft_exit) actions.push(<Badge key="sell" variant="red">VERKAUFEN (Schluss &lt; SMA10W)</Badge>);
          if (p.stop_raised && !p.soft_exit) actions.push(<Badge key="raise" variant="yellow">Stop-Order auf {fmt(p.new_stop)} anheben</Badge>);
          if (actions.length === 0) actions.push(<Badge key="hold" variant="secondary">{p.note || "halten"}</Badge>);
          const pnl = p.pnl_pct ?? null;
          return (
            <TableRow key={p.thesis_id}>
              <TableCell className="font-medium">
                <Link href={`/journal/${p.thesis_id}`} className="hover:underline">{p.symbol}</Link>
                <div className="text-xs text-muted-foreground">{p.sector} · {p.region}</div>
              </TableCell>
              <TableCell className="text-right tabular-nums">{fmt(p.shares, 0)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmt(p.entry)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmt(p.close)}</TableCell>
              <TableCell className={"text-right tabular-nums " + (pnl === null ? "" : pnl >= 0 ? "text-emerald-600" : "text-red-600")}>{pct(pnl)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmt(p.stop)}</TableCell>
              <TableCell className="text-right tabular-nums font-medium">{fmt(p.new_stop)}</TableCell>
              <TableCell><div className="flex flex-wrap gap-1">{actions}</div></TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

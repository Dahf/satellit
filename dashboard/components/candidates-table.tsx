import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Proposal } from "@/lib/data";
import { eur, fmt, pct } from "@/lib/utils";

export function CandidatesTable({ proposals }: { proposals: Proposal[] }) {
  if (proposals.length === 0) return <p className="text-sm text-muted-foreground">Keine Kandidaten, die alle Regeln erfüllen.</p>;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Symbol</TableHead>
          <TableHead>Region</TableHead>
          <TableHead>Sektor</TableHead>
          <TableHead className="text-right">Kurs</TableHead>
          <TableHead className="text-right">Ausbruch</TableHead>
          <TableHead className="text-right">Stop</TableHead>
          <TableHead className="text-right">Stücke</TableHead>
          <TableHead className="text-right">Wert</TableHead>
          <TableHead className="text-right">Risiko</TableHead>
          <TableHead className="text-right">Limit ≤</TableHead>
          <TableHead className="text-right">RS</TableHead>
          <TableHead></TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {proposals.map((p) => (
          <TableRow key={p.symbol}>
            <TableCell className="font-medium">
              {p.symbol}
              <div className="max-w-[16rem] truncate text-xs text-muted-foreground">{p.name}</div>
            </TableCell>
            <TableCell><Badge variant="outline">{p.region} · {p.ampel}</Badge></TableCell>
            <TableCell className="text-xs">{p.sector}</TableCell>
            <TableCell className="text-right tabular-nums">{fmt(p.close)} {p.currency}</TableCell>
            <TableCell className="text-right tabular-nums">{fmt(p.breakout_level)}</TableCell>
            <TableCell className="text-right tabular-nums">{fmt(p.initial_stop)}</TableCell>
            <TableCell className="text-right tabular-nums font-semibold">{p.shares}</TableCell>
            <TableCell className="text-right tabular-nums">{eur(p.value_eur)}</TableCell>
            <TableCell className="text-right tabular-nums">{eur(p.risk_eur)} <span className="text-xs text-muted-foreground">({fmt(p.risk_pct)} %)</span></TableCell>
            <TableCell className="text-right tabular-nums">{fmt(p.limit_price)}</TableCell>
            <TableCell className="text-right tabular-nums">{pct(p.rs_rank_pct, 0)}</TableCell>
            <TableCell>
              <Link href={`/aktionen?action=new&symbol=${encodeURIComponent(p.symbol)}&entry=${p.close}&stop=${p.initial_stop}`} className="text-xs underline">
                These anlegen
              </Link>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

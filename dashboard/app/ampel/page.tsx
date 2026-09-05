import { AmpelBadge } from "@/components/ampel-badge";
import { AmpelChart } from "@/components/ampel-chart";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getAmpelHistory } from "@/lib/data";
import { dateDe, fmt, pct } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default function AmpelPage() {
  const history = getAmpelHistory();
  const us = history.filter((r) => r.region === "US");
  const eu = history.filter((r) => r.region === "EU");
  const usData = us.map((r) => ({ date: r.date, a: r.uptrend ?? null, b: r.breadth ?? null }));
  const euData = eu.map((r) => ({ date: r.date, a: r.p200 === null || r.p200 === undefined ? null : r.p200 * 100, b: r.p50 === null || r.p50 === undefined ? null : r.p50 * 100 }));
  const recent = [...history].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 24);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>USA — Uptrend & Breadth</CardTitle>
            <CardDescription>Grün ≥ 60 · Gelb 40–59 · Rot &lt; 40 · Breadth &lt; 40 = Veto (eine Stufe runter)</CardDescription>
          </CardHeader>
          <CardContent><AmpelChart data={usData} labelA="Uptrend" labelB="Breadth" refLines={[40, 60]} domain={[0, 100]} /></CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Europa — Breadth-Proxy</CardTitle>
            <CardDescription>P200 = Anteil STOXX-600-Titel über SMA200 · Grün ≥ 55 % (mit Index über SMA200) · Rot &lt; 40 %</CardDescription>
          </CardHeader>
          <CardContent><AmpelChart data={euData} labelA="P200 %" labelB="P50 %" refLines={[40, 55]} domain={[0, 100]} /></CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Verlauf</CardTitle>
          <CardDescription>Roh = Messwert der Woche · Effektiv = mit Hysterese (runter sofort, hoch nach 2 Wochen).</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Datum</TableHead>
                <TableHead>Region</TableHead>
                <TableHead>Roh</TableHead>
                <TableHead>Effektiv</TableHead>
                <TableHead className="text-right">Uptrend</TableHead>
                <TableHead className="text-right">Breadth</TableHead>
                <TableHead className="text-right">P200</TableHead>
                <TableHead className="text-right">P50</TableHead>
                <TableHead>Index</TableHead>
                <TableHead>Notiz</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recent.map((r) => (
                <TableRow key={`${r.date}-${r.region}`}>
                  <TableCell>{dateDe(r.date)}</TableCell>
                  <TableCell>{r.region}</TableCell>
                  <TableCell><AmpelBadge state={r.raw} /></TableCell>
                  <TableCell><AmpelBadge state={r.effective} /></TableCell>
                  <TableCell className="text-right tabular-nums">{fmt(r.uptrend, 0)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmt(r.breadth, 0)}</TableCell>
                  <TableCell className="text-right tabular-nums">{pct(r.p200, 0)}</TableCell>
                  <TableCell className="text-right tabular-nums">{pct(r.p50, 0)}</TableCell>
                  <TableCell>{r.idx_above === null || r.idx_above === undefined ? "–" : r.idx_above ? "über SMA200" : "unter SMA200"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{r.note}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

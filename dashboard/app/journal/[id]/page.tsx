import Link from "next/link";
import { notFound } from "next/navigation";
import { AmpelBadge } from "@/components/ampel-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getThesis } from "@/lib/data";
import { dateDe, eur, fmt, pct } from "@/lib/utils";

export const dynamic = "force-dynamic";

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b py-1.5 text-sm last:border-0">
      <span className="text-muted-foreground">{k}</span>
      <span className="text-right font-medium tabular-nums">{v}</span>
    </div>
  );
}

export default async function ThesisPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const t = getThesis(id);
  if (!t) notFound();
  const raw = t.raw ?? {};
  const history: Array<{ status: string; at: string; reason?: string }> = raw.status_history ?? [];
  const canOpen = t.status === "ENTRY_READY";
  const canClose = t.status === "ACTIVE" || t.status === "PARTIALLY_CLOSED";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">{t.symbol}</h1>
        <Badge variant="outline">{t.status}</Badge>
        <AmpelBadge state={t.ampel} />
        <span className="text-xs text-muted-foreground">{t.id}</span>
        <div className="ml-auto flex gap-2 text-sm">
          {canOpen ? <Link className="underline" href={`/aktionen?action=open&id=${t.id}`}>Ausführung eintragen</Link> : null}
          {canClose ? <Link className="underline" href={`/aktionen?action=stop&id=${t.id}&stop=${t.stop ?? ""}`}>Stop nachziehen</Link> : null}
          {canClose ? <Link className="underline" href={`/aktionen?action=close&id=${t.id}`}>Schließen</Link> : null}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>These</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p>{t.statement}</p>
            {Array.isArray(raw.evidence) && raw.evidence.length ? (
              <div><div className="text-xs uppercase text-muted-foreground">Evidenz</div><ul className="list-disc pl-5">{raw.evidence.map((e: string, i: number) => <li key={i}>{e}</li>)}</ul></div>
            ) : null}
            {Array.isArray(raw.kill_criteria) && raw.kill_criteria.length ? (
              <div><div className="text-xs uppercase text-muted-foreground">Kill-Kriterien</div><ul className="list-disc pl-5">{raw.kill_criteria.map((e: string, i: number) => <li key={i}>{e}</li>)}</ul></div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Zahlen</CardTitle></CardHeader>
          <CardContent>
            <Row k="Region / Währung" v={`${t.region ?? "–"} / ${t.currency ?? "–"}`} />
            <Row k="Sektor" v={t.sector ?? "–"} />
            <Row k="Geplanter Einstieg" v={fmt(raw?.origin?.raw_provenance?.planned_entry)} />
            <Row k="Ausbruchsniveau" v={fmt(raw?.origin?.raw_provenance?.breakout_level)} />
            <Row k="Einstieg (tatsächlich)" v={t.entry_price ? `${fmt(t.entry_price)} am ${dateDe(t.entry_date)}` : "–"} />
            <Row k="Stücke" v={fmt(t.shares, 0)} />
            <Row k="Initialstop" v={fmt(t.initial_stop)} />
            <Row k="Aktueller Stop" v={fmt(t.stop)} />
            <Row k="Positionswert / Risiko" v={raw?.position ? `${eur(raw.position.position_value)} / ${eur(raw.position.risk_dollars)}` : "–"} />
            <Row k="Exit" v={t.exit_price ? `${fmt(t.exit_price)} am ${dateDe(t.exit_date)} (${t.exit_reason})` : "–"} />
            <Row k="P&L" v={t.pnl === null ? "–" : `${eur(t.pnl, 2)} · ${pct(t.pnl_pct, 2, false)} · ${t.r === null ? "" : fmt(t.r) + " R"}`} />
            <Row k="Nächster Review" v={dateDe(t.next_review)} />
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Stop-Verlauf</CardTitle><CardDescription>Stops werden nur angehoben.</CardDescription></CardHeader>
          <CardContent className="text-sm">
            {t.stop_ledger.length === 0 ? <p className="text-muted-foreground">Noch kein Nachzug.</p> : t.stop_ledger.map((s, i) => (
              <Row key={i} k={`${dateDe(s.date)} · ${s.note}`} v={`${fmt(s.old)} → ${fmt(s.new)}`} />
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Statusverlauf</CardTitle></CardHeader>
          <CardContent className="text-sm">
            {history.map((h, i) => (
              <Row key={i} k={`${dateDe(h.at)} · ${h.reason ?? ""}`} v={h.status} />
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

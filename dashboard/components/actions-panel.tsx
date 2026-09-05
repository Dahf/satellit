"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/select";
import { cn } from "@/lib/utils";

type ThesisOption = { id: string; label: string; status: string; stop: number | null; entry: number | null };

const TABS: Array<{ key: string; label: string }> = [
  { key: "new", label: "These anlegen" },
  { key: "open", label: "Ausführung" },
  { key: "stop", label: "Stop nachziehen" },
  { key: "close", label: "Schließen" },
  { key: "account", label: "Konto" },
  { key: "run", label: "Wochenlauf" },
];

async function callAction(action: string, body: Record<string, unknown>) {
  const res = await fetch("/api/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, body }),
  });
  const data = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
  return data as { ok: boolean; error?: string; result?: Record<string, unknown>; started?: boolean };
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

export function ActionsPanel({ initialAction, prefill, theses, equity, dryRunUntil, killActive }: {
  initialAction: string;
  prefill: { symbol: string; entry: string; stop: string; id: string };
  theses: ThesisOption[];
  equity: number | null;
  dryRunUntil: string | null;
  killActive: boolean;
}) {
  const router = useRouter();
  const [tab, setTab] = useState(TABS.some((t) => t.key === initialAction) ? initialAction : "new");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const today = new Date().toISOString().slice(0, 10);

  async function submit(action: string, body: Record<string, unknown>) {
    setBusy(true);
    setMsg(null);
    try {
      const data = await callAction(action, body);
      if (data.ok) {
        const r = data.result ?? {};
        const parts = Object.entries(r)
          .filter(([, v]) => v !== null && v !== undefined && typeof v !== "object")
          .map(([k, v]) => `${k}: ${typeof v === "number" ? Math.round(v * 100) / 100 : String(v)}`);
        setMsg({ ok: true, text: data.started ? "Wochenlauf gestartet — Übersicht in ein paar Minuten neu laden." : parts.join(" · ") || "OK" });
        router.refresh();
      } else {
        setMsg({ ok: false, text: data.error ?? "Fehler" });
      }
    } catch (err) {
      setMsg({ ok: false, text: String(err) });
    } finally {
      setBusy(false);
    }
  }

  const readyTheses = theses.filter((t) => t.status === "ENTRY_READY");
  const activeTheses = theses.filter((t) => t.status === "ACTIVE" || t.status === "PARTIALLY_CLOSED");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => { setTab(t.key); setMsg(null); }}
            className={cn("rounded-md px-3 py-1.5 text-sm font-medium", tab === t.key ? "bg-primary text-primary-foreground" : "border hover:bg-accent")}
          >
            {t.label}
          </button>
        ))}
        {killActive ? <Badge variant="red" className="ml-auto">Kill-Switch aktiv — keine neuen Einstiege</Badge> : null}
        {dryRunUntil ? <Badge variant="yellow">Trockenlauf bis {dryRunUntil}</Badge> : null}
      </div>

      {msg ? (
        <div className={cn("rounded-md border p-3 text-sm", msg.ok ? "border-emerald-300 bg-emerald-50 text-emerald-900" : "border-red-300 bg-red-50 text-red-900")}>
          {msg.text}
        </div>
      ) : null}

      {tab === "new" ? (
        <Card>
          <CardHeader>
            <CardTitle>These anlegen</CardTitle>
            <CardDescription>Kurs, Stop, Sektor und ISIN werden aus dem letzten Screener-Lauf übernommen, wenn leer. Danach: Positionsgröße wird berechnet und an die These gehängt.</CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="grid gap-3 md:grid-cols-4"
              onSubmit={(e) => {
                e.preventDefault();
                const f = new FormData(e.currentTarget);
                const body: Record<string, unknown> = { symbol: String(f.get("symbol") || "").trim(), core: f.get("core") === "on" };
                const entry = String(f.get("entry") || "").trim();
                const stop = String(f.get("stop") || "").trim();
                const statement = String(f.get("statement") || "").trim();
                if (entry) body.entry = Number(entry.replace(",", "."));
                if (stop) body.stop = Number(stop.replace(",", "."));
                if (statement) body.statement = statement;
                submit("journal.new", body);
              }}
            >
              <Field label="Symbol (Yahoo, z. B. SAP.DE)"><Input name="symbol" defaultValue={prefill.symbol} required /></Field>
              <Field label="Einstieg (leer = Screener)"><Input name="entry" defaultValue={prefill.entry} inputMode="decimal" /></Field>
              <Field label="Initialstop (leer = Screener)"><Input name="stop" defaultValue={prefill.stop} inputMode="decimal" /></Field>
              <Field label="Kern-Aktie?"><label className="flex h-9 items-center gap-2 text-sm"><input type="checkbox" name="core" /> ja (kein Stop, Review 180 Tage)</label></Field>
              <div className="md:col-span-4"><Field label="These (optional, sonst Standardtext)"><Input name="statement" placeholder="Warum dieser Trade — ein Satz." /></Field></div>
              <div className="md:col-span-4"><Button type="submit" disabled={busy || killActive}>{busy ? "…" : "These anlegen + Positionsgröße"}</Button></div>
            </form>
            {!equity ? <p className="mt-2 text-xs text-red-600">Kein Satelliten-Kapital hinterlegt — Positionsgröße kann nicht berechnet werden (Reiter „Konto").</p> : null}
          </CardContent>
        </Card>
      ) : null}

      {tab === "open" ? (
        <Card>
          <CardHeader><CardTitle>Ausführung eintragen</CardTitle><CardDescription>ENTRY_READY → ACTIVE. Danach Stop-Market-Order (360 Tage) beim Broker auf den Initialstop setzen.</CardDescription></CardHeader>
          <CardContent>
            <form className="grid gap-3 md:grid-cols-4" onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              submit("journal.open", { id: f.get("id"), price: Number(String(f.get("price")).replace(",", ".")), shares: Number(String(f.get("shares")).replace(",", ".")), date: f.get("date") });
            }}>
              <Field label="These"><NativeSelect name="id" defaultValue={prefill.id} required>{readyTheses.length === 0 ? <option value="">keine ENTRY_READY-These</option> : readyTheses.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}</NativeSelect></Field>
              <Field label="Ausführungskurs"><Input name="price" inputMode="decimal" required /></Field>
              <Field label="Stücke"><Input name="shares" inputMode="numeric" required /></Field>
              <Field label="Datum"><Input name="date" type="date" defaultValue={today} /></Field>
              <div className="md:col-span-4"><Button type="submit" disabled={busy || readyTheses.length === 0}>Eintragen</Button></div>
            </form>
          </CardContent>
        </Card>
      ) : null}

      {tab === "stop" ? (
        <Card>
          <CardHeader><CardTitle>Stop nachziehen</CardTitle><CardDescription>Nur anheben — ein niedrigerer Stop wird abgelehnt. Stop-Order beim Broker entsprechend anpassen.</CardDescription></CardHeader>
          <CardContent>
            <form className="grid gap-3 md:grid-cols-4" onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              submit("journal.stop", { id: f.get("id"), stop: Number(String(f.get("stop")).replace(",", ".")), note: f.get("note") || "Trailing-Stop (Dashboard)" });
            }}>
              <Field label="Position"><NativeSelect name="id" defaultValue={prefill.id} required>{activeTheses.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}</NativeSelect></Field>
              <Field label="Neuer Stop"><Input name="stop" defaultValue={prefill.stop} inputMode="decimal" required /></Field>
              <Field label="Notiz"><Input name="note" placeholder="Trailing-Stop KW …" /></Field>
              <div className="md:col-span-4"><Button type="submit" disabled={busy || activeTheses.length === 0}>Stop setzen</Button></div>
            </form>
          </CardContent>
        </Card>
      ) : null}

      {tab === "close" ? (
        <Card>
          <CardHeader><CardTitle>Position schließen</CardTitle><CardDescription>Grund „manuell" ist ein Regelbruch und wird als solcher gezählt.</CardDescription></CardHeader>
          <CardContent>
            <form className="grid gap-3 md:grid-cols-4" onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              submit("journal.close", { id: f.get("id"), price: Number(String(f.get("price")).replace(",", ".")), reason: f.get("reason"), date: f.get("date") });
            }}>
              <Field label="Position"><NativeSelect name="id" defaultValue={prefill.id} required>{activeTheses.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}</NativeSelect></Field>
              <Field label="Exit-Kurs"><Input name="price" inputMode="decimal" required /></Field>
              <Field label="Grund"><NativeSelect name="reason" defaultValue="stop"><option value="stop">Harter Stop ausgelöst</option><option value="trend">Weicher Exit (Trendbruch)</option><option value="manual">Manuell (Regelbruch)</option><option value="invalidated">These invalidiert</option></NativeSelect></Field>
              <Field label="Datum"><Input name="date" type="date" defaultValue={today} /></Field>
              <div className="md:col-span-4"><Button type="submit" variant="destructive" disabled={busy || activeTheses.length === 0}>Schließen</Button></div>
            </form>
          </CardContent>
        </Card>
      ) : null}

      {tab === "account" ? (
        <Card>
          <CardHeader><CardTitle>Satellit-Konto</CardTitle><CardDescription>Wert des Satelliten (Cash + Positionen) aus der Trade-Republic-App — wöchentlich am Sonntag eintragen. Daraus: Drawdown, Kill-Switch, Positionsgrößen.</CardDescription></CardHeader>
          <CardContent>
            <form className="grid gap-3 md:grid-cols-4" onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              const body: Record<string, unknown> = {};
              const eq = String(f.get("equity") || "").trim();
              if (eq) body.equity = Number(eq.replace(",", "."));
              body.dry_run_until = String(f.get("dry_run_until") || "") || null;
              if (f.get("reset_kill") === "on") body.reset_kill = true;
              submit("account", body);
            }}>
              <Field label="Satellit-Kapital (EUR)"><Input name="equity" defaultValue={equity ?? ""} inputMode="decimal" /></Field>
              <Field label="Trockenlauf bis (leer = aus)"><Input name="dry_run_until" type="date" defaultValue={dryRunUntil ?? ""} /></Field>
              <Field label="Kill-Switch zurücksetzen"><label className="flex h-9 items-center gap-2 text-sm"><input type="checkbox" name="reset_kill" /> nur nach schriftlicher Analyse (Plan 10.2)</label></Field>
              <div className="md:col-span-4"><Button type="submit" disabled={busy}>Speichern</Button></div>
            </form>
          </CardContent>
        </Card>
      ) : null}

      {tab === "run" ? (
        <Card>
          <CardHeader><CardTitle>Wochenlauf manuell starten</CardTitle><CardDescription>Normalerweise läuft er samstags automatisch. Manuell z. B. nach Korrekturen in symbol_overrides.yaml. Dauer: 5–15 Minuten.</CardDescription></CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <Button disabled={busy} onClick={() => submit("run.weekly", { push: true })}>Jetzt laufen lassen (mit Push)</Button>
            <Button variant="outline" disabled={busy} onClick={() => submit("run.weekly", { push: false })}>Ohne Push</Button>
            <Button variant="ghost" disabled={busy} onClick={() => submit("run.weekly", { push: false, demo: true })}>Demo-Lauf (synthetische Daten)</Button>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

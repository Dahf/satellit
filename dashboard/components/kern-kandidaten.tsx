"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { Entscheidung, KernScan } from "@/lib/view";
import { EntscheidungZeile } from "@/components/entscheidung-zeile";
import { dateDe } from "@/lib/utils";

/**
 * Kern-Aktien, die den Kriterienkatalog aus KERN.md 6 durchlaufen haben.
 *
 * Bewusst ein eigener Abschnitt und nicht Teil von "Zu erledigen": ein Kandidat ist keine
 * Aufgabe für den Montag. Der Kern wird nicht getimt (Trading-Plan 2), gekauft wird nur in
 * der ersten Handelswoche von Januar, April, Juli und Oktober — bis dahin wird notiert.
 *
 * Das Datum des Scans steht im Kopf, weil er nicht wöchentlich mitläuft. Eine Liste ohne
 * Datum sähe aus, als wäre sie von heute.
 */
export function KernKandidaten({ kandidaten, scan }: { kandidaten: Entscheidung[]; scan: KernScan }) {
  const [offen, setOffen] = useState(false);
  const bestanden = kandidaten.length;

  return (
    <section aria-labelledby="kern-kandidaten" className="mt-12">
      <h2 id="kern-kandidaten" className="font-display text-ansage font-semibold">
        Kern-Aktien: geprüfte Kandidaten
      </h2>
      <p className="mt-1 max-w-[62ch] text-etikett leading-relaxed text-muted-foreground">
        Der Katalog aus <span className="font-mono">KERN.md 6</span> ist ein Filter, kein Score — ein
        Titel muss <em>alle</em> sieben Muss-Kriterien erfüllen. Zwei davon kann kein Programm
        beantworten: ob du das Geschäftsmodell in zwei Sätzen erklären kannst, und welche zwei
        Ereignisse dich zum Verkauf bewegen. Die trägst du beim Anlegen der These ein.
      </p>

      <ScanKopf scan={scan} />

      {bestanden === 0 ? (
        <p className="mt-4 rounded-lg border border-dashed border-border px-5 py-6 text-lauftext leading-relaxed text-muted-foreground">
          {scan.gelaufen
            ? "Kein Titel besteht den Katalog. Das ist ein gültiges Ergebnis, kein Fehler — Qualität nach diesen Maßstäben ist selten."
            : "Noch kein Scan gelaufen. Er prüft das Index-Universum gegen den Katalog und dauert einige Minuten, weil je Titel Jahresabschlüsse abgerufen werden."}
        </p>
      ) : (
        <>
          <ul className="mt-4 overflow-hidden rounded-lg border border-border bg-card">
            {(offen ? kandidaten : kandidaten.slice(0, 5)).map((d) => (
              <EntscheidungZeile key={d.schluessel} d={d} />
            ))}
          </ul>
          {bestanden > 5 && (
            <button
              type="button"
              onClick={() => setOffen((o) => !o)}
              className="mt-3 text-etikett text-muted-foreground underline underline-offset-2"
            >
              {offen ? "Weniger zeigen" : `Alle ${bestanden} Kandidaten zeigen`}
            </button>
          )}
        </>
      )}

      <ScanKnoepfe scan={scan} />
    </section>
  );
}

function ScanKopf({ scan }: { scan: KernScan }) {
  if (!scan.gelaufen) return null;
  const t = scan.trichter ?? {};
  const umfang = { universum: "Index-Universum", watchlist: "eigene Watchlist", demo: "DEMO-Daten" }[
    scan.quelle ?? ""
  ] ?? scan.quelle;
  return (
    <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-1 text-etikett text-muted-foreground">
      <Wert label="Stand" wert={scan.as_of ? dateDe(scan.as_of) : "–"} />
      <Wert label="Umfang" wert={umfang ?? "–"} />
      <Wert label="Geprüft" wert={String(scan.geprueft ?? 0)} />
      <Wert label="Bestanden" wert={String(t.bestanden ?? 0)} />
      {scan.demo && <Wert label="Achtung" wert="erfundene Kennzahlen (DEMO)" />}
    </dl>
  );
}

function Wert({ label, wert }: { label: string; wert: string }) {
  return (
    <div className="flex gap-1.5">
      <dt className="text-marginalie uppercase tracking-wider">{label}</dt>
      <dd className="text-foreground">{wert}</dd>
    </div>
  );
}

function ScanKnoepfe({ scan }: { scan: KernScan }) {
  const router = useRouter();
  const [laeuft, setLaeuft] = useState<string | null>(null);
  const [meldung, setMeldung] = useState<string | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const [symbol, setSymbol] = useState("");

  async function ruf(action: string, body: Record<string, unknown>, was: string) {
    setLaeuft(was);
    setFehler(null);
    setMeldung(null);
    try {
      const antwort = await fetch("/api/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, body }),
      });
      const daten = await antwort.json();
      if (!antwort.ok || daten.ok === false) {
        setFehler(daten.error ?? `Fehlgeschlagen (${antwort.status})`);
      } else {
        const r = daten.result ?? {};
        setMeldung(
          r.gestartet
            ? "Der Scan läuft im Hintergrund. Er ruft je Titel Jahresabschlüsse ab und braucht einige Minuten — lad die Seite später neu."
            : r.geprueft !== undefined
              ? `${r.geprueft} Titel geprüft, ${r.bestanden} bestehen den Katalog.`
              : "Übernommen.",
        );
        setSymbol("");
        router.refresh();
      }
    } catch (e) {
      setFehler(String(e));
    } finally {
      setLaeuft(null);
    }
  }

  return (
    <div className="mt-5 rounded-lg border border-border bg-muted/30 p-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-[10rem] flex-1 flex-col gap-1">
          <span className="text-marginalie uppercase tracking-wider text-muted-foreground">
            Eigenen Titel prüfen
          </span>
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="z. B. SAP.DE"
            className="rounded-sm border border-input bg-card px-2 py-1.5 font-mono text-lauftext focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </label>
        <button
          type="button"
          disabled={!symbol || laeuft !== null}
          onClick={() => ruf("kern.watchlist", { symbol }, "watchlist")}
          className="rounded-md border border-border px-3 py-1.5 text-etikett font-medium transition-colors hover:bg-muted disabled:opacity-40"
        >
          {laeuft === "watchlist" ? "…" : "Auf die Liste"}
        </button>
        <button
          type="button"
          disabled={laeuft !== null || (scan.watchlist ?? 0) === 0}
          onClick={() => ruf("kern.scan", { nur_watchlist: true }, "watchlist-scan")}
          className="rounded-md border border-border px-3 py-1.5 text-etikett font-medium transition-colors hover:bg-muted disabled:opacity-40"
          title={
            (scan.watchlist ?? 0) === 0
              ? "Noch kein eigener Titel auf der Liste."
              : `${scan.watchlist} eigene Titel prüfen`
          }
        >
          {laeuft === "watchlist-scan" ? "Wird geprüft …" : `Liste prüfen (${scan.watchlist ?? 0})`}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-border pt-3">
        <button
          type="button"
          disabled={laeuft !== null}
          onClick={() => ruf("kern.scan", {}, "voll")}
          className="rounded-md border border-border px-3 py-1.5 text-etikett font-medium transition-colors hover:bg-muted disabled:opacity-40"
        >
          {laeuft === "voll" ? "Wird gestartet …" : "Ganzes Universum scannen"}
        </button>
        <span className="text-marginalie leading-snug text-muted-foreground">
          Rund 1.100 Titel, je Titel ein eigener Abruf — das dauert Minuten. Das Ergebnis hält 90
          Tage, was zum Kauffenster passt.
        </span>
      </div>

      {meldung && <p className="mt-3 text-etikett leading-relaxed text-foreground">{meldung}</p>}
      {fehler && <p className="mt-3 text-etikett text-verkauf">{fehler}</p>}
    </div>
  );
}

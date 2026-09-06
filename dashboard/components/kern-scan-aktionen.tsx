"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { KernLauf, KernScan } from "@/lib/view";

/**
 * Die interaktiven Teile des Kern-Abschnitts.
 *
 * Bewusst von `kern-kandidaten.tsx` getrennt: dort werden `EntscheidungZeile` und damit
 * `lib/view` gerendert, und `lib/view` ist `server-only` (es liest state/view_latest.json
 * vom Dateisystem). Eine Client-Komponente, die das importiert, bricht den Build. Dasselbe
 * Muster wie `EntscheidungZeile` (Server) mit `Aktion` (Client).
 *
 * Der Typ-Import oben ist unkritisch — `import type` wird beim Übersetzen entfernt und
 * landet nie im Bundle.
 */
export function KernScanAktionen({ scan, lauf }: { scan: KernScan; lauf?: KernLauf }) {
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
            ? "Der Scan läuft im Hintergrund. Er ruft je Titel Jahresabschlüsse ab und braucht rund " +
              "eine Stunde; der Fortschritt steht oben in diesem Abschnitt." +
              (r.demo ? " Achtung: Demo-Modus — die Kennzahlen sind erfunden." : "")
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

  const watchlist = scan.watchlist ?? 0;
  // Der Hintergrundlauf teilt sich das Schloss mit dem Wochenlauf und schreibt denselben
  // Kern-Stand. Solange er läuft, sperren beide Knöpfe — sonst schickt ein zweiter Klick
  // eine Anfrage los, die die API ohnehin ablehnt, und der Watchlist-Lauf schriebe
  // gleichzeitig in dieselbe Datei.
  const laeuftImHintergrund = Boolean(lauf?.running);

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
          disabled={laeuft !== null || laeuftImHintergrund || watchlist === 0}
          onClick={() => ruf("kern.scan", { nur_watchlist: true }, "watchlist-scan")}
          className="rounded-md border border-border px-3 py-1.5 text-etikett font-medium transition-colors hover:bg-muted disabled:opacity-40"
          title={watchlist === 0 ? "Noch kein eigener Titel auf der Liste." : `${watchlist} eigene Titel prüfen`}
        >
          {laeuft === "watchlist-scan" ? "Wird geprüft …" : `Liste prüfen (${watchlist})`}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-border pt-3">
        <button
          type="button"
          disabled={laeuft !== null || laeuftImHintergrund}
          onClick={() => ruf("kern.scan", {}, "voll")}
          className="rounded-md border border-border px-3 py-1.5 text-etikett font-medium transition-colors hover:bg-muted disabled:opacity-40"
        >
          {laeuftImHintergrund ? "Läuft …" : laeuft === "voll" ? "Wird gestartet …" : "Ganzes Universum scannen"}
        </button>
        <span className="max-w-[46ch] text-marginalie leading-snug text-muted-foreground">
          {laeuftImHintergrund && lauf?.fortschritt
            ? `${lauf.fortschritt.geprueft} von ${lauf.fortschritt.gesamt} Titeln geprüft. Lad die Seite neu, um den Stand zu aktualisieren.`
            : laeuftImHintergrund
              ? "Der Lauf hat begonnen und lädt zuerst das Index-Universum."
              : "Rund 1.100 Titel, je Titel ein eigener Abruf — das dauert etwa eine Stunde. Das Ergebnis hält 90 Tage, was zum Kauffenster passt."}
        </span>
      </div>

      {meldung && <p className="mt-3 text-etikett leading-relaxed text-foreground">{meldung}</p>}
      {fehler && <p className="mt-3 text-etikett text-verkauf">{fehler}</p>}
    </div>
  );
}

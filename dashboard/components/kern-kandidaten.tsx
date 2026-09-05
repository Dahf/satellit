import type { Entscheidung, KernScan } from "@/lib/view";
import { EntscheidungZeile } from "@/components/entscheidung-zeile";
import { KernScanAktionen } from "@/components/kern-scan-aktionen";
import { dateDe } from "@/lib/utils";

/**
 * Kern-Aktien, die den Kriterienkatalog aus KERN.md 6 durchlaufen haben.
 *
 * Bewusst ein eigener Abschnitt und nicht Teil von "Zu erledigen": ein Kandidat ist keine
 * Aufgabe für den Montag. Der Kern wird nicht getimt (Trading-Plan 2), gekauft wird nur in
 * der ersten Handelswoche von Januar, April, Juli und Oktober — bis dahin wird notiert.
 *
 * Server-Komponente. `EntscheidungZeile` zieht `lib/view` herein, und das ist `server-only`;
 * die interaktiven Teile stehen deshalb in `kern-scan-aktionen.tsx`. Das Aufklappen der
 * langen Liste macht ein natives <details>, wie bei `Ausklapp` auf der Startseite — dafür
 * braucht es keinen Zustand im Browser.
 */
export function KernKandidaten({ kandidaten, scan }: { kandidaten: Entscheidung[]; scan: KernScan }) {
  const sichtbar = kandidaten.slice(0, 5);
  const rest = kandidaten.slice(5);

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

      {kandidaten.length === 0 ? (
        <p className="mt-4 rounded-lg border border-dashed border-border px-5 py-6 text-lauftext leading-relaxed text-muted-foreground">
          {scan.gelaufen
            ? "Kein Titel besteht den Katalog. Das ist ein gültiges Ergebnis, kein Fehler — Qualität nach diesen Maßstäben ist selten."
            : "Noch kein Scan gelaufen. Er prüft das Index-Universum gegen den Katalog und dauert einige Minuten, weil je Titel Jahresabschlüsse abgerufen werden."}
        </p>
      ) : (
        <>
          <ul className="mt-4 overflow-hidden rounded-lg border border-border bg-card">
            {sichtbar.map((d) => (
              <EntscheidungZeile key={d.schluessel} d={d} />
            ))}
          </ul>
          {rest.length > 0 && (
            <details className="group mt-3">
              <summary className="cursor-pointer list-none text-etikett text-muted-foreground marker:content-none hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <span aria-hidden="true" className="mr-2 inline-block transition-transform group-open:rotate-90">
                  ▸
                </span>
                Weitere {rest.length} Kandidaten
              </summary>
              <ul className="mt-3 overflow-hidden rounded-lg border border-border bg-card">
                {rest.map((d) => (
                  <EntscheidungZeile key={d.schluessel} d={d} />
                ))}
              </ul>
            </details>
          )}
        </>
      )}

      <KernScanAktionen scan={scan} />
    </section>
  );
}

function ScanKopf({ scan }: { scan: KernScan }) {
  if (!scan.gelaufen) return null;
  const t = scan.trichter ?? {};
  const umfang =
    { universum: "Index-Universum", watchlist: "eigene Watchlist", demo: "DEMO-Daten" }[scan.quelle ?? ""] ??
    scan.quelle;
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

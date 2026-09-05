"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type Abschnitt = "lauf" | "konto" | "universum";

/**
 * Alles, was selten gebraucht wird, hinter einem Knopf: Wochenlauf, Kapital, Sperren,
 * Konstituenten-Import. Die Startseite bleibt dadurch eine reine Handlungsliste.
 */
export function Einstellungen({ offenBei }: { offenBei?: Abschnitt }) {
  const router = useRouter();
  const [offen, setOffen] = useState(Boolean(offenBei));
  const [laeuft, setLaeuft] = useState<string | null>(null);
  const [meldung, setMeldung] = useState<{ art: "ok" | "fehler"; text: string } | null>(null);

  useEffect(() => {
    if (!offen) return;
    const taste = (e: KeyboardEvent) => e.key === "Escape" && setOffen(false);
    document.addEventListener("keydown", taste);
    return () => document.removeEventListener("keydown", taste);
  }, [offen]);

  async function senden(aktion: string, body: Record<string, unknown>, was: string) {
    setLaeuft(was);
    setMeldung(null);
    try {
      const antwort = await fetch("/api/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: aktion, body }),
      });
      const daten = await antwort.json();
      if (!antwort.ok || daten.ok === false) {
        setMeldung({ art: "fehler", text: daten.error ?? `Fehlgeschlagen (${antwort.status})` });
      } else {
        setMeldung({ art: "ok", text: `${was} übernommen.` });
        router.refresh();
      }
    } catch (e) {
      setMeldung({ art: "fehler", text: String(e) });
    } finally {
      setLaeuft(null);
    }
  }

  if (!offen) {
    return (
      <button
        type="button"
        onClick={() => setOffen(true)}
        className="rounded-md border border-border px-3 py-1.5 text-etikett text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        Einstellungen
      </button>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-foreground/20" onClick={() => setOffen(false)}>
      <aside
        role="dialog"
        aria-label="Einstellungen"
        onClick={(e) => e.stopPropagation()}
        className="einblenden h-full w-full max-w-md overflow-y-auto border-l border-border bg-card p-6"
      >
        <div className="flex items-center justify-between">
          <h2 className="font-display text-ansage font-semibold">Einstellungen</h2>
          <button onClick={() => setOffen(false)} className="text-etikett text-muted-foreground underline">
            Schließen
          </button>
        </div>

        {meldung && (
          <p
            className={
              meldung.art === "ok"
                ? "mt-4 rounded-sm bg-kaufen-weich px-3 py-2 text-etikett text-kaufen"
                : "mt-4 rounded-sm bg-verkauf-weich px-3 py-2 text-etikett text-verkauf"
            }
          >
            {meldung.text}
          </p>
        )}

        <Block titel="Wochenlauf" hinweis="Läuft normalerweise samstags um 8 Uhr von selbst.">
          <div className="flex flex-wrap gap-2">
            <Knopf onClick={() => senden("run.weekly", { push: true }, "Wochenlauf")} laeuft={laeuft === "Wochenlauf"}>
              Jetzt laufen lassen
            </Knopf>
            <Knopf
              onClick={() => senden("run.weekly", { push: false }, "Wochenlauf ohne Push")}
              laeuft={laeuft === "Wochenlauf ohne Push"}
              leise
            >
              Ohne Benachrichtigung
            </Knopf>
          </div>
          <p className="mt-2 text-etikett text-muted-foreground">
            Der Lauf arbeitet im Hintergrund. Seite nach ein paar Minuten neu laden.
          </p>
        </Block>

        <Kontoblock senden={senden} laeuft={laeuft} />
        <Universumblock senden={senden} laeuft={laeuft} />

        <div className="mt-8 border-t border-border pt-5">
          <form action="/api/logout" method="post">
            <button className="text-etikett text-muted-foreground underline">Abmelden</button>
          </form>
        </div>
      </aside>
    </div>
  );
}

function Kontoblock({ senden, laeuft }: {
  senden: (a: string, b: Record<string, unknown>, w: string) => void;
  laeuft: string | null;
}) {
  const [kapital, setKapital] = useState("");
  const [bis, setBis] = useState("");
  return (
    <Block titel="Konto" hinweis="Das Kapital im Satelliten — laut Plan rund 10 % des Gesamtportfolios.">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-marginalie uppercase tracking-wider text-muted-foreground">Kapital in EUR</span>
          <input
            value={kapital}
            onChange={(e) => setKapital(e.target.value)}
            inputMode="decimal"
            placeholder="z. B. 5000"
            className="zahl rounded-sm border border-input bg-background px-2 py-1.5 text-lauftext"
          />
        </label>
        <Knopf
          onClick={() => senden("account", { equity: Number(kapital.replace(",", ".")) }, "Kapital")}
          laeuft={laeuft === "Kapital"}
        >
          Speichern
        </Knopf>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-2">
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-marginalie uppercase tracking-wider text-muted-foreground">Trockenlauf bis</span>
          <input
            type="date"
            value={bis}
            onChange={(e) => setBis(e.target.value)}
            className="rounded-sm border border-input bg-background px-2 py-1.5 text-lauftext"
          />
        </label>
        <Knopf onClick={() => senden("account", { dry_run_until: bis || null }, "Trockenlauf")} laeuft={laeuft === "Trockenlauf"} leise>
          Setzen
        </Knopf>
      </div>
      <p className="mt-2 text-etikett text-muted-foreground">
        Im Trockenlauf zeigt das System alles an, sperrt aber jede Order. Der Plan verlangt das für die ersten
        zwei Wochenenden.
      </p>

      <div className="mt-4">
        <Knopf onClick={() => senden("account", { reset_kill: true }, "Kill-Switch")} laeuft={laeuft === "Kill-Switch"} leise>
          Kill-Switch zurücksetzen
        </Knopf>
      </div>
    </Block>
  );
}

function Universumblock({ senden, laeuft }: {
  senden: (a: string, b: Record<string, unknown>, w: string) => void;
  laeuft: string | null;
}) {
  const [region, setRegion] = useState("US");
  return (
    <Block
      titel="Konstituenten"
      hinweis="Nur nötig, wenn der automatische Download bei iShares scheitert."
    >
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-marginalie uppercase tracking-wider text-muted-foreground">Region</span>
          <select
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            className="rounded-sm border border-input bg-background px-2 py-1.5 text-lauftext"
          >
            <option value="US">US — S&amp;P 500</option>
            <option value="EU">EU — STOXX Europe 600</option>
          </select>
        </label>
        <label className="flex-1">
          <span className="sr-only">Holdings-CSV auswählen</span>
          <input
            type="file"
            accept=".csv,text/csv"
            disabled={laeuft === "Konstituenten"}
            onChange={async (e) => {
              const datei = e.target.files?.[0];
              if (!datei) return;
              senden("universe.import", { region, inhalt: await datei.text() }, "Konstituenten");
              e.target.value = "";
            }}
            className="w-full text-etikett file:mr-3 file:rounded-md file:border file:border-border file:bg-background file:px-3 file:py-1.5 file:text-etikett"
          />
        </label>
      </div>
    </Block>
  );
}

function Block({ titel, hinweis, children }: { titel: string; hinweis: string; children: React.ReactNode }) {
  return (
    <section className="mt-8 border-t border-border pt-5">
      <h3 className="font-display text-lauftext font-semibold">{titel}</h3>
      <p className="mb-3 mt-0.5 text-etikett leading-snug text-muted-foreground">{hinweis}</p>
      {children}
    </section>
  );
}

function Knopf({ onClick, laeuft, leise, children }: {
  onClick: () => void;
  laeuft: boolean;
  leise?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={laeuft}
      className={
        leise
          ? "rounded-md border border-border px-3 py-1.5 text-etikett transition-colors hover:bg-muted disabled:opacity-40"
          : "rounded-md bg-primary px-3 py-1.5 text-etikett font-medium text-primary-foreground disabled:opacity-40"
      }
    >
      {laeuft ? "…" : children}
    </button>
  );
}

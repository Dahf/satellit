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
        <TradeRepublicBlock />
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

interface Vorschau {
  gelesen: number;
  neu: number;
  bereits_gebucht: number;
  nach_typ: Record<string, number>;
  warnungen: string[];
  zeitraum: [string | null, string | null];
  beispiele: { datum: string; typ: string; betrag_eur: number; notiz: string }[];
}

/**
 * Umsatzliste aus Trade Republic übernehmen.
 *
 * Trade Republic hat keine offizielle Schnittstelle. Der Weg führt über pytr, das der
 * Nutzer auf seinem eigenen Rechner ausführt — Zugangsdaten und Geräteschlüssel bleiben
 * damit bei ihm. Der Import zeigt erst, was gebucht würde, und schreibt erst nach
 * Bestätigung: das Dateiformat ist undokumentiert und kann sich jederzeit ändern.
 */
function TradeRepublicBlock() {
  const router = useRouter();
  const [inhalt, setInhalt] = useState<string | null>(null);
  const [vorschau, setVorschau] = useState<Vorschau | null>(null);
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const [fertig, setFertig] = useState<string | null>(null);

  async function ruf(uebernehmen: boolean, text: string) {
    setLaeuft(true);
    setFehler(null);
    try {
      const antwort = await fetch("/api/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "portfolio.import", body: { inhalt: text, uebernehmen } }),
      });
      const daten = await antwort.json();
      if (!antwort.ok || daten.ok === false) {
        setFehler(daten.error ?? `Fehlgeschlagen (${antwort.status})`);
        return;
      }
      if (uebernehmen) {
        setFertig(`${daten.result.gebucht} Buchungen übernommen, ${daten.result.bereits_gebucht} waren schon da.`);
        setVorschau(null);
        setInhalt(null);
        router.refresh();
      } else {
        setVorschau(daten.result as Vorschau);
      }
    } catch (e) {
      setFehler(String(e));
    } finally {
      setLaeuft(false);
    }
  }

  return (
    <Block
      titel="Trade Republic"
      hinweis="Trade Republic hat keine offizielle Schnittstelle. Der Umweg geht über pytr auf deinem eigenen Rechner — deine Zugangsdaten kommen nie auf diesen Server."
    >
      <ol className="mb-3 space-y-1 text-etikett leading-relaxed text-muted-foreground">
        <li>1. Einmalig installieren: <code className="font-mono">pipx install pytr</code></li>
        <li>2. Anmelden: <code className="font-mono">pytr login</code> (Bestätigung in der App)</li>
        <li>3. Exportieren: <code className="font-mono">pytr export_transactions</code></li>
        <li>4. Die Datei <code className="font-mono">account_transactions.csv</code> hier hochladen.</li>
      </ol>

      <input
        type="file"
        accept=".csv,text/csv"
        disabled={laeuft}
        onChange={async (e) => {
          const datei = e.target.files?.[0];
          if (!datei) return;
          const text = await datei.text();
          setInhalt(text);
          setFertig(null);
          await ruf(false, text);
          e.target.value = "";
        }}
        className="w-full text-etikett file:mr-3 file:rounded-md file:border file:border-border file:bg-background file:px-3 file:py-1.5 file:text-etikett"
      />

      {fehler && <p className="mt-2 rounded-sm bg-verkauf-weich px-2.5 py-1.5 text-etikett text-verkauf">{fehler}</p>}
      {fertig && <p className="mt-2 rounded-sm bg-kaufen-weich px-2.5 py-1.5 text-etikett text-kaufen">{fertig}</p>}

      {vorschau && (
        <div className="mt-4 rounded-md border border-border p-3">
          <p className="text-lauftext">
            <strong>{vorschau.neu}</strong> neue Buchungen
            {vorschau.bereits_gebucht > 0 && <> · {vorschau.bereits_gebucht} schon vorhanden</>}
            {vorschau.zeitraum[0] && <> · {vorschau.zeitraum[0]} bis {vorschau.zeitraum[1]}</>}
          </p>

          {Object.keys(vorschau.nach_typ).length > 0 && (
            <p className="mt-1.5 text-etikett text-muted-foreground">
              {Object.entries(vorschau.nach_typ).map(([t, n]) => `${n}× ${t}`).join(" · ")}
            </p>
          )}

          {vorschau.beispiele.length > 0 && (
            <ul className="zahl mt-3 space-y-0.5 text-marginalie text-muted-foreground">
              {vorschau.beispiele.map((b, i) => (
                <li key={i}>
                  {b.datum} · {b.typ} · {b.betrag_eur.toFixed(2)} € · {b.notiz.slice(0, 40)}
                </li>
              ))}
            </ul>
          )}

          {vorschau.warnungen.length > 0 && (
            <details className="mt-3">
              <summary className="cursor-pointer text-etikett text-achtung">
                {vorschau.warnungen.length} Zeilen übersprungen — bitte ansehen
              </summary>
              <ul className="mt-1.5 space-y-0.5 text-marginalie leading-snug text-muted-foreground">
                {vorschau.warnungen.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </details>
          )}

          <div className="mt-3 flex gap-2">
            <Knopf onClick={() => inhalt && ruf(true, inhalt)} laeuft={laeuft}>
              {vorschau.neu} Buchungen übernehmen
            </Knopf>
            <button
              type="button"
              onClick={() => { setVorschau(null); setInhalt(null); }}
              className="text-etikett text-muted-foreground underline"
            >
              Verwerfen
            </button>
          </div>
        </div>
      )}
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

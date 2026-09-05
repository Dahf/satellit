"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { eur } from "@/lib/utils";

// Der Katalog hält die Schlüssel ASCII-frei von Umlauten; die Anzeige nicht.
const ERTRAG: Record<string, string> = {
  thesaurierend: "thesaurierend",
  ausschuettend: "ausschüttend",
};

// Die Form spiegelt lib/view.ts. Bewusst hier noch einmal deklariert: lib/view.ts ist
// server-only, ein Import von dort würde diese Client-Komponente unbrauchbar machen.
export interface EtfEintrag {
  isin: string;
  symbol: string;
  name: string;
  index: string;
  ter: number;
  ertrag: string;
  gruppe: string;
  hinweis?: string;
}

/**
 * Die Ersteinrichtung. Sie ersetzt die Entscheidungsliste, solange nichts eingerichtet ist —
 * eine leere Seite mit dem Hinweis "keine Daten" wäre für jemanden, der gerade anfangen
 * will, die schlechteste aller Antworten.
 */
export function Onboarding({ etfs }: { etfs: EtfEintrag[] }) {
  const router = useRouter();
  // Der Katalog steckt im Payload, das aber erst ein Lauf erzeugt. Im Onboarding hat noch
  // keiner stattgefunden — deshalb bei leerer Liste direkt beim Backend nachfragen.
  const [geladen, setGeladen] = useState<EtfEintrag[]>(etfs);
  const [laedt, setLaedt] = useState(etfs.length === 0);

  useEffect(() => {
    if (etfs.length > 0) return;
    let abgebrochen = false;
    (async () => {
      try {
        const antwort = await fetch("/api/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "portfolio.katalog", body: {} }),
        });
        const daten = await antwort.json();
        if (!abgebrochen && daten?.result?.etfs) setGeladen(daten.result.etfs as EtfEintrag[]);
      } catch {
        /* Die freie ISIN-Eingabe trägt den Fall — kein Grund, das Onboarding zu blockieren. */
      } finally {
        if (!abgebrochen) setLaedt(false);
      }
    })();
    return () => {
      abgebrochen = true;
    };
  }, [etfs.length]);

  const welt = useMemo(() => geladen.filter((e) => e.gruppe === "welt"), [geladen]);
  const [start, setStart] = useState("");
  const [rate, setRate] = useState("");
  const [tag, setTag] = useState("1");
  const [isin, setIsin] = useState("");
  const [aktien, setAktien] = useState(false);
  const [trockenlauf, setTrockenlauf] = useState(true);
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);

  const startZahl = Number((start || "0").replace(",", "."));
  const kern = startZahl * 0.9;
  const satellit = startZahl - kern;
  const etfAnteil = aktien ? 0.8 : 1.0;
  const gewaehlt = geladen.find((e) => e.isin === isin);

  useEffect(() => {
    if (!isin && welt.length > 0) setIsin(welt[0].isin);
  }, [welt, isin]);

  async function absenden() {
    setFehler(null);
    if (!(startZahl > 0)) return setFehler("Trag ein, mit wie viel Geld du startest.");
    if (!isin) return setFehler("Wähle einen Welt-ETF.");
    setLaeuft(true);
    try {
      const antwort = await fetch("/api/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "portfolio.setup",
          body: {
            start_eur: startZahl,
            rate_eur: Number((rate || "0").replace(",", ".")),
            sparplan_tag: Number(tag) || 1,
            etf_isin: isin,
            etf_anteil: etfAnteil,
            trockenlauf_tage: trockenlauf ? 14 : 0,
          },
        }),
      });
      const daten = await antwort.json();
      if (!antwort.ok || daten.ok === false) setFehler(daten.error ?? `Fehlgeschlagen (${antwort.status})`);
      else router.refresh();
    } catch (e) {
      setFehler(String(e));
    } finally {
      setLaeuft(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl px-5 pb-24 pt-12 md:px-8">
      <p className="font-mono text-marginalie uppercase tracking-[0.14em] text-muted-foreground">Einrichtung</p>
      <h1 className="mt-3 font-display text-titel font-semibold">Lass uns anfangen.</h1>
      <p className="mt-3 max-w-[52ch] text-lauftext leading-relaxed text-muted-foreground">
        Vier Angaben, dann weiß das System, was es für dich rechnen soll. Ändern kannst du alles
        später — außer der Aufteilung deines Startbetrags, die triffst du einmal.
      </p>

      <Schritt nummer="1" titel="Mit wie viel Geld startest du?">
        <Feld wert={start} setzen={setStart} platzhalter="z. B. 5000" einheit="EUR" />
        {startZahl > 0 && (
          <p className="mt-2 text-etikett leading-relaxed text-muted-foreground">
            Davon gehen <strong className="text-foreground">{eur(kern)}</strong> in den Kern und{" "}
            <strong className="text-foreground">{eur(satellit)}</strong> in den Satelliten — die 90/10-Aufteilung
            aus deinem Trading-Plan.
          </p>
        )}
      </Schritt>

      <Schritt nummer="2" titel="Wie viel legst du monatlich an?">
        <div className="flex flex-wrap items-end gap-4">
          <Feld wert={rate} setzen={setRate} platzhalter="z. B. 500" einheit="EUR im Monat" />
          <label className="flex flex-col gap-1">
            <span className="text-marginalie uppercase tracking-wider text-muted-foreground">Tag im Monat</span>
            <input
              value={tag}
              onChange={(e) => setTag(e.target.value)}
              inputMode="numeric"
              className="zahl w-20 rounded-sm border border-input bg-card px-2 py-1.5 text-lauftext"
            />
          </label>
        </div>
        <p className="mt-2 text-etikett leading-relaxed text-muted-foreground">
          Am besten direkt nach dem Gehaltseingang. Der Sparplan wird nie wegen der Marktlage pausiert.
        </p>
      </Schritt>

      <Schritt nummer="3" titel="Welchen Welt-ETF?">
        {laedt && <p className="mb-4 text-etikett text-muted-foreground">Auswahlliste wird geladen …</p>}

        {!laedt && welt.length === 0 && (
          <div className="mb-4 rounded-md bg-achtung-weich px-3 py-2.5 text-etikett leading-relaxed text-achtung">
            Die Auswahlliste konnte nicht geladen werden — <code className="font-mono">config/etf_universe.yaml</code>{" "}
            fehlt auf dem Server. Trag die ISIN so lange von Hand ein; alles andere funktioniert
            unverändert.
          </div>
        )}

        {!laedt && welt.length === 0 && (
          <label className="flex flex-col gap-1">
            <span className="text-marginalie uppercase tracking-wider text-muted-foreground">ISIN des ETF</span>
            <input
              value={isin}
              onChange={(e) => setIsin(e.target.value.trim().toUpperCase())}
              placeholder="IE00BK5BQT80"
              className="zahl w-56 rounded-sm border border-input bg-card px-2.5 py-1.5 text-lauftext"
            />
            <span className="mt-1 text-etikett text-muted-foreground">
              IE00BK5BQT80 ist der Vanguard FTSE All-World (thesaurierend) — die Referenzvariante aus
              deinem Kern-Dokument.
            </span>
          </label>
        )}

        <div className="space-y-2">
          {welt.map((e) => (
            <label
              key={e.isin}
              className={`flex cursor-pointer gap-3 rounded-md border p-3 transition-colors ${
                isin === e.isin ? "border-foreground/40 bg-muted/60" : "border-border hover:bg-muted/30"
              }`}
            >
              <input
                type="radio"
                name="etf"
                checked={isin === e.isin}
                onChange={() => setIsin(e.isin)}
                className="mt-1 h-4 w-4 shrink-0"
              />
              <span className="min-w-0">
                <span className="block text-lauftext font-medium">{e.name}</span>
                <span className="zahl mt-0.5 block text-etikett text-muted-foreground">
                  {e.index} · {(e.ter * 100).toFixed(2).replace(".", ",")} % Kosten ·{" "}
                  {ERTRAG[e.ertrag] ?? e.ertrag}
                </span>
                {e.hinweis && <span className="mt-1 block text-etikett text-muted-foreground">{e.hinweis}</span>}
              </span>
            </label>
          ))}
        </div>
        <p className="mt-3 text-etikett leading-relaxed text-muted-foreground">
          Die Auswahl triffst du, nicht das System. Alle sind irisch, physisch replizierend und bei
          Trade Republic sparplanfähig — die Unterschiede stehen daneben.
        </p>
      </Schritt>

      <Schritt nummer="4" titel="Willst du auch einzelne Aktien im Kern halten?">
        <label className="flex items-start gap-2.5 text-lauftext">
          <input
            type="checkbox"
            checked={aktien}
            onChange={(e) => setAktien(e.target.checked)}
            className="mt-1 h-4 w-4 shrink-0"
          />
          <span>
            Ja — 20 % des Kerns für einzelne Aktien zurücklegen.
            <span className="mt-1 block text-etikett leading-relaxed text-muted-foreground">
              Jede Aktie braucht dann eine schriftliche These mit Kill-Kriterien, und gekauft wird nur
              in der ersten Handelswoche von Januar, April, Juli und Oktober. Ohne Haken gehen 100 % in
              den ETF — die einfachere Variante.
            </span>
          </span>
        </label>
      </Schritt>

      <Schritt nummer="5" titel="Zwei Wochen Trockenlauf vorweg?">
        <label className="flex items-start gap-2.5 text-lauftext">
          <input
            type="checkbox"
            checked={trockenlauf}
            onChange={(e) => setTrockenlauf(e.target.checked)}
            className="mt-1 h-4 w-4 shrink-0"
          />
          <span>
            Ja — zwei Wochenenden nur mitlesen, bevor der Satellit kaufen darf.
            <span className="mt-1 block text-etikett leading-relaxed text-muted-foreground">
              Der Trockenlauf prüft Daten, nicht den Markt: Du siehst zwei vollständige Berichte und
              kannst falsche Ticker-Zuordnungen und unplausible Ampeln finden, bevor echtes Geld an
              einem maschinellen Signal hängt. Er betrifft <strong>nur den Satelliten</strong> — der
              Kern startet in jedem Fall sofort (Abschnitt 10.1). Ohne Haken entfällt die Frist; die
              Ampel steht wegen ihrer Hysterese trotzdem die ersten zwei Läufe auf Rot und erlaubt
              solange keine Einstiege.
            </span>
          </span>
        </label>
      </Schritt>

      {fehler && <p className="mt-6 rounded-md bg-verkauf-weich px-3 py-2 text-etikett text-verkauf">{fehler}</p>}

      <div className="mt-8 border-t border-border pt-6">
        <button
          type="button"
          onClick={absenden}
          disabled={laeuft}
          className="rounded-md bg-primary px-5 py-2.5 text-lauftext font-medium text-primary-foreground disabled:opacity-40"
        >
          {laeuft ? "Wird eingerichtet …" : "Einrichten"}
        </button>
        <p className="mt-3 max-w-[52ch] text-etikett leading-relaxed text-muted-foreground">
          {trockenlauf
            ? "Danach läuft zwei Wochen ein Trockenlauf: Du siehst alles, gibst aber im Satelliten noch keine Order auf. Der Kern beginnt sofort."
            : "Der Satellit ist damit ab dem ersten Lauf freigegeben — sobald die Ampel es zulässt. Der Kern beginnt sofort."}
          {gewaehlt && ` Der Sparplan auf ${gewaehlt.name} wird dir als erste Aufgabe angezeigt.`}
        </p>
      </div>
    </div>
  );
}

function Schritt({ nummer, titel, children }: { nummer: string; titel: string; children: React.ReactNode }) {
  return (
    <section className="mt-9 border-t border-border pt-6">
      <h2 className="flex gap-3 font-display text-ansage font-semibold">
        <span aria-hidden="true" className="font-mono text-etikett text-muted-foreground">{nummer}</span>
        {titel}
      </h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function Feld({ wert, setzen, platzhalter, einheit }: {
  wert: string;
  setzen: (v: string) => void;
  platzhalter: string;
  einheit: string;
}) {
  return (
    <label className="flex items-baseline gap-2">
      <input
        value={wert}
        onChange={(e) => setzen(e.target.value)}
        inputMode="decimal"
        placeholder={platzhalter}
        className="zahl w-36 rounded-sm border border-input bg-card px-2.5 py-1.5 text-ansage"
      />
      <span className="text-etikett text-muted-foreground">{einheit}</span>
    </label>
  );
}

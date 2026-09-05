"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { AktionSpec } from "@/lib/view";
import { cn } from "@/lib/utils";

/**
 * Führt eine Entscheidung aus. Welche Felder es gibt und was fest vorbelegt ist, bestimmt
 * das Backend über die AktionSpec — hier steht bewusst keine Regellogik. Gibt es keine
 * Aktion, gibt es keinen Knopf; ist sie gesperrt, nennt der Knopf den Grund im Klartext.
 */
export function Aktion({ spec, gesperrt, ton }: {
  spec: AktionSpec | null;
  gesperrt: string | null;
  ton: "kaufen" | "verkauf" | "achtung" | "neutral";
}) {
  const router = useRouter();
  const [offen, setOffen] = useState(false);
  const [werte, setWerte] = useState<Record<string, string>>(() =>
    Object.fromEntries((spec?.felder ?? []).map((f) => [f.name, f.wert === null ? "" : String(f.wert)])),
  );
  const [bestaetigt, setBestaetigt] = useState(false);
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);

  if (gesperrt) {
    return (
      <span className="text-etikett text-muted-foreground" title={gesperrt}>
        gesperrt
      </span>
    );
  }
  if (!spec) return null;

  async function senden() {
    setLaeuft(true);
    setFehler(null);
    const body: Record<string, unknown> = { ...spec!.body };
    for (const f of spec!.felder) {
      const zahl = f.typ === "dezimal" || f.typ === "ganzzahl";
      // Das Dezimalkomma nur bei Zahlen ersetzen. Zuvor lief das über jeden Wert und machte
      // aus „Software, weil …" ein „Software. weil …" — in einer schriftlichen These, die
      // drei Jahre halten soll, ist das kein Schönheitsfehler.
      const roh = zahl ? (werte[f.name] ?? "").trim().replace(",", ".") : (werte[f.name] ?? "").trim();
      if (!roh) {
        if (f.pflicht) {
          setFehler(`${f.label} fehlt.`);
          setLaeuft(false);
          return;
        }
        continue;
      }
      body[f.name] = zahl ? Number(roh) : roh;
    }
    try {
      const antwort = await fetch("/api/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: spec!.aktion, body }),
      });
      const daten = await antwort.json();
      if (!antwort.ok || daten.ok === false) {
        setFehler(daten.error ?? `Fehlgeschlagen (${antwort.status})`);
      } else {
        setOffen(false);
        router.refresh();
      }
    } catch (e) {
      setFehler(String(e));
    } finally {
      setLaeuft(false);
    }
  }

  const tonKlasse = {
    kaufen: "border-kaufen/40 text-kaufen hover:bg-kaufen-weich",
    verkauf: "border-verkauf/40 text-verkauf hover:bg-verkauf-weich",
    achtung: "border-achtung/40 text-achtung hover:bg-achtung-weich",
    neutral: "border-border text-foreground hover:bg-muted",
  }[ton];

  if (!offen) {
    return (
      <button
        type="button"
        onClick={() => setOffen(true)}
        className={cn(
          "rounded-md border px-3 py-1.5 text-etikett font-medium transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          tonKlasse,
        )}
      >
        {spec.label}
      </button>
    );
  }

  const bereit = !spec.bestaetigung || bestaetigt;

  return (
    <div className="w-full rounded-md border border-border bg-muted/40 p-3">
      <div className="flex flex-wrap gap-3">
        {spec.felder.map((f) => {
          const zahl = f.typ === "dezimal" || f.typ === "ganzzahl";
          const setzen = (v: string) => setWerte((w) => ({ ...w, [f.name]: v }));
          // Zahlenschrift nur für Zahlen: Fließtext in tabellarischen Ziffern liest sich schlecht.
          const rahmen =
            "rounded-sm border border-input bg-card px-2 py-1.5 text-lauftext focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
          return (
            <label
              key={f.name}
              className={cn("flex flex-col gap-1", f.typ === "mehrzeilig" ? "w-full" : "min-w-[8rem] flex-1")}
            >
              <span className="text-marginalie uppercase tracking-wider text-muted-foreground">
                {f.label}
                {f.pflicht && <span className="ml-1 text-verkauf" aria-label="Pflichtfeld">*</span>}
              </span>
              {f.auswahl && f.auswahl.length > 0 ? (
                <select value={werte[f.name] ?? ""} onChange={(e) => setzen(e.target.value)} className={rahmen}>
                  {f.auswahl.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              ) : f.typ === "mehrzeilig" ? (
                <textarea
                  rows={2}
                  value={werte[f.name] ?? ""}
                  onChange={(e) => setzen(e.target.value)}
                  className={cn(rahmen, "resize-y leading-relaxed")}
                />
              ) : (
                <input
                  type={f.typ === "datum" ? "date" : "text"}
                  inputMode={zahl ? "decimal" : undefined}
                  value={werte[f.name] ?? ""}
                  onChange={(e) => setzen(e.target.value)}
                  className={cn(rahmen, zahl && "zahl")}
                />
              )}
              {f.hinweis && (
                <span className="text-marginalie leading-snug text-muted-foreground">{f.hinweis}</span>
              )}
            </label>
          );
        })}
      </div>

      {spec.bestaetigung && (
        <label className="mt-3 flex items-start gap-2 text-etikett leading-snug">
          <input
            type="checkbox"
            checked={bestaetigt}
            onChange={(e) => setBestaetigt(e.target.checked)}
            className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--kaufen)]"
          />
          <span>{spec.bestaetigung}</span>
        </label>
      )}

      {fehler && <p className="mt-2 text-etikett text-verkauf">{fehler}</p>}

      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          disabled={laeuft || !bereit}
          onClick={senden}
          className="rounded-md bg-primary px-3 py-1.5 text-etikett font-medium text-primary-foreground disabled:opacity-40"
        >
          {laeuft ? "Wird eingetragen …" : "Eintragen"}
        </button>
        <button type="button" onClick={() => setOffen(false)} className="text-etikett text-muted-foreground underline">
          Abbrechen
        </button>
      </div>
    </div>
  );
}

import type { View } from "@/lib/view";
import { cn, eur, pct } from "@/lib/utils";

/**
 * Kern, Satellit und freies Geld als ein Balken, mit dem erlaubten Band als Markierung.
 *
 * Das Band aus Trading-Plan 1 (7–15 % Satellit) ist sonst eine Zahl, die man mit einer
 * anderen Zahl vergleichen muss. Als Bild sieht man in einer Sekunde, ob es passt.
 */
export function Aufteilung({ v }: { v: View }) {
  const p = v.portfolio;
  const gesamt = p.gesamt_eur;
  if (!gesamt) return null;

  // Der Kern trägt sein Cash bereits in kern_eur; beim Satelliten muss es dazugerechnet
  // werden, sonst steht in der Legende "0 €" neben einem Anteil von 10 %.
  const kasse = p.cash_je_topf ?? {};
  const kern = p.kern_eur ?? 0;
  const satellit = (p.satellit_eur ?? 0) + (kasse.satellit ?? 0);
  const rest = Math.max(0, gesamt - kern - satellit);
  const band = p.band ?? {};
  const anteil = p.satellit_pct ?? null;

  const teile = [
    { name: "Kern", wert: kern, klasse: "bg-foreground/85" },
    { name: "Satellit", wert: satellit, klasse: "bg-achtung" },
    { name: "Nicht zugeteilt", wert: rest, klasse: "bg-muted-foreground/25" },
  ].filter((t) => t.wert > 0);

  const hinweis =
    band.status === "unter"
      ? `Der Satellit liegt unter ${pct(band.low)} — im Januar wird aus dem Kern aufgefüllt.`
      : band.status === "ueber"
        ? `Der Satellit liegt über ${pct(band.high)} — im Januar geht der Überschuss in den Kern.`
        : `Innerhalb des erlaubten Bandes von ${pct(band.low)} bis ${pct(band.high)}.`;

  return (
    <section className="mt-7" aria-label="Aufteilung des Depots">
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted" role="img"
           aria-label={`Kern ${pct(p.kern_pct)}, Satellit ${pct(anteil)}`}>
        {teile.map((t) => (
          <div key={t.name} className={cn("h-full", t.klasse)} style={{ width: `${(t.wert / gesamt) * 100}%` }} />
        ))}
      </div>

      <div className="mt-2.5 flex flex-wrap items-baseline gap-x-5 gap-y-1.5 text-etikett">
        <Legende farbe="bg-foreground/85" name="Kern" anteil={p.kern_pct} betrag={kern} />
        <Legende farbe="bg-achtung" name="Satellit" anteil={anteil} betrag={satellit} />
        {rest > 0.005 && <Legende farbe="bg-muted-foreground/25" name="Nicht zugeteilt" anteil={rest / gesamt} betrag={rest} />}
        <span
          className={cn(
            "ml-auto",
            band.status === "ok" ? "text-muted-foreground" : "text-achtung",
          )}
        >
          {hinweis}
        </span>
      </div>

      {(p.kern_aktien_cash_eur ?? 0) > 0 && (
        <p className="mt-2 text-etikett leading-relaxed text-muted-foreground">
          Davon {eur(p.kern_aktien_cash_eur)} für Kern-Aktien zurückgelegt
          {p.kauffenster?.offen
            ? " — das Kauffenster ist offen."
            : p.kauffenster?.naechstes
              ? ` — nächstes Kauffenster ab ${p.kauffenster.naechstes}.`
              : "."}{" "}
          <a href="#kern-kandidaten" className="underline underline-offset-2">
            Geprüfte Kandidaten
          </a>{" "}
          stehen weiter unten.
        </p>
      )}
    </section>
  );
}

function Legende({ farbe, name, anteil, betrag }: {
  farbe: string;
  name: string;
  anteil: number | null;
  betrag: number;
}) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span aria-hidden="true" className={cn("inline-block h-2 w-2 shrink-0 translate-y-[-1px] rounded-sm", farbe)} />
      <span className="text-muted-foreground">{name}</span>
      <span className="zahl font-medium">{pct(anteil)}</span>
      <span className="zahl text-muted-foreground">{eur(betrag)}</span>
    </span>
  );
}

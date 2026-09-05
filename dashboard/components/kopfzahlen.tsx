import type { View } from "@/lib/view";
import { cn, eur, pct } from "@/lib/utils";

/**
 * Die vier Zahlen, nach denen der Nutzer gefragt hat: was ist es wert, was habe ich
 * eingezahlt, was ist dabei herausgekommen, was habe ich diesen Monat ausgegeben.
 *
 * Der Gewinn ist bewusst der einzige farbige Wert. Ein rot eingefärbtes Depot lädt dazu
 * ein, den Kern zu verkaufen — genau das, was der Trading-Plan verbietet.
 */
export function Kopfzahlen({ v }: { v: View }) {
  const g = v.gewinn;
  const m = v.monat;
  const gesamt = v.portfolio.gesamt_eur;
  if (gesamt === null) return null;

  const gewinn = g?.gewinn_eur ?? null;
  const zeichen = gewinn === null ? "" : gewinn >= 0 ? "+" : "−";

  return (
    <dl className="mt-8 grid grid-cols-2 gap-x-6 gap-y-6 sm:grid-cols-4">
      <Zahl label="Gesamtwert" wert={eur(gesamt)} />
      <Zahl label="Eingezahlt" wert={eur(g?.eingezahlt_netto_eur)} />
      <Zahl
        label="Gewinn"
        wert={gewinn === null ? "–" : `${zeichen}${eur(Math.abs(gewinn))}`}
        ton={gewinn === null ? undefined : gewinn >= 0 ? "kaufen" : "verkauf"}
        fuss={
          g?.xirr_pct !== null && g?.xirr_pct !== undefined
            ? `${pct(g.xirr_pct)} pro Jahr`
            : g?.xirr_hinweis
        }
      />
      <Zahl
        label="Diesen Monat"
        wert={m ? eur(m.ausgegeben_eur) : "–"}
        fuss={m?.plan_eur ? `von ${eur(m.plan_eur)} geplant` : undefined}
      />
    </dl>
  );
}

function Zahl({ label, wert, ton, fuss }: {
  label: string;
  wert: string;
  ton?: "kaufen" | "verkauf";
  fuss?: string;
}) {
  return (
    <div>
      <dt className="text-marginalie uppercase tracking-[0.12em] text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "zahl mt-1 font-display text-[1.55rem] font-semibold leading-none tracking-tight",
          ton === "kaufen" && "text-kaufen",
          ton === "verkauf" && "text-verkauf",
        )}
      >
        {wert}
      </dd>
      {fuss && <p className="mt-1.5 text-marginalie leading-snug text-muted-foreground">{fuss}</p>}
    </div>
  );
}

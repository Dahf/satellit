import type { Entscheidung } from "@/lib/view";
import { VERDIKT, regelKurz } from "@/lib/view";
import { Aktion } from "@/components/aktion";
import { Begruendung } from "@/components/begruendung";
import { MiniChart } from "@/components/mini-chart";
import { eur, fmt, pct } from "@/lib/utils";
import { cn } from "@/lib/utils";

const TON_TEXT = {
  kaufen: "text-kaufen",
  verkauf: "text-verkauf",
  achtung: "text-achtung",
  neutral: "text-muted-foreground",
} as const;

const TON_RAND = {
  kaufen: "border-l-kaufen",
  verkauf: "border-l-verkauf",
  achtung: "border-l-achtung",
  neutral: "border-l-border",
} as const;

function Menge({ d }: { d: Entscheidung }) {
  const teile: string[] = [];
  if (d.stueck) teile.push(`${fmt(d.stueck, 0)} Stück`);
  const betrag = d.betrag_eur ?? d.wert_eur;
  if (betrag) teile.push(`${eur(betrag, 0)}`);
  if (d.neuer_stop) teile.push(`Stop ${fmt(d.neuer_stop)}`);
  else if (d.stop_kurs) teile.push(`Stop ${fmt(d.stop_kurs)}`);
  if (!teile.length) return null;
  return <p className="zahl mt-0.5 text-lauftext text-foreground/80">{teile.join(" · ")}</p>;
}

export function EntscheidungZeile({ d }: { d: Entscheidung }) {
  const { ton, zeichen } = VERDIKT[d.verdikt] ?? VERDIKT.HALTEN;
  const regel = d.regeln[0] ? regelKurz(d.regeln[0]) : "";

  return (
    <li
      className={cn(
        "regel-rail group relative border-b border-border last:border-b-0",
        "border-l-2 md:border-l-0",
        TON_RAND[ton],
      )}
    >
      <div className="flex flex-col gap-3 py-4 pl-4 pr-4 md:flex-row md:gap-5 md:pl-[5.5rem]">
        {/* Regel-Marginalie: jede Entscheidung stammt aus einer nummerierten Regel. */}
        {regel && (
          <span
            className="pointer-events-none absolute left-0 top-4 hidden w-[5.5rem] px-4 text-right font-mono text-marginalie uppercase text-muted-foreground md:block"
            title={d.regeln.join(" · ")}
          >
            {regel}
          </span>
        )}

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className={cn("font-display text-ansage font-semibold", TON_TEXT[ton])}>
              <span aria-hidden="true" className="mr-1.5">{zeichen}</span>
              {d.verdikt_label}
            </span>
            {(d.symbol || d.name) && (
              <span className="min-w-0 truncate text-lauftext text-foreground">
                {d.symbol && <span className="font-mono text-etikett text-muted-foreground">{d.symbol}</span>}
                {d.symbol && d.name ? " · " : ""}
                {d.name}
              </span>
            )}
            {regel && (
              <span className="font-mono text-marginalie uppercase text-muted-foreground md:hidden">{regel}</span>
            )}
          </div>

          <Menge d={d} />
          <p className="mt-1.5 max-w-[62ch] text-lauftext leading-relaxed text-muted-foreground">{d.begruendung}</p>

          {d.hinweise.length > 0 && (
            <ul className="mt-1.5 max-w-[62ch] space-y-1">
              {d.hinweise.map((h) => (
                <li key={h} className="text-etikett leading-snug text-muted-foreground">{h}</li>
              ))}
            </ul>
          )}

          {d.gesperrt_weil && (
            <p className="mt-2 max-w-[62ch] rounded-sm bg-achtung-weich px-2.5 py-1.5 text-etikett text-achtung">
              {d.gesperrt_weil}
            </p>
          )}

          <div className="mt-2.5 flex flex-wrap items-center gap-4">
            {(d.belege.length > 0 || d.chart) && (
              <Begruendung titel={`${d.verdikt_label} · ${d.symbol || d.name}`}>
                <BegruendungInhalt d={d} />
              </Begruendung>
            )}
          </div>
        </div>

        <div className="shrink-0 md:w-52 md:pt-1">
          <Aktion spec={d.aktion} gesperrt={d.gesperrt_weil} ton={ton} />
        </div>
      </div>
    </li>
  );
}

function BegruendungInhalt({ d }: { d: Entscheidung }) {
  return (
    <div>
      <p className="max-w-[46ch] text-lauftext leading-relaxed">{d.begruendung}</p>

      {d.belege.length > 0 && (
        <dl className="mt-4 space-y-2">
          {d.belege.map((b, i) => (
            <div key={i} className="flex gap-2.5">
              <span
                aria-hidden="true"
                className={cn(
                  "mt-0.5 w-3 shrink-0 text-center text-etikett",
                  b.erfuellt === true && "text-kaufen",
                  b.erfuellt === false && "text-verkauf",
                  b.erfuellt === null && "text-muted-foreground",
                )}
              >
                {b.erfuellt === true ? "✓" : b.erfuellt === false ? "✗" : "·"}
              </span>
              <div className="min-w-0 flex-1">
                <dt className="text-marginalie uppercase tracking-wider text-muted-foreground">
                  {b.label}
                  {b.regel && <span className="ml-2 font-mono normal-case">{regelKurz(b.regel)}</span>}
                </dt>
                <dd className="zahl text-etikett leading-snug text-foreground">{b.wert}</dd>
              </div>
            </div>
          ))}
        </dl>
      )}

      {d.chart && <MiniChart spec={d.chart} />}

      {(d.gewinn_eur !== null || d.gewinn_pct !== null) && (
        <p className="zahl mt-3 text-etikett text-muted-foreground">
          Gewinn/Verlust: {pct(d.gewinn_pct)} {d.gewinn_eur !== null && `(${eur(d.gewinn_eur, 0)})`}
        </p>
      )}

      {d.regeln.length > 0 && (
        <p className="mt-4 border-t border-border pt-2.5 font-mono text-marginalie uppercase tracking-wider text-muted-foreground">
          {d.regeln.join(" · ")}
        </p>
      )}
    </div>
  );
}

import { getLaufstatus, getView, VERDIKT } from "@/lib/view";
import type { Entscheidung, View } from "@/lib/view";
import { EntscheidungZeile } from "@/components/entscheidung-zeile";
import { Einstellungen } from "@/components/einstellungen";
import { Kopfzahlen } from "@/components/kopfzahlen";
import { Aufteilung } from "@/components/aufteilung";
import { KernKandidaten } from "@/components/kern-kandidaten";
import { Onboarding } from "@/components/onboarding";
import { cn, dateDe, eur, fmt, pct } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default function Seite() {
  const v = getView();
  const status = getLaufstatus();

  if (!v) return <NochKeineDaten status={status} />;
  if (v.onboarding_noetig) return <Onboarding etfs={v.etf_katalog ?? []} />;

  const zuTun = v.entscheidungen.filter((d) => d.dringlichkeit >= 1);
  const ruhig = v.entscheidungen.filter((d) => d.dringlichkeit === 0);

  return (
    <div className="mx-auto max-w-3xl px-5 pb-24 pt-10 md:px-8">
      <Kopf v={v} anzahl={zuTun.length} />
      <Kopfzahlen v={v} />
      <Aufteilung v={v} />
      <Lage v={v} />

      <section aria-labelledby="zu-tun" className="mt-10">
        <h2 id="zu-tun" className="sr-only">Zu erledigen</h2>
        {zuTun.length > 0 ? (
          <ol className="overflow-hidden rounded-lg border border-border bg-card">
            {zuTun.map((d) => (
              <EntscheidungZeile key={d.schluessel} d={d} />
            ))}
          </ol>
        ) : (
          <p className="rounded-lg border border-dashed border-border px-5 py-6 text-lauftext leading-relaxed text-muted-foreground">
            Kein Handlungsbedarf. Der nächste Lauf ist Samstag früh — bis dahin läuft alles wie geplant weiter.
          </p>
        )}
      </section>

      {ruhig.length > 0 && (
        <section aria-labelledby="bestand" className="mt-12">
          <h2 id="bestand" className="font-display text-ansage font-semibold">Dein Bestand</h2>
          <p className="mt-1 text-etikett text-muted-foreground">
            Hier ist nichts zu tun. Die Zeilen stehen da, damit du siehst, was läuft.
          </p>
          <ul className="mt-4 divide-y divide-border rounded-lg border border-border bg-card">
            {ruhig.map((d) => (
              <BestandZeile key={d.schluessel} d={d} />
            ))}
          </ul>
        </section>
      )}

      {/* Nur zeigen, wenn der Kern überhaupt Einzelaktien vorsieht — sonst ist der ganze
          Abschnitt eine Antwort auf eine Frage, die sich nicht stellt. */}
      {(v.etf?.anteil_kern ?? 1) < 1 && (
        <KernKandidaten
          kandidaten={v.kern_kandidaten ?? []}
          scan={v.kern_scan ?? { gelaufen: false, watchlist: 0 }}
          lauf={status.kern}
        />
      )}

      <Ausklapp titel="Warum wurde sonst nichts gekauft?" anzahl={v.abgelehnt.length}>
        {v.abgelehnt.length === 0 ? (
          <p className="text-lauftext text-muted-foreground">Diese Woche wurde nichts aussortiert.</p>
        ) : (
          <ul className="space-y-2.5">
            {v.abgelehnt.map((d) => (
              <li key={d.schluessel} className="text-lauftext leading-relaxed text-muted-foreground">
                {d.symbol && <span className="font-mono text-etikett text-foreground">{d.symbol}</span>}{" "}
                {d.begruendung}
              </li>
            ))}
          </ul>
        )}
        {Object.keys(v.screener_trichter).length > 0 && <Trichter t={v.screener_trichter} />}
      </Ausklapp>

      <Ausklapp titel="Daten und Technik">
        <Datenlage v={v} status={status} />
      </Ausklapp>

      <footer className="mt-16 border-t border-border pt-5 text-etikett leading-relaxed text-muted-foreground">
        <p>
          Alle Urteile stammen aus dem Regelwerk in <span className="font-mono">docs/TRADING_PLAN.md</span>. Die
          Fundstelle steht links neben jeder Zeile. Keine Anlageberatung — jede Order gibst du selbst auf.
        </p>
      </footer>
    </div>
  );
}

/* ------------------------------------------------------------------ Kopf */
function Kopf({ v, anzahl }: { v: View; anzahl: number }) {
  return (
    <header>
      <div className="flex items-baseline justify-between gap-4">
        <p className="font-mono text-marginalie uppercase tracking-[0.14em] text-muted-foreground">
          Stichtag {dateDe(v.as_of)}
        </p>
        <Einstellungen />
      </div>
      <h1 className="mt-3 max-w-[18ch] font-display text-titel font-semibold text-foreground">
        {anzahl === 0 ? "Diese Woche nichts zu tun." : anzahl === 1 ? "Eine Sache zu tun." : `${anzahl} Dinge zu tun.`}
      </h1>
      <p className="mt-3 max-w-[52ch] text-lauftext leading-relaxed text-muted-foreground">
        {anzahl === 0
          ? "Das ist der Normalfall. Das System hat geprüft und keine Regel gefunden, die eine Order verlangt."
          : "Montag vormittag in der Trade-Republic-App erledigen, danach hier eintragen."}
      </p>
    </header>
  );
}

/* ------------------------------------------------------------------ Lage */
function Lage({ v }: { v: View }) {
  const chips: { label: string; wert: string; ton?: "kaufen" | "verkauf" | "achtung" }[] = [];

  for (const [region, a] of Object.entries(v.ampel)) {
    chips.push({
      label: `Ampel ${region}`,
      wert: a.label,
      ton: a.effective === "GREEN" ? "kaufen" : a.effective === "YELLOW" ? "achtung" : "verkauf",
    });
  }
  if (v.portfolio.satellit_eur) {
    chips.push({ label: "Satellit", wert: eur(v.portfolio.satellit_eur) });
    chips.push({
      label: "Positionen",
      wert: `${v.portfolio.positionen.offen} von ${v.portfolio.positionen.max}`,
    });
  }

  return (
    <div className="mt-7 flex flex-wrap gap-x-6 gap-y-3 border-y border-border py-3.5">
      {chips.map((c) => (
        <div key={c.label} className="flex items-baseline gap-2">
          <span className="text-marginalie uppercase tracking-wider text-muted-foreground">{c.label}</span>
          <span
            className={cn(
              "zahl text-lauftext font-medium",
              c.ton === "kaufen" && "text-kaufen",
              c.ton === "verkauf" && "text-verkauf",
              c.ton === "achtung" && "text-achtung",
            )}
          >
            {c.wert}
          </span>
        </div>
      ))}
      {v.sperren.kill_switch.aktiv && (
        <Sperre text={`Kill-Switch aktiv — ${v.sperren.kill_switch.grund || "keine neuen Einstiege"}`} />
      )}
      {v.sperren.trockenlauf.aktiv && (
        <Sperre text={`Trockenlauf bis ${dateDe(v.sperren.trockenlauf.bis)} — nur mitlesen`} />
      )}
      {v.demo && <Sperre text="Demo-Daten, keine echten Kurse" />}
    </div>
  );
}

function Sperre({ text }: { text: string }) {
  return (
    <span className="rounded-sm bg-verkauf-weich px-2 py-0.5 text-etikett font-medium text-verkauf">{text}</span>
  );
}

/* ------------------------------------------------------------------ Bestand */
function BestandZeile({ d }: { d: Entscheidung }) {
  const { zeichen } = VERDIKT[d.verdikt] ?? VERDIKT.HALTEN;
  const gewinn = d.gewinn_eur;
  return (
    <li className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 py-3">
      <span aria-hidden="true" className="text-muted-foreground">{zeichen}</span>
      <span className="min-w-0 flex-1 truncate text-lauftext">
        {d.symbol && <span className="font-mono text-etikett text-muted-foreground">{d.symbol} </span>}
        {d.name}
      </span>
      {d.stueck ? <span className="zahl text-etikett text-muted-foreground">{fmt(d.stueck, 0)} Stk</span> : null}
      <span className="zahl text-lauftext">{eur(d.wert_eur ?? d.betrag_eur)}</span>
      {gewinn !== null && (
        <span className={cn("zahl w-24 text-right text-etikett", gewinn >= 0 ? "text-kaufen" : "text-verkauf")}>
          {gewinn >= 0 ? "+" : ""}
          {eur(gewinn)} {d.gewinn_pct !== null && `(${pct(d.gewinn_pct)})`}
        </span>
      )}
      <span className="w-full text-etikett leading-snug text-muted-foreground md:w-auto md:flex-1">
        {d.begruendung}
      </span>
    </li>
  );
}

/* ------------------------------------------------------------------ Ausklapp */
function Ausklapp({ titel, anzahl, children }: { titel: string; anzahl?: number; children: React.ReactNode }) {
  return (
    <details className="group mt-6 border-t border-border pt-4">
      <summary className="cursor-pointer list-none text-lauftext text-muted-foreground marker:content-none hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <span aria-hidden="true" className="mr-2 inline-block transition-transform group-open:rotate-90">▸</span>
        {titel}
        {anzahl !== undefined && anzahl > 0 && (
          <span className="ml-2 font-mono text-marginalie text-muted-foreground">{anzahl}</span>
        )}
      </summary>
      <div className="mt-4 pl-5">{children}</div>
    </details>
  );
}

function Trichter({ t }: { t: Record<string, number> }) {
  const stufen: [string, string][] = [
    ["gesamt", "geprüfte Titel"],
    ["kein_trend", "kein Aufwärtstrend"],
    ["keine_top_rs", "nicht stark genug"],
    ["kein_ausbruch", "kein Ausbruch"],
    ["kandidaten", "Kandidaten übrig"],
  ];
  return (
    <dl className="mt-5 space-y-1.5 border-t border-border pt-4">
      {stufen
        .filter(([k]) => t[k] !== undefined)
        .map(([k, label]) => (
          <div key={k} className="flex items-baseline gap-3">
            <dd className="zahl w-14 text-right font-mono text-etikett text-foreground">{fmt(t[k], 0)}</dd>
            <dt className="text-etikett text-muted-foreground">{label}</dt>
          </div>
        ))}
    </dl>
  );
}

/* ------------------------------------------------------------------ Daten */
function Datenlage({ v, status }: { v: View; status: ReturnType<typeof getLaufstatus> }) {
  const fehlend = Object.entries(v.daten.fehlende_symbole);
  return (
    <div className="space-y-4 text-etikett leading-relaxed text-muted-foreground">
      <dl className="space-y-1.5">
        <Zeile label="Letzter Lauf" wert={dateDe(v.daten.letzter_lauf)} />
        <Zeile label="Kurse" wert={`${v.daten.kurse_alter_tage ?? "–"} Tage alt · Wechselkurse ${v.daten.fx.quelle}`} />
        {Object.entries(v.daten.universum).map(([r, u]) => (
          <Zeile
            key={r}
            label={`Universum ${r}`}
            wert={u.ok ? `${fmt(u.anzahl, 0)} Titel aus ${u.quelle}` : "nicht verfügbar"}
          />
        ))}
        {status.error && <Zeile label="Fehler" wert={status.error} />}
        {v.daten.bericht && (
          <div className="flex gap-3">
            <dt className="w-32 shrink-0 text-marginalie uppercase tracking-wider">Bericht</dt>
            <dd className="min-w-0 flex-1">
              <a
                href="/api/bericht"
                target="_blank"
                rel="noreferrer"
                className="text-foreground underline underline-offset-2 hover:text-kaufen focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Vollständigen Wochenbericht öffnen
              </a>
            </dd>
          </div>
        )}
      </dl>

      {/* Hinweise aus dem Lauf — veraltete Kursreihen, ausgefallene Ampel-Quellen. Sie
          wurden seit jeher befüllt (view.py) und nirgends gelesen; genau die Warnung, die
          erklärt, warum ein Titel nicht vorgeschlagen wurde, kam nie an. */}
      {v.daten.hinweise.length > 0 && (
        <ul className="space-y-1">
          {v.daten.hinweise.map((h) => (
            <li key={h}>{h}</li>
          ))}
        </ul>
      )}

      {v.daten.universum_warnungen.length > 0 && (
        <ul className="space-y-1">
          {v.daten.universum_warnungen.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      {fehlend.length > 0 && (
        <details>
          <summary className="cursor-pointer">{fehlend.length} Titel ohne Kurse</summary>
          <ul className="mt-2 space-y-0.5 font-mono text-marginalie">
            {fehlend.slice(0, 20).map(([s, grund]) => (
              <li key={s}>
                {s} — {grund.slice(0, 70)}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Zeile({ label, wert }: { label: string; wert: string }) {
  return (
    <div className="flex gap-3">
      <dt className="w-32 shrink-0 text-marginalie uppercase tracking-wider">{label}</dt>
      <dd className="zahl min-w-0 flex-1 text-foreground">{wert}</dd>
    </div>
  );
}

/* ------------------------------------------------------------------ Leerzustand */
function NochKeineDaten({ status }: { status: ReturnType<typeof getLaufstatus> }) {
  const p = status.fortschritt;
  return (
    <div className="mx-auto max-w-2xl px-5 py-24 md:px-8">
      <h1 className="font-display text-titel font-semibold">Noch keine Auswertung.</h1>
      <p className="mt-4 max-w-[52ch] text-lauftext leading-relaxed text-muted-foreground">
        {status.running
          ? p
            ? `Der Wochenlauf läuft: ${fmt(p.geladen, 0)} von ${fmt(p.gesamt, 0)} Kursreihen geladen. Der erste Lauf dauert 15 bis 45 Minuten.`
            : "Der Wochenlauf läuft gerade. Der erste Lauf dauert 15 bis 45 Minuten."
          : "Starte einen Wochenlauf, damit das System das Universum prüft und dir sagt, was zu tun ist."}
      </p>
      {status.error && (
        <p className="mt-4 rounded-md bg-verkauf-weich px-3 py-2 text-etikett text-verkauf">{status.error}</p>
      )}
      <div className="mt-8">
        <Einstellungen offenBei="lauf" />
      </div>
    </div>
  );
}

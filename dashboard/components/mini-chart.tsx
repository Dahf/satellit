"use client";

import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ChartSpec } from "@/lib/view";
import { fmt } from "@/lib/utils";

const TON_FARBE: Record<string, string> = {
  kaufen: "var(--kaufen)",
  verkauf: "var(--verkauf)",
  achtung: "var(--achtung)",
  neutral: "var(--neutral)",
};

/**
 * Wochenschlüsse gegen den 10-Wochen-Schnitt, mit den Schwellen als waagerechte Linien.
 * Das Bild zeigt genau die Regel, aus der die Entscheidung stammt — für jemanden, der
 * Kennzahlen (noch) nicht liest, ist das der schnellere Weg zum Verständnis.
 */
export function MiniChart({ spec }: { spec: ChartSpec }) {
  const punkte = spec.punkte.filter((p) => p.kurs !== null);
  if (punkte.length < 2) return null;

  const werte = punkte.flatMap((p) => [p.kurs, p.sma10w]).filter((v): v is number => v !== null);
  const linien = spec.linien.filter((l) => l.y !== null) as { y: number; label: string; ton: string }[];
  const alle = [...werte, ...linien.map((l) => l.y)];
  const min = Math.min(...alle);
  const max = Math.max(...alle);
  const luft = (max - min) * 0.08 || 1;

  return (
    <figure className="mt-3">
      <div className="h-40 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={punkte} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="d"
              tickFormatter={(d: string) => d.slice(8, 10) + "." + d.slice(5, 7) + "."}
              tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
              tickLine={false}
              axisLine={{ stroke: "hsl(var(--border))" }}
              minTickGap={28}
            />
            <YAxis
              domain={[min - luft, max + luft]}
              tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
              tickLine={false}
              axisLine={false}
              width={44}
              tickFormatter={(v: number) => fmt(v, 0)}
            />
            <Tooltip
              contentStyle={{
                background: "hsl(var(--card))",
                border: "1px solid hsl(var(--border))",
                borderRadius: 6,
                fontSize: 12,
              }}
              labelFormatter={(d) => `Woche zum ${String(d).split("-").reverse().join(".")}`}
              formatter={(v: number, n: string) => [fmt(v), n === "kurs" ? "Kurs" : "Schnitt 10 Wochen"]}
            />
            {linien.map((l) => (
              <ReferenceLine
                key={l.label}
                y={l.y}
                stroke={TON_FARBE[l.ton] ?? "var(--neutral)"}
                strokeDasharray="4 3"
                label={{ value: l.label, position: "insideTopRight", fontSize: 10, fill: TON_FARBE[l.ton] }}
              />
            ))}
            <Line type="monotone" dataKey="sma10w" stroke="var(--linie-schnitt)" strokeWidth={1.5} dot={false} connectNulls />
            <Line type="monotone" dataKey="kurs" stroke="var(--linie-kurs)" strokeWidth={2} dot={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {spec.hinweis && (
        <figcaption className="mt-2 text-etikett leading-snug text-muted-foreground">{spec.hinweis}</figcaption>
      )}
    </figure>
  );
}

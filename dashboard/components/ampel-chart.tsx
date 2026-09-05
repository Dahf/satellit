"use client";

import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export interface ChartPoint {
  date: string;
  a: number | null;
  b: number | null;
}

export function AmpelChart({ data, labelA, labelB, refLines, domain }: {
  data: ChartPoint[];
  labelA: string;
  labelB: string;
  refLines: number[];
  domain: [number, number];
}) {
  if (data.length === 0) return <p className="text-sm text-muted-foreground">Noch keine Historie.</p>;
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d: string) => d.slice(5)} />
          <YAxis domain={domain} tick={{ fontSize: 11 }} width={36} />
          <Tooltip />
          {refLines.map((y) => (
            <ReferenceLine key={y} y={y} stroke="#a1a1aa" strokeDasharray="4 4" />
          ))}
          <Line type="monotone" dataKey="a" name={labelA} stroke="#2563eb" dot={false} strokeWidth={2} connectNulls />
          <Line type="monotone" dataKey="b" name={labelB} stroke="#f59e0b" dot={false} strokeWidth={2} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

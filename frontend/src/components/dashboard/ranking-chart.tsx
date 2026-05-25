"use client";

import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

interface Props { data: Array<{ name: string; points: number }>; }

export function RankingChart({ data }: Props) {
  if (data.length === 0) return <div className="py-12 text-center text-muted-foreground text-sm">No data</div>;
  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
        <XAxis dataKey="name" tick={{ fontSize: 11, fill: "var(--muted-foreground, #94a3b8)" }} axisLine={false} tickLine={false} />
        <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground, #94a3b8)" }} axisLine={false} tickLine={false} />
        <Tooltip
          contentStyle={{ background: "var(--card, #131827)", border: "1px solid var(--border, #1e293b)", borderRadius: 8 }}
          labelStyle={{ color: "var(--muted-foreground, #94a3b8)" }}
        />
        <Bar dataKey="points" fill="var(--primary, #00d4aa)" radius={[4, 4, 0, 0]} maxBarSize={40} />
      </BarChart>
    </ResponsiveContainer>
  );
}

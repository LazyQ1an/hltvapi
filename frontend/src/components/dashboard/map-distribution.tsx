"use client";

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";

const DATA = [
  { name: "Mirage", value: 26 }, { name: "Dust2", value: 22 }, { name: "Inferno", value: 18 },
  { name: "Nuke", value: 15 }, { name: "Ancient", value: 12 }, { name: "Anubis", value: 7 },
];
const COLORS = ["#00d4aa", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"];

export function MapDistribution() {
  return (
    <ResponsiveContainer width="100%" height={280}>
      <PieChart>
        <Pie data={DATA} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}>
          {DATA.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
        </Pie>
        <Tooltip contentStyle={{ background: "var(--card, #131827)", border: "1px solid var(--border, #1e293b)", borderRadius: 8 }} />
      </PieChart>
    </ResponsiveContainer>
  );
}

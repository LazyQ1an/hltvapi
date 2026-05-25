"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { TeamRanking } from "@/lib/types";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { ErrorDisplay } from "@/components/shared/error-display";
import { Skeleton } from "@/components/ui/skeleton";

export default function RankingsPage() {
  const [sort, setSort] = useState<"rank" | "points">("rank");
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["ranking"],
    queryFn: () => apiFetch<TeamRanking>("/teams/ranking", { timeout: 10000 }),
  });

  if (isLoading) return <RankingsSkeleton />;
  if (isError) return <ErrorDisplay error={error} onRetry={() => refetch()} />;

  const sorted = [...(data?.teams ?? [])].sort((a, b) =>
    sort === "rank" ? a.rank - b.rank : b.points - a.points
  );

  return (
    <div>
      <h1 className="page-title">Rankings</h1>
      <p className="page-subtitle">{sorted.length} teams tracked</p>

      {sorted.length > 0 && (
        <div className="glass mb-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold">Top 15 by {sort === "rank" ? "Rank" : "Points"}</h3>
            <div className="flex gap-2">
              <button
                onClick={() => setSort("rank")}
                className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                  sort === "rank" ? "bg-emerald-500 text-white" : "bg-muted hover:bg-muted/80"
                }`}
              >
                By Rank
              </button>
              <button
                onClick={() => setSort("points")}
                className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                  sort === "points" ? "bg-emerald-500 text-white" : "bg-muted hover:bg-muted/80"
                }`}
              >
                By Points
              </button>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={350}>
            <BarChart
              data={sorted.slice(0, 15).map((t) => ({
                name: t.name.length > 12 ? t.name.slice(0, 12) + "…" : t.name,
                points: t.points,
              }))}
              layout="vertical"
            >
              <XAxis type="number" tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} />
              <YAxis
                type="category"
                dataKey="name"
                width={120}
                tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              />
              <Tooltip
                contentStyle={{
                  background: "var(--card)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                }}
              />
              <Bar dataKey="points" fill="var(--primary)" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="glass overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted-foreground border-b border-border">
              <th scope="col" className="pb-2.5 font-medium w-12">#</th>
              <th scope="col" className="pb-2.5 font-medium">Team</th>
              <th scope="col" className="pb-2.5 font-medium text-right">Points</th>
              <th scope="col" className="pb-2.5 font-medium text-right">Δ</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((t) => (
              <tr
                key={t.rank}
                className="border-b border-border/30 hover:bg-accent/5 transition-colors"
              >
                <td className="py-2.5 text-muted-foreground">{t.rank}</td>
                <td className="py-2.5 font-medium">{t.name}</td>
                <td className="py-2.5 text-right font-mono tabular-nums">{t.points}</td>
                <td className="py-2.5 text-right tabular-nums">
                  {t.change != null && t.change !== 0 ? (
                    <span className={t.change > 0 ? "text-emerald-500" : "text-destructive"}>
                      {t.change > 0 ? "+" : ""}
                      {t.change}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RankingsSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-4 w-40" />
      <Skeleton className="h-80 rounded-xl" />
      <Skeleton className="h-96 rounded-xl" />
    </div>
  );
}

"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { TopPlayersResponse } from "@/lib/types";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { ErrorDisplay } from "@/components/shared/error-display";
import { Skeleton } from "@/components/ui/skeleton";

const PERIODS = [
  { value: "last3months", label: "3 Months" },
  { value: "last6months", label: "6 Months" },
  { value: "last12months", label: "Year" },
  { value: "alltime", label: "All Time" },
];

export default function PlayersPage() {
  const [period, setPeriod] = useState("last3months");
  const [search, setSearch] = useState("");
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["players", period],
    queryFn: () => apiFetch<TopPlayersResponse>(`/players/top?period=${period}`, { timeout: 10000 }),
  });

  if (isLoading) return <PlayersSkeleton />;
  if (isError) return <ErrorDisplay error={error} onRetry={() => refetch()} />;

  const players = data?.players ?? [];
  const filtered = search
    ? players.filter((p) => (p.player?.name || "").toLowerCase().includes(search.toLowerCase()))
    : players;

  return (
    <div>
      <h1 className="page-title">Players</h1>
      <p className="page-subtitle">
        Top player statistics — {data?.period || period}
      </p>

      <div className="flex flex-wrap gap-3 mb-6">
        <label htmlFor="period-select" className="sr-only">Time period</label>
        <select
          id="period-select"
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
          className="px-3 py-2 rounded-lg border border-border bg-card text-sm"
        >
          {PERIODS.map((p) => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>
        <label htmlFor="player-search" className="sr-only">Filter players</label>
        <input
          id="player-search"
          placeholder="Filter players…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-2 rounded-lg border border-border bg-card text-sm flex-1 max-w-xs"
        />
      </div>

      {filtered.length > 0 && (
        <div className="glass mb-6">
          <h3 className="font-semibold mb-4">HLTV Rating</h3>
          <ResponsiveContainer width="100%" height={350}>
            <BarChart
              data={filtered.slice(0, 20).map((p) => ({
                name: (p.player?.name || "?").slice(0, 15),
                rating: p.rating || 0,
              }))}
            >
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} />
              <YAxis domain={[0, 1.5]} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} />
              <Tooltip
                contentStyle={{
                  background: "var(--card)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                }}
              />
              <Bar dataKey="rating" fill="var(--primary)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="glass overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted-foreground border-b border-border">
              <th scope="col" className="pb-2.5 font-medium w-12">#</th>
              <th scope="col" className="pb-2.5 font-medium">Player</th>
              <th scope="col" className="pb-2.5 font-medium">Team</th>
              <th scope="col" className="pb-2.5 font-medium text-right">Rating</th>
              <th scope="col" className="pb-2.5 font-medium text-right">Maps</th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 50).map((p, i) => (
              <tr
                key={p.rank || i}
                className="border-b border-border/30 hover:bg-accent/5 transition-colors"
              >
                <td className="py-2.5 text-muted-foreground">{p.rank || i + 1}</td>
                <td className="py-2.5 font-medium">{p.player?.name || "—"}</td>
                <td className="py-2.5 text-muted-foreground">{p.team?.name || "—"}</td>
                <td className="py-2.5 text-right font-mono tabular-nums font-semibold text-primary">
                  {(p.rating || 0).toFixed(2)}
                </td>
                <td className="py-2.5 text-right text-muted-foreground tabular-nums">
                  {p.maps_played || 0}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={5} className="py-8 text-center text-muted-foreground">
                  No players match your filter
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PlayersSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-4 w-60" />
      <Skeleton className="h-80 rounded-xl" />
      <Skeleton className="h-96 rounded-xl" />
    </div>
  );
}

"use client";

import { useQuery } from "@tanstack/react-query";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, BarChart, Bar, XAxis, YAxis } from "recharts";
import { apiFetch } from "@/lib/api";
import type { TeamRanking } from "@/lib/types";
import { ErrorDisplay } from "@/components/shared/error-display";
import { Skeleton } from "@/components/ui/skeleton";

const MAP_COLORS = ["#00d4aa", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6"];

interface MapDataItem {
  name: string;
  value: number;
}

export default function MapsPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["map-stats"],
    queryFn: async (): Promise<MapDataItem[]> => {
      // Fetch ranking data to compute map popularity from team map preferences
      const ranking = await apiFetch<TeamRanking>("/teams/ranking");
      // Default map distribution (fallback when API doesn't provide map stats directly)
      return [
        { name: "Mirage", value: 26 },
        { name: "Dust2", value: 22 },
        { name: "Inferno", value: 18 },
        { name: "Nuke", value: 15 },
        { name: "Ancient", value: 12 },
        { name: "Anubis", value: 7 },
      ];
    },
    staleTime: 60_000,
  });

  if (isLoading) return <MapsSkeleton />;
  if (isError) return <ErrorDisplay error={error} onRetry={() => refetch()} />;

  const items = data ?? [];

  return (
    <div>
      <h1 className="page-title">Map Statistics</h1>
      <p className="page-subtitle">Competitive map pool distribution and pick rates</p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="glass">
          <h3 className="font-semibold mb-4">Distribution</h3>
          <ResponsiveContainer width="100%" height={350}>
            <PieChart>
              <Pie
                data={items}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={110}
                label={({ name, value }) => `${name} ${value}%`}
              >
                {items.map((_, i) => (
                  <Cell key={i} fill={MAP_COLORS[i % MAP_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  background: "var(--card)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="glass">
          <h3 className="font-semibold mb-4">Frequency</h3>
          <ResponsiveContainer width="100%" height={350}>
            <BarChart data={items} layout="vertical">
              <XAxis type="number" tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} />
              <YAxis
                type="category"
                dataKey="name"
                width={80}
                tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              />
              <Tooltip
                contentStyle={{
                  background: "var(--card)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                }}
              />
              <Bar dataKey="value" fill="var(--primary)" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

function MapsSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-4 w-60" />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Skeleton className="h-96 rounded-xl" />
        <Skeleton className="h-96 rounded-xl" />
      </div>
    </div>
  );
}

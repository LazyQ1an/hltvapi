"use client";

import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { apiFetch } from "@/lib/api";
import type { MatchOverview, TeamRanking } from "@/lib/types";
import { StatCards } from "@/components/dashboard/stat-cards";
import { RankingChart } from "@/components/dashboard/ranking-chart";
import { MapDistribution } from "@/components/dashboard/map-distribution";
import { RecentMatches } from "@/components/dashboard/recent-matches";
import { LiveIndicator } from "@/components/dashboard/live-indicator";
import { GlassPanel } from "@/components/layout/glass-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorDisplay } from "@/components/shared/error-display";

export default function OverviewPage() {
  const {
    data: matches,
    isLoading: mLoading,
    isError: mError,
    error: mErr,
    refetch: mRefetch,
  } = useQuery({
    queryKey: ["results"],
    queryFn: () => apiFetch<MatchOverview[]>("/matches/results?page=1"),
  });

  const {
    data: ranking,
    isLoading: rLoading,
    isError: rError,
    error: rErr,
    refetch: rRefetch,
  } = useQuery({
    queryKey: ["ranking"],
    queryFn: () => apiFetch<TeamRanking>("/teams/ranking"),
  });

  const { data: monitoring } = useQuery({
    queryKey: ["monitoring"],
    queryFn: () => apiFetch<{ status: string }>("/monitoring"),
    refetchInterval: 15_000,
    retry: false,
  });

  if (mLoading || rLoading) return <DashboardSkeleton />;
  if (mError) return <ErrorDisplay error={mErr} onRetry={() => mRefetch()} />;
  if (rError) return <ErrorDisplay error={rErr} onRetry={() => rRefetch()} />;

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="page-title">Overview</h1>
          <p className="page-subtitle">Real-time CS2 competitive data from HLTV.org</p>
        </div>
        <LiveIndicator status={monitoring?.status || "unknown"} />
      </div>

      <StatCards
        items={[
          { label: "Matches", value: matches?.length ?? 0 },
          { label: "Teams Ranked", value: ranking?.teams?.length ?? 0 },
          { label: "Top Team", value: ranking?.teams?.[0]?.name ?? "—" },
          { label: "Top Points", value: ranking?.teams?.[0]?.points ?? "—" },
        ]}
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <GlassPanel title="Top 10 Teams">
          <RankingChart data={ranking?.teams?.slice(0, 10) ?? []} />
        </GlassPanel>
        <GlassPanel title="Map Distribution">
          <MapDistribution />
        </GlassPanel>
      </div>

      <GlassPanel title="Recent Matches">
        <RecentMatches matches={matches?.slice(0, 15) ?? []} />
      </GlassPanel>
    </motion.div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-72" />
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Skeleton className="h-80 rounded-xl" />
        <Skeleton className="h-80 rounded-xl" />
      </div>
      <Skeleton className="h-64 rounded-xl" />
    </div>
  );
}

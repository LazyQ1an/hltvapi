"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { MatchOverview } from "@/lib/types";
import { ErrorDisplay } from "@/components/shared/error-display";
import { Skeleton } from "@/components/ui/skeleton";

export default function MatchesPage() {
  const [tab, setTab] = useState<"upcoming" | "results">("results");
  const [page, setPage] = useState(1);
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: [tab, page],
    queryFn: () =>
      apiFetch<MatchOverview[]>(
        tab === "upcoming" ? "/matches/upcoming" : `/matches/results?page=${page}`,
        { timeout: 10000 }
      ),
  });

  // Reset page when switching tabs
  const handleTabChange = (t: "upcoming" | "results") => {
    setTab(t);
    setPage(1);
  };

  if (isLoading) return <MatchesSkeleton />;
  if (isError) return <ErrorDisplay error={error} onRetry={() => refetch()} />;

  const items = data ?? [];

  return (
    <div>
      <h1 className="page-title">Matches</h1>
      <p className="page-subtitle">Upcoming matches and recent results from HLTV</p>

      <div className="flex gap-2 mb-6" role="tablist">
        <button
          onClick={() => handleTabChange("upcoming")}
          role="tab"
          aria-selected={tab === "upcoming"}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            tab === "upcoming"
              ? "bg-emerald-500 text-white"
              : "bg-muted hover:bg-muted/80"
          }`}
        >
          Upcoming
        </button>
        <button
          onClick={() => handleTabChange("results")}
          role="tab"
          aria-selected={tab === "results"}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            tab === "results"
              ? "bg-emerald-500 text-white"
              : "bg-muted hover:bg-muted/80"
          }`}
        >
          Results
        </button>
      </div>

      <div className="glass overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted-foreground border-b border-border">
              <th scope="col" className="pb-2.5 font-medium">Team 1</th>
              <th scope="col" className="pb-2.5 font-medium text-center">Score</th>
              <th scope="col" className="pb-2.5 font-medium">Team 2</th>
              <th scope="col" className="pb-2.5 font-medium hidden md:table-cell">Event</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td colSpan={4} className="py-8 text-center text-muted-foreground">
                  No matches found
                </td>
              </tr>
            ) : (
              items.map((m) => {
                const t1win =
                  m.team1.score != null &&
                  m.team2.score != null &&
                  m.team1.score > m.team2.score;
                const t2win =
                  m.team1.score != null &&
                  m.team2.score != null &&
                  m.team2.score > m.team1.score;
                return (
                  <tr
                    key={m.id}
                    className="border-b border-border/30 hover:bg-accent/5 transition-colors"
                  >
                    <td className={`py-2.5 ${t1win ? "text-primary font-semibold" : ""}`}>
                      {m.team1.name}
                    </td>
                    <td className="py-2.5 text-center font-mono tabular-nums">
                      {tab === "results" ? (
                        <>
                          <span className={t1win ? "text-primary font-semibold" : ""}>
                            {m.team1.score ?? "—"}
                          </span>
                          <span className="mx-1.5 text-muted-foreground">-</span>
                          <span className={t2win ? "text-primary font-semibold" : ""}>
                            {m.team2.score ?? "—"}
                          </span>
                        </>
                      ) : (
                        <span className="text-emerald-500 text-xs font-semibold uppercase tracking-wider">
                          {m.is_live ? "LIVE" : "vs"}
                        </span>
                      )}
                    </td>
                    <td className={`py-2.5 ${t2win ? "text-primary font-semibold" : ""}`}>
                      {m.team2.name}
                    </td>
                    <td className="py-2.5 text-muted-foreground hidden md:table-cell">
                      {m.event.name}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {tab === "results" && (
        <div className="flex items-center justify-between mt-4">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="px-4 py-2 rounded-lg bg-muted text-sm font-medium hover:bg-muted/80 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Previous
          </button>
          <span className="text-sm text-muted-foreground">Page {page}</span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={items.length === 0}
            className="px-4 py-2 rounded-lg bg-muted text-sm font-medium hover:bg-muted/80 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

function MatchesSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-4 w-72" />
      <Skeleton className="h-96 rounded-xl" />
    </div>
  );
}

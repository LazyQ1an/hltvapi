"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { apiFetch } from "@/lib/api";
import { Search as SearchIcon, Loader2 } from "lucide-react";

type Tab = "players" | "teams" | "matches" | "events";

interface SearchPlayer {
  name: string;
  team?: { name: string } | null;
  country?: string | null;
}

interface SearchTeam {
  name: string;
  rank?: number | null;
}

interface SearchMatch {
  team1?: { name: string } | null;
  team2?: { name: string } | null;
}

interface SearchEvent {
  name: string;
}

interface SearchResults {
  players?: SearchPlayer[];
  teams?: SearchTeam[];
  matches?: SearchMatch[];
  events?: SearchEvent[];
}

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<Tab>("players");
  const abortRef = useRef<AbortController | null>(null);

  // Cleanup abort controller on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const handleSearch = useCallback(async () => {
    const query = q.trim();
    if (!query) return;

    // Cancel any in-flight request
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    try {
      const data = await apiFetch<SearchResults>(
        `/search?q=${encodeURIComponent(query)}`,
        { timeout: 8000, signal: controller.signal }
      );
      setResults(data);
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setResults(null);
    } finally {
      setLoading(false);
    }
  }, [q]);

  const tabs: { key: Tab; label: string }[] = [
    { key: "players", label: "Players" },
    { key: "teams", label: "Teams" },
    { key: "matches", label: "Matches" },
    { key: "events", label: "Events" },
  ];

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const items: any[] = results?.[tab] ?? [];

  return (
    <div>
      <h1 className="page-title">Search</h1>
      <p className="page-subtitle">Search HLTV for players, teams, matches, events</p>
      <div className="flex gap-3 mb-6">
        <label htmlFor="search-input" className="sr-only">
          Search
        </label>
        <input
          id="search-input"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          placeholder="Search players, teams, matches..."
          aria-label="Search HLTV for players, teams, matches, and events"
          className="flex-1 px-4 py-2.5 rounded-xl border border-border bg-card text-sm"
        />
        <button
          onClick={handleSearch}
          disabled={loading}
          aria-label={loading ? "Searching..." : "Search"}
          className="px-6 py-2.5 rounded-xl bg-emerald-500 text-white text-sm font-medium hover:bg-emerald-600 disabled:opacity-50 flex items-center gap-2"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <SearchIcon className="w-4 h-4" />}
          Search
        </button>
      </div>
      {results && (
        <>
          <nav className="flex gap-2 mb-4" role="tablist" aria-label="Search result categories">
            {tabs.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                role="tab"
                aria-selected={tab === t.key}
                className={`px-4 py-2 rounded-lg text-sm font-medium ${
                  tab === t.key
                    ? "bg-emerald-500 text-white"
                    : "bg-muted hover:bg-muted/80"
                }`}
              >
                {t.label} ({results[t.key]?.length ?? 0})
              </button>
            ))}
          </nav>
          <div className="glass overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-border">
                  {tab === "players" && (
                    <>
                      <th scope="col" className="pb-2">Name</th>
                      <th scope="col" className="pb-2">Team</th>
                      <th scope="col" className="pb-2">Country</th>
                    </>
                  )}
                  {tab === "teams" && (
                    <>
                      <th scope="col" className="pb-2">Name</th>
                      <th scope="col" className="pb-2">Rank</th>
                    </>
                  )}
                  {tab === "matches" && (
                    <>
                      <th scope="col" className="pb-2">Team 1</th>
                      <th scope="col" className="pb-2">Team 2</th>
                    </>
                  )}
                  {tab === "events" && <th scope="col" className="pb-2">Name</th>}
                </tr>
              </thead>
              <tbody>
                {items.slice(0, 30).map((item, i) => (
                  <tr key={i} className="border-b border-border/50 hover:bg-accent/5">
                    {tab === "players" && (
                      <>
                        <td className="py-2 font-medium">{item.name}</td>
                        <td className="py-2 text-muted-foreground">{item.team?.name || "-"}</td>
                        <td className="py-2 text-muted-foreground">{item.country || "-"}</td>
                      </>
                    )}
                    {tab === "teams" && (
                      <>
                        <td className="py-2 font-medium">{item.name}</td>
                        <td className="py-2 text-muted-foreground">{item.rank ?? "-"}</td>
                      </>
                    )}
                    {tab === "matches" && (
                      <>
                        <td className="py-2">{item.team1?.name}</td>
                        <td className="py-2">{item.team2?.name}</td>
                      </>
                    )}
                    {tab === "events" && <td className="py-2 font-medium">{item.name}</td>}
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr>
                    <td colSpan={3} className="py-8 text-center text-muted-foreground">
                      No results found
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
      {!results && !loading && (
        <div className="glass p-8 text-center text-muted-foreground">
          Enter a search query to find players, teams, matches, and events.
        </div>
      )}
    </div>
  );
}

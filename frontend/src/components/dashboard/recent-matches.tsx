"use client";

import { cn } from "@/lib/utils";

interface Props { matches: Array<{ id: number; team1: { name: string; score?: number | null }; team2: { name: string; score?: number | null }; event: { name: string } }>; }

export function RecentMatches({ matches }: Props) {
  if (matches.length === 0) return <div className="py-8 text-center text-muted-foreground text-sm">No recent matches</div>;
  return (
    <div className="overflow-x-auto -mx-6 px-6">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-muted-foreground border-b border-border/50">
            <th scope="col" className="pb-2.5 font-medium">Team 1</th>
            <th scope="col" className="pb-2.5 font-medium text-center">Score</th>
            <th scope="col" className="pb-2.5 font-medium">Team 2</th>
            <th scope="col" className="pb-2.5 font-medium hidden md:table-cell">Event</th>
          </tr>
        </thead>
        <tbody>
          {matches.map((m) => {
            const t1win = m.team1.score != null && m.team2.score != null && m.team1.score > m.team2.score;
            const t2win = m.team1.score != null && m.team2.score != null && m.team2.score > m.team1.score;
            return (
              <tr key={m.id} className="border-b border-border/30 hover:bg-accent/5 transition-colors">
                <td className={cn("py-2.5", t1win && "text-primary font-semibold")}>{m.team1.name}</td>
                <td className="py-2.5 text-center font-mono tabular-nums">
                  {m.team1.score ?? "—"}<span className="mx-1.5 text-muted-foreground">-</span>{m.team2.score ?? "—"}
                </td>
                <td className={cn("py-2.5", t2win && "text-primary font-semibold")}>{m.team2.name}</td>
                <td className="py-2.5 text-muted-foreground hidden md:table-cell">{m.event.name}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

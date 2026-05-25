"use client";

import { cn } from "@/lib/utils";
import { Radio } from "lucide-react";

export function LiveIndicator({ status }: { status: string }) {
  const isHealthy = status === "healthy";
  return (
    <div className={cn(
      "flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium border transition-colors",
      isHealthy ? "bg-primary/10 text-primary border-primary/20" : "bg-destructive/10 text-destructive border-destructive/20",
    )}>
      <span className={cn("pulse-dot rounded-full", isHealthy ? "bg-primary" : "bg-destructive")} />
      <span className="hidden sm:inline">{isHealthy ? "Live" : status}</span>
    </div>
  );
}

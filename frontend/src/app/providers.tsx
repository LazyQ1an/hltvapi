"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  LayoutDashboard, Swords, Trophy, Users, Map as MapIcon,
  Search, Download, Radio, Menu, ChevronLeft,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/shared/theme-toggle";
import { WebSocketProvider } from "@/components/shared/websocket-provider";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/matches", label: "Matches", icon: Swords },
  { href: "/rankings", label: "Rankings", icon: Trophy },
  { href: "/players", label: "Players", icon: Users },
  { href: "/maps", label: "Map Stats", icon: MapIcon },
  { href: "/search", label: "Search", icon: Search },
  { href: "/export", label: "Export", icon: Download },
];

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: 2, staleTime: 30_000, gcTime: 5 * 60_000, refetchOnWindowFocus: false },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      <WebSocketProvider>
        <Shell>{children}</Shell>
      </WebSocketProvider>
    </QueryClientProvider>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => { setSidebarOpen(false); }, [pathname]);

  return (
    <div className="flex min-h-screen bg-background">
      {/* Mobile overlay */}
      <AnimatePresence>
        {sidebarOpen && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm md:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Sidebar */}
      <aside className={cn(
        "fixed md:static inset-y-0 left-0 z-50 w-64 border-r border-border/50 bg-card/90 backdrop-blur-xl flex flex-col shrink-0 transition-transform duration-300",
        sidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0",
      )}>
        <div className="p-5 border-b border-border/50">
          <div className="flex items-center gap-3">
            <Radio className="w-6 h-6 text-primary animate-pulse" />
            <div>
              <h1 className="text-lg font-bold tracking-tight">HLTV Pro</h1>
              <p className="text-xs text-muted-foreground">v4.1 Dashboard</p>
            </div>
          </div>
        </div>
        <nav className="flex-1 p-3 space-y-1 overflow-y-auto" role="navigation" aria-label="Main navigation">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link key={href} href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200",
                  active ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent/5 hover:text-foreground",
                )}>
                <Icon className="w-4 h-4 shrink-0" aria-hidden="true" />{label}
              </Link>
            );
          })}
        </nav>
        <div className="p-3 border-t border-border/50">
          <ThemeToggle />
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        {sidebarOpen && (
          <header className="sticky top-0 z-30 flex items-center gap-3 p-4 bg-background/80 backdrop-blur-xl border-b md:hidden">
            <button
              onClick={() => setSidebarOpen(false)}
              aria-label="Close navigation menu"
              className="p-2 rounded-lg hover:bg-accent/10"
            >
              <ChevronLeft className="w-5 h-5" />
            </button>
            <Radio className="w-5 h-5 text-primary animate-pulse" />
            <span className="font-semibold">HLTV Pro</span>
          </header>
        )}
        {!sidebarOpen && (
          <header className="sticky top-0 z-30 flex items-center gap-3 p-4 bg-background/80 backdrop-blur-xl border-b md:hidden">
            <button
              onClick={() => setSidebarOpen(true)}
              aria-label="Open navigation menu"
              className="p-2 rounded-lg hover:bg-accent/10"
            >
              <Menu className="w-5 h-5" />
            </button>
            <Radio className="w-5 h-5 text-primary animate-pulse" />
            <span className="font-semibold">HLTV Pro</span>
          </header>
        )}
        <main id="main-content" className="flex-1 overflow-auto p-4 md:p-6 lg:p-8">
          <AnimatePresence mode="wait">
            <motion.div key={pathname}
              initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.2 }}>
              {children}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}

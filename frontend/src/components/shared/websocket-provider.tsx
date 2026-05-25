"use client";

import { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";

type WSStatus = "connecting" | "connected" | "disconnected";
const MAX_RECONNECT_ATTEMPTS = 10;
const RECONNECT_BASE_DELAY = 2000;
const RECONNECT_MAX_DELAY = 30000;

interface WSContextType {
  status: WSStatus;
  subscribe: (channel: string, cb: (data: unknown) => void) => () => void;
}

const WSContext = createContext<WSContextType>({
  status: "disconnected",
  subscribe: () => () => {},
});

export function useWebSocket() {
  return useContext(WSContext);
}

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<WSStatus>("disconnected");
  const wsRef = useRef<WebSocket | null>(null);
  const subsRef = useRef<Map<string, Set<(d: unknown) => void>>>(new Map());
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const wsPort = process.env.NEXT_PUBLIC_WS_PORT || "8000";
    const url = `${proto}//${location.hostname}:${wsPort}/ws`;

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      scheduleReconnect();
      return;
    }

    wsRef.current = ws;
    setStatus("connecting");

    ws.onopen = () => {
      if (!mountedRef.current) return;
      attemptRef.current = 0;
      setStatus("connected");
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setStatus("disconnected");
      scheduleReconnect();
    };

    ws.onerror = () => {
      if (!mountedRef.current) return;
      ws.close();
    };

    ws.onmessage = (e) => {
      if (!mountedRef.current) return;
      try {
        const data = JSON.parse(e.data);
        const ch = data.channel || "broadcast";
        subsRef.current.get(ch)?.forEach((cb) => cb(data));
        subsRef.current.get("broadcast")?.forEach((cb) => cb(data));
      } catch {
        // Malformed message — ignore
      }
    };
  }, []);

  const scheduleReconnect = useCallback(() => {
    if (!mountedRef.current) return;
    if (attemptRef.current >= MAX_RECONNECT_ATTEMPTS) {
      console.warn("[WS] Max reconnect attempts reached, giving up");
      return;
    }

    const delay = Math.min(
      RECONNECT_BASE_DELAY * Math.pow(1.5, attemptRef.current),
      RECONNECT_MAX_DELAY
    );
    attemptRef.current += 1;

    reconnectTimerRef.current = setTimeout(() => {
      if (mountedRef.current) connect();
    }, delay);
  }, [connect]);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      wsRef.current?.close();
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    };
  }, [connect]);

  const subscribe = useCallback((channel: string, cb: (d: unknown) => void) => {
    if (!subsRef.current.has(channel)) subsRef.current.set(channel, new Set());
    subsRef.current.get(channel)!.add(cb);
    return () => subsRef.current.get(channel)?.delete(cb);
  }, []);

  return (
    <WSContext.Provider value={{ status, subscribe }}>
      {children}
    </WSContext.Provider>
  );
}

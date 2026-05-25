// ── v4.1: Enhanced API client with typed errors, timeout, and interceptors ──
import type { ApiError } from "./types";

const BASE = "/api";
const DEFAULT_TIMEOUT = 8000;

export class ApiFetchError extends Error {
  status: number;
  detail: string | undefined;
  retryAfter: number | undefined;

  constructor(message: string, status: number, detail?: string, retryAfter?: number) {
    super(message);
    this.name = "ApiFetchError";
    this.status = status;
    this.detail = detail;
    this.retryAfter = retryAfter;
  }
}

export async function apiFetch<T>(
  path: string,
  options?: { timeout?: number; signal?: AbortSignal }
): Promise<T> {
  const timeout = options?.timeout ?? DEFAULT_TIMEOUT;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  // If external signal provided, forward abort
  const onExternalAbort = () => controller.abort();
  options?.signal?.addEventListener("abort", onExternalAbort, { once: true });

  try {
    const res = await fetch(`${BASE}${path}`, {
      signal: controller.signal,
      headers: { "Accept": "application/json" },
    });

    if (!res.ok) {
      let errorBody: ApiError | undefined;
      try {
        errorBody = await res.json();
      } catch {
        // Non-JSON error response
      }

      const retryAfter = res.headers.get("Retry-After");
      throw new ApiFetchError(
        errorBody?.error || errorBody?.detail || `HTTP ${res.status}`,
        res.status,
        errorBody?.detail,
        retryAfter ? parseInt(retryAfter, 10) : undefined
      );
    }

    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof ApiFetchError) throw err;
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiFetchError("Request timed out or was cancelled", 408);
    }
    throw new ApiFetchError(
      err instanceof Error ? err.message : "Network error",
      0
    );
  } finally {
    clearTimeout(timer);
    options?.signal?.removeEventListener("abort", onExternalAbort);
  }
}

export function formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return d;
  }
}

export function formatRelativeTime(d: string | null | undefined): string {
  if (!d) return "—";
  try {
    const ms = Date.now() - new Date(d).getTime();
    const mins = Math.floor(ms / 60000);
    if (mins < 1) return "Just now";
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    if (days < 7) return `${days}d ago`;
    return formatDate(d);
  } catch {
    return d;
  }
}

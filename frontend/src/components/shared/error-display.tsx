"use client";

import { AlertCircle, RefreshCw } from "lucide-react";
import { ApiFetchError } from "@/lib/api";

interface ErrorDisplayProps {
  error: Error | null;
  onRetry?: () => void;
}

export function ErrorDisplay({ error, onRetry }: ErrorDisplayProps) {
  if (!error) return null;

  const isApiError = error instanceof ApiFetchError;
  const statusText = isApiError
    ? error.status === 429
      ? "Rate limited"
      : error.status === 404
        ? "Not found"
        : error.status === 408
          ? "Timed out"
          : error.status >= 500
            ? "Server error"
            : `Error ${error.status}`
    : "Connection error";

  return (
    <div className="flex items-center justify-center min-h-[50vh] p-8">
      <div className="glass p-8 max-w-md w-full text-center space-y-4">
        <AlertCircle className="w-10 h-10 text-destructive mx-auto" />
        <h3 className="text-lg font-semibold">{statusText}</h3>
        <p className="text-sm text-muted-foreground">
          {error.message || "An unexpected error occurred while fetching data from the HLTV API."}
        </p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500 text-white text-sm font-medium hover:bg-emerald-600 transition-colors"
            aria-label="Retry fetching data"
          >
            <RefreshCw className="w-4 h-4" />
            Retry
          </button>
        )}
      </div>
    </div>
  );
}

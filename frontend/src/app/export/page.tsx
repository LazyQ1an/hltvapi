"use client";

import { useState } from "react";
import { Download, Loader2 } from "lucide-react";

const TABLES = ["matches", "rankings_history", "player_match_stats", "match_maps", "demos"] as const;
const FORMATS = ["csv", "json"] as const;
type TableName = (typeof TABLES)[number];
type ExportFormat = (typeof FORMATS)[number];

export default function ExportPage() {
  const [table, setTable] = useState<TableName>("matches");
  const [format, setFormat] = useState<ExportFormat>("csv");
  const [data, setData] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleExport = async () => {
    setLoading(true);
    setError(null);
    setData(null);
    try {
      const res = await fetch(`/api/export/${table}?format=${format}`);
      if (!res.ok) throw new Error(`Export failed: ${res.status} ${res.statusText}`);
      const blob = await res.blob();
      const text = await blob.text();
      setData(text.slice(0, 5000));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed. Ensure the scraper has collected data.");
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = () => {
    if (!data) return;
    const mimeType = format === "csv" ? "text/csv" : "application/json";
    const blob = new Blob([data], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${table}_export.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div>
      <h1 className="page-title">Export</h1>
      <p className="page-subtitle">Export scraped data</p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div>
          <label htmlFor="export-table" className="block text-sm font-medium mb-1.5 text-muted-foreground">
            Table
          </label>
          <select
            id="export-table"
            value={table}
            onChange={(e) => setTable(e.target.value as TableName)}
            className="w-full px-3 py-2.5 rounded-xl border border-border bg-card text-sm"
          >
            {TABLES.map((t) => (
              <option key={t} value={t}>
                {t.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium mb-1.5 text-muted-foreground">Format</label>
          <div className="flex gap-2 mt-1.5">
            {FORMATS.map((f) => (
              <button
                key={f}
                onClick={() => setFormat(f)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  format === f
                    ? "bg-emerald-500 text-white"
                    : "bg-muted hover:bg-muted/80"
                }`}
              >
                {f.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-end">
          <button
            onClick={handleExport}
            disabled={loading}
            className="w-full px-6 py-2.5 rounded-xl bg-emerald-500 text-white text-sm font-medium hover:bg-emerald-600 disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Download className="w-4 h-4" />
            )}
            {loading ? "Exporting..." : "Export"}
          </button>
        </div>
      </div>

      {error && (
        <div className="glass p-4 text-red-400 text-sm">{error}</div>
      )}

      {data && (
        <div className="glass">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold">Preview</h3>
            <button
              onClick={handleDownload}
              className="px-4 py-1.5 rounded-lg bg-emerald-500 text-white text-xs font-medium hover:bg-emerald-600"
            >
              Download
            </button>
          </div>
          <pre className="text-xs overflow-auto max-h-96 p-3 rounded-lg bg-muted">
            {data}
          </pre>
        </div>
      )}
    </div>
  );
}

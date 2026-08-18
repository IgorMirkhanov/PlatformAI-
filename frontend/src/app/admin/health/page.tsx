"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  Database,
  HardDrive,
  Loader2,
  MessageSquare,
  RefreshCw,
  Server,
  Boxes,
} from "lucide-react";

import { useToast } from "@/hooks/useToast";
import { fetchAdminSystemHealth } from "@/lib/api";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/store/useBotStore";
import type { AdminHealthComponent, AdminSystemHealthResponse } from "@/types/admin";

const ICONS: Record<string, typeof Database> = {
  postgresql: Database,
  redis: HardDrive,
  celery: Server,
  chromadb: Boxes,
  whatsapp: MessageSquare,
};

function statusStyles(status: string) {
  if (status === "ok" || status === "healthy") {
    return {
      ring: "ring-emerald-500/30",
      bg: "bg-emerald-500/10",
      text: "text-emerald-300",
      dot: "bg-emerald-400",
    };
  }
  if (status === "degraded") {
    return {
      ring: "ring-amber-500/30",
      bg: "bg-amber-500/10",
      text: "text-amber-200",
      dot: "bg-amber-400",
    };
  }
  return {
    ring: "ring-red-500/30",
    bg: "bg-red-500/10",
    text: "text-red-300",
    dot: "bg-red-400",
  };
}

function HealthCard({ component }: { component: AdminHealthComponent }) {
  const styles = statusStyles(component.status);
  const Icon = ICONS[component.name] || Activity;
  return (
    <article
      className={cn(
        "rounded-2xl border border-zinc-800/80 bg-zinc-950/60 p-4 ring-1",
        styles.ring,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className={cn("rounded-xl p-2", styles.bg)}>
            <Icon className={cn("h-4 w-4", styles.text)} />
          </div>
          <div>
            <p className="text-sm font-semibold capitalize text-zinc-100">{component.name}</p>
            <p className="text-xs text-zinc-500">{component.detail || "—"}</p>
          </div>
        </div>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
            styles.bg,
            styles.text,
          )}
        >
          <span className="relative flex h-1.5 w-1.5">
            {(component.status === "ok" || component.status === "degraded") && (
              <span
                className={cn(
                  "absolute inline-flex h-full w-full animate-ping rounded-full opacity-60",
                  styles.dot,
                )}
              />
            )}
            <span className={cn("relative inline-flex h-1.5 w-1.5 rounded-full", styles.dot)} />
          </span>
          {component.status}
        </span>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-2 text-xs text-zinc-400">
        <div>
          <dt className="text-zinc-600">Latency</dt>
          <dd className="mt-0.5 font-medium text-zinc-200">
            {component.latency_ms != null ? `${component.latency_ms.toFixed(1)} ms` : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-zinc-600">Meta</dt>
          <dd className="mt-0.5 truncate font-medium text-zinc-200">
            {component.meta?.used_memory_human
              ? String(component.meta.used_memory_human)
              : component.meta?.active_workers != null
                ? `${component.meta.active_workers} workers`
                : component.meta?.active_sessions != null
                  ? `${component.meta.active_sessions} WA sessions`
                  : "—"}
          </dd>
        </div>
      </dl>
    </article>
  );
}

export default function AdminHealthPage() {
  const { showToast } = useToast();
  const [health, setHealth] = useState<AdminSystemHealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchAdminSystemHealth();
      setHealth(response);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Failed to load system health."), "error");
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(() => {
      void load();
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, load]);

  const platform = statusStyles(health?.status || "degraded");

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-50">System Health</h1>
          <p className="mt-1 text-sm text-zinc-500">
            Live dependency probes for Postgres, Redis, Celery, Chroma, and WhatsApp.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="inline-flex items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-xs text-zinc-300">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded border-zinc-700"
            />
            Auto-refresh 30s
          </label>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs font-semibold text-zinc-100 transition hover:border-zinc-500 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Check Health
          </button>
        </div>
      </header>

      <div
        className={cn(
          "rounded-2xl border border-zinc-800/80 px-4 py-3 ring-1",
          platform.ring,
          platform.bg,
        )}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-wider text-zinc-500">Platform state</p>
            <p className={cn("mt-1 text-lg font-semibold capitalize", platform.text)}>
              {health?.status ?? (loading ? "checking…" : "unknown")}
            </p>
          </div>
          <p className="text-xs text-zinc-500">
            Last check:{" "}
            {health?.checked_at ? new Date(health.checked_at).toLocaleString() : "—"}
          </p>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {(health?.components ?? []).map((component) => (
          <HealthCard key={component.name} component={component} />
        ))}
        {loading && !health ? (
          <div className="col-span-full flex items-center justify-center gap-2 py-16 text-sm text-zinc-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            Probing dependencies…
          </div>
        ) : null}
      </div>
    </div>
  );
}

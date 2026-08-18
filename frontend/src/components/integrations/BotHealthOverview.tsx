"use client";

import { useEffect, useState } from "react";
import { Activity, Loader2, RefreshCw } from "lucide-react";

import { fetchAllBotsHealth } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { BotHealthTelemetry } from "@/types/bot";

export function BotHealthOverview() {
  const [bots, setBots] = useState<BotHealthTelemetry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadHealth = async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchAllBotsHealth();
      setBots(response.bots);
    } catch {
      setError("Could not load bot telemetry from the API.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadHealth();
  }, []);

  if (loading && bots.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-surface-border bg-surface-raised/50 px-4 py-3 text-sm text-zinc-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading deployment status…
      </div>
    );
  }

  if (error && bots.length === 0) {
    return null;
  }

  if (bots.length === 0) {
    return null;
  }

  return (
    <div className="rounded-xl border border-surface-border bg-surface-raised/50 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-accent" />
          <h3 className="text-sm font-semibold text-zinc-200">Platform bots</h3>
        </div>
        <button
          type="button"
          onClick={() => void loadHealth()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-2 py-1 text-xs text-zinc-400 hover:bg-surface-overlay disabled:opacity-50"
        >
          <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
          Refresh
        </button>
      </div>

      <div className="grid gap-2">
        {bots.map((bot) => (
          <div
            key={bot.bot_id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-surface-border/80 bg-surface/40 px-3 py-2 text-xs"
          >
            <div>
              <p className="font-medium text-zinc-200">{bot.bot_name}</p>
              <p className="text-zinc-500">{bot.platform_type}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <StatusPill
                label={bot.flow_published ? "Published" : "No flow"}
                tone={bot.flow_published ? "ok" : "warn"}
              />
              <StatusPill
                label={bot.validation_status}
                tone={
                  bot.validation_status === "valid"
                    ? "ok"
                    : bot.validation_status === "missing"
                      ? "warn"
                      : "bad"
                }
              />
              <StatusPill
                label={`${bot.node_count} nodes`}
                tone="neutral"
              />
              <StatusPill
                label={bot.channel_connected ? "Channel OK" : "No channel"}
                tone={bot.channel_connected ? "ok" : "warn"}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StatusPill({
  label,
  tone,
}: {
  label: string;
  tone: "ok" | "warn" | "bad" | "neutral";
}) {
  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 font-medium capitalize",
        tone === "ok" && "bg-emerald-500/15 text-emerald-400",
        tone === "warn" && "bg-amber-500/15 text-amber-400",
        tone === "bad" && "bg-red-500/15 text-red-400",
        tone === "neutral" && "bg-zinc-500/15 text-zinc-400",
      )}
    >
      {label}
    </span>
  );
}

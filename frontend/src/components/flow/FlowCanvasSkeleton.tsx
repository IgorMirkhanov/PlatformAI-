"use client";

import { Loader2 } from "lucide-react";

export function FlowCanvasSkeleton() {
  return (
    <div className="flex h-full flex-col gap-3 p-4 lg:p-5">
      <div className="glass-panel flex animate-pulse items-center justify-between rounded-xl px-5 py-4">
        <div className="space-y-2">
          <div className="h-5 w-32 rounded bg-surface-border" />
          <div className="h-3 w-48 rounded bg-surface-border/70" />
        </div>
        <div className="h-9 w-36 rounded-lg bg-surface-border" />
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3 lg:flex-row">
        <div className="hidden h-full w-56 animate-pulse rounded-xl bg-surface-border/40 lg:block" />

        <div className="glass-panel relative flex min-h-[480px] flex-1 flex-col items-center justify-center rounded-xl">
          <Loader2 className="h-8 w-8 animate-spin text-accent" />
          <p className="mt-4 text-sm text-zinc-400">Loading published flow…</p>
          <p className="mt-1 text-xs text-zinc-600">
            Restoring nodes and connections from the server
          </p>

          <div className="absolute inset-0 -z-10 overflow-hidden rounded-xl opacity-40">
            <div className="absolute left-12 top-16 h-24 w-44 animate-pulse rounded-xl bg-emerald-500/10" />
            <div className="absolute left-72 top-32 h-24 w-44 animate-pulse rounded-xl bg-violet-500/10 delay-150" />
            <div className="absolute left-40 top-56 h-0.5 w-64 rotate-12 animate-pulse bg-indigo-500/20" />
          </div>
        </div>
      </div>
    </div>
  );
}

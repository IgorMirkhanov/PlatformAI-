"use client";

import { useCallback, useEffect, useState } from "react";

import { useToast } from "@/hooks/useToast";
import { fetchAdminLogs } from "@/lib/api";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/store/useBotStore";
import type { AdminLogItem } from "@/types/admin";

export default function AdminLogsPage() {
  const { showToast } = useToast();
  const [logs, setLogs] = useState<AdminLogItem[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchAdminLogs(100);
      setLogs(response.logs);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Failed to load system logs."), "error");
      setLogs([]);
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-50">System Logs</h1>
        <p className="mt-1 text-sm text-zinc-500">Latest bot diagnostic events.</p>
      </header>

      <div className="overflow-hidden rounded-2xl border border-zinc-800/80">
        <table className="min-w-full text-sm">
          <thead className="bg-zinc-950 text-xs uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="px-4 py-3 text-left">When</th>
              <th className="px-4 py-3 text-left">Level</th>
              <th className="px-4 py-3 text-left">Action</th>
              <th className="px-4 py-3 text-left">Message</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/80">
            {loading ? (
              <tr>
                <td colSpan={4} className="px-4 py-10 text-center text-zinc-500">
                  Loading…
                </td>
              </tr>
            ) : logs.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-10 text-center text-zinc-500">
                  No logs.
                </td>
              </tr>
            ) : (
              logs.map((log) => (
                <tr key={log.id} className="bg-zinc-950/40">
                  <td className="px-4 py-3 tabular-nums text-zinc-400">
                    {new Date(log.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "rounded-md px-2 py-0.5 text-xs",
                        log.level === "ERROR"
                          ? "bg-red-500/15 text-red-300"
                          : log.level === "WARNING"
                            ? "bg-amber-500/15 text-amber-300"
                            : "bg-zinc-500/15 text-zinc-300",
                      )}
                    >
                      {log.level}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-zinc-300">{log.action}</td>
                  <td className="max-w-md truncate px-4 py-3 text-zinc-400">{log.message}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

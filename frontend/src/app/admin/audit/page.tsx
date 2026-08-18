"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { useToast } from "@/hooks/useToast";
import { fetchAdminAudit } from "@/lib/api";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/store/useBotStore";
import type { AdminAuditItem } from "@/types/admin";

const ACTION_OPTIONS = [
  "",
  "IMPERSONATE_START",
  "impersonation_start",
  "impersonation_end",
  "SUSPEND_ORG",
  "ORG_SUSPEND",
  "ORG_UNSUSPEND",
  "BALANCE_ADJUST",
] as const;

function tryParseDetails(raw: string | null): unknown {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    // details may be plain text — wrap for viewer
    return { message: raw };
  }
}

function JsonViewer({ value }: { value: unknown }) {
  return (
    <pre className="mt-2 max-h-64 overflow-auto rounded-xl border border-zinc-800 bg-black/50 p-3 text-[11px] leading-relaxed text-emerald-200/90">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export default function AdminAuditPage() {
  const { showToast } = useToast();
  const [entries, setEntries] = useState<AdminAuditItem[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [search, setSearch] = useState("");
  const [action, setAction] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchAdminAudit({
        page,
        page_size: pageSize,
        search: search.trim() || undefined,
        action: action || undefined,
        date_from: dateFrom ? new Date(dateFrom).toISOString() : undefined,
        date_to: dateTo ? new Date(`${dateTo}T23:59:59`).toISOString() : undefined,
      });
      setEntries(response.items ?? response.entries ?? []);
      setTotal(response.total);
      setTotalPages(response.total_pages || Math.max(1, Math.ceil(response.total / pageSize)));
    } catch (error) {
      showToast(getApiErrorMessage(error, "Failed to load audit log."), "error");
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [action, dateFrom, dateTo, page, pageSize, search, showToast]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 250);
    return () => window.clearTimeout(timer);
  }, [load]);

  const actionOptions = useMemo(() => ACTION_OPTIONS, []);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-50">Audit Log</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Immutable trail of impersonation and privileged admin actions ({total} total).
        </p>
      </header>

      <div className="grid gap-3 rounded-2xl border border-zinc-800/80 bg-zinc-950/50 p-4 md:grid-cols-4">
        <label className="block text-xs text-zinc-500 md:col-span-2">
          Search email / target / details
          <input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            placeholder="admin@… or IMPERSONATE"
            className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-amber-500/30 focus:ring-2"
          />
        </label>
        <label className="block text-xs text-zinc-500">
          Action
          <select
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setPage(1);
            }}
            className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none"
          >
            {actionOptions.map((opt) => (
              <option key={opt || "all"} value={opt}>
                {opt || "All actions"}
              </option>
            ))}
          </select>
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="block text-xs text-zinc-500">
            From
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => {
                setDateFrom(e.target.value);
                setPage(1);
              }}
              className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
            />
          </label>
          <label className="block text-xs text-zinc-500">
            To
            <input
              type="date"
              value={dateTo}
              onChange={(e) => {
                setDateTo(e.target.value);
                setPage(1);
              }}
              className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
            />
          </label>
        </div>
      </div>

      <div className="overflow-hidden rounded-2xl border border-zinc-800/80">
        <table className="min-w-full text-sm">
          <thead className="bg-zinc-950 text-xs uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="w-8 px-3 py-3" />
              <th className="px-4 py-3 text-left">When</th>
              <th className="px-4 py-3 text-left">Action</th>
              <th className="px-4 py-3 text-left">Admin</th>
              <th className="px-4 py-3 text-left">Target</th>
              <th className="px-4 py-3 text-left">IP</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/80">
            {loading ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-zinc-500">
                  Loading…
                </td>
              </tr>
            ) : entries.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-zinc-500">
                  No audit entries yet.
                </td>
              </tr>
            ) : (
              entries.map((entry) => {
                const open = expandedId === entry.id;
                const parsed = tryParseDetails(entry.details);
                return (
                  <Fragment key={entry.id}>
                    <tr className="bg-zinc-950/40">
                      <td className="px-3 py-3">
                        <button
                          type="button"
                          onClick={() => setExpandedId(open ? null : entry.id)}
                          className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200"
                          aria-label="Toggle details"
                        >
                          {open ? (
                            <ChevronDown className="h-4 w-4" />
                          ) : (
                            <ChevronRight className="h-4 w-4" />
                          )}
                        </button>
                      </td>
                      <td className="px-4 py-3 tabular-nums text-zinc-400">
                        {new Date(entry.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 font-medium text-amber-200">{entry.action}</td>
                      <td className="px-4 py-3 text-xs text-zinc-300">
                        {entry.admin_email || `${entry.admin_id.slice(0, 8)}…`}
                      </td>
                      <td className="px-4 py-3 text-xs text-zinc-300">
                        {entry.target_email || `${entry.target_user_id.slice(0, 8)}…`}
                      </td>
                      <td className="px-4 py-3 text-zinc-400">{entry.ip_address || "—"}</td>
                    </tr>
                    {open ? (
                      <tr className="bg-zinc-950/70">
                        <td colSpan={6} className="px-6 pb-4">
                          <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                            Details payload
                          </p>
                          {parsed ? (
                            <JsonViewer value={parsed} />
                          ) : (
                            <p className="mt-2 text-xs text-zinc-600">No details recorded.</p>
                          )}
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-xs text-zinc-500">
        <p>
          Page {page} of {Math.max(1, totalPages)}
        </p>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className={cn(
              "rounded-lg border border-zinc-800 px-3 py-1.5 text-zinc-300 hover:border-zinc-600 disabled:opacity-40",
            )}
          >
            Prev
          </button>
          <button
            type="button"
            disabled={page >= totalPages || loading}
            onClick={() => setPage((p) => p + 1)}
            className="rounded-lg border border-zinc-800 px-3 py-1.5 text-zinc-300 hover:border-zinc-600 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

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
  "IMPERSONATION_START",
  "IMPERSONATION_END",
  "IMPERSONATE_START",
  "impersonation_start",
  "impersonation_end",
  "BALANCE_ADJUST",
] as const;

function tryParseDetails(raw: string | null): unknown {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
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

export function AdminAuditTab() {
  const { showToast } = useToast();
  const [entries, setEntries] = useState<AdminAuditItem[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [search, setSearch] = useState("");
  const [action, setAction] = useState("");
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
      });
      setEntries(response.items ?? response.entries ?? []);
      setTotal(response.total);
      setTotalPages(response.total_pages || Math.max(1, Math.ceil(response.total / pageSize)));
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить аудит."), "error");
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [action, page, pageSize, search, showToast]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 250);
    return () => window.clearTimeout(timer);
  }, [load]);

  const actionOptions = useMemo(() => ACTION_OPTIONS, []);

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-lg font-medium text-zinc-100">Логи аудита</h2>
        <p className="mt-1 text-sm text-zinc-500">
          Кто из админов заходил под клиентами и какие привилегированные действия выполнял (
          {total} записей).
        </p>
      </header>

      <div className="grid gap-3 rounded-2xl border border-zinc-800/80 bg-zinc-950/50 p-4 md:grid-cols-3">
        <label className="block text-xs text-zinc-500 md:col-span-2">
          Поиск (email, цель, детали)
          <input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-amber-500/30 focus:ring-2"
          />
        </label>
        <label className="block text-xs text-zinc-500">
          Действие
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
                {opt || "Все"}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="overflow-hidden rounded-2xl border border-zinc-800/80">
        <table className="min-w-full text-sm">
          <thead className="bg-zinc-950 text-xs uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="w-8 px-3 py-3" />
              <th className="px-4 py-3 text-left">Когда</th>
              <th className="px-4 py-3 text-left">Действие</th>
              <th className="px-4 py-3 text-left">Админ</th>
              <th className="px-4 py-3 text-left">Клиент</th>
              <th className="px-4 py-3 text-left">IP</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/80">
            {loading ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-zinc-500">
                  Загрузка…
                </td>
              </tr>
            ) : entries.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-zinc-500">
                  Записей пока нет.
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
                        >
                          {open ? (
                            <ChevronDown className="h-4 w-4" />
                          ) : (
                            <ChevronRight className="h-4 w-4" />
                          )}
                        </button>
                      </td>
                      <td className="px-4 py-3 tabular-nums text-zinc-400">
                        {new Date(entry.created_at).toLocaleString("ru-RU")}
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
                          {parsed ? <JsonViewer value={parsed} /> : null}
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
          Стр. {page} из {Math.max(1, totalPages)}
        </p>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="rounded-lg border border-zinc-800 px-3 py-1.5 text-zinc-300 hover:border-zinc-600 disabled:opacity-40"
          >
            Назад
          </button>
          <button
            type="button"
            disabled={page >= totalPages || loading}
            onClick={() => setPage((p) => p + 1)}
            className="rounded-lg border border-zinc-800 px-3 py-1.5 text-zinc-300 hover:border-zinc-600 disabled:opacity-40"
          >
            Вперёд
          </button>
        </div>
      </div>
    </div>
  );
}

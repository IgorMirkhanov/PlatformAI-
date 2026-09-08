"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { AdminBotFinanceModal } from "@/components/admin/AdminBotFinanceModal";
import { AdminDataTable, type AdminColumn } from "@/components/admin/AdminDataTable";
import { useToast } from "@/hooks/useToast";
import { fetchAdminBots } from "@/lib/api";
import { getApiErrorMessage } from "@/store/useBotStore";
import type { AdminBotItem } from "@/types/admin";

export default function AdminBotsPage() {
  const { showToast } = useToast();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [bots, setBots] = useState<AdminBotItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [financeBot, setFinanceBot] = useState<AdminBotItem | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchAdminBots({
        page,
        page_size: pageSize,
        search: query.trim() || undefined,
        status: status || undefined,
      });
      setBots(response.items ?? response.bots ?? []);
      setTotal(response.total);
      setTotalPages(response.total_pages || Math.max(1, Math.ceil(response.total / pageSize)));
    } catch (error) {
      showToast(getApiErrorMessage(error, "Failed to load bots."), "error");
      setBots([]);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, query, showToast, status]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 250);
    return () => window.clearTimeout(timer);
  }, [load]);

  const columns = useMemo<AdminColumn<AdminBotItem>[]>(
    () => [
      { id: "name", header: "Bot", cell: (row) => row.name },
      {
        id: "org",
        header: "Organization",
        cell: (row) => row.organization_name || "—",
      },
      {
        id: "owner",
        header: "Owner",
        cell: (row) => row.owner_email || "—",
      },
      {
        id: "subscription",
        header: "Подписка",
        cell: (row) => (row.subscription_active ? "Да" : "Нет"),
      },
      {
        id: "wallet",
        header: "Баланс бота",
        cell: (row) => String(row.wallet_balance ?? 0),
      },
      {
        id: "actions",
        header: "",
        cell: (row) => (
          <button
            type="button"
            onClick={() => setFinanceBot(row)}
            className="rounded-lg border border-zinc-700 px-2.5 py-1 text-xs text-zinc-200 hover:border-amber-500/40"
          >
            Баланс / подписка
          </button>
        ),
      },
    ],
    [],
  );

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-50">Bots</h1>
          <p className="mt-1 text-sm text-zinc-500">
            Подписка и баланс у каждого агента свои. Без подписки бот не отвечает в чате.
          </p>
        </div>
        <label className="text-xs text-zinc-500">
          Status
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
            className="ml-2 rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-200"
          >
            <option value="">All</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
      </header>
      <AdminDataTable
        columns={columns}
        rows={bots}
        rowKey={(row) => row.id}
        search={query}
        onSearchChange={(value) => {
          setQuery(value);
          setPage(1);
        }}
        searchPlaceholder="Search bot, org, owner…"
        loading={loading}
        page={page}
        pageSize={pageSize}
        total={total}
        totalPages={totalPages}
        onPageChange={setPage}
      />
      <AdminBotFinanceModal
        open={financeBot !== null}
        bot={financeBot}
        onClose={() => setFinanceBot(null)}
        onSuccess={() => void load()}
      />
    </div>
  );
}

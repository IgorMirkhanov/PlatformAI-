"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { AdminDataTable, type AdminColumn } from "@/components/admin/AdminDataTable";
import { CrmSubNav } from "@/components/crm/CrmSubNav";
import { useToast } from "@/hooks/useToast";
import { getContacts } from "@/lib/crm/api";
import type { CrmContact } from "@/lib/crm/types";
import { getApiErrorMessage } from "@/store/useBotStore";

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

export default function CrmContactsPage() {
  const { showToast } = useToast();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [contacts, setContacts] = useState<CrmContact[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await getContacts(page, pageSize, query.trim() || undefined);
      setContacts(response.items);
      setTotal(response.total);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить контакты."), "error");
      setContacts([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, query, showToast]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 250);
    return () => window.clearTimeout(timer);
  }, [load]);

  const columns = useMemo<AdminColumn<CrmContact>[]>(
    () => [
      {
        id: "name",
        header: "Имя",
        cell: (row) => {
          const name = `${row.first_name || ""} ${row.last_name || ""}`.trim();
          return (
            <div>
              <p className="font-medium text-zinc-100">{name || "Без имени"}</p>
              {row.linked_client_id ? (
                <p className="text-[11px] text-zinc-500">linked inbox</p>
              ) : null}
            </div>
          );
        },
      },
      {
        id: "phone",
        header: "Телефон",
        cell: (row) => row.phone || "—",
      },
      {
        id: "email",
        header: "Email",
        cell: (row) => row.email || "—",
      },
      {
        id: "source",
        header: "Источник",
        cell: (row) => (
          <span className="capitalize text-zinc-300">{row.source || "—"}</span>
        ),
      },
      {
        id: "created_at",
        header: "Дата создания",
        cell: (row) => formatDate(row.created_at),
      },
    ],
    [],
  );

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 p-4 md:p-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-2">
          <CrmSubNav />
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-violet-300/80">
              Native CRM
            </p>
            <h1 className="mt-1 text-2xl font-semibold text-zinc-50">Контакты</h1>
            <p className="mt-1 text-sm text-zinc-400">
              Люди из воронки и автозахвата лидов.
            </p>
          </div>
        </div>
      </header>

      <AdminDataTable
        columns={columns}
        rows={contacts}
        rowKey={(row) => row.id}
        search={query}
        onSearchChange={(value) => {
          setPage(1);
          setQuery(value);
        }}
        searchPlaceholder="Поиск по имени, телефону, email…"
        loading={loading}
        emptyMessage="Контакты не найдены."
        page={page}
        pageSize={pageSize}
        total={total}
        totalPages={totalPages}
        onPageChange={setPage}
      />
    </div>
  );
}

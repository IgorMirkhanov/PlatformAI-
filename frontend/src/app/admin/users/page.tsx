"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, ShieldCheck, ShieldOff } from "lucide-react";

import { AdminDataTable, type AdminColumn } from "@/components/admin/AdminDataTable";
import { useAuth } from "@/components/auth/AuthContext";
import { useToast } from "@/hooks/useToast";
import { fetchAdminUsers, updateAdminUserPlatformRole } from "@/lib/api";
import { useBotStore, getApiErrorMessage } from "@/store/useBotStore";
import type { AdminClientItem } from "@/types/admin";

type PlatformRoleValue = "USER" | "SUPERADMIN";

/** Admin Panel access is superadmin-only, so the table shows a binary role. */
function normalizePlatformRole(user: AdminClientItem): PlatformRoleValue {
  if (user.is_superadmin || user.platform_role === "SUPERADMIN") return "SUPERADMIN";
  return "USER";
}

function formatBalance(value: number | undefined): string {
  const amount = Number.isFinite(value) ? Number(value) : 0;
  return `${amount.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₸`;
}

export default function AdminUsersPage() {
  const { startImpersonation } = useAuth();
  const { showToast } = useToast();
  const currentUser = useBotStore((state) => state.currentUser);
  const canManageRoles = Boolean(currentUser?.is_superadmin);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [clients, setClients] = useState<AdminClientItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchAdminUsers({
        page,
        page_size: pageSize,
        search: query.trim() || undefined,
        status: status || undefined,
      });
      setClients(response.items ?? response.clients ?? []);
      setTotal(response.total);
      setTotalPages(response.total_pages || Math.max(1, Math.ceil(response.total / pageSize)));
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить пользователей."), "error");
      setClients([]);
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

  const handleLoginAs = useCallback(
    async (user: AdminClientItem) => {
      const password = window.prompt(
        `Введите свой пароль администратора, чтобы войти как ${user.email}:`,
      );
      if (!password) return;
      setPendingId(user.id);
      try {
        await startImpersonation(user.email, password);
        showToast(`Вы вошли как ${user.email}`, "success");
      } catch (error) {
        showToast(getApiErrorMessage(error, "Имперсонация не удалась."), "error");
        setPendingId(null);
      }
    },
    [showToast, startImpersonation],
  );

  const handleRoleChange = useCallback(
    async (user: AdminClientItem, nextRole: PlatformRoleValue) => {
      if (normalizePlatformRole(user) === nextRole) return;
      setPendingId(user.id);
      try {
        const updated = await updateAdminUserPlatformRole(user.id, nextRole);
        setClients((rows) =>
          rows.map((row) =>
            row.id === user.id
              ? {
                  ...row,
                  platform_role: updated.platform_role,
                  is_superadmin: updated.is_superadmin,
                  is_support: updated.is_support,
                }
              : row,
          ),
        );
        showToast(`Роль ${user.email} → ${updated.platform_role}`, "success");
      } catch (error) {
        showToast(getApiErrorMessage(error, "Не удалось сменить роль."), "error");
      } finally {
        setPendingId(null);
      }
    },
    [showToast],
  );

  const columns = useMemo<AdminColumn<AdminClientItem>[]>(
    () => [
      {
        id: "email",
        header: "Пользователь",
        cell: (row) => (
          <div>
            <p className="font-medium text-zinc-100">{row.email}</p>
            <p className="text-xs text-zinc-500">{row.full_name || "—"}</p>
          </div>
        ),
      },
      {
        id: "company",
        header: "Организация",
        cell: (row) => row.company_name,
      },
      {
        id: "balance",
        header: "Баланс",
        cell: (row) => (
          <span className="tabular-nums text-zinc-200">{formatBalance(row.wallet_balance)}</span>
        ),
      },
      {
        id: "role",
        header: "Роль",
        cell: (row) => {
          const isAdmin = normalizePlatformRole(row) === "SUPERADMIN";
          return (
            <div className="flex items-center gap-2">
              <span
                className={
                  isAdmin
                    ? "rounded-md bg-amber-500/10 px-2 py-0.5 text-xs font-semibold text-amber-200 ring-1 ring-amber-500/30"
                    : "rounded-md bg-zinc-800/80 px-2 py-0.5 text-xs text-zinc-300"
                }
              >
                {isAdmin ? "SUPERADMIN" : "USER"}
              </span>
              {canManageRoles ? (
                <button
                  type="button"
                  disabled={pendingId === row.id}
                  onClick={() =>
                    void handleRoleChange(row, isAdmin ? "USER" : "SUPERADMIN")
                  }
                  className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-800 px-2 py-1 text-xs font-medium text-zinc-300 transition hover:bg-zinc-900 disabled:opacity-50"
                >
                  {pendingId === row.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : isAdmin ? (
                    <ShieldOff className="h-3.5 w-3.5" />
                  ) : (
                    <ShieldCheck className="h-3.5 w-3.5" />
                  )}
                  {isAdmin ? "Снять админа" : "Сделать админом"}
                </button>
              ) : null}
            </div>
          );
        },
      },
      {
        id: "status",
        header: "Статус",
        cell: (row) => (row.is_active === false ? "Неактивен" : "Активен"),
      },
      {
        id: "login_as",
        header: "Войти как",
        className: "text-right",
        cell: (row) => (
          <button
            type="button"
            disabled={pendingId === row.id || row.is_superadmin}
            onClick={() => void handleLoginAs(row)}
            className="inline-flex items-center justify-center rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs font-semibold text-amber-100 transition hover:bg-amber-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {pendingId === row.id ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Вход…
              </>
            ) : (
              "Login as"
            )}
          </button>
        ),
      },
    ],
    [canManageRoles, handleLoginAs, handleRoleChange, pendingId],
  );

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-50">Пользователи</h1>
          <p className="mt-1 text-sm text-zinc-500">
            Баланс организаций, выдача прав Superadmin и имперсонация.
          </p>
        </div>
        <label className="text-xs text-zinc-500">
          Статус
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
            className="ml-2 rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-200"
          >
            <option value="">Все</option>
            <option value="active">Активные</option>
            <option value="inactive">Неактивные</option>
          </select>
        </label>
      </header>
      <AdminDataTable
        columns={columns}
        rows={clients}
        rowKey={(row) => row.id}
        search={query}
        onSearchChange={(value) => {
          setQuery(value);
          setPage(1);
        }}
        searchPlaceholder="Поиск по email, имени, организации…"
        loading={loading}
        page={page}
        pageSize={pageSize}
        total={total}
        totalPages={totalPages}
        onPageChange={setPage}
      />
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Search, ShieldCheck, ShieldOff } from "lucide-react";

import { useAuth } from "@/components/auth/AuthContext";
import { useToast } from "@/hooks/useToast";
import { fetchAdminUserSearch, updateAdminUserPlatformRole } from "@/lib/api";
import { isSuperAdminUser } from "@/lib/auth/admin";
import { formatBillingCurrency } from "@/lib/billing-utils";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/store/useBotStore";
import type { AdminUserSearchItem } from "@/types/admin";

const PAGE_SIZE = 25;

function formatLastActivity(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("ru-RU", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function isSuperadminRow(user: AdminUserSearchItem): boolean {
  return Boolean(user.is_superadmin) || user.platform_role === "SUPERADMIN";
}

export function AdminSupportTab() {
  const { startImpersonation } = useAuth();
  const { showToast } = useToast();
  const canManage = isSuperAdminUser();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [items, setItems] = useState<AdminUserSearchItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [pendingEmail, setPendingEmail] = useState<string | null>(null);
  const [pendingRoleId, setPendingRoleId] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(query.trim());
      setPage(1);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [query]);

  // Empty query intentionally loads the full user list on mount.
  const runSearch = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchAdminUserSearch(debounced, {
        page,
        pageSize: PAGE_SIZE,
      });
      setItems(response.items);
      setTotal(response.total ?? response.items.length);
      setTotalPages(response.total_pages ?? 1);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить пользователей."), "error");
      setItems([]);
      setTotal(0);
      setTotalPages(1);
    } finally {
      setLoading(false);
    }
  }, [debounced, page, showToast]);

  useEffect(() => {
    void runSearch();
  }, [runSearch]);

  const handleImpersonate = async (user: AdminUserSearchItem) => {
    const password = window.prompt(
      `Подтвердите пароль администратора для входа как ${user.email}:`,
    );
    if (!password) return;
    setPendingEmail(user.email);
    try {
      await startImpersonation(user.email, password);
      showToast(`Вы вошли как ${user.email}`, "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Имперсонация не удалась."), "error");
      setPendingEmail(null);
    }
  };

  const handleToggleSuperadmin = async (user: AdminUserSearchItem) => {
    const makeAdmin = !isSuperadminRow(user);
    setPendingRoleId(user.id);
    try {
      const updated = await updateAdminUserPlatformRole(
        user.id,
        makeAdmin ? "SUPERADMIN" : "USER",
      );
      setItems((prev) =>
        prev.map((row) =>
          row.id === user.id
            ? {
                ...row,
                is_superadmin: updated.is_superadmin,
                is_support: updated.is_support,
                platform_role: updated.platform_role,
              }
            : row,
        ),
      );
      showToast(
        makeAdmin
          ? `${user.email} — права администратора выданы`
          : `${user.email} — права администратора сняты`,
        "success",
      );
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось изменить роль."), "error");
    } finally {
      setPendingRoleId(null);
    }
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-medium text-zinc-100">Пользователи и поддержка</h2>
          <p className="mt-1 text-sm text-zinc-500">
            Все зарегистрированные аккаунты. Поиск по e-mail, имени или организации.
          </p>
        </div>
        <span className="text-xs text-zinc-500">
          Всего аккаунтов: <span className="tabular-nums text-zinc-300">{total}</span>
        </span>
      </header>

      <label className="relative block max-w-xl">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="client@example.com или Acme Corp…"
          className="w-full rounded-xl border border-zinc-800 bg-zinc-950/80 py-2.5 pl-10 pr-3 text-sm text-zinc-100 outline-none ring-amber-500/30 placeholder:text-zinc-600 focus:ring-2"
        />
      </label>

      <div className="overflow-x-auto rounded-2xl border border-zinc-800/80">
        <table className="min-w-full text-sm">
          <thead className="bg-zinc-950 text-xs uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="px-4 py-3 text-left">Пользователь</th>
              <th className="px-4 py-3 text-left">Организация</th>
              <th className="px-4 py-3 text-right">Баланс</th>
              <th className="px-4 py-3 text-center">Боты</th>
              <th className="px-4 py-3 text-left">Активность</th>
              <th className="px-4 py-3 text-left">Роль</th>
              <th className="px-4 py-3 text-right">Действия</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/80">
            {loading ? (
              <tr>
                <td colSpan={7} className="px-4 py-10 text-center text-zinc-500">
                  <Loader2 className="mx-auto h-5 w-5 animate-spin" />
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-10 text-center text-zinc-500">
                  {debounced ? "Клиенты не найдены." : "Пользователей пока нет."}
                </td>
              </tr>
            ) : (
              items.map((user) => {
                const superadmin = isSuperadminRow(user);
                return (
                  <tr key={user.id} className="bg-zinc-950/40 hover:bg-zinc-900/40">
                    <td className="px-4 py-3">
                      <p className="font-medium text-zinc-100">{user.email}</p>
                      {user.full_name ? (
                        <p className="text-xs text-zinc-500">{user.full_name}</p>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 text-zinc-400">
                      <p className="truncate">{user.organization_name}</p>
                      <p className="text-xs text-zinc-600">{user.plan_name || "—"}</p>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-amber-100/90">
                      {formatBillingCurrency(user.credit_balance, "KZT")}
                    </td>
                    <td className="px-4 py-3 text-center tabular-nums text-zinc-300">
                      {user.active_bots}
                    </td>
                    <td className="px-4 py-3 text-xs text-zinc-500">
                      {formatLastActivity(user.last_activity_at)}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          "rounded-md px-2 py-0.5 text-xs font-semibold ring-1",
                          superadmin
                            ? "bg-amber-500/10 text-amber-200 ring-amber-500/30"
                            : "bg-zinc-800/80 text-zinc-300 ring-zinc-700",
                        )}
                      >
                        {superadmin ? "SUPERADMIN" : "USER"}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap items-center justify-end gap-2">
                        {canManage ? (
                          <button
                            type="button"
                            disabled={pendingRoleId === user.id}
                            onClick={() => void handleToggleSuperadmin(user)}
                            className={cn(
                              "inline-flex items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-xs font-semibold transition disabled:opacity-50",
                              superadmin
                                ? "border-zinc-700 text-zinc-300 hover:bg-zinc-900"
                                : "border-amber-500/50 bg-amber-500/10 text-amber-100 hover:bg-amber-500/20",
                            )}
                          >
                            {pendingRoleId === user.id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : superadmin ? (
                              <ShieldOff className="h-3.5 w-3.5" />
                            ) : (
                              <ShieldCheck className="h-3.5 w-3.5" />
                            )}
                            {superadmin ? "Снять админа" : "Сделать админом"}
                          </button>
                        ) : null}
                        {canManage ? (
                          <button
                            type="button"
                            disabled={!user.is_active || pendingEmail === user.email}
                            onClick={() => void handleImpersonate(user)}
                            className="inline-flex items-center rounded-xl border border-zinc-700 px-2.5 py-1.5 text-xs font-medium text-zinc-200 transition hover:bg-zinc-900 disabled:opacity-50"
                          >
                            {pendingEmail === user.email ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              "Войти как клиент"
                            )}
                          </button>
                        ) : (
                          <span className="text-xs text-zinc-500">
                            Только суперадмин
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 ? (
        <div className="flex items-center justify-between text-xs text-zinc-500">
          <span>
            Страница {page} из {totalPages}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={page <= 1 || loading}
              onClick={() => setPage((prev) => Math.max(1, prev - 1))}
              className="rounded-lg border border-zinc-800 px-2.5 py-1.5 text-zinc-300 transition hover:bg-zinc-900 disabled:opacity-40"
            >
              Назад
            </button>
            <button
              type="button"
              disabled={page >= totalPages || loading}
              onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
              className="rounded-lg border border-zinc-800 px-2.5 py-1.5 text-zinc-300 transition hover:bg-zinc-900 disabled:opacity-40"
            >
              Вперёд
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

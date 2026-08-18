"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Search } from "lucide-react";

import { AdminBalanceModal } from "@/components/admin/AdminBalanceModal";
import { useToast } from "@/hooks/useToast";
import { fetchAdminOrganizations } from "@/lib/api";
import { formatBillingCurrency } from "@/lib/billing-utils";
import { getApiErrorMessage } from "@/store/useBotStore";
import type { AdminOrganizationItem } from "@/types/admin";
import type { BillingCurrency } from "@/types/billing";

export function AdminBillingTab() {
  const { showToast } = useToast();
  const [orgs, setOrgs] = useState<AdminOrganizationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [balanceOrg, setBalanceOrg] = useState<AdminOrganizationItem | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchAdminOrganizations();
      setOrgs(response.organizations);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить организации."), "error");
      setOrgs([]);
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return orgs;
    return orgs.filter(
      (org) =>
        org.name.toLowerCase().includes(needle) ||
        (org.owner_email || "").toLowerCase().includes(needle),
    );
  }, [orgs, query]);

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-lg font-medium text-zinc-100">Организации и биллинг</h2>
        <p className="mt-1 text-sm text-zinc-500">
          Ручное начисление или списание кредитов с кошелька организации.
        </p>
      </header>

      <label className="relative block max-w-md">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Организация или email владельца…"
          className="w-full rounded-xl border border-zinc-800 bg-zinc-950/80 py-2 pl-9 pr-3 text-sm text-zinc-100 outline-none ring-amber-500/30 placeholder:text-zinc-600 focus:ring-2"
        />
      </label>

      <div className="overflow-hidden rounded-2xl border border-zinc-800/80">
        <table className="min-w-full text-sm">
          <thead className="bg-zinc-950 text-xs uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="px-4 py-3 text-left">Организация</th>
              <th className="px-4 py-3 text-left">Владелец</th>
              <th className="px-4 py-3 text-left">План</th>
              <th className="px-4 py-3 text-right">Баланс</th>
              <th className="px-4 py-3 text-right">Боты</th>
              <th className="px-4 py-3 text-right">Действия</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/80">
            {loading ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-zinc-500">
                  <Loader2 className="mx-auto h-5 w-5 animate-spin" />
                </td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-zinc-500">
                  Организации не найдены.
                </td>
              </tr>
            ) : (
              filtered.map((org) => (
                <tr key={org.id} className="bg-zinc-950/40 hover:bg-zinc-900/40">
                  <td className="px-4 py-3 font-medium text-zinc-100">{org.name}</td>
                  <td className="px-4 py-3 text-zinc-400">{org.owner_email || "—"}</td>
                  <td className="px-4 py-3 text-zinc-400">{org.stripe_plan || "—"}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-amber-100/90">
                    {formatBillingCurrency(
                      org.wallet_balance,
                      (org.currency || "KZT") as BillingCurrency,
                    )}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-zinc-300">
                    {org.active_bots}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => setBalanceOrg(org)}
                      className="rounded-lg border border-zinc-700 bg-zinc-900/60 px-2.5 py-1 text-xs font-medium text-zinc-200 hover:border-amber-500/40 hover:text-amber-100"
                    >
                      Изменить баланс
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <AdminBalanceModal
        open={Boolean(balanceOrg)}
        organization={balanceOrg}
        onClose={() => setBalanceOrg(null)}
        onSuccess={() => void load()}
      />
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";

import { useToast } from "@/hooks/useToast";
import { formatBillingCurrency, formatTransactionDate } from "@/lib/billing-utils";
import { fetchAdminTransactions } from "@/lib/api";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/store/useBotStore";
import type { AdminTransactionItem, AdminTransactionStatus } from "@/types/admin";
import type { BillingCurrency } from "@/types/billing";

function statusBadgeClass(status: AdminTransactionStatus): string {
  switch (String(status).toLowerCase()) {
    case "succeeded":
      return "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30";
    case "pending":
      return "bg-amber-500/15 text-amber-300 ring-amber-500/30";
    case "failed":
      return "bg-red-500/15 text-red-300 ring-red-500/30";
    default:
      return "bg-zinc-500/15 text-zinc-400 ring-zinc-500/25";
  }
}

export default function AdminBillingPage() {
  const { showToast } = useToast();
  const [transactions, setTransactions] = useState<AdminTransactionItem[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchAdminTransactions(200);
      setTransactions(response.transactions);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Failed to load transactions."), "error");
      setTransactions([]);
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
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-50">Billing</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Global ledger. Balance adjusts require SUPERADMIN outside impersonation.
        </p>
      </header>

      <div className="overflow-hidden rounded-2xl border border-zinc-800/80">
        <table className="min-w-full text-sm">
          <thead className="bg-zinc-950 text-xs uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="px-4 py-3 text-left">When</th>
              <th className="px-4 py-3 text-left">Org / User</th>
              <th className="px-4 py-3 text-left">Type</th>
              <th className="px-4 py-3 text-right">Amount</th>
              <th className="px-4 py-3 text-left">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/80">
            {loading ? (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-zinc-500">
                  Loading…
                </td>
              </tr>
            ) : transactions.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-zinc-500">
                  No transactions.
                </td>
              </tr>
            ) : (
              transactions.map((txn) => (
                <tr key={txn.id} className="bg-zinc-950/40">
                  <td className="px-4 py-3 text-zinc-400">
                    {formatTransactionDate(txn.created_at)}
                  </td>
                  <td className="px-4 py-3">
                    <p className="text-zinc-100">{txn.organization_name || "—"}</p>
                    <p className="text-xs text-zinc-500">{txn.user_email}</p>
                  </td>
                  <td className="px-4 py-3 text-zinc-300">{txn.transaction_type}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-zinc-100">
                    {formatBillingCurrency(
                      txn.amount,
                      (txn.currency || "KZT") as BillingCurrency,
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "inline-flex rounded-md px-2 py-0.5 text-xs ring-1",
                        statusBadgeClass(txn.status as AdminTransactionStatus),
                      )}
                    >
                      {txn.status}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

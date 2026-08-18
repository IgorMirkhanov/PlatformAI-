"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import { useToast } from "@/hooks/useToast";
import { fetchAdminLlmModels, updateAdminLlmModel } from "@/lib/api";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/store/useBotStore";
import type { LlmModelRecord } from "@/types/llm-model-api";

export function AdminLlmModelsTab() {
  const { showToast } = useToast();
  const [items, setItems] = useState<LlmModelRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchAdminLlmModels();
      setItems(response.items);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить модели."), "error");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleActive = async (row: LlmModelRecord) => {
    setPendingId(row.id);
    try {
      const updated = await updateAdminLlmModel(row.id, { is_active: !row.is_active });
      setItems((prev) => prev.map((item) => (item.id === row.id ? updated : item)));
      showToast(`Модель ${updated.display_name} обновлена`, "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось обновить модель."), "error");
    } finally {
      setPendingId(null);
    }
  };

  const sorted = useMemo(
    () => [...items].sort((a, b) => a.provider.localeCompare(b.provider)),
    [items],
  );

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-medium text-zinc-100">LLM модели и цены</h2>
          <p className="mt-1 text-sm text-zinc-500">
            Реестр провайдеров, тарификация за 1k токенов (платформенные единицы).
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex items-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900/60 px-3 py-2 text-xs font-medium text-zinc-300 hover:border-zinc-600"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Обновить
        </button>
      </header>

      <div className="overflow-hidden rounded-2xl border border-zinc-800/80">
        <table className="min-w-full text-sm">
          <thead className="bg-zinc-950 text-xs uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="px-4 py-3 text-left">Модель</th>
              <th className="px-4 py-3 text-left">Провайдер</th>
              <th className="px-4 py-3 text-right">Input / 1k</th>
              <th className="px-4 py-3 text-right">Output / 1k</th>
              <th className="px-4 py-3 text-center">Контекст</th>
              <th className="px-4 py-3 text-left">Статус</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/80">
            {loading ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-zinc-500">
                  <Loader2 className="mx-auto h-5 w-5 animate-spin" />
                </td>
              </tr>
            ) : sorted.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-zinc-500">
                  Модели не найдены.
                </td>
              </tr>
            ) : (
              sorted.map((row) => (
                <tr key={row.id} className="bg-zinc-950/40 hover:bg-zinc-900/40">
                  <td className="px-4 py-3">
                    <p className="font-medium text-zinc-100">{row.display_name}</p>
                    <p className="text-xs text-zinc-500">{row.model_name}</p>
                  </td>
                  <td className="px-4 py-3 text-zinc-400">{row.provider}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-zinc-300">
                    {row.cost_per_1k_input}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-zinc-300">
                    {row.cost_per_1k_output}
                  </td>
                  <td className="px-4 py-3 text-center tabular-nums text-zinc-400">
                    {row.context_window.toLocaleString("ru-RU")}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      disabled={pendingId === row.id}
                      onClick={() => void toggleActive(row)}
                      className={cn(
                        "rounded-lg px-2.5 py-1 text-xs font-semibold ring-1 transition disabled:opacity-50",
                        row.is_active
                          ? "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30"
                          : "bg-zinc-800/80 text-zinc-400 ring-zinc-700",
                      )}
                    >
                      {pendingId === row.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : row.is_active ? (
                        "Активна"
                      ) : (
                        "Выключена"
                      )}
                    </button>
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

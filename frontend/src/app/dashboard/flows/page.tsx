"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Bot, Plus, Workflow } from "lucide-react";
import { useRouter } from "next/navigation";

import {
  createFlow,
  deleteFlow,
  getFlows,
  type FlowRecord,
} from "@/lib/flow/api";
import { ApiError, fetchDashboardStats } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { AgentStatusSummary } from "@/types/dashboard";

const DEFAULT_TRIGGER_GRAPH = {
  nodes: [
    {
      id: "trigger-1",
      type: "trigger",
      position: { x: 80, y: 160 },
      data: {
        label: "Trigger",
        trigger_type: "message_received",
        webhook_event: "",
      },
    },
  ],
  edges: [] as Array<{ id: string; source: string; target: string }>,
};

export default function FlowsListPage() {
  const router = useRouter();
  const [items, setItems] = useState<FlowRecord[]>([]);
  const [agents, setAgents] = useState<AgentStatusSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [flowsResponse, stats] = await Promise.all([
        getFlows(),
        fetchDashboardStats().catch(() => null),
      ]);
      setItems(flowsResponse.items);
      setAgents(stats?.agents ?? []);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось загрузить сценарии");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const onCreate = async () => {
    setCreating(true);
    setError(null);
    try {
      const flow = await createFlow({
        name: `Новый сценарий ${new Date().toLocaleString()}`,
        ...DEFAULT_TRIGGER_GRAPH,
      });
      router.push(`/dashboard/flows/${flow.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось создать сценарий");
      setCreating(false);
    }
  };

  const onDeactivate = async (id: string) => {
    try {
      await deleteFlow(id);
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось удалить сценарий");
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">Сценарии</h1>
          <p className="mt-1 text-sm text-zinc-500">
            Единый конструктор: org-графы и сценарии агентов.{" "}
            <Link href="/dashboard/templates" className="text-emerald-400 hover:underline">
              Шаблоны
            </Link>
          </p>
        </div>
        <button
          type="button"
          onClick={() => void onCreate()}
          disabled={creating}
          className={cn(
            "inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-2 text-sm font-medium text-white",
            "hover:bg-emerald-500 disabled:opacity-60",
          )}
        >
          <Plus className="h-4 w-4" />
          {creating ? "Создание…" : "Новый сценарий"}
        </button>
      </div>

      {error ? (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      ) : null}

      <section className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Workflow className="h-4 w-4 text-emerald-400" />
          <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">
            Org-сценарии
          </h2>
        </div>
        {loading ? (
          <div className="text-sm text-zinc-500">Загрузка…</div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-zinc-800 px-6 py-12 text-center">
            <Workflow className="h-8 w-8 text-zinc-600" />
            <p className="text-sm text-zinc-400">Пока нет org-сценариев. Создайте первый граф.</p>
          </div>
        ) : (
          <ul className="divide-y divide-zinc-800/80 overflow-hidden rounded-2xl border border-zinc-800">
            {items.map((flow) => (
              <li
                key={flow.id}
                className="flex flex-wrap items-center justify-between gap-3 bg-[#0d0d0f] px-4 py-4"
              >
                <div>
                  <Link
                    href={`/dashboard/flows/${flow.id}`}
                    className="text-sm font-medium text-zinc-100 hover:text-emerald-300"
                  >
                    {flow.name}
                  </Link>
                  <p className="mt-1 text-xs text-zinc-500">
                    {flow.nodes.length} nodes · {flow.edges.length} edges ·{" "}
                    {flow.is_active ? "active" : "inactive"}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Link
                    href={`/dashboard/flows/${flow.id}`}
                    className="rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:bg-zinc-800"
                  >
                    Открыть конструктор
                  </Link>
                  {flow.is_active ? (
                    <button
                      type="button"
                      onClick={() => void onDeactivate(flow.id)}
                      className="rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-400 hover:border-red-500/40 hover:text-red-300"
                    >
                      Выключить
                    </button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Bot className="h-4 w-4 text-indigo-400" />
          <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">
            Сценарии агентов
          </h2>
        </div>
        <p className="text-xs text-zinc-500">
          Опубликованный граф конкретного бота (вкладка «Сценарий» в агенте).
        </p>
        {agents.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-zinc-800 px-6 py-10 text-center text-sm text-zinc-500">
            Нет агентов — создайте бота на дашборде.
          </div>
        ) : (
          <ul className="divide-y divide-zinc-800/80 overflow-hidden rounded-2xl border border-zinc-800">
            {agents.map((agent) => (
              <li
                key={agent.bot_id}
                className="flex flex-wrap items-center justify-between gap-3 bg-[#0d0d0f] px-4 py-4"
              >
                <div>
                  <p className="text-sm font-medium text-zinc-100">{agent.bot_name}</p>
                  <p className="mt-1 text-xs text-zinc-500">
                    {agent.platform_type}
                    {agent.flow_published ? " · опубликован" : " · черновик"}
                  </p>
                </div>
                <Link
                  href={`/flow-builder?botId=${encodeURIComponent(agent.bot_id)}`}
                  className="rounded-lg border border-indigo-500/40 bg-indigo-500/10 px-3 py-1.5 text-xs font-medium text-indigo-200 hover:bg-indigo-500/20"
                >
                  Открыть конструктор
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

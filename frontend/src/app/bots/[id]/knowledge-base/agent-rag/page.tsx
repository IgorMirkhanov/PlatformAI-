"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, MoreHorizontal, Plus, Trash2 } from "lucide-react";

import { PageSkeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/hooks/useToast";
import { useAgentWorkspace } from "@/hooks/useAgentWorkspace";
import {
  createAgentRagCollection,
  deleteAgentRagCollection,
  fetchAgentRagCollections,
} from "@/lib/api";
import { getApiErrorMessage } from "@/store/useBotStore";
import type { AgentRagCollection } from "@/types/agent";

export default function AgentRagListPage() {
  const params = useParams<{ id: string }>();
  const botId = params.id;
  const router = useRouter();
  const { profile, loading } = useAgentWorkspace(botId);
  const { showToast } = useToast();
  const [items, setItems] = useState<AgentRagCollection[]>([]);
  const [busy, setBusy] = useState(false);
  const [menuId, setMenuId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const response = await fetchAgentRagCollections(botId);
    setItems(response.items || []);
  }, [botId]);

  useEffect(() => {
    void load().catch((error) => {
      showToast(getApiErrorMessage(error, "Не удалось загрузить коллекции."), "error");
    });
  }, [load, showToast]);

  const handleCreate = async (): Promise<void> => {
    setBusy(true);
    try {
      const created = await createAgentRagCollection(botId, {
        function_name: `knowledge_${Date.now().toString(36)}`,
        description: "",
      });
      router.push(`/bots/${botId}/knowledge-base/agent-rag/${created.id}`);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось создать коллекцию."), "error");
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (item: AgentRagCollection): Promise<void> => {
    try {
      await deleteAgentRagCollection(botId, item.id);
      setItems((current) => current.filter((row) => row.id !== item.id));
      showToast("Коллекция удалена.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось удалить коллекцию."), "error");
    }
  };

  if (loading && !profile) return <PageSkeleton />;
  if (!profile) return null;

  return (
    <div className="space-y-5">
      <Link
        href={`/bots/${botId}/knowledge-base`}
        className="inline-flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-200"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        К выбору типа RAG
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-zinc-50">Агентный RAG</h2>
          <p className="mt-1 text-sm text-zinc-500">
            ИИ вызывает знания в зависимости от условия.
          </p>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => void handleCreate()}
          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
          Загрузить знание
        </button>
      </div>

      <div className="overflow-hidden rounded-2xl border border-zinc-800 bg-[#0d0d0f]">
        <table className="min-w-full text-left text-sm">
          <thead className="border-b border-zinc-800 bg-zinc-950/80 text-[11px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="px-4 py-3 font-medium">Название (Function Name)</th>
              <th className="px-4 py-3 font-medium">Условие вызова / Описание</th>
              <th className="w-16 px-4 py-3 font-medium">Действия</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/80">
            {items.length === 0 ? (
              <tr>
                <td colSpan={3} className="px-4 py-10 text-center text-sm text-zinc-500">
                  Коллекций пока нет — нажмите «Загрузить знание».
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <tr key={item.id} className="hover:bg-zinc-900/40">
                  <td className="px-4 py-3">
                    <Link
                      href={`/bots/${botId}/knowledge-base/agent-rag/${item.id}`}
                      className="font-mono text-sm text-violet-200 hover:underline"
                    >
                      {item.function_name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-zinc-400">
                    {item.description || "—"}
                  </td>
                  <td className="relative px-4 py-3">
                    <button
                      type="button"
                      onClick={() => setMenuId((current) => (current === item.id ? null : item.id))}
                      className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200"
                    >
                      <MoreHorizontal className="h-4 w-4" />
                    </button>
                    {menuId === item.id ? (
                      <div className="absolute right-4 z-20 mt-1 w-40 rounded-xl border border-zinc-800 bg-zinc-950 py-1 shadow-xl">
                        <Link
                          href={`/bots/${botId}/knowledge-base/agent-rag/${item.id}`}
                          className="block px-3 py-2 text-xs text-zinc-300 hover:bg-zinc-900"
                        >
                          Редактировать
                        </Link>
                        <button
                          type="button"
                          onClick={() => void handleDelete(item)}
                          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-rose-300 hover:bg-zinc-900"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          Удалить
                        </button>
                      </div>
                    ) : null}
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

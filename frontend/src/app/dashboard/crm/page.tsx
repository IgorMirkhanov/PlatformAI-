"use client";

import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo } from "react";

import { CrmSubNav } from "@/components/crm/CrmSubNav";
import { KanbanBoard } from "@/components/crm/KanbanBoard";
import { useCrmWebSocket } from "@/hooks/useCrmWebSocket";
import { cn } from "@/lib/utils";
import { useCrmStore } from "@/store/useCrmStore";

export default function CrmKanbanPage() {
  // Keep operator WS alive on this page for CRM real-time deal events.
  useCrmWebSocket();

  const pipelines = useCrmStore((s) => s.pipelines);
  const activePipelineId = useCrmStore((s) => s.activePipelineId);
  const deals = useCrmStore((s) => s.deals);
  const isLoading = useCrmStore((s) => s.isLoading);
  const fetchPipelines = useCrmStore((s) => s.fetchPipelines);
  const setActivePipeline = useCrmStore((s) => s.setActivePipeline);
  const fetchDeals = useCrmStore((s) => s.fetchDeals);

  const activePipeline = useMemo(
    () => pipelines.find((p) => p.id === activePipelineId) ?? null,
    [pipelines, activePipelineId],
  );

  const bootstrap = useCallback(async () => {
    const list = await fetchPipelines();
    const nextId =
      useCrmStore.getState().activePipelineId ??
      list.find((p) => p.is_default)?.id ??
      list[0]?.id;
    if (nextId) {
      setActivePipeline(nextId);
      await fetchDeals(nextId);
    }
  }, [fetchPipelines, fetchDeals, setActivePipeline]);

  useEffect(() => {
    void bootstrap().catch(() => {
      /* toast already shown in store */
    });
  }, [bootstrap]);

  const onSelectPipeline = async (pipelineId: string) => {
    if (pipelineId === activePipelineId) return;
    setActivePipeline(pipelineId);
    await fetchDeals(pipelineId).catch(() => undefined);
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 p-4 md:p-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-2">
          <CrmSubNav />
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-violet-300/80">
              Native CRM
            </p>
            <h1 className="mt-1 text-2xl font-semibold text-zinc-50">Сделки</h1>
            <p className="mt-1 text-sm text-zinc-400">
              Канбан-доска по этапам воронки. Перетащите карточку, чтобы сменить этап.
            </p>
          </div>
        </div>

        {pipelines.length > 1 ? (
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="Воронки">
            {pipelines.map((pipeline) => {
              const active = pipeline.id === activePipelineId;
              return (
                <button
                  key={pipeline.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => void onSelectPipeline(pipeline.id)}
                  className={cn(
                    "rounded-full border px-3.5 py-1.5 text-sm font-medium transition",
                    active
                      ? "border-violet-500/60 bg-violet-500/15 text-violet-100"
                      : "border-zinc-700 bg-zinc-900/50 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200",
                  )}
                >
                  {pipeline.name}
                  {pipeline.is_default ? (
                    <span className="ml-1.5 text-[10px] uppercase text-zinc-500">default</span>
                  ) : null}
                </button>
              );
            })}
          </div>
        ) : null}
      </header>

      {isLoading && !activePipeline ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-sm text-zinc-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Загрузка воронок…
        </div>
      ) : null}

      {!isLoading && pipelines.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-zinc-700 bg-zinc-900/30 px-6 py-16 text-center">
          <p className="text-sm font-medium text-zinc-200">Воронки ещё не созданы</p>
          <p className="mt-2 text-sm text-zinc-500">
            Создайте воронку в настройках CRM или дождитесь сида «Продажи» для организации.
          </p>
        </div>
      ) : null}

      {activePipeline ? (
        <div className="relative min-h-0 flex-1">
          {isLoading ? (
            <div className="pointer-events-none absolute inset-0 z-10 flex items-start justify-center pt-8">
              <span className="inline-flex items-center gap-2 rounded-full border border-zinc-700 bg-zinc-950/90 px-3 py-1.5 text-xs text-zinc-300">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Обновление…
              </span>
            </div>
          ) : null}
          <KanbanBoard
            stages={activePipeline.stages ?? []}
            deals={deals}
            pipelineId={activePipeline.id}
          />
        </div>
      ) : null}
    </div>
  );
}

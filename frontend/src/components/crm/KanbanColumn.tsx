"use client";

import { Droppable } from "@hello-pangea/dnd";
import { Plus } from "lucide-react";
import { useState } from "react";

import { DealCard } from "@/components/crm/DealCard";
import type { CrmDeal, CrmStage } from "@/lib/crm/types";
import { cn } from "@/lib/utils";
import { useCrmStore } from "@/store/useCrmStore";

interface KanbanColumnProps {
  stage: CrmStage;
  deals: CrmDeal[];
  pipelineId: string;
}

export function KanbanColumn({ stage, deals, pipelineId }: KanbanColumnProps) {
  const createDealInStage = useCrmStore((state) => state.createDealInStage);
  const [isCreating, setIsCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const accent = stage.color?.trim() || "#8B5CF6";
  const total = deals.reduce((sum, deal) => {
    const value = typeof deal.amount === "number" ? deal.amount : Number(deal.amount);
    return sum + (Number.isFinite(value) ? value : 0);
  }, 0);
  const canCreate = !stage.is_won && !stage.is_lost;

  const submitCreate = async () => {
    if (!title.trim() || submitting) return;
    setSubmitting(true);
    try {
      await createDealInStage(pipelineId, stage.id, title);
      setTitle("");
      setIsCreating(false);
    } catch {
      // toast handled in store
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section
      className="flex h-full min-h-[28rem] w-[280px] shrink-0 flex-col rounded-2xl border border-zinc-800/80 bg-zinc-900/40"
      style={{ borderTopColor: accent, borderTopWidth: 3 }}
    >
      <header className="flex items-start justify-between gap-2 border-b border-zinc-800/70 px-3 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: accent }}
              aria-hidden
            />
            <h2 className="truncate text-sm font-semibold text-zinc-100">{stage.name}</h2>
          </div>
          <p className="mt-1 text-[11px] text-zinc-500">
            {deals.length} ·{" "}
            {new Intl.NumberFormat("ru-RU", {
              style: "currency",
              currency: deals[0]?.currency || "KZT",
              maximumFractionDigits: 0,
            }).format(total)}
          </p>
        </div>
        <div className="flex items-center gap-1">
          {canCreate ? (
            <button
              type="button"
              onClick={() => setIsCreating((value) => !value)}
              className="rounded-lg border border-zinc-700 p-1.5 text-zinc-400 transition hover:border-violet-500/50 hover:text-violet-200"
              aria-label={`Добавить сделку в этап ${stage.name}`}
            >
              <Plus className="h-4 w-4" />
            </button>
          ) : null}
          {(stage.is_won || stage.is_lost) && (
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                stage.is_won && "bg-emerald-500/15 text-emerald-300",
                stage.is_lost && "bg-rose-500/15 text-rose-300",
              )}
            >
              {stage.is_won ? "Won" : "Lost"}
            </span>
          )}
        </div>
      </header>

      {isCreating ? (
        <div className="space-y-2 border-b border-zinc-800/70 p-2">
          <input
            autoFocus
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void submitCreate();
              }
              if (event.key === "Escape") {
                setIsCreating(false);
                setTitle("");
              }
            }}
            placeholder="Название сделки"
            className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-2.5 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/60"
          />
          <div className="flex gap-2">
            <button
              type="button"
              disabled={submitting || !title.trim()}
              onClick={() => void submitCreate()}
              className="flex-1 rounded-lg bg-violet-600 px-2 py-1.5 text-xs font-medium text-white disabled:opacity-50"
            >
              Создать
            </button>
            <button
              type="button"
              onClick={() => {
                setIsCreating(false);
                setTitle("");
              }}
              className="rounded-lg border border-zinc-700 px-2 py-1.5 text-xs text-zinc-400"
            >
              Отмена
            </button>
          </div>
        </div>
      ) : null}

      <Droppable droppableId={stage.id}>
        {(provided, snapshot) => (
          <div
            ref={provided.innerRef}
            {...provided.droppableProps}
            className={cn(
              "flex flex-1 flex-col gap-2 overflow-y-auto p-2 transition-colors",
              snapshot.isDraggingOver && "bg-violet-500/5",
            )}
          >
            {deals.map((deal, index) => (
              <DealCard key={deal.id} deal={deal} index={index} />
            ))}
            {provided.placeholder}
            {deals.length === 0 ? (
              <p className="px-2 py-6 text-center text-xs text-zinc-600">Нет сделок</p>
            ) : null}
          </div>
        )}
      </Droppable>
    </section>
  );
}

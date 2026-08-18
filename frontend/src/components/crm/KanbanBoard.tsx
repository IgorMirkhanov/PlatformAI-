"use client";

import {
  DragDropContext,
  type DropResult,
} from "@hello-pangea/dnd";
import { useMemo } from "react";

import { KanbanColumn } from "@/components/crm/KanbanColumn";
import type { CrmDeal, CrmStage } from "@/lib/crm/types";
import { useCrmStore } from "@/store/useCrmStore";

interface KanbanBoardProps {
  stages: CrmStage[];
  deals: CrmDeal[];
  pipelineId: string;
}

export function KanbanBoard({ stages, deals, pipelineId }: KanbanBoardProps) {
  const moveDealOptimistic = useCrmStore((state) => state.moveDealOptimistic);

  const sortedStages = useMemo(
    () => [...stages].sort((a, b) => a.position - b.position),
    [stages],
  );

  const dealsByStage = useMemo(() => {
    const map = new Map<string, CrmDeal[]>();
    for (const stage of sortedStages) {
      map.set(stage.id, []);
    }
    for (const deal of deals) {
      const bucket = map.get(deal.stage_id);
      if (bucket) {
        bucket.push(deal);
      }
    }
    map.forEach((list) => {
      list.sort(
        (a: CrmDeal, b: CrmDeal) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      );
    });
    return map;
  }, [deals, sortedStages]);

  const onDragEnd = (result: DropResult) => {
    const { destination, source, draggableId } = result;
    if (!destination) return;
    if (
      destination.droppableId === source.droppableId &&
      destination.index === source.index
    ) {
      return;
    }
    void moveDealOptimistic(draggableId, destination.droppableId);
  };

  if (sortedStages.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-zinc-700 bg-zinc-900/30 px-6 py-16 text-center text-sm text-zinc-400">
        У этой воронки пока нет этапов.
      </div>
    );
  }

  return (
    <DragDropContext onDragEnd={onDragEnd}>
      <div className="flex gap-3 overflow-x-auto pb-4">
        {sortedStages.map((stage) => (
          <KanbanColumn
            key={stage.id}
            stage={stage}
            deals={dealsByStage.get(stage.id) ?? []}
            pipelineId={pipelineId}
          />
        ))}
      </div>
    </DragDropContext>
  );
}

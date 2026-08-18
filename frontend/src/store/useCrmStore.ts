import { create } from "zustand";

import { createDeal, getDeals, getPipelines, moveDealStage } from "@/lib/crm/api";
import type { CrmDeal, CrmPipeline } from "@/lib/crm/types";
import { ApiError } from "@/lib/api";
import { useToastStore } from "@/hooks/useToast";
import type {
  WSCrmDealClosedPayload,
  WSCrmDealCreatedPayload,
  WSCrmDealUpdatedPayload,
} from "@/types/ws";

interface CrmStoreState {
  pipelines: CrmPipeline[];
  activePipelineId: string | null;
  deals: CrmDeal[];
  isLoading: boolean;
  error: string | null;
  fetchPipelines: () => Promise<CrmPipeline[]>;
  setActivePipeline: (id: string) => void;
  fetchDeals: (pipelineId: string) => Promise<CrmDeal[]>;
  createDealInStage: (pipelineId: string, stageId: string, title: string) => Promise<CrmDeal>;
  moveDealOptimistic: (dealId: string, destStageId: string) => Promise<void>;
  handleWsDealCreated: (payload: WSCrmDealCreatedPayload) => void;
  handleWsDealUpdated: (payload: WSCrmDealUpdatedPayload) => void;
  handleWsDealClosed: (payload: WSCrmDealClosedPayload) => void;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Не удалось выполнить действие CRM.";
}

export const useCrmStore = create<CrmStoreState>((set, get) => ({
  pipelines: [],
  activePipelineId: null,
  deals: [],
  isLoading: false,
  error: null,

  fetchPipelines: async () => {
    set({ isLoading: true, error: null });
    try {
      const pipelines = await getPipelines();
      const sorted = [...pipelines].sort(
        (a, b) => a.position - b.position || a.name.localeCompare(b.name),
      );
      const preferred =
        sorted.find((p) => p.is_default)?.id ?? sorted[0]?.id ?? null;
      set({
        pipelines: sorted,
        activePipelineId: get().activePipelineId ?? preferred,
        isLoading: false,
      });
      return sorted;
    } catch (error) {
      const message = errorMessage(error);
      set({ isLoading: false, error: message, pipelines: [] });
      useToastStore.getState().showToast(message, "error");
      throw error;
    }
  },

  setActivePipeline: (id) => {
    set({ activePipelineId: id });
  },

  fetchDeals: async (pipelineId) => {
    set({ isLoading: true, error: null });
    try {
      const deals = await getDeals(pipelineId);
      set({ deals, isLoading: false, activePipelineId: pipelineId });
      return deals;
    } catch (error) {
      const message = errorMessage(error);
      set({ isLoading: false, error: message, deals: [] });
      useToastStore.getState().showToast(message, "error");
      throw error;
    }
  },

  createDealInStage: async (pipelineId, stageId, title) => {
    const trimmed = title.trim();
    if (!trimmed) {
      throw new Error("Укажите название сделки.");
    }
    try {
      const deal = await createDeal({
        title: trimmed,
        pipeline_id: pipelineId,
        stage_id: stageId,
      });
      if (get().activePipelineId === pipelineId) {
        set({ deals: [deal, ...get().deals] });
      }
      useToastStore.getState().showToast("Сделка создана.", "success");
      return deal;
    } catch (error) {
      useToastStore.getState().showToast(errorMessage(error), "error");
      throw error;
    }
  },

  moveDealOptimistic: async (dealId, destStageId) => {
    const previous = get().deals;
    const current = previous.find((d) => d.id === dealId);
    if (!current) return;
    if (current.stage_id === destStageId) return;

    set({
      deals: previous.map((deal) =>
        deal.id === dealId
          ? { ...deal, stage_id: destStageId, updated_at: new Date().toISOString() }
          : deal,
      ),
    });

    try {
      const updated = await moveDealStage(dealId, destStageId);
      set({
        deals: get().deals.map((deal) => (deal.id === dealId ? { ...deal, ...updated } : deal)),
      });
    } catch (error) {
      set({ deals: previous });
      useToastStore.getState().showToast(errorMessage(error), "error");
      throw error;
    }
  },

  handleWsDealCreated: (payload) => {
    const deal = payload.deal;
    if (!deal?.id) return;
    const activePipelineId = get().activePipelineId;
    if (activePipelineId && deal.pipeline_id !== activePipelineId) {
      return;
    }
    if (deal.status && deal.status !== "open") {
      return;
    }
    const exists = get().deals.some((d) => d.id === deal.id);
    if (exists) return;
    set({ deals: [deal, ...get().deals] });
  },

  handleWsDealUpdated: (payload) => {
    const { deal_id, stage_id, pipeline_id } = payload;
    if (!deal_id || !stage_id) return;
    const activePipelineId = get().activePipelineId;
    if (pipeline_id && activePipelineId && pipeline_id !== activePipelineId) {
      // Deal moved to another pipeline — drop from this board if present.
      set({ deals: get().deals.filter((d) => d.id !== deal_id) });
      return;
    }
    const found = get().deals.find((d) => d.id === deal_id);
    if (!found) return;
    if (found.stage_id === stage_id) return;
    set({
      deals: get().deals.map((deal) =>
        deal.id === deal_id
          ? { ...deal, stage_id, updated_at: new Date().toISOString() }
          : deal,
      ),
    });
  },

  handleWsDealClosed: (payload) => {
    const { deal_id } = payload;
    if (!deal_id) return;
    set({ deals: get().deals.filter((deal) => deal.id !== deal_id) });
  },
}));

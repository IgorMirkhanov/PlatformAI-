"use client";

import { useEffect, useMemo, useRef } from "react";

import { useFlowStore, type SaveStatus } from "@/store/useFlowStore";
import { useBotStore } from "@/store/useBotStore";

export type AutoSaveStatus = "idle" | "saving" | "saved" | "error";

function mapSaveStatus(status: SaveStatus): AutoSaveStatus {
  switch (status) {
    case "loading":
      return "saving";
    case "success":
      return "saved";
    case "error":
      return "error";
    default:
      return "idle";
  }
}

export const AUTO_SAVE_STATUS_LABEL: Record<AutoSaveStatus, string> = {
  idle: "",
  saving: "Сохранение…",
  saved: "Сохранены все изменения",
  error: "Ошибка сохранения",
};

interface UseAutoSaveFlowOptions {
  /** Debounce window before POST /bots/{id}/flow */
  debounceMs?: number;
  enabled?: boolean;
  title?: string;
}

/**
 * Debounced auto-save for React Flow canvas topology + node data.
 */
export function useAutoSaveFlow(options: UseAutoSaveFlowOptions = {}) {
  const { debounceMs = 1000, enabled = true, title } = options;

  const nodes = useFlowStore((state) => state.nodes);
  const edges = useFlowStore((state) => state.edges);
  const saveFlow = useFlowStore((state) => state.saveFlow);
  const saveStatus = useFlowStore((state) => state.saveStatus);
  const saveError = useFlowStore((state) => state.saveError);

  const connection = useBotStore((state) => state.connection);
  const activeBotId = useBotStore((state) => state.activeBotId);
  const agentProfiles = useBotStore((state) => state.agentProfiles);

  const botId = connection?.botId ?? activeBotId ?? Object.keys(agentProfiles)[0] ?? null;
  const botName =
    connection?.botName ??
    (botId && agentProfiles[botId] ? agentProfiles[botId].name : null) ??
    "Agent";

  const skipFirst = useRef(true);
  const timerRef = useRef<number | null>(null);
  const signature = useMemo(
    () => JSON.stringify({ nodes, edges }),
    [nodes, edges],
  );

  useEffect(() => {
    if (!enabled || !botId) return;
    if (skipFirst.current) {
      skipFirst.current = false;
      return;
    }
    if (nodes.length === 0) return;

    if (timerRef.current) {
      window.clearTimeout(timerRef.current);
    }

    timerRef.current = window.setTimeout(() => {
      void saveFlow(botId, title ?? `${botName} Flow`);
    }, debounceMs);

    return () => {
      if (timerRef.current) {
        window.clearTimeout(timerRef.current);
      }
    };
  }, [botId, botName, debounceMs, enabled, nodes.length, saveFlow, signature, title]);

  const status = mapSaveStatus(saveStatus);

  return {
    saveStatus: status,
    saveError,
    statusLabel: AUTO_SAVE_STATUS_LABEL[status],
    botId,
  };
}

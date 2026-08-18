"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Focus,
  Grid3X3,
  Loader2,
  Magnet,
  Network,
  Download,
  Redo2,
  Rocket,
  Save,
  Undo2,
} from "lucide-react";
import { useStoreApi } from "reactflow";

import {
  AUTO_SAVE_STATUS_LABEL,
  type AutoSaveStatus,
} from "@/lib/hooks/use-auto-save-flow";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { useBotStore } from "@/store/useBotStore";
import { useFlowStore, type SaveStatus } from "@/store/useFlowStore";

const ZOOM_INDICATOR_DEBOUNCE_MS = 150;

interface TopControlBarProps {
  className?: string;
  snapToGrid?: boolean;
  showGrid?: boolean;
  /** Optional override from `useAutoSaveFlow` — falls back to store saveStatus. */
  autoSaveStatus?: AutoSaveStatus;
  onToggleSnap?: () => void;
  onToggleGrid?: () => void;
  onFitView?: () => void;
}

function mapStoreSaveStatus(status: SaveStatus): AutoSaveStatus {
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

/** Read viewport zoom from React Flow without re-rendering the canvas parent. */
function useDebouncedZoomPercent(defaultPercent = 100): number {
  const store = useStoreApi();
  const [zoomPercent, setZoomPercent] = useState(defaultPercent);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const readZoom = (): number =>
      Math.round(store.getState().transform[2] * 100);

    setZoomPercent(readZoom());

    const unsubscribe = store.subscribe((state, previous) => {
      if (state.transform[2] === previous.transform[2]) {
        return;
      }
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
      timerRef.current = setTimeout(() => {
        const next = Math.round(state.transform[2] * 100);
        setZoomPercent((prev) => (prev === next ? prev : next));
        timerRef.current = null;
      }, ZOOM_INDICATOR_DEBOUNCE_MS);
    });

    return () => {
      unsubscribe();
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, [store]);

  return zoomPercent;
}

export function TopControlBar({
  className,
  snapToGrid = true,
  showGrid = true,
  autoSaveStatus,
  onToggleSnap,
  onToggleGrid,
  onFitView,
}: TopControlBarProps) {
  const zoomPercent = useDebouncedZoomPercent(100);
  const nodes = useFlowStore((state) => state.nodes);
  const edges = useFlowStore((state) => state.edges);
  const exportGraphJSON = useFlowStore((state) => state.exportGraphJSON);
  const saveFlow = useFlowStore((state) => state.saveFlow);
  const publishFlow = useFlowStore((state) => state.publishFlow);
  const runGraphValidation = useFlowStore((state) => state.runGraphValidation);
  const publishStatus = useFlowStore((state) => state.publishStatus);
  const publishError = useFlowStore((state) => state.publishError);
  const publishIssues = useFlowStore((state) => state.publishIssues);
  const lastPublishedFlowId = useFlowStore((state) => state.lastPublishedFlowId);
  const saveStatus = useFlowStore((state) => state.saveStatus);
  const saveError = useFlowStore((state) => state.saveError);
  const autoLayout = useFlowStore((state) => state.autoLayout);
  const exportJSONDownload = useFlowStore((state) => state.exportJSONDownload);
  const undo = useFlowStore((state) => state.undo);
  const redo = useFlowStore((state) => state.redo);
  const pastLength = useFlowStore((state) => state.past.length);
  const futureLength = useFlowStore((state) => state.future.length);
  const { showToast } = useToast();

  const connection = useBotStore((state) => state.connection);
  const activeBotId = useBotStore((state) => state.activeBotId);
  const agentProfiles = useBotStore((state) => state.agentProfiles);

  const targetBotId = useMemo(() => {
    if (connection?.botId) return connection.botId;
    if (activeBotId) return activeBotId;
    const profileIds = Object.keys(agentProfiles);
    return profileIds[0] ?? null;
  }, [activeBotId, agentProfiles, connection?.botId]);

  const targetBotName = useMemo(() => {
    if (connection?.botName) return connection.botName;
    if (targetBotId && agentProfiles[targetBotId]) return agentProfiles[targetBotId].name;
    return null;
  }, [agentProfiles, connection?.botName, targetBotId]);

  const resolvedAutoSave = autoSaveStatus ?? mapStoreSaveStatus(saveStatus);
  const autoSaveLabel = AUTO_SAVE_STATUS_LABEL[resolvedAutoSave];

  const handleSaveFlow = useCallback(async (): Promise<void> => {
    if (!targetBotId) {
      showToast("Сначала создайте агента через боковую панель.", "error");
      return;
    }

    const graph = exportGraphJSON();
    if (graph.nodes.length === 0) {
      showToast("Добавьте хотя бы один блок перед сохранением.", "settings");
      return;
    }

    await saveFlow(targetBotId, `${targetBotName ?? "Agent"} Flow`);

    const { saveStatus: statusAfter, saveError: errorAfter } = useFlowStore.getState();
    if (statusAfter === "success") {
      showToast("Сценарий сохранён.", "success");
      return;
    }
    if (statusAfter === "error" && errorAfter) {
      showToast(errorAfter, "error");
    }
  }, [exportGraphJSON, saveFlow, showToast, targetBotId, targetBotName]);

  const handleSaveAndPublish = useCallback(async (): Promise<void> => {
    if (!targetBotId) {
      useFlowStore.setState({
        publishStatus: "error",
        publishError: "Сначала создайте агента через боковую панель «Создать агента».",
        publishIssues: [],
      });
      showToast("Сначала создайте агента через боковую панель.", "error");
      return;
    }

    const issues = runGraphValidation();
    if (issues.length > 0) {
      const alertMessage =
        issues[0]?.message ?? "Ошибка публикации: Проверка сценария не пройдена.";
      showToast(alertMessage, "settings");
      return;
    }

    await publishFlow(targetBotId, `${targetBotName ?? "Agent"} Flow`);

    const { publishStatus: statusAfter, publishError: errorAfter } =
      useFlowStore.getState();

    if (statusAfter === "success") {
      useFlowStore.setState({
        publishError: null,
        publishIssues: [],
        invalidNodeIds: [],
      });
      showToast("Сценарий успешно скомпилирован и опубликован!", "success");
      return;
    }

    if (statusAfter === "error" && errorAfter) {
      showToast(errorAfter, "settings");
    }
  }, [publishFlow, runGraphValidation, showToast, targetBotId, targetBotName]);

  const isPublishing = publishStatus === "loading";
  const isSuccess = publishStatus === "success";
  const isSaving = saveStatus === "loading" || resolvedAutoSave === "saving";
  const isSaved = saveStatus === "success" || resolvedAutoSave === "saved";
  const canUndo = pastLength > 0;
  const canRedo = futureLength > 0;

  const toggleButtonClass = (active: boolean): string =>
    cn(
      "flex items-center gap-1.5 rounded-lg border px-2.5 py-2 text-xs font-medium transition-all duration-200",
      active
        ? "border-violet-500/50 bg-violet-500/15 text-violet-200 shadow-[0_0_12px_rgba(139,92,246,0.25)]"
        : "border-zinc-800 text-zinc-400 hover:border-zinc-700 hover:bg-zinc-900/60",
    );

  return (
    <header
      className={cn(
        "flex flex-col gap-3 rounded-2xl border border-zinc-800/90 bg-[#0d0d0f]/95 px-4 py-3 backdrop-blur-sm sm:flex-row sm:items-center sm:justify-between",
        className,
      )}
    >
      <div>
        <h1 className="text-base font-semibold text-zinc-100">Flow Builder</h1>
        <p className="text-xs text-zinc-500">
          {nodes.length} node{nodes.length !== 1 ? "s" : ""} · {edges.length}{" "}
          connection{edges.length !== 1 ? "s" : ""}
          {targetBotName ? (
            <>
              {" "}
              · <span className="text-zinc-400">{targetBotName}</span>
            </>
          ) : (
            <> · агент не выбран</>
          )}
        </p>
        {autoSaveLabel ? (
          <p
            className={cn(
              "mt-1 text-[11px]",
              resolvedAutoSave === "saving" && "text-zinc-400",
              resolvedAutoSave === "saved" && "text-sky-300",
              resolvedAutoSave === "error" && "text-red-300",
            )}
            aria-live="polite"
          >
            {resolvedAutoSave === "saving" ? (
              <span className="inline-flex items-center gap-1.5">
                <Loader2 className="h-3 w-3 animate-spin" />
                {autoSaveLabel}
              </span>
            ) : resolvedAutoSave === "saved" ? (
              <span className="inline-flex items-center gap-1.5">
                <CheckCircle2 className="h-3 w-3" />
                {autoSaveLabel}
              </span>
            ) : (
              autoSaveLabel
            )}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col items-stretch gap-2 sm:items-end">
        {publishError && publishStatus === "error" && (
          <div className="max-w-md space-y-1 rounded-lg border border-amber-500/30 bg-gradient-to-r from-amber-950/40 to-violet-950/30 px-3 py-2 backdrop-blur-md">
            <div className="flex items-start gap-1.5 text-xs text-amber-200">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{publishError}</span>
            </div>
            {publishIssues.length > 0 && (
              <ul className="space-y-1 pl-5 text-[11px] text-amber-100/90">
                {publishIssues.map((issue) => (
                  <li key={`${issue.code}-${issue.nodeId ?? issue.edgeId ?? issue.message}`}>
                    {issue.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {saveError && saveStatus === "error" && (
          <div className="max-w-md rounded-lg border border-red-500/30 bg-red-950/30 px-3 py-2 text-xs text-red-200">
            {saveError}
          </div>
        )}

        {isSuccess && lastPublishedFlowId && (
          <span className="flex items-center gap-1.5 text-xs text-emerald-400">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Сценарий опубликован (flow {lastPublishedFlowId.slice(0, 8)}…)
          </span>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 rounded-lg border border-zinc-800/90 bg-zinc-950/70 p-1">
            <button
              type="button"
              title="Отменить (Ctrl+Z)"
              onClick={() => undo()}
              disabled={!canUndo}
              className="rounded-md p-1.5 text-zinc-300 transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-35"
            >
              <Undo2 className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              title="Повторить (Ctrl+Y)"
              onClick={() => redo()}
              disabled={!canRedo}
              className="rounded-md p-1.5 text-zinc-300 transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-35"
            >
              <Redo2 className="h-3.5 w-3.5" />
            </button>
          </div>

          <div className="flex items-center gap-2 rounded-lg border border-zinc-800/90 bg-zinc-950/70 px-2 py-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              Масштаб
            </span>
            <span className="min-w-[3rem] text-center text-xs font-semibold tabular-nums text-violet-300">
              {zoomPercent}%
            </span>
          </div>

          <button
            type="button"
            title="Snap to Grid"
            onClick={onToggleSnap}
            className={toggleButtonClass(snapToGrid)}
          >
            <Magnet className={cn("h-3.5 w-3.5", snapToGrid && "text-violet-300")} />
            <span className="hidden sm:inline">Snap to Grid</span>
          </button>

          <button
            type="button"
            title="Show Grid"
            onClick={onToggleGrid}
            className={toggleButtonClass(showGrid)}
          >
            <Grid3X3 className={cn("h-3.5 w-3.5", showGrid && "text-violet-300")} />
            <span className="hidden sm:inline">Show Grid</span>
          </button>

          <button
            type="button"
            title="Auto layout"
            onClick={() => {
              autoLayout();
              showToast("Auto-layout applied.", "settings");
            }}
            className={toggleButtonClass(false)}
          >
            <Network className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Auto layout</span>
          </button>

          <button
            type="button"
            title="Export JSON"
            onClick={() => exportJSONDownload()}
            className={toggleButtonClass(false)}
          >
            <Download className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Export</span>
          </button>

          <button
            type="button"
            title="Центрировать граф"
            onClick={onFitView}
            disabled={nodes.length === 0}
            className="flex items-center gap-1.5 rounded-lg border border-zinc-800 px-2.5 py-2 text-xs font-medium text-zinc-300 transition hover:border-violet-500/30 hover:bg-violet-500/10 hover:text-violet-200 disabled:opacity-40"
          >
            <Focus className="h-3.5 w-3.5" />
            <span className="hidden md:inline">Центрировать граф</span>
          </button>

          <button
            type="button"
            onClick={() => void handleSaveFlow()}
            disabled={isSaving || nodes.length === 0 || !targetBotId}
            className={cn(
              "flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition-all",
              "border-zinc-700 bg-zinc-900 text-zinc-100 hover:border-sky-500/40 hover:bg-sky-500/10",
              "disabled:cursor-not-allowed disabled:opacity-50",
              isSaved && "border-sky-500/50 text-sky-200",
            )}
          >
            {isSaving ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            {isSaving ? "Saving…" : isSaved ? "Saved" : "Save Flow"}
          </button>

          <button
            type="button"
            onClick={() => void handleSaveAndPublish()}
            disabled={isPublishing || nodes.length === 0 || !targetBotId}
            className={cn(
              "flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all",
              "bg-accent text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50",
              isSuccess && "bg-emerald-600 hover:bg-emerald-500",
            )}
          >
            {isPublishing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : isSuccess ? (
              <CheckCircle2 className="h-4 w-4" />
            ) : (
              <Rocket className="h-4 w-4" />
            )}
            {isPublishing ? "Publishing…" : isSuccess ? "Published" : "Save & Publish"}
          </button>
        </div>
      </div>
    </header>
  );
}

"use client";

import { Suspense, useCallback, useEffect, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlowProvider,
  type Connection,
  type NodeMouseHandler,
} from "reactflow";
import "reactflow/dist/style.css";

import { flowEdgeTypes } from "@/components/flow/edges";
import { FlowBuilderOnboarding } from "@/components/flow/FlowBuilderOnboarding";
import { FlowCanvasSkeleton } from "@/components/flow/FlowCanvasSkeleton";
import { FlowPreviewPane } from "@/components/flow/FlowPreviewPane";
import { flowNodeTypes } from "@/components/flow/nodes";
import { NodePalette } from "@/components/flow/NodePalette";
import { PropertiesPanel } from "@/components/flow/PropertiesPanel";
import { TopControlBar } from "@/components/flow/TopControlBar";
import { useAutoSaveFlow } from "@/lib/hooks/use-auto-save-flow";
import { useFlowHistoryHotkeys } from "@/lib/hooks/use-flow-history";
import { cn } from "@/lib/utils";
import { useBotStore } from "@/store/useBotStore";
import { useFlowStore } from "@/store/useFlowStore";
import {
  CANVAS_SNAP_GRID,
  FLOW_EDGE_TYPE,
  isValidFlowConnection,
  type FlowCanvasNode,
} from "@/types/flow";

function minimapNodeColor(node: FlowCanvasNode): string {
  switch (node.type) {
    case "trigger":
      return "#38bdf8";
    case "aiAgent":
    case "llm":
      return "#a78bfa";
    case "textMessage":
    case "whatsapp":
      return "#34d399";
    case "condition":
    case "loop":
      return "#fbbf24";
    case "apiRequest":
      return "#22d3ee";
    case "knowledgeSearch":
    case "rag":
      return "#2dd4bf";
    case "crmAction":
    case "crm":
      return "#818cf8";
    case "humanHandoff":
      return "#fb7185";
    default:
      return "#71717a";
  }
}

function FlowBuilderWorkspace({ botId }: { botId: string }) {
  const nodes = useFlowStore((state) => state.nodes);
  const edges = useFlowStore((state) => state.edges);
  const snapToGrid = useFlowStore((state) => state.snapToGrid);
  const showGrid = useFlowStore((state) => state.showGrid);
  const setSnapToGrid = useFlowStore((state) => state.setSnapToGrid);
  const setShowGrid = useFlowStore((state) => state.setShowGrid);
  const onNodesChange = useFlowStore((state) => state.onNodesChange);
  const onEdgesChange = useFlowStore((state) => state.onEdgesChange);
  const onConnect = useFlowStore((state) => state.onConnect);
  const onNodeDragStart = useFlowStore((state) => state.onNodeDragStart);
  const onNodeDragStop = useFlowStore((state) => state.onNodeDragStop);
  const setSelectedNode = useFlowStore((state) => state.setSelectedNode);
  const resetSelection = useFlowStore((state) => state.resetSelection);

  const { saveStatus: autoSaveStatus } = useAutoSaveFlow({ enabled: Boolean(botId) });
  useFlowHistoryHotkeys(true);

  const onNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      setSelectedNode(node as FlowCanvasNode);
    },
    [setSelectedNode],
  );

  const isValidConnection = useCallback(
    (connection: Connection) => isValidFlowConnection(connection, edges),
    [edges],
  );

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4 lg:p-5">
      <TopControlBar
        snapToGrid={snapToGrid}
        showGrid={showGrid}
        autoSaveStatus={autoSaveStatus}
        onToggleSnap={() => setSnapToGrid(!snapToGrid)}
        onToggleGrid={() => setShowGrid(!showGrid)}
        onFitView={() => undefined}
      />

      <div className="flex min-h-0 flex-1 flex-col gap-3 xl:flex-row">
        <NodePalette className="hidden max-h-[40vh] overflow-y-auto lg:flex xl:max-h-none" />

        <div
          className={cn(
            "relative flex min-h-0 flex-1 overflow-hidden rounded-2xl border border-zinc-800/90 bg-[#09090b]",
            "h-[calc(100vh-12rem)] xl:h-auto",
          )}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            isValidConnection={isValidConnection}
            onNodeClick={onNodeClick}
            onNodeDragStart={onNodeDragStart}
            onNodeDragStop={onNodeDragStop}
            onPaneClick={resetSelection}
            nodeTypes={flowNodeTypes}
            edgeTypes={flowEdgeTypes}
            defaultEdgeOptions={{ type: FLOW_EDGE_TYPE }}
            snapToGrid={snapToGrid}
            snapGrid={CANVAS_SNAP_GRID}
            fitView
            className="bg-transparent"
            proOptions={{ hideAttribution: true }}
          >
            {showGrid && (
              <Background
                variant={BackgroundVariant.Dots}
                gap={20}
                size={1}
                color="#3f3f46"
              />
            )}
            <Controls className="!border-zinc-800 !bg-zinc-950/90 !shadow-lg [&>button]:!border-zinc-800 [&>button]:!bg-zinc-900 [&>button]:!text-zinc-300" />
            <MiniMap
              nodeColor={minimapNodeColor}
              maskColor="rgba(9,9,11,0.7)"
              className="!border-zinc-800 !bg-zinc-950/90"
            />
          </ReactFlow>
        </div>

        <div className="flex w-full shrink-0 flex-col gap-3 xl:w-80">
          <PropertiesPanel className="hidden max-h-[45vh] xl:flex xl:max-h-none xl:flex-1" />
          <FlowPreviewPane botId={botId} className="min-h-[220px] flex-1" />
        </div>
      </div>
    </div>
  );
}

function FlowBuilderContent() {
  const searchParams = useSearchParams();
  const connectionBotId = useBotStore((state) => state.connection?.botId);
  const activeBotId = useBotStore((state) => state.activeBotId);
  const agentProfiles = useBotStore((state) => state.agentProfiles);

  const botId = useMemo(() => {
    const fromQuery = searchParams.get("botId");
    if (fromQuery) return fromQuery;
    if (connectionBotId) return connectionBotId;
    if (activeBotId) return activeBotId;
    const profileIds = Object.keys(agentProfiles);
    return profileIds[0] ?? null;
  }, [activeBotId, agentProfiles, connectionBotId, searchParams]);

  const loadPublishedFlow = useFlowStore((state) => state.loadPublishedFlow);
  const loadStatus = useFlowStore((state) => state.loadStatus);
  const loadedBotId = useFlowStore((state) => state.loadedBotId);
  const loadError = useFlowStore((state) => state.loadError);

  useEffect(() => {
    if (!botId) return;
    if (loadedBotId === botId && loadStatus === "success") return;
    void loadPublishedFlow(botId);
  }, [botId, loadPublishedFlow, loadedBotId, loadStatus]);

  if (!botId) {
    return <FlowBuilderOnboarding />;
  }

  if (loadStatus === "loading") {
    return <FlowCanvasSkeleton />;
  }

  if (loadStatus === "error" && loadError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
        <p className="max-w-md text-sm text-red-400">{loadError}</p>
        <button
          type="button"
          onClick={() => void loadPublishedFlow(botId)}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover"
        >
          Retry loading flow
        </button>
      </div>
    );
  }

  return (
    <ReactFlowProvider>
      <FlowBuilderWorkspace botId={botId} />
    </ReactFlowProvider>
  );
}

export default function FlowBuilderPage() {
  return (
    <div className="h-full min-h-0">
      <Suspense fallback={<FlowCanvasSkeleton />}>
        <FlowBuilderContent />
      </Suspense>
    </div>
  );
}

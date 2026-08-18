"use client";

import { useCallback, useEffect, useMemo } from "react";
import { useParams } from "next/navigation";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlowProvider,
  type NodeMouseHandler,
} from "reactflow";
import "reactflow/dist/style.css";

import { flowEdgeTypes } from "@/components/flow/edges";
import { FlowCanvasSkeleton } from "@/components/flow/FlowCanvasSkeleton";
import { FlowPreviewPane } from "@/components/flow/FlowPreviewPane";
import { flowNodeTypes } from "@/components/flow/nodes";
import { NodePalette } from "@/components/flow/NodePalette";
import { PropertiesPanel } from "@/components/flow/PropertiesPanel";
import { TopControlBar } from "@/components/flow/TopControlBar";
import { useAutoSaveFlow } from "@/lib/hooks/use-auto-save-flow";
import { useFlowHistoryHotkeys } from "@/lib/hooks/use-flow-history";
import { cn } from "@/lib/utils";
import { useFlowStore } from "@/store/useFlowStore";
import {
  CANVAS_SNAP_GRID,
  FLOW_EDGE_TYPE,
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
      return "#fbbf24";
    case "apiRequest":
      return "#22d3ee";
    case "knowledgeSearch":
    case "rag":
      return "#2dd4bf";
    case "crmAction":
    case "crm":
      return "#818cf8";
    default:
      return "#71717a";
  }
}

function FlowBuilderCanvas({ botId }: { botId: string }) {
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
            onNodeClick={onNodeClick}
            onNodeDragStart={onNodeDragStart}
            onNodeDragStop={onNodeDragStop}
            onPaneClick={resetSelection}
            nodeTypes={flowNodeTypes}
            edgeTypes={flowEdgeTypes}
            snapToGrid={snapToGrid}
            snapGrid={CANVAS_SNAP_GRID}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            minZoom={0.2}
            maxZoom={2}
            defaultEdgeOptions={{ type: FLOW_EDGE_TYPE }}
            proOptions={{ hideAttribution: true }}
            className="h-full w-full"
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={CANVAS_SNAP_GRID[0]}
              size={1.2}
              color={showGrid ? "#3f3f46" : "#27272a"}
            />
            <Controls showInteractive={false} />
            <MiniMap
              nodeColor={(node) => minimapNodeColor(node as FlowCanvasNode)}
              nodeStrokeColor="#27272a"
              nodeBorderRadius={12}
              maskColor="rgba(9, 9, 11, 0.72)"
              style={{ width: 180, height: 120 }}
            />
          </ReactFlow>
        </div>

        <div className="flex max-h-[50vh] shrink-0 flex-col gap-3 xl:max-h-none xl:w-auto xl:flex-row">
          <PropertiesPanel className="hidden min-h-0 flex-1 xl:flex" />
          <FlowPreviewPane botId={botId} className="min-h-[280px] flex-1 xl:min-h-0" />
        </div>
      </div>
    </div>
  );
}

export default function DashboardFlowBuilderPage() {
  const params = useParams<{ id: string }>();
  const botId = useMemo(() => {
    const raw = params?.id;
    return typeof raw === "string" ? raw : Array.isArray(raw) ? raw[0] : null;
  }, [params]);

  const loadPublishedFlow = useFlowStore((state) => state.loadPublishedFlow);
  const loadStatus = useFlowStore((state) => state.loadStatus);
  const loadedBotId = useFlowStore((state) => state.loadedBotId);
  const loadError = useFlowStore((state) => state.loadError);

  useEffect(() => {
    if (!botId) {
      return;
    }
    if (loadedBotId === botId && loadStatus === "success") {
      return;
    }
    void loadPublishedFlow(botId);
  }, [botId, loadPublishedFlow, loadedBotId, loadStatus]);

  if (!botId) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-sm text-zinc-400">
        Missing bot id in route.
      </div>
    );
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
    <div className="flex h-full min-h-0 flex-col">
      <ReactFlowProvider>
        <FlowBuilderCanvas botId={botId} />
      </ReactFlowProvider>
    </div>
  );
}

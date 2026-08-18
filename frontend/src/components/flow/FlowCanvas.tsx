"use client";

import { useCallback, useRef } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlowProvider,
  type NodeMouseHandler,
  type ReactFlowInstance,
} from "reactflow";
import "reactflow/dist/style.css";

import { flowEdgeTypes } from "@/components/flow/edges";
import { flowNodeTypes } from "@/components/flow/nodes";
import { NodePalette } from "@/components/flow/NodePalette";
import { TopControlBar } from "@/components/flow/TopControlBar";
import { useAutoSaveFlow } from "@/lib/hooks/use-auto-save-flow";
import { useFlowHistoryHotkeys } from "@/lib/hooks/use-flow-history";
import { cn } from "@/lib/utils";
import { useFlowStore } from "@/store/useFlowStore";
import { CANVAS_SNAP_GRID, FLOW_EDGE_TYPE, type CanvasNodeType, type FlowCanvasNode } from "@/types/flow";

function minimapNodeColor(node: FlowCanvasNode): string {
  switch (node.type) {
    case "trigger":
      return "#38bdf8";
    case "aiAgent":
    case "llm":
      return "#a78bfa";
    case "textMessage":
      return "#34d399";
    case "condition":
      return "#fbbf24";
    case "apiRequest":
      return "#22d3ee";
    case "crmAction":
    case "crm":
      return "#818cf8";
    default:
      return "#71717a";
  }
}

function FlowCanvasInner() {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const reactFlowInstance = useRef<ReactFlowInstance | null>(null);

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
  const addNode = useFlowStore((state) => state.addNode);
  const setSelectedNode = useFlowStore((state) => state.setSelectedNode);
  const resetSelection = useFlowStore((state) => state.resetSelection);

  const { saveStatus: autoSaveStatus } = useAutoSaveFlow();
  useFlowHistoryHotkeys(true);

  const onInit = useCallback((instance: ReactFlowInstance): void => {
    reactFlowInstance.current = instance;
  }, []);

  const handleFitView = useCallback((): void => {
    reactFlowInstance.current?.fitView({
      padding: 0.22,
      duration: 450,
      maxZoom: 1.15,
    });
  }, []);

  const onDragOver = useCallback((event: React.DragEvent<HTMLDivElement>): void => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>): void => {
      event.preventDefault();

      const type = event.dataTransfer.getData(
        "application/reactflow",
      ) as CanvasNodeType;

      if (!type || !reactFlowWrapper.current || !reactFlowInstance.current) {
        return;
      }

      const bounds = reactFlowWrapper.current.getBoundingClientRect();
      const position = reactFlowInstance.current.project({
        x: event.clientX - bounds.left,
        y: event.clientY - bounds.top,
      });

      addNode(type, position);
    },
    [addNode],
  );

  const onNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      setSelectedNode(node as FlowCanvasNode);
    },
    [setSelectedNode],
  );

  const onPaneClick = useCallback((): void => {
    resetSelection();
  }, [resetSelection]);

  return (
    <div className="flex h-full flex-col gap-3 p-4 lg:p-5">
      <TopControlBar
        snapToGrid={snapToGrid}
        showGrid={showGrid}
        autoSaveStatus={autoSaveStatus}
        onToggleSnap={() => setSnapToGrid(!snapToGrid)}
        onToggleGrid={() => setShowGrid(!showGrid)}
        onFitView={handleFitView}
      />

      <div className="flex min-h-0 flex-1 flex-col gap-3 lg:flex-row">
        <NodePalette className="hidden lg:flex" />

        <div
          ref={reactFlowWrapper}
          className={cn(
            "relative min-h-[480px] flex-1 overflow-hidden rounded-2xl border border-zinc-800/90 bg-[#09090b]",
            "h-[calc(100vh-12rem)] lg:h-auto",
          )}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onInit={onInit}
            onDrop={onDrop}
            onDragOver={onDragOver}
            onNodeClick={onNodeClick}
            onNodeDragStart={onNodeDragStart}
            onNodeDragStop={onNodeDragStop}
            onPaneClick={onPaneClick}
            nodeTypes={flowNodeTypes}
            edgeTypes={flowEdgeTypes}
            snapToGrid={snapToGrid}
            snapGrid={CANVAS_SNAP_GRID}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            minZoom={0.2}
            maxZoom={2}
            defaultEdgeOptions={{
              type: FLOW_EDGE_TYPE,
            }}
            proOptions={{ hideAttribution: true }}
          >
            {showGrid ? (
              <Background
                variant={BackgroundVariant.Dots}
                gap={CANVAS_SNAP_GRID[0]}
                size={1.2}
                color="#3f3f46"
              />
            ) : null}
            <Controls
              showInteractive={false}
              className="!overflow-hidden !rounded-xl !border !border-zinc-800 !bg-zinc-950/80 !shadow-glow-purple"
            />
            <MiniMap
              nodeColor={(node) => minimapNodeColor(node as FlowCanvasNode)}
              nodeStrokeColor="#27272a"
              nodeBorderRadius={12}
              maskColor="rgba(9, 9, 11, 0.72)"
              maskStrokeColor="rgba(139, 92, 246, 0.35)"
              maskStrokeWidth={2}
              className={cn(
                "!absolute !bottom-4 !right-4 !overflow-hidden !rounded-2xl",
                "!border !border-zinc-800 !bg-zinc-950/40 !shadow-glow-purple backdrop-blur-md",
              )}
              style={{ width: 180, height: 120 }}
            />
          </ReactFlow>
        </div>
      </div>

      <div className="flex gap-2 lg:hidden">
        <NodePalette className="w-full" />
      </div>
    </div>
  );
}

export function FlowCanvas() {
  return (
    <ReactFlowProvider>
      <FlowCanvasInner />
    </ReactFlowProvider>
  );
}

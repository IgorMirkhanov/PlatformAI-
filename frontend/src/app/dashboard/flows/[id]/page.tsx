"use client";

import { useCallback, useEffect, useMemo, useState, type DragEvent } from "react";
import { useParams, useRouter } from "next/navigation";
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
import { ArrowLeft, Play, Save } from "lucide-react";

import { flowEdgeTypes } from "@/components/flow/edges";
import { FlowCanvasSkeleton } from "@/components/flow/FlowCanvasSkeleton";
import { flowNodeTypes } from "@/components/flow/nodes";
import { NodePalette } from "@/components/flow/NodePalette";
import { PropertiesPanel } from "@/components/flow/PropertiesPanel";
import { useFlowHistoryHotkeys } from "@/lib/hooks/use-flow-history";
import { ApiError } from "@/lib/api";
import {
  getFlow,
  testRunFlow,
  updateFlow,
  type FlowGraphEdge,
  type FlowGraphNode,
  type FlowTestRunResult,
} from "@/lib/flow/api";
import { cn } from "@/lib/utils";
import { useFlowStore } from "@/store/useFlowStore";
import {
  CANVAS_SNAP_GRID,
  FLOW_EDGE_TYPE,
  importGraphFromJSON,
  isValidFlowConnection,
  type ExportedGraphJSON,
  type FlowCanvasNode,
} from "@/types/flow";

function minimapNodeColor(node: FlowCanvasNode): string {
  switch (node.type) {
    case "trigger":
      return "#38bdf8";
    case "aiAgent":
    case "llm":
      return "#a78bfa";
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

function OrgFlowCanvas({
  flowId,
  flowName,
  onNameChange,
}: {
  flowId: string;
  flowName: string;
  onNameChange: (name: string) => void;
}) {
  const router = useRouter();
  const nodes = useFlowStore((state) => state.nodes);
  const edges = useFlowStore((state) => state.edges);
  const snapToGrid = useFlowStore((state) => state.snapToGrid);
  const showGrid = useFlowStore((state) => state.showGrid);
  const onNodesChange = useFlowStore((state) => state.onNodesChange);
  const onEdgesChange = useFlowStore((state) => state.onEdgesChange);
  const onConnect = useFlowStore((state) => state.onConnect);
  const onNodeDragStart = useFlowStore((state) => state.onNodeDragStart);
  const onNodeDragStop = useFlowStore((state) => state.onNodeDragStop);
  const setSelectedNode = useFlowStore((state) => state.setSelectedNode);
  const resetSelection = useFlowStore((state) => state.resetSelection);
  const exportGraphJSON = useFlowStore((state) => state.exportGraphJSON);

  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<FlowTestRunResult | null>(null);
  const [testMessage, setTestMessage] = useState("Hello from admin test-run");

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

  const onSave = async () => {
    setSaving(true);
    setStatusMessage(null);
    try {
      const graph = exportGraphJSON();
      await updateFlow(flowId, {
        name: flowName.trim() || "Untitled Flow",
        nodes: graph.nodes as unknown as FlowGraphNode[],
        edges: graph.edges as unknown as FlowGraphEdge[],
      });
      setStatusMessage("Flow saved");
    } catch (err) {
      setStatusMessage(err instanceof ApiError ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const onTestRun = async () => {
    setTesting(true);
    setStatusMessage(null);
    try {
      // Persist latest canvas before running.
      const graph = exportGraphJSON();
      await updateFlow(flowId, {
        name: flowName.trim() || "Untitled Flow",
        nodes: graph.nodes as unknown as FlowGraphNode[],
        edges: graph.edges as unknown as FlowGraphEdge[],
      });
      const result = await testRunFlow(flowId, {
        message: testMessage,
        sender_id: "admin-test",
      });
      setTestResult(result);
      setStatusMessage(`Test-run: ${result.status} (${result.steps_executed} steps)`);
    } catch (err) {
      setStatusMessage(err instanceof ApiError ? err.message : "Test-run failed");
    } finally {
      setTesting(false);
    }
  };

  const onDragOver = useCallback((event: DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const addNode = useFlowStore((state) => state.addNode);

  const onDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault();
      const type = event.dataTransfer.getData("application/reactflow");
      if (!type) return;
      addNode(type);
    },
    [addNode],
  );

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4 lg:p-5">
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-zinc-800/90 bg-[#0d0d0f] px-4 py-3">
        <button
          type="button"
          onClick={() => router.push("/dashboard/flows")}
          className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 px-2.5 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Flows
        </button>
        <input
          value={flowName}
          onChange={(event) => onNameChange(event.target.value)}
          className="min-w-[12rem] flex-1 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-1.5 text-sm text-zinc-100 outline-none focus:border-zinc-600"
          aria-label="Flow name"
        />
        <input
          value={testMessage}
          onChange={(event) => setTestMessage(event.target.value)}
          className="w-56 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-300 outline-none focus:border-zinc-600"
          aria-label="Test message"
          placeholder="Test inbound message"
        />
        <button
          type="button"
          onClick={() => void onTestRun()}
          disabled={testing}
          className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:bg-zinc-800 disabled:opacity-60"
        >
          <Play className="h-3.5 w-3.5" />
          {testing ? "Running…" : "Test run"}
        </button>
        <button
          type="button"
          onClick={() => void onSave()}
          disabled={saving}
          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-60"
        >
          <Save className="h-3.5 w-3.5" />
          {saving ? "Saving…" : "Save Flow"}
        </button>
      </div>

      {statusMessage ? (
        <div className="rounded-xl border border-zinc-800 bg-zinc-950/80 px-3 py-2 text-xs text-zinc-400">
          {statusMessage}
          {testResult ? (
            <span className="ml-2 text-zinc-500">path: {testResult.path.join(" → ")}</span>
          ) : null}
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 flex-col gap-3 xl:flex-row">
        <NodePalette className="hidden max-h-[40vh] overflow-y-auto lg:flex xl:max-h-none" />

        <div
          className={cn(
            "relative flex min-h-0 flex-1 overflow-hidden rounded-2xl border border-zinc-800/90 bg-[#09090b]",
            "h-[calc(100vh-12rem)] xl:h-auto",
          )}
          onDragOver={onDragOver}
          onDrop={onDrop}
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
            isValidConnection={isValidConnection}
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

        <PropertiesPanel className="hidden min-h-0 xl:flex" />
      </div>
    </div>
  );
}

export default function OrgFlowEditorPage() {
  const params = useParams<{ id: string }>();
  const flowId = useMemo(() => {
    const raw = params?.id;
    return typeof raw === "string" ? raw : Array.isArray(raw) ? raw[0] : null;
  }, [params]);

  const setGraph = useFlowStore((state) => state.setGraph);
  const [flowName, setFlowName] = useState("Untitled Flow");
  const [loadStatus, setLoadStatus] = useState<"loading" | "success" | "error">("loading");
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!flowId) return;
    let cancelled = false;
    setLoadStatus("loading");
    setLoadError(null);

    void (async () => {
      try {
        const flow = await getFlow(flowId);
        if (cancelled) return;
        setFlowName(flow.name);
        const imported = importGraphFromJSON({
          nodes: flow.nodes as ExportedGraphJSON["nodes"],
          edges: flow.edges as ExportedGraphJSON["edges"],
        });
        setGraph(imported.nodes, imported.edges);
        setLoadStatus("success");
      } catch (err) {
        if (cancelled) return;
        setLoadError(err instanceof ApiError ? err.message : "Failed to load flow");
        setLoadStatus("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [flowId, setGraph]);

  if (!flowId) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-sm text-zinc-400">
        Missing flow id in route.
      </div>
    );
  }

  if (loadStatus === "loading") {
    return <FlowCanvasSkeleton />;
  }

  if (loadStatus === "error") {
    return (
      <div className="flex h-full items-center justify-center p-8 text-sm text-red-400">
        {loadError}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ReactFlowProvider>
        <OrgFlowCanvas
          flowId={flowId}
          flowName={flowName}
          onNameChange={setFlowName}
        />
      </ReactFlowProvider>
    </div>
  );
}

"use client";

import { Position, type NodeProps } from "reactflow";
import { FileSearch, Hash, Variable } from "lucide-react";

import { FlowHandle } from "@/components/flow/nodes/FlowHandle";
import {
  flowFieldClassName,
  flowLabelClassName,
  FlowNodeShell,
} from "@/components/flow/nodes/FlowNodeShell";
import { FlowNodeWrapper } from "@/components/flow/nodes/FlowNodeWrapper";
import { useFlowStore } from "@/store/useFlowStore";
import type { KnowledgeSearchNodeData } from "@/types/flow";

/**
 * Intermediary RAG step: runs Chroma similarity search on the user query,
 * then exposes retrieved text as ``{{rag_context}}`` for downstream LLM prompts.
 */
export function KnowledgeSearchNode({
  id,
  data,
  selected,
}: NodeProps<KnowledgeSearchNodeData>) {
  const updateNodeData = useFlowStore((state) => state.updateNodeData);

  return (
    <FlowNodeWrapper nodeId={id} selected={selected}>
      <FlowHandle
        type="target"
        position={Position.Left}
        className="!-left-1.5 !top-1/2 !bg-teal-400"
      />

      <FlowNodeShell
        selected={selected}
        accentClass="border-teal-500/20"
        title="Knowledge Search"
        subtitle={data.label || "RAG retrieval"}
        widthClass="w-[340px]"
        icon={
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-500/10">
            <FileSearch className="h-4 w-4 text-teal-300" />
          </div>
        }
      >
        <p className="text-[11px] leading-relaxed text-zinc-500">
          Queries the bot Chroma collection with the inbound message, then stores
          top chunks in{" "}
          <code className="rounded bg-zinc-950 px-1 text-teal-300/90">
            {"{{rag_context}}"}
          </code>{" "}
          for the next LLM node.
        </p>

        <div>
          <label htmlFor={`${id}-top-k`} className={flowLabelClassName}>
            <span className="inline-flex items-center gap-1.5">
              <Hash className="h-3 w-3" />
              Top-k chunks
            </span>
          </label>
          <input
            id={`${id}-top-k`}
            type="number"
            min={1}
            max={10}
            value={data.top_k}
            onChange={(event) =>
              updateNodeData(id, {
                top_k: Math.max(1, Math.min(10, Number(event.target.value) || 3)),
              })
            }
            className={flowFieldClassName}
          />
        </div>

        <div>
          <label htmlFor={`${id}-query-var`} className={flowLabelClassName}>
            <span className="inline-flex items-center gap-1.5">
              <Variable className="h-3 w-3" />
              Query variable
            </span>
          </label>
          <input
            id={`${id}-query-var`}
            value={data.query_variable}
            onChange={(event) =>
              updateNodeData(id, { query_variable: event.target.value || "message" })
            }
            placeholder="message"
            className={flowFieldClassName}
          />
        </div>

        <div>
          <label htmlFor={`${id}-output-var`} className={flowLabelClassName}>
            Output variable
          </label>
          <input
            id={`${id}-output-var`}
            value={data.output_variable}
            onChange={(event) =>
              updateNodeData(id, {
                output_variable: event.target.value || "rag_context",
              })
            }
            placeholder="rag_context"
            className={flowFieldClassName}
          />
        </div>

        <div>
          <label htmlFor={`${id}-kb`} className={flowLabelClassName}>
            Knowledge base id (optional)
          </label>
          <input
            id={`${id}-kb`}
            value={data.knowledge_base_id}
            onChange={(event) =>
              updateNodeData(id, { knowledge_base_id: event.target.value })
            }
            placeholder="Defaults to bot id"
            className={flowFieldClassName}
          />
        </div>
      </FlowNodeShell>

      <FlowHandle
        type="source"
        position={Position.Right}
        id="default"
        className="!-right-1.5 !top-1/2 !bg-teal-500"
      />
    </FlowNodeWrapper>
  );
}

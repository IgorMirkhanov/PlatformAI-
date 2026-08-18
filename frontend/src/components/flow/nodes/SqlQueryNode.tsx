"use client";

import { Database, Rows3 } from "lucide-react";
import { Position, type NodeProps } from "reactflow";

import { FlowHandle } from "@/components/flow/nodes/FlowHandle";
import {
  flowFieldClassName,
  flowLabelClassName,
  flowTextareaClassName,
  FlowNodeShell,
} from "@/components/flow/nodes/FlowNodeShell";
import { FlowNodeWrapper } from "@/components/flow/nodes/FlowNodeWrapper";
import { useFlowStore } from "@/store/useFlowStore";
import type { SqlQueryNodeData } from "@/types/flow";

export function SqlQueryNode({ id, data, selected }: NodeProps<SqlQueryNodeData>) {
  const updateNodeData = useFlowStore((state) => state.updateNodeData);

  return (
    <FlowNodeWrapper nodeId={id} selected={selected}>
      <FlowHandle
        type="target"
        position={Position.Left}
        className="!-left-1.5 !top-1/2 !bg-sky-400"
      />

      <FlowNodeShell
        selected={selected}
        accentClass="border-sky-500/20"
        title="SQL Query"
        subtitle={data.label || "Read-only database lookup"}
        widthClass="w-[360px]"
        icon={
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-500/10">
            <Database className="h-4 w-4 text-sky-300" />
          </div>
        }
      >
        <div>
          <label className={flowLabelClassName}>Saved connection</label>
          <div className={`${flowFieldClassName} text-zinc-300`}>
            {data.connection_label || data.connection_id || "Select in properties panel"}
          </div>
        </div>

        <div>
          <label htmlFor={`${id}-query`} className={flowLabelClassName}>
            Query template
          </label>
          <textarea
            id={`${id}-query`}
            rows={4}
            value={data.query}
            onChange={(event) => updateNodeData(id, { query: event.target.value })}
            className={flowTextareaClassName}
          />
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)_88px] gap-2">
          <div>
            <label htmlFor={`${id}-result`} className={flowLabelClassName}>
              Result variable
            </label>
            <input
              id={`${id}-result`}
              value={data.result_variable}
              onChange={(event) => updateNodeData(id, { result_variable: event.target.value })}
              placeholder="sql_result"
              className={flowFieldClassName}
            />
          </div>
          <div>
            <label htmlFor={`${id}-rows`} className={flowLabelClassName}>
              <span className="inline-flex items-center gap-1">
                <Rows3 className="h-3 w-3" />
                Max
              </span>
            </label>
            <input
              id={`${id}-rows`}
              type="number"
              min={1}
              max={500}
              value={data.max_rows}
              onChange={(event) =>
                updateNodeData(id, {
                  max_rows: Math.max(1, Math.min(500, Number(event.target.value) || 1)),
                })
              }
              className={flowFieldClassName}
            />
          </div>
        </div>
      </FlowNodeShell>

      <FlowHandle
        type="source"
        position={Position.Right}
        id="default"
        className="!-right-1.5 !top-1/2 !bg-sky-500"
      />
    </FlowNodeWrapper>
  );
}

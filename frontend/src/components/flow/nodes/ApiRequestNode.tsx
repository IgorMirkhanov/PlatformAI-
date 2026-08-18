"use client";

import { Position, type NodeProps } from "reactflow";
import { Globe2 } from "lucide-react";

import { FlowHandle } from "@/components/flow/nodes/FlowHandle";
import {
  flowFieldClassName,
  flowLabelClassName,
  flowTextareaClassName,
  FlowNodeShell,
} from "@/components/flow/nodes/FlowNodeShell";
import { FlowNodeWrapper } from "@/components/flow/nodes/FlowNodeWrapper";
import { useFlowStore } from "@/store/useFlowStore";
import type { ApiHttpMethod, ApiRequestNodeData } from "@/types/flow";

export function ApiRequestNode({ id, data, selected }: NodeProps<ApiRequestNodeData>) {
  const updateNodeData = useFlowStore((state) => state.updateNodeData);

  return (
    <FlowNodeWrapper nodeId={id} selected={selected}>
      <FlowHandle
        type="target"
        position={Position.Left}
        className="!-left-1.5 !top-1/2 !bg-cyan-400"
      />

      <FlowNodeShell
        selected={selected}
        accentClass="border-cyan-500/20"
        title="API Request"
        subtitle={data.label}
        widthClass="w-[360px]"
        icon={
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan-500/10">
            <Globe2 className="h-4 w-4 text-cyan-300" />
          </div>
        }
        footer={
          <div className="relative border-t border-zinc-800/90 px-4 pb-4 pt-3">
            <div className="flex justify-between text-[10px] uppercase tracking-wider text-zinc-500">
              <span>{data.success_label}</span>
              <span>{data.failure_label}</span>
            </div>
            <FlowHandle
              type="source"
              position={Position.Bottom}
              id="success"
              style={{ left: "28%" }}
              className="!bg-emerald-400"
            />
            <FlowHandle
              type="source"
              position={Position.Bottom}
              id="failure"
              style={{ left: "72%" }}
              className="!bg-red-400"
            />
          </div>
        }
      >
        <div className="grid grid-cols-[96px_minmax(0,1fr)] gap-2">
          <div>
            <label className={flowLabelClassName}>Method</label>
            <select
              value={data.method}
              onChange={(event) =>
                updateNodeData(id, { method: event.target.value as ApiHttpMethod })
              }
              className={flowFieldClassName}
            >
              <option value="GET">GET</option>
              <option value="POST">POST</option>
            </select>
          </div>
          <div>
            <label className={flowLabelClassName}>Variable name</label>
            <input
              value={data.variable_name}
              onChange={(event) => updateNodeData(id, { variable_name: event.target.value })}
              className={flowFieldClassName}
            />
          </div>
        </div>

        <div>
          <label className={flowLabelClassName}>Endpoint URL</label>
          <input
            value={data.url}
            onChange={(event) => updateNodeData(id, { url: event.target.value })}
            placeholder="https://api.example.com/webhook"
            className={flowFieldClassName}
          />
        </div>

        <div>
          <label className={flowLabelClassName}>Request body template</label>
          <textarea
            value={data.body_template}
            onChange={(event) => updateNodeData(id, { body_template: event.target.value })}
            rows={4}
            placeholder='{"message":"{{message}}"}'
            className={flowTextareaClassName}
          />
          <p className="mt-1 text-[10px] text-zinc-600">
            Use <code className="text-zinc-400">{`{{message}}`}</code> for the inbound user text.
          </p>
        </div>
      </FlowNodeShell>
    </FlowNodeWrapper>
  );
}

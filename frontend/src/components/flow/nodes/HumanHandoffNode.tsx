"use client";

import { Position, type NodeProps } from "reactflow";
import { Headset } from "lucide-react";

import { FlowHandle } from "@/components/flow/nodes/FlowHandle";
import {
  flowFieldClassName,
  flowLabelClassName,
  flowTextareaClassName,
  FlowNodeShell,
} from "@/components/flow/nodes/FlowNodeShell";
import { FlowNodeWrapper } from "@/components/flow/nodes/FlowNodeWrapper";
import { useFlowStore } from "@/store/useFlowStore";
import type { HumanHandoffNodeData } from "@/types/flow";

/** Transfer conversation to a human operator and optionally pause the bot. */
export function HumanHandoffNode({
  id,
  data,
  selected,
}: NodeProps<HumanHandoffNodeData>) {
  const updateNodeData = useFlowStore((state) => state.updateNodeData);

  return (
    <FlowNodeWrapper nodeId={id} selected={selected}>
      <FlowHandle
        type="target"
        position={Position.Left}
        className="!-left-1.5 !top-1/2 !bg-rose-400"
      />

      <FlowNodeShell
        selected={selected}
        accentClass="border-rose-500/25"
        title="Human Handoff"
        subtitle={data.label}
        icon={
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-rose-500/10">
            <Headset className="h-4 w-4 text-rose-300" />
          </div>
        }
      >
        <div>
          <label htmlFor={`${id}-msg`} className={flowLabelClassName}>
            Handoff message
          </label>
          <textarea
            id={`${id}-msg`}
            rows={3}
            value={data.handoff_message}
            onChange={(e) => updateNodeData(id, { handoff_message: e.target.value })}
            className={flowTextareaClassName}
          />
        </div>
        <div>
          <label htmlFor={`${id}-queue`} className={flowLabelClassName}>
            Queue tag
          </label>
          <input
            id={`${id}-queue`}
            value={data.queue_tag}
            onChange={(e) => updateNodeData(id, { queue_tag: e.target.value })}
            className={flowFieldClassName}
          />
        </div>
        <label className="flex items-center gap-2 text-xs text-zinc-400">
          <input
            type="checkbox"
            checked={data.pause_bot}
            onChange={(e) => updateNodeData(id, { pause_bot: e.target.checked })}
            className="rounded border-zinc-700"
          />
          Pause bot until operator resumes
        </label>
      </FlowNodeShell>

      <FlowHandle
        type="source"
        position={Position.Right}
        className="!-right-1.5 !top-1/2 !bg-rose-400"
      />
    </FlowNodeWrapper>
  );
}

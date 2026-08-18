"use client";

import { Position, type NodeProps } from "reactflow";
import { Repeat2 } from "lucide-react";

import { FlowHandle } from "@/components/flow/nodes/FlowHandle";
import {
  flowFieldClassName,
  flowLabelClassName,
  FlowNodeShell,
} from "@/components/flow/nodes/FlowNodeShell";
import { FlowNodeWrapper } from "@/components/flow/nodes/FlowNodeWrapper";
import { useFlowStore } from "@/store/useFlowStore";
import type { LoopNodeData } from "@/types/flow";

/** Loop block — body / exit handles with max iteration guard. */
export function LoopNode({ id, data, selected }: NodeProps<LoopNodeData>) {
  const updateNodeData = useFlowStore((state) => state.updateNodeData);

  return (
    <FlowNodeWrapper nodeId={id} selected={selected}>
      <FlowHandle
        type="target"
        position={Position.Left}
        className="!-left-1.5 !top-1/2 !bg-amber-400"
      />

      <FlowNodeShell
        selected={selected}
        accentClass="border-amber-500/25"
        title="Loop"
        subtitle={data.label}
        icon={
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-500/10">
            <Repeat2 className="h-4 w-4 text-amber-300" />
          </div>
        }
      >
        <div>
          <label htmlFor={`${id}-max`} className={flowLabelClassName}>
            Max iterations
          </label>
          <input
            id={`${id}-max`}
            type="number"
            min={1}
            max={100}
            value={data.max_iterations}
            onChange={(e) =>
              updateNodeData(id, {
                max_iterations: Math.max(1, Number(e.target.value) || 1),
              })
            }
            className={flowFieldClassName}
          />
        </div>
        <div>
          <label htmlFor={`${id}-expr`} className={flowLabelClassName}>
            Continue when
          </label>
          <input
            id={`${id}-expr`}
            value={data.continue_expression}
            onChange={(e) => updateNodeData(id, { continue_expression: e.target.value })}
            placeholder="true / {{needs_more}}"
            className={flowFieldClassName}
          />
        </div>
      </FlowNodeShell>

      <FlowHandle
        id="body"
        type="source"
        position={Position.Right}
        style={{ top: "35%" }}
        className="!-right-1.5 !bg-amber-400"
      />
      <FlowHandle
        id="exit"
        type="source"
        position={Position.Right}
        style={{ top: "70%" }}
        className="!-right-1.5 !bg-zinc-400"
      />
    </FlowNodeWrapper>
  );
}

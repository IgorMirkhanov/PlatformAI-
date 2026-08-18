"use client";

import { useCallback } from "react";
import { Position, type NodeProps } from "reactflow";
import { GitBranch } from "lucide-react";

import { FlowHandle } from "@/components/flow/nodes/FlowHandle";
import {
  flowFieldClassName,
  flowLabelClassName,
  FlowNodeShell,
} from "@/components/flow/nodes/FlowNodeShell";
import { FlowNodeWrapper } from "@/components/flow/nodes/FlowNodeWrapper";
import {
  LocalNodeInput,
  stopFlowKeyboardPropagation,
} from "@/components/flow/nodes/LocalNodeField";
import { useFlowStore } from "@/store/useFlowStore";
import type { ConditionNodeData, ConditionType } from "@/types/flow";

/** If / Else branch node with dual source handles. */
export function ConditionNode({ id, data, selected }: NodeProps<ConditionNodeData>) {
  const updateNodeData = useFlowStore((state) => state.updateNodeData);

  const commitTag = useCallback(
    (tag: string) => {
      updateNodeData(id, { tag });
    },
    [id, updateNodeData],
  );

  const commitExpression = useCallback(
    (expression: string) => {
      updateNodeData(id, { expression });
    },
    [id, updateNodeData],
  );

  const commitTrueLabel = useCallback(
    (true_label: string) => {
      updateNodeData(id, { true_label });
    },
    [id, updateNodeData],
  );

  const commitFalseLabel = useCallback(
    (false_label: string) => {
      updateNodeData(id, { false_label });
    },
    [id, updateNodeData],
  );

  return (
    <FlowNodeWrapper nodeId={id} selected={selected}>
      <FlowHandle
        type="target"
        position={Position.Left}
        className="!-left-1.5 !top-1/2 !bg-amber-400"
      />

      <FlowNodeShell
        selected={selected}
        accentClass="border-amber-500/20"
        title="Condition"
        subtitle={data.label || "If / Else"}
        icon={
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-500/10">
            <GitBranch className="h-4 w-4 text-amber-300" />
          </div>
        }
        footer={
          <div className="relative border-t border-zinc-800/90 px-4 pb-5 pt-3">
            <div className="flex justify-between text-[10px] font-semibold uppercase tracking-wider">
              <span className="text-emerald-400">If · {data.true_label || "Match"}</span>
              <span className="text-red-400">Else · {data.false_label || "Else"}</span>
            </div>
            <FlowHandle
              type="source"
              position={Position.Bottom}
              id="true"
              style={{ left: "28%" }}
              className="!bg-emerald-400"
            />
            <FlowHandle
              type="source"
              position={Position.Bottom}
              id="false"
              style={{ left: "72%" }}
              className="!bg-red-400"
            />
          </div>
        }
      >
        <div>
          <label className={flowLabelClassName}>Match parameter</label>
          <select
            value={data.condition_type}
            onChange={(event) =>
              updateNodeData(id, {
                condition_type: event.target.value as ConditionType,
              })
            }
            onKeyDown={stopFlowKeyboardPropagation}
            className={flowFieldClassName}
          >
            <option value="customer_tag">Customer tag</option>
            <option value="working_hours">Working hours</option>
            <option value="expression">Expression / keyword</option>
          </select>
        </div>

        {data.condition_type === "customer_tag" ? (
          <div>
            <label className={flowLabelClassName}>If tag equals</label>
            <LocalNodeInput
              externalValue={data.tag}
              onCommit={commitTag}
              placeholder="vip, hot-lead, mp-ai"
            />
          </div>
        ) : null}

        {data.condition_type === "expression" ? (
          <div>
            <label className={flowLabelClassName}>If expression matches</label>
            <LocalNodeInput
              externalValue={data.expression}
              onCommit={commitExpression}
              placeholder="true, pricing, refund"
            />
          </div>
        ) : null}

        {data.condition_type === "working_hours" ? (
          <p className="rounded-xl border border-dashed border-zinc-800 bg-zinc-950/70 px-3 py-2 text-xs text-zinc-500">
            If inside agent schedule →{" "}
            <span className="text-emerald-300">{data.true_label || "Match"}</span>
            , else → <span className="text-red-300">{data.false_label || "Else"}</span>.
          </p>
        ) : null}

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className={flowLabelClassName}>If branch label</label>
            <LocalNodeInput
              externalValue={data.true_label}
              onCommit={commitTrueLabel}
            />
          </div>
          <div>
            <label className={flowLabelClassName}>Else branch label</label>
            <LocalNodeInput
              externalValue={data.false_label}
              onCommit={commitFalseLabel}
            />
          </div>
        </div>
      </FlowNodeShell>
    </FlowNodeWrapper>
  );
}

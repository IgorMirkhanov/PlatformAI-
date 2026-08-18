"use client";

import { Position, type NodeProps } from "reactflow";
import { MessageSquare, Webhook, Zap } from "lucide-react";

import { FlowHandle } from "@/components/flow/nodes/FlowHandle";
import {
  flowFieldClassName,
  flowLabelClassName,
  FlowNodeShell,
} from "@/components/flow/nodes/FlowNodeShell";
import { FlowNodeWrapper } from "@/components/flow/nodes/FlowNodeWrapper";
import { useFlowStore } from "@/store/useFlowStore";
import type { TriggerNodeData, TriggerType } from "@/types/flow";

const TRIGGER_OPTIONS: Array<{ value: TriggerType; label: string; icon: typeof Zap }> = [
  { value: "message_received", label: "Message received", icon: MessageSquare },
  { value: "webhook", label: "Webhook", icon: Webhook },
  { value: "manual", label: "Manual / sandbox", icon: Zap },
];

export function TriggerNode({ id, data, selected }: NodeProps<TriggerNodeData>) {
  const updateNodeData = useFlowStore((state) => state.updateNodeData);

  return (
    <FlowNodeWrapper nodeId={id} selected={selected}>
      <FlowNodeShell
        selected={selected}
        accentClass="border-sky-500/25"
        title="Trigger"
        subtitle={data.label}
        widthClass="w-[320px]"
        icon={
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-500/10">
            <Zap className="h-4 w-4 text-sky-300" />
          </div>
        }
      >
        <div>
          <label className={flowLabelClassName}>Start when</label>
          <select
            value={data.trigger_type}
            onChange={(event) =>
              updateNodeData(id, { trigger_type: event.target.value as TriggerType })
            }
            className={flowFieldClassName}
          >
            {TRIGGER_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        {data.trigger_type === "webhook" ? (
          <div>
            <label className={flowLabelClassName}>Webhook path / event</label>
            <input
              value={data.webhook_event}
              onChange={(event) => updateNodeData(id, { webhook_event: event.target.value })}
              placeholder="/hooks/inbound or message.created"
              className={flowFieldClassName}
            />
          </div>
        ) : null}

        {data.trigger_type === "message_received" ? (
          <p className="rounded-xl border border-dashed border-zinc-800 bg-zinc-950/70 px-3 py-2 text-xs text-zinc-500">
            Fires when the connected channel delivers a new inbound customer message.
          </p>
        ) : null}

        <div>
          <label className={flowLabelClassName}>Display name</label>
          <input
            value={data.label}
            onChange={(event) => updateNodeData(id, { label: event.target.value })}
            className={flowFieldClassName}
          />
        </div>
      </FlowNodeShell>

      <FlowHandle
        type="source"
        position={Position.Right}
        id="default"
        className="!-right-1.5 !top-1/2 !bg-sky-400"
      />
    </FlowNodeWrapper>
  );
}

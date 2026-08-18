"use client";

import { MessageCircle } from "lucide-react";
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
import type { WhatsAppNodeData } from "@/types/flow";

/** WhatsApp outbound block — exports as text_message with channel=whatsapp metadata. */
export function WhatsAppNode({ id, data, selected }: NodeProps<WhatsAppNodeData>) {
  const updateNodeData = useFlowStore((state) => state.updateNodeData);

  return (
    <FlowNodeWrapper nodeId={id} selected={selected}>
      <FlowHandle
        type="target"
        position={Position.Left}
        className="!-left-1.5 !top-1/2 !bg-emerald-400"
      />

      <FlowNodeShell
        selected={selected}
        accentClass="border-emerald-500/25"
        title="WhatsApp"
        subtitle={data.label}
        icon={
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10">
            <MessageCircle className="h-4 w-4 text-emerald-300" />
          </div>
        }
      >
        <div>
          <label htmlFor={`${id}-wa-text`} className={flowLabelClassName}>
            Message template
          </label>
          <textarea
            id={`${id}-wa-text`}
            value={data.text}
            onChange={(event) => updateNodeData(id, { text: event.target.value })}
            placeholder="Здравствуйте, {{user_name}}! ..."
            rows={3}
            className={flowTextareaClassName}
          />
        </div>
        <div>
          <label htmlFor={`${id}-wa-media`} className={flowLabelClassName}>
            Media URL (optional)
          </label>
          <input
            id={`${id}-wa-media`}
            value={data.media_url ?? ""}
            onChange={(event) => updateNodeData(id, { media_url: event.target.value })}
            placeholder="https://..."
            className={flowFieldClassName}
          />
        </div>
      </FlowNodeShell>

      <FlowHandle
        type="source"
        position={Position.Right}
        className="!-right-1.5 !top-1/2 !bg-emerald-400"
      />
    </FlowNodeWrapper>
  );
}

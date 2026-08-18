"use client";

import { ImageIcon } from "lucide-react";
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
import type { ImageGenerationNodeData } from "@/types/flow";

const PROVIDER_LABELS = {
  kling: "Kling AI",
  nanobanana: "Nano Banana Pro",
} as const;

export function ImageGenerationNode({
  id,
  data,
  selected,
}: NodeProps<ImageGenerationNodeData>) {
  const updateNodeData = useFlowStore((state) => state.updateNodeData);

  return (
    <FlowNodeWrapper nodeId={id} selected={selected}>
      <FlowHandle
        type="target"
        position={Position.Left}
        className="!-left-1.5 !top-1/2 !bg-fuchsia-400"
      />

      <FlowNodeShell
        selected={selected}
        accentClass="border-fuchsia-500/20"
        title="Image Generation"
        subtitle={data.label || PROVIDER_LABELS[data.provider]}
        widthClass="w-[360px]"
        icon={
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-fuchsia-500/10">
            <ImageIcon className="h-4 w-4 text-fuchsia-300" />
          </div>
        }
      >
        <div>
          <label className={flowLabelClassName}>Provider</label>
          <div className={`${flowFieldClassName} text-zinc-300`}>
            {PROVIDER_LABELS[data.provider]}
          </div>
        </div>

        <div>
          <label htmlFor={`${id}-prompt`} className={flowLabelClassName}>
            Prompt template
          </label>
          <textarea
            id={`${id}-prompt`}
            rows={3}
            value={data.prompt_template}
            onChange={(event) => updateNodeData(id, { prompt_template: event.target.value })}
            className={flowTextareaClassName}
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className={flowLabelClassName}>Aspect ratio</label>
            <div className={`${flowFieldClassName} text-zinc-300`}>{data.aspect_ratio}</div>
          </div>
          <div>
            <label htmlFor={`${id}-result`} className={flowLabelClassName}>
              Result variable
            </label>
            <input
              id={`${id}-result`}
              value={data.result_variable}
              onChange={(event) => updateNodeData(id, { result_variable: event.target.value })}
              className={flowFieldClassName}
            />
          </div>
        </div>
      </FlowNodeShell>

      <FlowHandle
        type="source"
        position={Position.Right}
        id="default"
        className="!-right-1.5 !top-1/2 !bg-fuchsia-500"
      />
    </FlowNodeWrapper>
  );
}

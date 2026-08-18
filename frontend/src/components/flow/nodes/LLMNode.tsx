"use client";

import { useCallback } from "react";
import { Position, type NodeProps } from "reactflow";
import { Bot, Braces, Thermometer } from "lucide-react";

import { FlowHandle } from "@/components/flow/nodes/FlowHandle";
import {
  flowLabelClassName,
  FlowNodeShell,
} from "@/components/flow/nodes/FlowNodeShell";
import { FlowNodeWrapper } from "@/components/flow/nodes/FlowNodeWrapper";
import { LLMNodeConfig } from "@/components/flow/nodes/LLMNodeConfig";
import {
  LocalNodeInput,
  stopFlowKeyboardPropagation,
} from "@/components/flow/nodes/LocalNodeField";
import { cn } from "@/lib/utils";
import { useFlowStore } from "@/store/useFlowStore";
import type { LLMNodeData } from "@/types/flow";

const PROMPT_VARIABLES = [
  "{{message}}",
  "{{user_name}}",
  "{{channel}}",
  "{{tags}}",
  "{{rag_context}}",
  "{{api_response}}",
] as const;

/** LLM / AI Agent block — system prompt, temperature, and variable insertion. */
export function LLMNode({ id, data, selected }: NodeProps<LLMNodeData>) {
  const updateNodeData = useFlowStore((state) => state.updateNodeData);

  const commitPrompt = useCallback(
    (prompt_context: string) => {
      updateNodeData(id, { prompt_context });
    },
    [id, updateNodeData],
  );

  const commitModifier = useCallback(
    (prompt_modifier: string) => {
      updateNodeData(id, { prompt_modifier });
    },
    [id, updateNodeData],
  );

  const commitKb = useCallback(
    (knowledge_base_id: string) => {
      updateNodeData(id, { knowledge_base_id });
    },
    [id, updateNodeData],
  );

  const insertVariable = (token: string): void => {
    const next = data.prompt_context ? `${data.prompt_context.trimEnd()} ${token}` : token;
    updateNodeData(id, { prompt_context: next });
  };

  return (
    <FlowNodeWrapper nodeId={id} selected={selected}>
      <FlowHandle
        type="target"
        position={Position.Left}
        className="!-left-1.5 !top-1/2 !bg-violet-400"
      />

      <FlowNodeShell
        selected={selected}
        accentClass="border-violet-500/20"
        title="LLM"
        subtitle={data.label}
        icon={
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-500/10">
            <Bot className="h-4 w-4 text-violet-300" />
          </div>
        }
      >
        <LLMNodeConfig
          textareaId={`${id}-prompt`}
          modelSelectId={`${id}-model`}
          promptValue={data.prompt_context}
          modelName={data.model_name}
          onPromptChange={commitPrompt}
          onModelChange={(model_name) => updateNodeData(id, { model_name })}
          botTask={data.label}
          rows={4}
        />

        <div>
          <label className={flowLabelClassName}>
            <span className="inline-flex items-center gap-1.5">
              <Braces className="h-3 w-3" />
              Insert variable
            </span>
          </label>
          <div className="flex flex-wrap gap-1.5">
            {PROMPT_VARIABLES.map((token) => (
              <button
                key={token}
                type="button"
                onClick={() => insertVariable(token)}
                className={cn(
                  "nodrag rounded-full border border-zinc-800 bg-zinc-950/80 px-2.5 py-1",
                  "text-[11px] font-medium text-zinc-400 transition",
                  "hover:border-violet-500/40 hover:bg-violet-500/10 hover:text-violet-200",
                )}
              >
                {token}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label htmlFor={`${id}-temp`} className={flowLabelClassName}>
            <span className="inline-flex items-center gap-1.5">
              <Thermometer className="h-3 w-3" />
              Temperature
              <span className="ml-auto tabular-nums text-violet-300">
                {Number(data.temperature ?? 0.7).toFixed(2)}
              </span>
            </span>
          </label>
          <input
            id={`${id}-temp`}
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={data.temperature ?? 0.7}
            onChange={(event) =>
              updateNodeData(id, { temperature: Number(event.target.value) })
            }
            onKeyDown={stopFlowKeyboardPropagation}
            className="nodrag nowheel w-full accent-violet-500"
          />
          <div className="mt-1 flex justify-between text-[10px] uppercase tracking-wider text-zinc-600">
            <span>Precise</span>
            <span>Creative</span>
          </div>
        </div>

        <div>
          <label htmlFor={`${id}-modifier`} className={flowLabelClassName}>
            Prompt modifier
          </label>
          <LocalNodeInput
            id={`${id}-modifier`}
            externalValue={data.prompt_modifier}
            onCommit={commitModifier}
            placeholder="Be concise. Always offer next step."
          />
        </div>

        <div>
          <label htmlFor={`${id}-kb`} className={flowLabelClassName}>
            Knowledge base id (RAG)
          </label>
          <LocalNodeInput
            id={`${id}-kb`}
            externalValue={data.knowledge_base_id}
            onCommit={commitKb}
            placeholder="kb_faq_support"
          />
        </div>
      </FlowNodeShell>

      <FlowHandle
        type="source"
        position={Position.Right}
        id="default"
        className="!-right-1.5 !top-1/2 !bg-violet-500"
      />
    </FlowNodeWrapper>
  );
}

/** Backward-compatible alias used by older palette registrations. */
export { LLMNode as AIAgentNode };

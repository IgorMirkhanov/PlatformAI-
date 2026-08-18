"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Cpu, Loader2, Sparkles } from "lucide-react";

import { LocalNodeTextarea } from "@/components/flow/nodes/LocalNodeField";
import { flowLabelClassName } from "@/components/flow/nodes/FlowNodeShell";
import { optimizeAIPrompt } from "@/lib/api";
import { getAvailableLlmModels } from "@/services/api";
import { cn } from "@/lib/utils";
import {
  DEFAULT_LLM_MODEL,
  LLM_REGISTRY_BY_PROVIDER,
  resolveRegistryModel,
  type LLMRegistryOption,
} from "@/types/llm-models";
import type { LlmModelRecord } from "@/types/llm-model-api";

interface LLMNodeConfigProps {
  promptValue: string;
  onPromptChange: (value: string) => void;
  modelName?: string;
  onModelChange?: (value: string) => void;
  /** Optional bot task / use-case hint for the optimizer. */
  botTask?: string;
  textareaId?: string;
  modelSelectId?: string;
  rows?: number;
  className?: string;
  /** Use canvas-local buffered textarea (default) or plain controlled textarea. */
  variant?: "canvas" | "panel";
  textareaClassName?: string;
  selectClassName?: string;
}

function providerLabel(provider: string): string {
  const labels: Record<string, string> = {
    openai: "OpenAI",
    anthropic: "Anthropic",
    gemini: "Google Gemini",
    deepseek: "DeepSeek",
    glm: "GLM / Zhipu",
    qwen: "Qwen",
    ollama: "Ollama (local)",
    custom_openai: "Custom OpenAI-compatible",
    openrouter: "OpenRouter",
    vllm: "vLLM",
  };
  return labels[provider] ?? provider;
}

function toRegistryOption(row: LlmModelRecord): LLMRegistryOption {
  return {
    id: row.model_name,
    label: row.display_name,
    provider: row.provider,
    providerLabel: providerLabel(row.provider),
  };
}

export function LLMNodeConfig({
  promptValue,
  onPromptChange,
  modelName = DEFAULT_LLM_MODEL,
  onModelChange,
  botTask,
  textareaId = "llm-system-prompt",
  modelSelectId = "llm-model",
  rows = 4,
  className,
  variant = "canvas",
  textareaClassName,
  selectClassName,
}: LLMNodeConfigProps) {
  const [optimizing, setOptimizing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [remoteModels, setRemoteModels] = useState<LLMRegistryOption[] | null>(null);
  const [modelsLoading, setModelsLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setModelsLoading(true);
      try {
        const response = await getAvailableLlmModels({ activeOnly: true });
        if (cancelled) {
          return;
        }
        setRemoteModels(response.items.map(toRegistryOption));
      } catch {
        if (!cancelled) {
          setRemoteModels(null);
        }
      } finally {
        if (!cancelled) {
          setModelsLoading(false);
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const groupedModels = useMemo(() => {
    if (remoteModels && remoteModels.length > 0) {
      const groups = new Map<string, LLMRegistryOption[]>();
      for (const option of remoteModels) {
        const label = option.providerLabel ?? providerLabel(option.provider);
        const bucket = groups.get(label) ?? [];
        bucket.push(option);
        groups.set(label, bucket);
      }
      return Object.fromEntries(groups.entries());
    }
    return LLM_REGISTRY_BY_PROVIDER;
  }, [remoteModels]);

  const selectedModel = useMemo(() => {
    if (remoteModels?.length) {
      const hit = remoteModels.find((item) => item.id === modelName);
      if (hit) {
        return hit;
      }
    }
    return resolveRegistryModel(modelName);
  }, [modelName, remoteModels]);

  const handleOptimize = useCallback(async () => {
    const source = promptValue.trim();
    if (!source) {
      setError("Введите текст промпта перед улучшением.");
      return;
    }

    setOptimizing(true);
    setError(null);
    try {
      const response = await optimizeAIPrompt({
        prompt_text: source,
        bot_task: botTask?.trim() || null,
      });
      onPromptChange(response.optimized_prompt);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Не удалось улучшить промпт. Попробуйте позже.";
      setError(message);
    } finally {
      setOptimizing(false);
    }
  }, [botTask, onPromptChange, promptValue]);

  const selectClass =
    selectClassName ??
    cn(
      "nodrag w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-violet-500/50",
    );

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      {onModelChange ? (
        <div className="flex flex-col gap-1.5">
          <label htmlFor={modelSelectId} className={flowLabelClassName}>
            <span className="inline-flex items-center gap-1.5">
              <Cpu className="h-3 w-3 text-violet-300" />
              Model
              {modelsLoading ? (
                <Loader2 className="h-3 w-3 animate-spin text-zinc-500" aria-hidden />
              ) : null}
            </span>
          </label>
          <select
            id={modelSelectId}
            value={selectedModel.id}
            onChange={(event) => onModelChange(event.target.value)}
            className={selectClass}
          >
            {Object.entries(groupedModels).map(([providerLabelText, options]) => (
              <optgroup key={providerLabelText} label={providerLabelText}>
                {options.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          <p className="text-[10px] text-zinc-600">
            {selectedModel.providerLabel} · {selectedModel.id}
            {remoteModels ? " · catalog from API" : " · static fallback"}
          </p>
        </div>
      ) : null}

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <label htmlFor={textareaId} className={flowLabelClassName}>
            <span className="inline-flex items-center gap-1.5">
              <Sparkles className="h-3 w-3 text-violet-300" />
              System prompt
            </span>
          </label>
          <button
            type="button"
            onClick={() => void handleOptimize()}
            disabled={optimizing}
            className="nodrag inline-flex items-center gap-1 rounded-lg border border-violet-500/30 bg-violet-500/10 px-2 py-1 text-[10px] font-medium text-violet-200 transition hover:bg-violet-500/20 disabled:opacity-50"
          >
            {optimizing ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
            Improve prompt
          </button>
        </div>
        {variant === "canvas" ? (
          <LocalNodeTextarea
            id={textareaId}
            externalValue={promptValue}
            onCommit={onPromptChange}
            rows={rows}
            className={textareaClassName}
          />
        ) : (
          <textarea
            id={textareaId}
            value={promptValue}
            onChange={(event) => onPromptChange(event.target.value)}
            rows={rows}
            className={textareaClassName}
          />
        )}
        {error ? <p className="text-xs text-red-400">{error}</p> : null}
      </div>
    </div>
  );
}

"use client";

import { Cpu } from "lucide-react";

import { TemperatureSlider } from "@/components/prompting/TemperatureSlider";
import { Toggle } from "@/components/ui/Toggle";
import { formatCurrency } from "@/lib/dashboard-utils";
import { LLM_MODEL_OPTIONS } from "@/types/agent";
import {
  PROMPTING_CONTEXT_TOGGLES,
  type PromptingContextVisibility,
  type PromptingModelConfig,
} from "@/types/prompting";

interface NeuralModelSidebarProps {
  model: PromptingModelConfig;
  visibility: PromptingContextVisibility;
  onModelChange: (model: PromptingModelConfig) => void;
  onVisibilityChange: (visibility: PromptingContextVisibility) => void;
  disabled?: boolean;
}

export function NeuralModelSidebar({
  model,
  visibility,
  onModelChange,
  onVisibilityChange,
  disabled = false,
}: NeuralModelSidebarProps) {
  const selectedModel =
    LLM_MODEL_OPTIONS.find((option) => option.id === model.llm_model_name) ?? LLM_MODEL_OPTIONS[0];

  return (
    <aside className="moonai-panel flex flex-col gap-6 lg:sticky lg:top-24 lg:self-start">
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-500">
          Neural Model Matrix
        </p>
        <h3 className="mt-1 flex items-center gap-2 text-base font-semibold text-zinc-50">
          <Cpu className="h-4 w-4 text-violet-400" />
          LLM Tuning
        </h3>
      </div>

      <div>
        <label htmlFor="neural-model-select" className="text-xs text-zinc-500">
          Model Selector
        </label>
        <select
          id="neural-model-select"
          disabled={disabled}
          value={model.llm_model_name}
          onChange={(event) =>
            onModelChange({ ...model, llm_model_name: event.target.value })
          }
          className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-950/80 px-3 py-2.5 text-sm text-zinc-100 focus:border-violet-500 focus:outline-none"
        >
          {LLM_MODEL_OPTIONS.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label} · {option.provider}
            </option>
          ))}
        </select>

        <div className="mt-3 rounded-xl border border-zinc-800/80 bg-black/30 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-zinc-100">{selectedModel.label}</p>
            <span className="rounded-full bg-violet-500/15 px-2 py-0.5 text-[10px] font-semibold text-violet-300">
              {formatCurrency(selectedModel.costPer1kTokens)} / 1k
            </span>
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">{selectedModel.description}</p>
        </div>
      </div>

      <TemperatureSlider
        value={model.llm_temperature}
        onChange={(llm_temperature) => onModelChange({ ...model, llm_temperature })}
        disabled={disabled}
      />

      <div className="space-y-4 border-t border-zinc-800/80 pt-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">
            Context Injector
          </p>
          <p className="mt-1 text-[11px] text-zinc-600">
            Переменные, автоматически добавляемые в orchestration prompt.
          </p>
        </div>

        {PROMPTING_CONTEXT_TOGGLES.map((toggle) => (
          <div
            key={toggle.key}
            className="rounded-xl border border-zinc-800/80 bg-zinc-950/40 px-3 py-3"
          >
            <Toggle
              checked={visibility[toggle.key]}
              disabled={disabled}
              onChange={(checked) =>
                onVisibilityChange({ ...visibility, [toggle.key]: checked })
              }
              label={toggle.label}
              description={toggle.description}
            />
          </div>
        ))}
      </div>
    </aside>
  );
}

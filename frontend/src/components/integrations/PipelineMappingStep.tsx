"use client";

import { useMemo } from "react";
import { Loader2 } from "lucide-react";

import { TagsChipInput } from "@/components/integrations/TagsChipInput";
import {
  buildPipelineOptions,
  filterStagesForPipeline,
  type CRMPipelineMappingForm,
  type CRMPipelineStage,
} from "@/types/crm";

interface PipelineMappingStepProps {
  stages: CRMPipelineStage[];
  loading: boolean;
  value: CRMPipelineMappingForm;
  onChange: (value: CRMPipelineMappingForm) => void;
  disabled?: boolean;
}

export function PipelineMappingStep({
  stages,
  loading,
  value,
  onChange,
  disabled = false,
}: PipelineMappingStepProps) {
  const pipelineOptions = useMemo(() => buildPipelineOptions(stages), [stages]);
  const stageOptions = useMemo(
    () => filterStagesForPipeline(stages, value.pipeline_id),
    [stages, value.pipeline_id],
  );

  if (loading) {
    return (
      <div className="flex min-h-[220px] items-center justify-center text-sm text-zinc-500">
        <Loader2 className="mr-2 h-4 w-4 animate-spin text-violet-400" />
        Загрузка воронок из CRM…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <label htmlFor="crm-pipeline" className="text-xs text-zinc-500">
          Выбор воронки
        </label>
        <select
          id="crm-pipeline"
          disabled={disabled || pipelineOptions.length === 0}
          value={value.pipeline_id}
          onChange={(event) =>
            onChange({
              ...value,
              pipeline_id: event.target.value,
              stage_id: "",
            })
          }
          className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 focus:border-violet-500 focus:outline-none"
        >
          <option value="">Выберите воронку</option>
          {pipelineOptions.map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="crm-stage" className="text-xs text-zinc-500">
          Этап создания сделки
        </label>
        <select
          id="crm-stage"
          disabled={disabled || !value.pipeline_id || stageOptions.length === 0}
          value={value.stage_id}
          onChange={(event) => onChange({ ...value, stage_id: event.target.value })}
          className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 focus:border-violet-500 focus:outline-none"
        >
          <option value="">Выберите этап</option>
          {stageOptions.map((stage) => (
            <option key={stage.id} value={stage.id}>
              {stage.name}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="text-xs text-zinc-500">Системные теги по умолчанию</label>
        <p className="mt-1 text-[11px] text-zinc-600">
          AI executor добавит эти теги к каждой новой сделке, созданной через Celery `crm_actions`.
        </p>
        <div className="mt-2">
          <TagsChipInput
            value={value.default_tags}
            onChange={(default_tags) => onChange({ ...value, default_tags })}
            disabled={disabled}
          />
        </div>
      </div>
    </div>
  );
}

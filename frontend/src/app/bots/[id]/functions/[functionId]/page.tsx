"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Plus, Trash2 } from "lucide-react";

import { PageSkeleton } from "@/components/ui/Skeleton";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/hooks/useToast";
import { useAgentWorkspace } from "@/hooks/useAgentWorkspace";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import {
  FUNCTION_INTEGRATION_OPTIONS,
  FUNCTION_NAME_PATTERN,
  type FunctionParamType,
  type FunctionToolDefinition,
  type FunctionToolParameter,
} from "@/types/agent";

const PARAM_TYPES: FunctionParamType[] = ["string", "number", "boolean"];

export default function FunctionEditorPage() {
  const params = useParams<{ id: string; functionId: string }>();
  const botId = params.id;
  const functionId = params.functionId;
  const router = useRouter();
  const { profile, loading } = useAgentWorkspace(botId);
  const saveAgentFunctions = useBotStore((state) => state.saveAgentFunctions);
  const saving = useBotStore((state) => state.profileSaving[botId] ?? false);
  const { showToast } = useToast();

  const source = useMemo(
    () => (profile?.function_tools ?? []).find((item) => item.id === functionId),
    [profile, functionId],
  );

  const [draft, setDraft] = useState<FunctionToolDefinition | null>(null);
  const current = draft ?? source ?? null;

  if (loading && !profile) return <PageSkeleton />;
  if (!profile) return null;
  if (!current) {
    return (
      <div className="rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-8 text-center text-sm text-zinc-500">
        Функция не найдена.{" "}
        <Link href={`/bots/${botId}/functions`} className="text-violet-300 hover:underline">
          К списку
        </Link>
      </div>
    );
  }

  const update = (patch: Partial<FunctionToolDefinition>): void => {
    setDraft({ ...current, ...patch });
  };

  const updateParam = (index: number, patch: Partial<FunctionToolParameter>): void => {
    const parameters = current.parameters.map((item, i) => (i === index ? { ...item, ...patch } : item));
    update({ parameters });
  };

  const handleSave = async (): Promise<void> => {
    if (!FUNCTION_NAME_PATTERN.test(current.name.trim())) {
      showToast("Название: латиница, цифры и _, начинается с буквы.", "error");
      return;
    }
    const next = (profile.function_tools ?? []).map((item) =>
      item.id === current.id ? { ...current, name: current.name.trim() } : item,
    );
    try {
      await saveAgentFunctions(botId, { function_tools: next });
      showToast("Функция сохранена. LLM получит её в формате tools[].", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось сохранить функцию."), "error");
    }
  };

  const handleDelete = async (): Promise<void> => {
    const next = (profile.function_tools ?? []).filter((item) => item.id !== current.id);
    try {
      await saveAgentFunctions(botId, { function_tools: next });
      router.push(`/bots/${botId}/functions`);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось удалить функцию."), "error");
    }
  };

  return (
    <div className="space-y-5">
      <Link
        href={`/bots/${botId}/functions`}
        className="inline-flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-200"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        К списку функций
      </Link>

      <div className="rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-5 space-y-4">
        <div>
          <label className="text-xs font-medium text-zinc-400">Название функции</label>
          <input
            value={current.name}
            onChange={(event) => update({ name: event.target.value })}
            className="mt-1.5 h-11 w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 font-mono text-sm text-zinc-100 focus:border-violet-500/40 focus:outline-none"
          />
        </div>
        <div>
          <label className="text-xs font-medium text-zinc-400">Описание (когда LLM должна вызвать функцию)</label>
          <textarea
            value={current.description}
            onChange={(event) => update({ description: event.target.value })}
            rows={3}
            className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm text-zinc-100 focus:border-violet-500/40 focus:outline-none"
          />
        </div>
      </div>

      <div className="rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-5 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-zinc-100">Параметры функции</h3>
          <button
            type="button"
            onClick={() =>
              update({
                parameters: [
                  ...current.parameters,
                  { name: "param", type: "string", instruction: "", required: false },
                ],
              })
            }
            className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-800 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-900"
          >
            <Plus className="h-3.5 w-3.5" />
            Параметр
          </button>
        </div>
        {current.parameters.length === 0 ? (
          <p className="text-xs text-zinc-500">Параметров нет — функция вызывается без аргументов.</p>
        ) : (
          current.parameters.map((param, index) => (
            <div key={`${param.name}-${index}`} className="grid gap-2 rounded-xl border border-zinc-800 p-3 md:grid-cols-12">
              <input
                value={param.name}
                onChange={(event) => updateParam(index, { name: event.target.value })}
                placeholder="Название"
                className="md:col-span-3 h-10 rounded-lg border border-zinc-800 bg-zinc-950 px-2 font-mono text-xs text-zinc-100"
              />
              <select
                value={param.type}
                onChange={(event) => updateParam(index, { type: event.target.value as FunctionParamType })}
                className="md:col-span-2 h-10 rounded-lg border border-zinc-800 bg-zinc-950 px-2 text-xs text-zinc-100"
              >
                {PARAM_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type === "string" ? "String" : type === "number" ? "Number" : "Boolean"}
                  </option>
                ))}
              </select>
              <input
                value={param.instruction}
                onChange={(event) => updateParam(index, { instruction: event.target.value })}
                placeholder="Инструкция"
                className="md:col-span-5 h-10 rounded-lg border border-zinc-800 bg-zinc-950 px-2 text-xs text-zinc-100"
              />
              <label className="md:col-span-1 flex items-center gap-2 text-[11px] text-zinc-400">
                <input
                  type="checkbox"
                  checked={param.required}
                  onChange={(event) => updateParam(index, { required: event.target.checked })}
                />
                Обяз.
              </label>
              <button
                type="button"
                onClick={() =>
                  update({ parameters: current.parameters.filter((_, i) => i !== index) })
                }
                className="md:col-span-1 flex h-10 items-center justify-center rounded-lg text-rose-300 hover:bg-zinc-900"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-5 space-y-3">
          <h3 className="text-sm font-semibold text-zinc-100">Реакция на выполнение</h3>
          <div className="flex gap-2">
            {(["llm", "fixed"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => update({ reaction_mode: mode })}
                className={`rounded-lg px-3 py-1.5 text-xs ${
                  current.reaction_mode === mode
                    ? "bg-violet-600/20 text-violet-200 ring-1 ring-violet-500/30"
                    : "text-zinc-500 hover:text-zinc-200"
                }`}
              >
                {mode === "llm" ? "ИИ сам решает" : "Фиксированный ответ"}
              </button>
            ))}
          </div>
          {current.reaction_mode === "fixed" ? (
            <textarea
              value={current.reaction_text}
              onChange={(event) => update({ reaction_text: event.target.value })}
              rows={3}
              className="w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
            />
          ) : null}
        </div>
        <div className="rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-5 space-y-3">
          <h3 className="text-sm font-semibold text-zinc-100">Отправка результатов (Интеграции)</h3>
          <select
            value={current.integration}
            onChange={(event) =>
              update({ integration: event.target.value as FunctionToolDefinition["integration"] })
            }
            className="h-11 w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 text-sm text-zinc-100"
          >
            {FUNCTION_INTEGRATION_OPTIONS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
          <div className="flex items-center justify-between pt-2">
            <span className="text-xs text-zinc-500">Активна</span>
            <Switch
              checked={current.is_active}
              onCheckedChange={(checked) => update({ is_active: checked })}
            />
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={saving}
          onClick={() => void handleSave()}
          className="rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
        >
          Сохранить
        </button>
        <button
          type="button"
          onClick={() => void handleDelete()}
          className="rounded-xl border border-rose-500/30 px-4 py-2.5 text-sm text-rose-300 hover:bg-rose-500/10"
        >
          Удалить
        </button>
      </div>
    </div>
  );
}

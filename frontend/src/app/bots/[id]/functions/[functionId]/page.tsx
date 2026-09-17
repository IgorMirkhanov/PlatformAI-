"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, GripVertical, Info, MoreVertical, Plus, Trash2 } from "lucide-react";

import { PageSkeleton } from "@/components/ui/Skeleton";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/hooks/useToast";
import { useAgentWorkspace } from "@/hooks/useAgentWorkspace";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import {
  FUNCTION_INTEGRATION_OPTIONS,
  FUNCTION_NAME_PATTERN,
  type FunctionIntegrationKind,
  type FunctionParamType,
  type FunctionResultField,
  type FunctionToolDefinition,
  type FunctionToolParameter,
} from "@/types/agent";
import { cn } from "@/lib/utils";

const PARAM_TYPES: Array<{ id: FunctionParamType; label: string }> = [
  { id: "string", label: "Текстовый" },
  { id: "number", label: "Числовой" },
  { id: "boolean", label: "Логический" },
];

const RESULT_INTEGRATION_PICKER = FUNCTION_INTEGRATION_OPTIONS.filter((o) => o.id !== "none");

const fieldClass =
  "h-9 w-full rounded-lg border border-zinc-600 bg-[#0c0c0e] px-2.5 text-sm text-zinc-100 outline-none transition placeholder:text-zinc-500 focus:border-violet-500 focus:ring-1 focus:ring-violet-500/40";

const primaryBtnClass =
  "inline-flex items-center justify-center gap-1.5 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white shadow-[0_0_0_1px_rgba(139,92,246,0.4),0_6px_18px_rgba(124,58,237,0.3)] transition hover:bg-violet-500 disabled:opacity-50";

const dangerBtnClass =
  "inline-flex items-center justify-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2.5 text-sm font-semibold text-white shadow-[0_0_0_1px_rgba(244,63,94,0.35)] transition hover:bg-rose-500 disabled:opacity-50";

function Section({
  title,
  children,
  action,
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <section className="space-y-3 rounded-2xl border border-zinc-700/90 bg-[#121214] p-4 shadow-soft sm:p-5">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-zinc-50">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-zinc-400">{children}</label>;
}

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
  const allFunctions = profile?.function_tools ?? [];

  if (loading && !profile) return <PageSkeleton />;
  if (!profile) return null;
  if (!current) {
    return (
      <div className="rounded-2xl border border-zinc-700 bg-[#121214] p-8 text-center text-sm text-zinc-400">
        Функция не найдена.{" "}
        <Link href={`/bots/${botId}/functions`} className="text-violet-400 hover:underline">
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

  const addParam = (): void => {
    update({
      parameters: [
        ...current.parameters,
        { name: "param", type: "string", instruction: "", required: false, enum_values: "" },
      ],
    });
  };

  const resultIntegrations = current.result_integrations ?? (
    current.integration !== "none" ? [current.integration] : []
  );
  const resultFields = current.result_fields ?? [];

  const toggleIntegration = (id: FunctionIntegrationKind): void => {
    const next = resultIntegrations.includes(id)
      ? resultIntegrations.filter((x) => x !== id)
      : [...resultIntegrations, id];
    update({
      result_integrations: next,
      integration: next[0] ?? "none",
    });
  };

  const updateField = (index: number, patch: Partial<FunctionResultField>): void => {
    const next = resultFields.map((row, i) => (i === index ? { ...row, ...patch } : row));
    update({ result_fields: next });
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
      showToast("Функция сохранена.", "success");
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
    <div className="mx-auto max-w-4xl space-y-4 pb-16">
      <nav className="flex flex-wrap items-center gap-1.5 text-xs text-zinc-500">
        <Link href="/dashboard" className="hover:text-zinc-200">
          ИИ-Агенты
        </Link>
        <span>/</span>
        <span className="text-zinc-300">{profile.name}</span>
        <span>/</span>
        <Link href={`/bots/${botId}/functions`} className="hover:text-zinc-200">
          Функции
        </Link>
        <span>/</span>
        <span className="font-mono text-violet-400">{current.name}</span>
      </nav>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-mono text-2xl font-semibold text-zinc-50">{current.name}</h1>
        <Link
          href={`/bots/${botId}/functions`}
          className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-600 bg-[#0c0c0e] px-3 py-1.5 text-xs font-medium text-zinc-200 transition hover:border-violet-500/50 hover:text-white"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          К списку
        </Link>
      </div>

      <Section title="Детали функции">
        <div>
          <FieldLabel>Название</FieldLabel>
          <input
            value={current.name}
            onChange={(e) => update({ name: e.target.value })}
            className={cn(fieldClass, "font-mono")}
          />
        </div>
        <div>
          <FieldLabel>Описание</FieldLabel>
          <textarea
            value={current.description}
            onChange={(e) => update({ description: e.target.value })}
            rows={3}
            className={cn(fieldClass, "h-auto min-h-[4.5rem] py-2")}
          />
        </div>
        <div className="flex items-center justify-between gap-3 rounded-xl border border-zinc-600 bg-[#0c0c0e] px-3.5 py-2.5">
          <div>
            <p className="text-sm font-medium text-zinc-100">Статус функции</p>
            <p className="text-[11px] text-zinc-400">Активировать или деактивировать</p>
          </div>
          <Switch
            checked={current.is_active}
            onCheckedChange={(v) => update({ is_active: v })}
          />
        </div>
      </Section>

      <Section title="Параметры функции">
        {current.parameters.length === 0 ? (
          <p className="text-xs text-zinc-500">Параметров нет — добавьте первый.</p>
        ) : (
          <div className="space-y-2.5">
            <div className="hidden grid-cols-[auto_minmax(7rem,0.9fr)_minmax(7rem,0.85fr)_minmax(12rem,1.6fr)_auto] gap-2 px-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500 sm:grid">
              <span className="w-5" />
              <span>Название</span>
              <span>Тип параметра</span>
              <span>Инструкция</span>
              <span className="w-8" />
            </div>

            {current.parameters.map((param, index) => (
              <div
                key={`${param.name}-${index}`}
                className="rounded-xl border border-zinc-600 bg-[#0c0c0e] p-2.5 sm:p-3"
              >
                <div className="grid grid-cols-1 items-start gap-2 sm:grid-cols-[auto_minmax(7rem,0.9fr)_minmax(7rem,0.85fr)_minmax(12rem,1.6fr)_auto]">
                  <div className="hidden h-9 items-center text-zinc-500 sm:flex">
                    <GripVertical className="h-4 w-4" />
                  </div>

                  <div>
                    <span className="mb-1 block text-[10px] font-medium uppercase tracking-wide text-zinc-500 sm:hidden">
                      Название
                    </span>
                    <input
                      value={param.name}
                      onChange={(e) => updateParam(index, { name: e.target.value })}
                      className={cn(fieldClass, "font-mono text-[13px]")}
                      placeholder="param_name"
                    />
                  </div>

                  <div>
                    <span className="mb-1 block text-[10px] font-medium uppercase tracking-wide text-zinc-500 sm:hidden">
                      Тип
                    </span>
                    <select
                      value={param.type}
                      onChange={(e) => updateParam(index, { type: e.target.value as FunctionParamType })}
                      className={fieldClass}
                    >
                      {PARAM_TYPES.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <span className="mb-1 block text-[10px] font-medium uppercase tracking-wide text-zinc-500 sm:hidden">
                      Инструкция
                    </span>
                    <input
                      value={param.instruction}
                      onChange={(e) => updateParam(index, { instruction: e.target.value })}
                      className={fieldClass}
                      placeholder="Как LLM заполняет параметр"
                    />
                  </div>

                  <div className="flex h-9 items-center justify-end gap-1">
                    <button
                      type="button"
                      aria-label="Меню параметра"
                      className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-600 text-zinc-300 transition hover:border-zinc-400 hover:text-white"
                    >
                      <MoreVertical className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      aria-label="Удалить параметр"
                      onClick={() =>
                        update({ parameters: current.parameters.filter((_, i) => i !== index) })
                      }
                      className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-rose-500/40 bg-rose-500/10 text-rose-300 transition hover:bg-rose-500/20 hover:text-rose-200"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>

                <div className="mt-2.5 flex flex-col gap-2 border-t border-zinc-700/80 pt-2.5 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0 flex-1 sm:max-w-md">
                    <span className="mb-1 block text-[10px] font-medium uppercase tracking-wide text-zinc-500">
                      Возможные значения
                    </span>
                    <input
                      value={param.enum_values ?? ""}
                      onChange={(e) => updateParam(index, { enum_values: e.target.value })}
                      placeholder="Добавить значение…"
                      className={fieldClass}
                    />
                  </div>
                  <label className="inline-flex cursor-pointer items-center gap-2 self-start rounded-lg border border-zinc-600 bg-[#121214] px-3 py-2 text-sm text-zinc-100 sm:mt-5">
                    <input
                      type="checkbox"
                      checked={param.required}
                      onChange={(e) => updateParam(index, { required: e.target.checked })}
                      className="h-4 w-4 rounded border-zinc-500 text-violet-600 focus:ring-violet-500/40"
                    />
                    Обязательный параметр
                  </label>
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="flex justify-center pt-1">
          <button
            type="button"
            onClick={addParam}
            aria-label="Добавить параметр"
            className={cn(
              "inline-flex h-10 w-10 items-center justify-center rounded-full",
              "bg-violet-600 text-white",
              "shadow-[0_0_0_1px_rgba(139,92,246,0.5),0_8px_22px_rgba(124,58,237,0.4)]",
              "transition hover:bg-violet-500",
            )}
          >
            <Plus className="h-5 w-5" strokeWidth={2.5} />
          </button>
        </div>
      </Section>

      <Section title="Реакция на выполнение функции">
        <div>
          <FieldLabel>Действие</FieldLabel>
          <select
            value={current.reaction_mode}
            onChange={(e) => update({ reaction_mode: e.target.value as "llm" | "fixed" })}
            className={fieldClass}
          >
            <option value="llm">ИИ-агент сам решит</option>
            <option value="fixed">Автоматический ответ</option>
          </select>
        </div>
        {current.reaction_mode === "fixed" ? (
          <div>
            <FieldLabel>Текст ответа</FieldLabel>
            <textarea
              value={current.reaction_text}
              onChange={(e) => update({ reaction_text: e.target.value })}
              rows={3}
              className={cn(fieldClass, "h-auto min-h-[4.5rem] py-2")}
            />
          </div>
        ) : (
          <div className="flex gap-3 rounded-xl border border-violet-500/30 bg-violet-500/10 px-3.5 py-2.5">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-violet-300" />
            <p className="text-xs leading-relaxed text-zinc-300">
              ИИ самостоятельно сформирует ответ по результатам функции без дополнительных инструкций.
            </p>
          </div>
        )}
      </Section>

      <Section title="Пост-сценарий">
        <div>
          <FieldLabel>Действие</FieldLabel>
          <select
            value={current.post_scenario ?? "continue"}
            onChange={(e) =>
              update({ post_scenario: e.target.value as "continue" | "end" })
            }
            className={fieldClass}
          >
            <option value="continue">Продолжать диалог</option>
            <option value="end">Завершить диалог</option>
          </select>
        </div>
      </Section>

      <Section title="Вложенные функции">
        <div>
          <FieldLabel>Целевая функция</FieldLabel>
          <select
            value={current.nested_function_id ?? ""}
            onChange={(e) => update({ nested_function_id: e.target.value || null })}
            className={fieldClass}
          >
            <option value="">Выберите функцию</option>
            {allFunctions
              .filter((fn) => fn.id !== current.id)
              .map((fn) => (
                <option key={fn.id} value={fn.id}>
                  {fn.name}
                </option>
              ))}
          </select>
        </div>
      </Section>

      <Section title="Отключить отложенные сообщения">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-zinc-400">
            После выполнения этой функции отложенные сообщения будут отключены.
          </p>
          <Switch
            checked={Boolean(current.disable_delayed_messages)}
            onCheckedChange={(v) => update({ disable_delayed_messages: v })}
          />
        </div>
      </Section>

      <Section title="Отправка результатов">
        <div>
          <FieldLabel>Интеграции</FieldLabel>
          <div className="mt-1.5 flex flex-wrap gap-2">
            {RESULT_INTEGRATION_PICKER.map((opt) => {
              const active = resultIntegrations.includes(opt.id);
              return (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => toggleIntegration(opt.id)}
                  className={cn(
                    "rounded-lg border px-3 py-1.5 text-xs font-semibold transition",
                    active
                      ? "border-violet-400/60 bg-violet-600 text-white shadow-[0_0_0_1px_rgba(167,139,250,0.35)]"
                      : "border-zinc-600 bg-[#0c0c0e] text-zinc-300 hover:border-zinc-400 hover:text-white",
                  )}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="space-y-2">
          <div className="grid grid-cols-[1fr_1fr_1fr_auto] gap-2 px-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            <span>Имя</span>
            <span>Действие</span>
            <span>Значение</span>
            <span />
          </div>
          {resultFields.map((field, index) => (
            <div
              key={field.id}
              className="grid grid-cols-[1fr_1fr_1fr_auto] items-center gap-2 rounded-xl border border-zinc-600 bg-[#0c0c0e] p-2"
            >
              <input
                value={field.name}
                onChange={(e) => updateField(index, { name: e.target.value })}
                className={cn(fieldClass, "h-8 text-xs")}
              />
              <select
                value={field.action}
                onChange={(e) =>
                  updateField(index, { action: e.target.value as "text" | "system" })
                }
                className={cn(fieldClass, "h-8 text-xs")}
              >
                <option value="text">Текст</option>
                <option value="system">Системные параметры</option>
              </select>
              <input
                value={field.value}
                onChange={(e) => updateField(index, { value: e.target.value })}
                className={cn(fieldClass, "h-8 text-xs")}
              />
              <button
                type="button"
                onClick={() =>
                  update({ result_fields: resultFields.filter((_, i) => i !== index) })
                }
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-rose-500/40 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() =>
              update({
                result_fields: [
                  ...resultFields,
                  { id: crypto.randomUUID(), name: "", action: "text", value: "" },
                ],
              })
            }
            className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-violet-600 text-white shadow-[0_0_0_1px_rgba(139,92,246,0.45)] hover:bg-violet-500"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>
      </Section>

      <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
        <button type="button" onClick={() => void handleDelete()} className={dangerBtnClass}>
          Удалить функцию
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => void handleSave()}
          className={primaryBtnClass}
        >
          Сохранить
        </button>
      </div>
    </div>
  );
}

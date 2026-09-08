"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, GripVertical, Info, Plus, Trash2 } from "lucide-react";

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
    <section className="space-y-4 rounded-2xl border border-[var(--canvas-border)] bg-[var(--card)] p-5 shadow-soft">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-[var(--canvas-fg)]">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return <label className="text-xs font-medium text-[var(--canvas-muted)]">{children}</label>;
}

const inputClass =
  "mt-1.5 h-11 w-full rounded-xl border border-[var(--canvas-border)] bg-[var(--canvas)] px-3 text-sm text-[var(--canvas-fg)] outline-none focus:border-violet-500/40";

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
      <div className="rounded-2xl border border-[var(--canvas-border)] bg-[var(--card)] p-8 text-center text-sm text-[var(--canvas-muted)]">
        Функция не найдена.{" "}
        <Link href={`/bots/${botId}/functions`} className="text-violet-500 hover:underline">
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
    <div className="mx-auto max-w-3xl space-y-5 pb-16">
      <nav className="flex flex-wrap items-center gap-1.5 text-xs text-[var(--canvas-muted)]">
        <Link href="/dashboard" className="hover:text-[var(--canvas-fg)]">
          ИИ-Агенты
        </Link>
        <span>/</span>
        <span className="text-[var(--canvas-fg)]">{profile.name}</span>
        <span>/</span>
        <Link href={`/bots/${botId}/functions`} className="hover:text-[var(--canvas-fg)]">
          Функции
        </Link>
        <span>/</span>
        <span className="font-mono text-violet-400">{current.name}</span>
      </nav>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-mono text-2xl font-semibold text-[var(--canvas-fg)]">{current.name}</h1>
        <Link
          href={`/bots/${botId}/functions`}
          className="inline-flex items-center gap-1.5 text-xs text-[var(--canvas-muted)] hover:text-[var(--canvas-fg)]"
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
            className={cn(inputClass, "font-mono")}
          />
        </div>
        <div>
          <FieldLabel>Описание</FieldLabel>
          <textarea
            value={current.description}
            onChange={(e) => update({ description: e.target.value })}
            rows={3}
            className={cn(inputClass, "h-auto py-2.5")}
          />
        </div>
        <div className="flex items-center justify-between gap-3 rounded-xl border border-[var(--canvas-border)] bg-[var(--canvas)] px-4 py-3">
          <div>
            <p className="text-sm font-medium text-[var(--canvas-fg)]">Статус функции</p>
            <p className="text-xs text-[var(--canvas-muted)]">Активировать или деактивировать</p>
          </div>
          <Switch checked={current.is_active} onCheckedChange={(v) => update({ is_active: v })} />
        </div>
      </Section>

      <Section
        title="Параметры функции"
        action={
          <button
            type="button"
            onClick={() =>
              update({
                parameters: [
                  ...current.parameters,
                  { name: "param", type: "string", instruction: "", required: false, enum_values: "" },
                ],
              })
            }
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--canvas-border)] px-3 py-1.5 text-xs text-[var(--canvas-fg)] hover:bg-[var(--canvas)]"
          >
            <Plus className="h-3.5 w-3.5" />
            Параметр
          </button>
        }
      >
        {current.parameters.length === 0 ? (
          <p className="text-xs text-[var(--canvas-muted)]">Параметров нет.</p>
        ) : (
          <div className="space-y-3">
            {current.parameters.map((param, index) => (
              <div
                key={`${param.name}-${index}`}
                className="rounded-xl border border-[var(--canvas-border)] bg-[var(--canvas)] p-4"
              >
                <div className="mb-3 flex items-center justify-between">
                  <GripVertical className="h-4 w-4 text-[var(--canvas-muted)]" />
                  <button
                    type="button"
                    onClick={() =>
                      update({ parameters: current.parameters.filter((_, i) => i !== index) })
                    }
                    className="text-[var(--canvas-muted)] hover:text-rose-400"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <FieldLabel>Имя</FieldLabel>
                    <input
                      value={param.name}
                      onChange={(e) => updateParam(index, { name: e.target.value })}
                      className={cn(inputClass, "font-mono")}
                    />
                  </div>
                  <div>
                    <FieldLabel>Тип</FieldLabel>
                    <select
                      value={param.type}
                      onChange={(e) => updateParam(index, { type: e.target.value as FunctionParamType })}
                      className={inputClass}
                    >
                      {PARAM_TYPES.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="sm:col-span-2">
                    <FieldLabel>Инструкция</FieldLabel>
                    <input
                      value={param.instruction}
                      onChange={(e) => updateParam(index, { instruction: e.target.value })}
                      className={inputClass}
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <FieldLabel>Возможные значения (enum)</FieldLabel>
                    <input
                      value={param.enum_values ?? ""}
                      onChange={(e) => updateParam(index, { enum_values: e.target.value })}
                      placeholder="value1, value2"
                      className={inputClass}
                    />
                  </div>
                  <label className="flex items-center gap-2 text-sm text-[var(--canvas-fg)] sm:col-span-2">
                    <input
                      type="checkbox"
                      checked={param.required}
                      onChange={(e) => updateParam(index, { required: e.target.checked })}
                      className="rounded border-[var(--canvas-border)]"
                    />
                    Обязательный параметр
                  </label>
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Реакция на выполнение функции">
        <div>
          <FieldLabel>Действие</FieldLabel>
          <select
            value={current.reaction_mode}
            onChange={(e) => update({ reaction_mode: e.target.value as "llm" | "fixed" })}
            className={inputClass}
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
              className={cn(inputClass, "h-auto py-2.5")}
            />
          </div>
        ) : (
          <div className="flex gap-3 rounded-xl border border-violet-500/20 bg-violet-500/5 px-4 py-3">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-violet-400" />
            <p className="text-xs leading-relaxed text-[var(--canvas-muted)]">
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
            className={inputClass}
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
            className={inputClass}
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
          <p className="text-sm text-[var(--canvas-muted)]">
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
          <div className="mt-2 flex flex-wrap gap-2">
            {RESULT_INTEGRATION_PICKER.map((opt) => {
              const active = resultIntegrations.includes(opt.id);
              return (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => toggleIntegration(opt.id)}
                  className={cn(
                    "rounded-lg border px-3 py-1.5 text-xs font-medium transition",
                    active
                      ? "border-violet-500/40 bg-violet-500/15 text-violet-300"
                      : "border-[var(--canvas-border)] text-[var(--canvas-muted)] hover:text-[var(--canvas-fg)]",
                  )}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="space-y-2">
          <div className="grid grid-cols-[1fr_1fr_1fr_auto] gap-2 px-1 text-[10px] uppercase tracking-wider text-[var(--canvas-muted)]">
            <span>Имя</span>
            <span>Действие</span>
            <span>Значение</span>
            <span />
          </div>
          {resultFields.map((field, index) => (
            <div
              key={field.id}
              className="grid grid-cols-[1fr_1fr_1fr_auto] items-center gap-2 rounded-xl border border-[var(--canvas-border)] bg-[var(--canvas)] p-2"
            >
              <input
                value={field.name}
                onChange={(e) => updateField(index, { name: e.target.value })}
                className="h-9 rounded-lg border border-[var(--canvas-border)] bg-[var(--card)] px-2 text-xs"
              />
              <select
                value={field.action}
                onChange={(e) =>
                  updateField(index, { action: e.target.value as "text" | "system" })
                }
                className="h-9 rounded-lg border border-[var(--canvas-border)] bg-[var(--card)] px-2 text-xs"
              >
                <option value="text">Текст</option>
                <option value="system">Системные параметры</option>
              </select>
              <input
                value={field.value}
                onChange={(e) => updateField(index, { value: e.target.value })}
                className="h-9 rounded-lg border border-[var(--canvas-border)] bg-[var(--card)] px-2 text-xs"
              />
              <button
                type="button"
                onClick={() =>
                  update({ result_fields: resultFields.filter((_, i) => i !== index) })
                }
                className="p-2 text-[var(--canvas-muted)] hover:text-rose-400"
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
            className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-violet-600 text-white hover:bg-violet-500"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>
      </Section>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => void handleDelete()}
          className="rounded-xl bg-rose-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-rose-500"
        >
          Удалить функцию
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => void handleSave()}
          className="rounded-xl bg-violet-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-violet-500 disabled:opacity-50"
        >
          Сохранить
        </button>
      </div>
    </div>
  );
}

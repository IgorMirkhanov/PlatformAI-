"use client";

import { Loader2, Plus, Power, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { CrmSubNav } from "@/components/crm/CrmSubNav";
import { useToast } from "@/hooks/useToast";
import {
  createAutomationRule,
  deleteAutomationRule,
  listAutomationRules,
  updateAutomationRule,
  type CrmAutomationRule,
} from "@/lib/crm/api";
import type { CrmAutomationTriggerType } from "@/lib/crm/types";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/store/useBotStore";

const TRIGGER_OPTIONS: Array<{ value: CrmAutomationTriggerType; label: string }> = [
  { value: "stage_entered", label: "Смена / вход в этап" },
  { value: "deal_created", label: "Создание сделки" },
  { value: "tag_added", label: "Добавление тега" },
  { value: "field_changed", label: "Изменение поля" },
  { value: "no_activity_for", label: "Нет активности" },
];

const ACTION_OPTIONS = [
  { value: "add_tag", label: "Добавить тег" },
  { value: "send_webhook", label: "Отправить вебхук" },
  { value: "add_note", label: "Добавить заметку" },
  { value: "move_stage", label: "Переместить на этап" },
] as const;

function actionSummary(actions: Array<Record<string, unknown>>): string {
  if (!actions.length) return "без действий";
  return actions
    .map((a) => String(a.type || "action"))
    .join(" → ");
}

export default function CrmAutomationsPage() {
  const { showToast } = useToast();
  const [rules, setRules] = useState<CrmAutomationRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);

  const [name, setName] = useState("");
  const [triggerType, setTriggerType] = useState<CrmAutomationTriggerType>("stage_entered");
  const [stageId, setStageId] = useState("");
  const [actionType, setActionType] = useState<(typeof ACTION_OPTIONS)[number]["value"]>("add_tag");
  const [actionValue, setActionValue] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const response = await listAutomationRules();
      setRules(response.items);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить правила."), "error");
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const onCreate = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || saving) return;
    setSaving(true);
    try {
      const trigger_config: Record<string, unknown> = {};
      if (triggerType === "stage_entered" && stageId.trim()) {
        trigger_config.stage_id = stageId.trim();
      }
      if (triggerType === "no_activity_for") {
        trigger_config.hours = Number(stageId) || 24;
      }

      const action: Record<string, unknown> = { type: actionType };
      if (actionType === "add_tag") action.tag_id = actionValue.trim();
      if (actionType === "send_webhook") action.url = actionValue.trim();
      if (actionType === "add_note") action.text = actionValue.trim() || "Automation note";
      if (actionType === "move_stage") action.stage_id = actionValue.trim();

      await createAutomationRule({
        name: name.trim(),
        is_active: true,
        trigger_type: triggerType,
        trigger_config,
        conditions: {},
        actions: [action],
      });
      setName("");
      setStageId("");
      setActionValue("");
      setShowForm(false);
      showToast("Правило создано.", "success");
      await reload();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось создать правило."), "error");
    } finally {
      setSaving(false);
    }
  };

  const onToggle = async (rule: CrmAutomationRule) => {
    try {
      await updateAutomationRule(rule.id, { is_active: !rule.is_active });
      await reload();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось обновить правило."), "error");
    }
  };

  const onDelete = async (ruleId: string) => {
    try {
      await deleteAutomationRule(ruleId);
      showToast("Правило удалено.", "success");
      await reload();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось удалить правило."), "error");
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-4 md:p-6">
      <header className="space-y-3">
        <CrmSubNav />
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-zinc-50">Автоматизации</h1>
            <p className="mt-1 text-sm text-zinc-400">
              Триггер → условие → действие для сделок CRM
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowForm((v) => !v)}
            className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2 text-sm font-semibold text-white hover:bg-violet-500"
          >
            <Plus className="h-4 w-4" />
            Новое правило
          </button>
        </div>
      </header>

      {showForm ? (
        <form
          onSubmit={(e) => void onCreate(e)}
          className="space-y-3 rounded-2xl border border-zinc-800 bg-zinc-950/60 p-4"
        >
          <div className="grid gap-3 md:grid-cols-2">
            <label className="block text-sm text-zinc-300">
              Название
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
              />
            </label>
            <label className="block text-sm text-zinc-300">
              Триггер
              <select
                value={triggerType}
                onChange={(e) => setTriggerType(e.target.value as CrmAutomationTriggerType)}
                className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
              >
                {TRIGGER_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm text-zinc-300">
              {triggerType === "no_activity_for" ? "Часы без активности" : "Stage ID (опционально)"}
              <input
                value={stageId}
                onChange={(e) => setStageId(e.target.value)}
                placeholder={triggerType === "no_activity_for" ? "24" : "uuid этапа"}
                className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
              />
            </label>
            <label className="block text-sm text-zinc-300">
              Действие
              <select
                value={actionType}
                onChange={(e) =>
                  setActionType(e.target.value as (typeof ACTION_OPTIONS)[number]["value"])
                }
                className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
              >
                {ACTION_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm text-zinc-300 md:col-span-2">
              Параметр действия (tag_id / url / stage_id / текст)
              <input
                value={actionValue}
                onChange={(e) => setActionValue(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
              />
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="rounded-xl border border-zinc-700 px-4 py-2 text-sm text-zinc-300"
            >
              Отмена
            </button>
            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Создать
            </button>
          </div>
        </form>
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-zinc-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Загрузка…
        </div>
      ) : rules.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-zinc-800 px-6 py-14 text-center text-sm text-zinc-500">
          Правил пока нет. Создайте первое.
        </div>
      ) : (
        <ul className="space-y-3">
          {rules.map((rule) => (
            <li
              key={rule.id}
              className="rounded-2xl border border-zinc-800/90 bg-zinc-950/60 p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-sm font-semibold text-zinc-100">{rule.name}</h2>
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
                        rule.is_active
                          ? "bg-emerald-500/15 text-emerald-300"
                          : "bg-zinc-800 text-zinc-500",
                      )}
                    >
                      {rule.is_active ? "active" : "off"}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-zinc-400">
                    <span className="text-violet-300">{rule.trigger_type}</span>
                    {" → "}
                    <span className="text-zinc-300">{actionSummary(rule.actions)}</span>
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void onToggle(rule)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 px-2.5 py-1.5 text-xs text-zinc-300 hover:bg-zinc-900"
                    title={rule.is_active ? "Деактивировать" : "Активировать"}
                  >
                    <Power className="h-3.5 w-3.5" />
                    {rule.is_active ? "Выкл" : "Вкл"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void onDelete(rule.id)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-red-500/30 px-2.5 py-1.5 text-xs text-red-300 hover:bg-red-500/10"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    Удалить
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

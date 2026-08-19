"use client";

import { useMemo, useState, type FormEvent } from "react";
import { Loader2, Plus, Trash2, X } from "lucide-react";

import { useToast } from "@/hooks/useToast";
import {
  createCustomField,
  deleteCustomField,
} from "@/lib/crm/api";
import type { CrmCustomFieldDefinition, CrmEntityType, CrmFieldType } from "@/lib/crm/types";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/store/useBotStore";

const FIELD_TYPES: { value: CrmFieldType; label: string }[] = [
  { value: "text", label: "Строка" },
  { value: "number", label: "Число" },
  { value: "date", label: "Дата" },
  { value: "boolean", label: "Да/Нет" },
  { value: "select", label: "Список" },
  { value: "url", label: "Ссылка" },
];

function slugifyFieldKey(label: string): string {
  const map: Record<string, string> = {
    а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e", ж: "zh", з: "z",
    и: "i", й: "y", к: "k", л: "l", м: "m", н: "n", о: "o", п: "p", р: "r",
    с: "s", т: "t", у: "u", ф: "f", х: "h", ц: "ts", ч: "ch", ш: "sh", щ: "sch",
    ъ: "", ы: "y", ь: "", э: "e", ю: "yu", я: "ya",
  };
  const lowered = label.trim().toLowerCase();
  let out = "";
  for (const ch of lowered) {
    if (map[ch]) out += map[ch];
    else if (/[a-z0-9]/.test(ch)) out += ch;
    else if (/\s|[-_]/.test(ch)) out += "_";
  }
  out = out.replace(/_+/g, "_").replace(/^_|_$/g, "").slice(0, 40);
  return out || `field_${Date.now().toString(36)}`;
}

interface AddCustomFieldModalProps {
  open: boolean;
  entityType: CrmEntityType;
  nextPosition: number;
  onClose: () => void;
  onCreated: (field: CrmCustomFieldDefinition) => void;
}

export function AddCustomFieldModal({
  open,
  entityType,
  nextPosition,
  onClose,
  onCreated,
}: AddCustomFieldModalProps) {
  const { showToast } = useToast();
  const [label, setLabel] = useState("");
  const [fieldKey, setFieldKey] = useState("");
  const [fieldType, setFieldType] = useState<CrmFieldType>("text");
  const [optionsText, setOptionsText] = useState("");
  const [keyTouched, setKeyTouched] = useState(false);
  const [saving, setSaving] = useState(false);

  const suggestedKey = useMemo(() => slugifyFieldKey(label), [label]);

  if (!open) return null;

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!label.trim()) {
      showToast("Укажите название поля.", "error");
      return;
    }
    const key = (keyTouched ? fieldKey : suggestedKey).trim().toLowerCase();
    if (!/^[a-z][a-z0-9_]{0,49}$/.test(key)) {
      showToast("Код поля: латиница, цифры и _, начинается с буквы.", "error");
      return;
    }
    const options =
      fieldType === "select" || fieldType === "multiselect"
        ? optionsText
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean)
        : undefined;
    if ((fieldType === "select" || fieldType === "multiselect") && (!options || options.length === 0)) {
      showToast("Для списка укажите варианты (по одному на строку).", "error");
      return;
    }

    setSaving(true);
    try {
      const created = await createCustomField({
        entity_type: entityType,
        field_key: key,
        label: label.trim(),
        field_type: fieldType,
        options,
        position: nextPosition,
      });
      showToast("Поле создано.", "success");
      onCreated(created);
      setLabel("");
      setFieldKey("");
      setFieldType("text");
      setOptionsText("");
      setKeyTouched(false);
      onClose();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось создать поле."), "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        className="w-full max-w-md rounded-2xl border border-zinc-800 bg-zinc-950 p-5 shadow-2xl"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h3 className="text-lg font-semibold text-zinc-50">Новое поле сделки</h3>
            <p className="mt-1 text-xs text-zinc-500">
              Как в Bitrix24 — поле появится во всех сделках организации.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={(e) => void onSubmit(e)} className="space-y-4">
          <label className="block text-xs text-zinc-400">
            Название поля
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Например: Источник рекламы"
              className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/40"
              autoFocus
            />
          </label>

          <label className="block text-xs text-zinc-400">
            Код поля (латиница)
            <input
              value={keyTouched ? fieldKey : suggestedKey}
              onChange={(e) => {
                setKeyTouched(true);
                setFieldKey(e.target.value);
              }}
              placeholder="istochnik_reklamy"
              className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 font-mono text-sm text-zinc-100 outline-none focus:border-violet-500/40"
            />
          </label>

          <label className="block text-xs text-zinc-400">
            Тип
            <select
              value={fieldType}
              onChange={(e) => setFieldType(e.target.value as CrmFieldType)}
              className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100"
            >
              {FIELD_TYPES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          {fieldType === "select" ? (
            <label className="block text-xs text-zinc-400">
              Варианты списка (по одному на строку)
              <textarea
                value={optionsText}
                onChange={(e) => setOptionsText(e.target.value)}
                rows={4}
                placeholder={"Google\nInstagram\nРекомендация"}
                className="mt-1.5 w-full resize-y rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100"
              />
            </label>
          ) : null}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-zinc-700 px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-900"
            >
              Отмена
            </button>
            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2 text-sm font-semibold text-white hover:bg-violet-500 disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Создать поле
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

interface DealCustomFieldsPanelProps {
  fieldDefs: CrmCustomFieldDefinition[];
  fieldDraft: Record<string, string>;
  savingFields: boolean;
  onDraftChange: (key: string, value: string) => void;
  onSave: () => void;
  onFieldDefsChange: (defs: CrmCustomFieldDefinition[]) => void;
}

export function DealCustomFieldsPanel({
  fieldDefs,
  fieldDraft,
  savingFields,
  onDraftChange,
  onSave,
  onFieldDefsChange,
}: DealCustomFieldsPanelProps) {
  const { showToast } = useToast();
  const [addOpen, setAddOpen] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const onDeleteField = async (field: CrmCustomFieldDefinition) => {
    if (!window.confirm(`Удалить поле «${field.label}»? Значения в сделках сохранятся в JSON.`)) {
      return;
    }
    setDeletingId(field.id);
    try {
      await deleteCustomField(field.id);
      onFieldDefsChange(fieldDefs.filter((item) => item.id !== field.id));
      showToast("Поле удалено.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось удалить поле."), "error");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <>
      <div className="rounded-2xl border border-zinc-800/90 bg-zinc-950/60 p-4">
        <div className="mb-3 flex items-center justify-between gap-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Поля сделки
          </p>
          <button
            type="button"
            onClick={() => setAddOpen(true)}
            className="inline-flex items-center gap-1 rounded-lg border border-violet-500/30 bg-violet-500/10 px-2 py-1 text-[11px] font-medium text-violet-200 hover:bg-violet-500/20"
          >
            <Plus className="h-3 w-3" />
            Добавить поле
          </button>
        </div>

        {fieldDefs.length === 0 ? (
          <p className="text-xs leading-relaxed text-zinc-500">
            Нет пользовательских полей. Нажмите «Добавить поле», чтобы создать поля как в Bitrix24
            (источник, бюджет, менеджер и т.д.).
          </p>
        ) : (
          <div className="space-y-3">
            {fieldDefs.map((def) => (
              <div key={def.id} className="group relative rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-3">
                <div className="mb-1 flex items-start justify-between gap-2">
                  <span className="text-xs font-medium text-zinc-300">{def.label}</span>
                  <button
                    type="button"
                    title="Удалить определение поля"
                    disabled={deletingId === def.id}
                    onClick={() => void onDeleteField(def)}
                    className="rounded p-1 text-zinc-600 opacity-0 transition hover:bg-red-500/10 hover:text-red-300 group-hover:opacity-100"
                  >
                    {deletingId === def.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5" />
                    )}
                  </button>
                </div>
                {def.field_type === "boolean" ? (
                  <select
                    value={fieldDraft[def.field_key] ?? ""}
                    onChange={(e) => onDraftChange(def.field_key, e.target.value)}
                    className="w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
                  >
                    <option value="">—</option>
                    <option value="true">Да</option>
                    <option value="false">Нет</option>
                  </select>
                ) : def.field_type === "select" && def.options?.length ? (
                  <select
                    value={fieldDraft[def.field_key] ?? ""}
                    onChange={(e) => onDraftChange(def.field_key, e.target.value)}
                    className="w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
                  >
                    <option value="">—</option>
                    {def.options.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={
                      def.field_type === "number"
                        ? "number"
                        : def.field_type === "date"
                          ? "date"
                          : def.field_type === "url"
                            ? "url"
                            : "text"
                    }
                    value={fieldDraft[def.field_key] ?? ""}
                    onChange={(e) => onDraftChange(def.field_key, e.target.value)}
                    className="w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/40"
                  />
                )}
              </div>
            ))}
            <button
              type="button"
              onClick={onSave}
              disabled={savingFields}
              className={cn(
                "inline-flex w-full items-center justify-center gap-2 rounded-xl bg-zinc-800 px-3 py-2.5 text-sm font-medium text-zinc-100 hover:bg-zinc-700",
                savingFields && "opacity-60",
              )}
            >
              {savingFields ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Сохранить значения полей
            </button>
          </div>
        )}
      </div>

      <AddCustomFieldModal
        open={addOpen}
        entityType="deal"
        nextPosition={fieldDefs.length}
        onClose={() => setAddOpen(false)}
        onCreated={(field) => {
          onFieldDefsChange([...fieldDefs, field].sort((a, b) => a.position - b.position));
          onDraftChange(field.field_key, "");
        }}
      />
    </>
  );
}

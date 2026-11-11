"use client";

import { Plus, Trash2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type { FunctionKeyValueRow } from "@/types/agent";

const fieldClass =
  "h-8 w-full rounded-lg border border-zinc-600 bg-[#0c0c0e] px-2.5 text-xs text-zinc-100 outline-none transition placeholder:text-zinc-500 focus:border-violet-500 focus:ring-1 focus:ring-violet-500/40";

export function FunctionKeyValueEditor({
  title,
  rows,
  onChange,
  keyPlaceholder = "Ключ",
  valuePlaceholder = "Значение",
}: {
  title: string;
  rows: FunctionKeyValueRow[];
  onChange: (next: FunctionKeyValueRow[]) => void;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
}) {
  const updateRow = (index: number, patch: Partial<FunctionKeyValueRow>): void => {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  const addRow = (): void => {
    onChange([
      ...rows,
      { id: crypto.randomUUID(), key: "", value: "", enabled: true },
    ]);
  };

  return (
    <div className="space-y-2 rounded-xl border border-zinc-700 bg-[#121214] p-3">
      <h5 className="text-xs font-semibold uppercase tracking-wide text-zinc-400">{title}</h5>
      {rows.length === 0 ? (
        <p className="py-3 text-center text-sm text-zinc-500">Нет параметров для настройки</p>
      ) : (
        <div className="space-y-2">
          <div className="grid grid-cols-[1fr_1fr_auto] gap-2 px-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            <span>Ключ</span>
            <span>Значение</span>
            <span />
          </div>
          {rows.map((row, index) => (
            <div
              key={row.id}
              className="grid grid-cols-[1fr_1fr_auto] items-center gap-2 rounded-lg border border-zinc-700 bg-[#0c0c0e] p-1.5"
            >
              <input
                value={row.key}
                onChange={(e) => updateRow(index, { key: e.target.value })}
                placeholder={keyPlaceholder}
                className={fieldClass}
              />
              <input
                value={row.value}
                onChange={(e) => updateRow(index, { value: e.target.value })}
                placeholder={valuePlaceholder}
                className={fieldClass}
              />
              <button
                type="button"
                aria-label="Удалить параметр"
                onClick={() => onChange(rows.filter((_, i) => i !== index))}
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-rose-500/40 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
      <button
        type="button"
        aria-label={`Добавить параметр: ${title}`}
        onClick={addRow}
        className={cn(
          "inline-flex h-9 w-9 items-center justify-center rounded-full bg-violet-600 text-white",
          "shadow-[0_0_0_1px_rgba(139,92,246,0.45)] hover:bg-violet-500",
          rows.length === 0 && "mx-auto",
        )}
      >
        <Plus className="h-4 w-4" />
      </button>
    </div>
  );
}

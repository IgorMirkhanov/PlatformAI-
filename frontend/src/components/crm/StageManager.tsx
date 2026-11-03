"use client";

import { Loader2, Pencil, Plus, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";

import { useToast } from "@/hooks/useToast";
import { createStage, deleteStage, updateStage } from "@/lib/crm/api";
import type { CrmPipeline, CrmStage } from "@/lib/crm/types";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/store/useBotStore";

const STAGE_COLORS = [
  "#94A3B8",
  "#38BDF8",
  "#A78BFA",
  "#FBBF24",
  "#34D399",
  "#F87171",
  "#FB7185",
  "#22D3EE",
];

interface StageManagerProps {
  pipeline: CrmPipeline;
  onChanged: () => Promise<void> | void;
}

export function StageManager({ pipeline, onChanged }: StageManagerProps) {
  const { showToast } = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [color, setColor] = useState(STAGE_COLORS[2]);
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");

  const stages = useMemo(
    () => [...(pipeline.stages || [])].sort((a, b) => a.position - b.position),
    [pipeline.stages],
  );

  const nextPosition = stages.length === 0 ? 0 : Math.max(...stages.map((s) => s.position)) + 1;

  const onCreate = async () => {
    const trimmed = name.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    try {
      await createStage(pipeline.id, {
        name: trimmed,
        color,
        position: nextPosition,
      });
      setName("");
      showToast("Этап добавлен.", "success");
      await onChanged();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось добавить этап."), "error");
    } finally {
      setBusy(false);
    }
  };

  const onRename = async (stage: CrmStage) => {
    const trimmed = editName.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    try {
      await updateStage(pipeline.id, stage.id, { name: trimmed });
      setEditingId(null);
      showToast("Этап обновлён.", "success");
      await onChanged();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось переименовать этап."), "error");
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async (stage: CrmStage) => {
    if (busy) return;
    if (stage.is_won || stage.is_lost) {
      showToast("Этапы «Выиграна» и «Проиграна» нельзя удалить.", "error");
      return;
    }
    const confirmed = window.confirm(
      `Удалить этап «${stage.name}»? Сделки на нём нужно сначала перенести.`,
    );
    if (!confirmed) return;
    setBusy(true);
    try {
      await deleteStage(pipeline.id, stage.id);
      showToast("Этап удалён.", "success");
      await onChanged();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось удалить этап."), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900/70 px-3.5 py-2 text-sm font-medium text-zinc-200 transition hover:border-violet-500/40 hover:text-violet-100"
      >
        <Plus className="h-4 w-4" />
        Этапы воронки
      </button>

      {open ? (
        <div className="absolute right-0 z-30 mt-2 w-[min(100vw-2rem,22rem)] rounded-2xl border border-zinc-800 bg-zinc-950 p-4 shadow-2xl shadow-black/50">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <p className="text-sm font-semibold text-zinc-100">Этапы · {pipeline.name}</p>
              <p className="text-xs text-zinc-500">Добавляйте и переименовывайте колонки канбана</p>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-900 hover:text-zinc-200"
              aria-label="Закрыть"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <ul className="mb-3 max-h-56 space-y-1.5 overflow-y-auto">
            {stages.map((stage) => (
              <li
                key={stage.id}
                className="flex items-center gap-2 rounded-xl border border-zinc-800/80 bg-zinc-900/40 px-2.5 py-2"
              >
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: stage.color || "#8B5CF6" }}
                />
                {editingId === stage.id ? (
                  <input
                    autoFocus
                    value={editName}
                    onChange={(event) => setEditName(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        void onRename(stage);
                      }
                      if (event.key === "Escape") setEditingId(null);
                    }}
                    className="min-w-0 flex-1 rounded-lg border border-zinc-700 bg-zinc-950 px-2 py-1 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
                  />
                ) : (
                  <span className="min-w-0 flex-1 truncate text-sm text-zinc-200">{stage.name}</span>
                )}
                {stage.is_won || stage.is_lost ? (
                  <span
                    className={cn(
                      "rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase",
                      stage.is_won && "bg-emerald-500/15 text-emerald-300",
                      stage.is_lost && "bg-rose-500/15 text-rose-300",
                    )}
                  >
                    {stage.is_won ? "Won" : "Lost"}
                  </span>
                ) : null}
                {editingId === stage.id ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void onRename(stage)}
                    className="rounded-lg bg-violet-600 px-2 py-1 text-[11px] font-medium text-white disabled:opacity-50"
                  >
                    OK
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      setEditingId(stage.id);
                      setEditName(stage.name);
                    }}
                    className="rounded-lg p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200"
                    aria-label={`Переименовать ${stage.name}`}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                )}
                {!stage.is_won && !stage.is_lost ? (
                  <button
                    type="button"
                    onClick={() => void onDelete(stage)}
                    className="rounded-lg p-1 text-zinc-500 hover:bg-rose-500/10 hover:text-rose-300"
                    aria-label={`Удалить ${stage.name}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                ) : null}
              </li>
            ))}
          </ul>

          <div className="space-y-2 border-t border-zinc-800 pt-3">
            <label className="block text-xs text-zinc-500">
              Новый этап
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void onCreate();
                  }
                }}
                placeholder="Например: Счёт выставлен"
                className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/40"
              />
            </label>
            <div className="flex flex-wrap gap-1.5">
              {STAGE_COLORS.map((swatch) => (
                <button
                  key={swatch}
                  type="button"
                  onClick={() => setColor(swatch)}
                  className={cn(
                    "h-5 w-5 rounded-full border-2",
                    color === swatch ? "border-white" : "border-transparent",
                  )}
                  style={{ backgroundColor: swatch }}
                  aria-label={`Цвет ${swatch}`}
                />
              ))}
            </div>
            <button
              type="button"
              disabled={busy || !name.trim()}
              onClick={() => void onCreate()}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-violet-600 px-3 py-2 text-sm font-semibold text-white hover:bg-violet-500 disabled:opacity-50"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Добавить этап
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

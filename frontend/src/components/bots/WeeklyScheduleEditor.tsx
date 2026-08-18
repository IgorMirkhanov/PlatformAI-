"use client";

import { Plus, Trash2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ScheduleConfig, ScheduleWindow } from "@/types/agent";
import { WEEKDAY_LABELS, WEEKDAYS } from "@/types/agent";

interface WeeklyScheduleEditorProps {
  value: ScheduleConfig;
  onChange: (value: ScheduleConfig) => void;
  disabled?: boolean;
}

const WEEKDAY_ROWS = WEEKDAYS.slice(0, 5);
const DEFAULT_START = "00:00";
const DEFAULT_END = "23:59";

function findPrimaryWindowForDay(windows: ScheduleWindow[], day: string): ScheduleWindow | undefined {
  return windows.find((window) => window.day === day);
}

function countWindowsForDay(windows: ScheduleWindow[], day: string): number {
  return windows.filter((window) => window.day === day).length;
}

export function WeeklyScheduleEditor({ value, onChange, disabled = false }: WeeklyScheduleEditorProps) {
  const upsertPrimaryDayWindow = (day: string, patch: Partial<ScheduleWindow>): void => {
    const existing = findPrimaryWindowForDay(value.windows, day);

    if (existing) {
      onChange({
        ...value,
        windows: value.windows.map((window) =>
          window === existing ? { ...window, ...patch } : window,
        ),
      });
      return;
    }

    onChange({
      ...value,
      windows: [
        ...value.windows,
        {
          day,
          start: patch.start ?? DEFAULT_START,
          end: patch.end ?? DEFAULT_END,
        },
      ],
    });
  };

  const addExtraSlotForDay = (day: string): void => {
    onChange({
      ...value,
      windows: [
        ...value.windows,
        { day, start: DEFAULT_START, end: DEFAULT_END },
      ],
    });
  };

  const removeWindowAt = (index: number): void => {
    onChange({
      ...value,
      windows: value.windows.filter((_, i) => i !== index),
    });
  };

  const getPrimaryTimes = (day: string): { start: string; end: string } => {
    const window = findPrimaryWindowForDay(value.windows, day);
    return {
      start: window?.start ?? DEFAULT_START,
      end: window?.end ?? DEFAULT_END,
    };
  };

  const extraWindows = value.windows.filter((window, index) => {
    if (!WEEKDAY_ROWS.includes(window.day as (typeof WEEKDAY_ROWS)[number])) {
      return true;
    }
    const firstIndex = value.windows.findIndex((item) => item.day === window.day);
    return index !== firstIndex;
  });

  return (
    <div className={cn("mt-6 space-y-4", disabled && "pointer-events-none opacity-50")}>
      <div className="overflow-hidden rounded-2xl border border-zinc-800/80 bg-black/20">
        <div className="grid grid-cols-[56px_1fr_16px_1fr_40px] gap-3 border-b border-zinc-800/80 px-4 py-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-600 max-sm:hidden">
          <span>День</span>
          <span>Начало</span>
          <span />
          <span>Конец</span>
          <span />
        </div>

        {WEEKDAY_ROWS.map((day) => {
          const times = getPrimaryTimes(day);
          const extraCount = countWindowsForDay(value.windows, day) - 1;

          return (
            <div
              key={day}
              className="grid grid-cols-1 gap-3 border-b border-zinc-800/60 px-4 py-3 last:border-b-0 sm:grid-cols-[56px_1fr_16px_1fr_40px] sm:items-center"
            >
              <div className="flex items-center gap-2">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-zinc-900 text-xs font-semibold text-zinc-200 ring-1 ring-zinc-800">
                  {WEEKDAY_LABELS[day]}
                </span>
                {extraCount > 0 && (
                  <span className="text-[10px] text-violet-400">+{extraCount}</span>
                )}
              </div>

              <input
                type="time"
                min={DEFAULT_START}
                max={DEFAULT_END}
                disabled={disabled}
                value={times.start}
                onChange={(event) =>
                  upsertPrimaryDayWindow(day, {
                    day,
                    start: event.target.value,
                    end: times.end,
                  })
                }
                className="w-full rounded-xl border border-zinc-800 bg-[#0a0a0c] px-3 py-2 text-sm text-zinc-100"
              />

              <span className="hidden text-center text-xs text-zinc-600 sm:block">—</span>

              <input
                type="time"
                min={DEFAULT_START}
                max={DEFAULT_END}
                disabled={disabled}
                value={times.end}
                onChange={(event) =>
                  upsertPrimaryDayWindow(day, {
                    day,
                    start: times.start,
                    end: event.target.value,
                  })
                }
                className="w-full rounded-xl border border-zinc-800 bg-[#0a0a0c] px-3 py-2 text-sm text-zinc-100"
              />

              <button
                type="button"
                disabled={disabled}
                onClick={() => addExtraSlotForDay(day)}
                className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-violet-500/30 bg-violet-500/10 text-violet-300 transition hover:bg-violet-500/20 disabled:opacity-50"
                aria-label={`Добавить интервал для ${WEEKDAY_LABELS[day]}`}
              >
                <Plus className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>

      {extraWindows.map((window) => {
        const index = value.windows.indexOf(window);
        if (index < 0) return null;

        return (
          <div
            key={`extra-${window.day}-${index}`}
            className="grid gap-2 rounded-xl border border-zinc-800/80 bg-black/20 p-3 sm:grid-cols-[120px_1fr_1fr_auto]"
          >
            <select
              value={window.day}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...value,
                  windows: value.windows.map((item, i) =>
                    i === index ? { ...item, day: event.target.value } : item,
                  ),
                })
              }
              className="rounded-xl border border-zinc-800 bg-[#0a0a0c] px-3 py-2 text-sm text-zinc-100"
            >
              {WEEKDAYS.map((day) => (
                <option key={day} value={day}>
                  {WEEKDAY_LABELS[day]}
                </option>
              ))}
            </select>
            <input
              type="time"
              value={window.start}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...value,
                  windows: value.windows.map((item, i) =>
                    i === index ? { ...item, start: event.target.value } : item,
                  ),
                })
              }
              className="rounded-xl border border-zinc-800 bg-[#0a0a0c] px-3 py-2 text-sm text-zinc-100"
            />
            <input
              type="time"
              value={window.end}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...value,
                  windows: value.windows.map((item, i) =>
                    i === index ? { ...item, end: event.target.value } : item,
                  ),
                })
              }
              className="rounded-xl border border-zinc-800 bg-[#0a0a0c] px-3 py-2 text-sm text-zinc-100"
            />
            <button
              type="button"
              disabled={disabled}
              onClick={() => removeWindowAt(index)}
              className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-red-500/30 text-red-400 hover:bg-red-500/10 disabled:opacity-50"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}

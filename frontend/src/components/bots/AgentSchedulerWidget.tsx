"use client";

import { useMemo } from "react";
import { Plus, Trash2 } from "lucide-react";

import {
  buildDaySchedulesFromConfig,
  buildScheduleConfigFromDays,
} from "@/lib/agent-utils";
import { cn } from "@/lib/utils";
import type { DayScheduleUI, ScheduleConfig, Weekday } from "@/types/agent";
import { DEFAULT_DAY_INTERVAL, WEEKDAY_LABELS, WEEKDAYS } from "@/types/agent";

interface AgentSchedulerWidgetProps {
  value: ScheduleConfig;
  onChange: (value: ScheduleConfig) => void;
  disabled?: boolean;
}

function DayToggle({
  checked,
  disabled,
  onChange,
  label,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative h-6 w-10 shrink-0 rounded-full transition-colors disabled:opacity-40",
        checked ? "bg-violet-600 shadow-glow-purple" : "bg-zinc-700",
      )}
    >
      <span
        className={cn(
          "absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-[18px]" : "translate-x-0.5",
        )}
      />
    </button>
  );
}

function TimeField({
  value,
  disabled,
  onChange,
  label,
}: {
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
  label: string;
}) {
  return (
    <input
      type="time"
      min="00:00"
      max="23:59"
      step={60}
      disabled={disabled}
      value={value}
      aria-label={label}
      onChange={(event) => onChange(event.target.value)}
      className={cn(
        "w-full min-w-0 rounded-lg border border-zinc-800/80 bg-[#0a0a0c] px-2.5 py-2",
        "text-sm tabular-nums text-zinc-100 transition",
        "focus:border-violet-500/50 focus:outline-none focus:ring-1 focus:ring-violet-500/25",
        "disabled:cursor-not-allowed disabled:opacity-50",
      )}
    />
  );
}

export function AgentSchedulerWidget({
  value,
  onChange,
  disabled = false,
}: AgentSchedulerWidgetProps) {
  const dayRows = useMemo(() => buildDaySchedulesFromConfig(value), [value]);

  const commitDays = (nextDays: DayScheduleUI[]): void => {
    onChange(
      buildScheduleConfigFromDays(nextDays, {
        enabled: value.enabled,
        timezone: value.timezone,
      }),
    );
  };

  const updateDay = (day: Weekday, patch: Partial<DayScheduleUI>): void => {
    commitDays(dayRows.map((row) => (row.day === day ? { ...row, ...patch } : row)));
  };

  const updateInterval = (
    day: Weekday,
    intervalIndex: number,
    patch: Partial<{ start: string; end: string }>,
  ): void => {
    const row = dayRows.find((item) => item.day === day);
    if (!row) {
      return;
    }

    const intervals = row.intervals.map((interval, index) =>
      index === intervalIndex ? { ...interval, ...patch } : interval,
    );

    updateDay(day, { intervals });
  };

  const addInterval = (day: Weekday): void => {
    const row = dayRows.find((item) => item.day === day);
    if (!row) {
      return;
    }

    updateDay(day, {
      enabled: true,
      intervals: [...row.intervals, { ...DEFAULT_DAY_INTERVAL }],
    });
  };

  const removeInterval = (day: Weekday, intervalIndex: number): void => {
    const row = dayRows.find((item) => item.day === day);
    if (!row || row.intervals.length <= 1) {
      return;
    }

    updateDay(day, {
      intervals: row.intervals.filter((_, index) => index !== intervalIndex),
    });
  };

  return (
    <div className={cn("mt-6 space-y-3", disabled && "pointer-events-none opacity-50")}>
      <div className="hidden grid-cols-[40px_44px_minmax(0,1fr)_16px_minmax(0,1fr)_36px] items-center gap-3 px-4 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-600 lg:grid">
        <span>День</span>
        <span>Актив.</span>
        <span>Начало</span>
        <span />
        <span>Конец</span>
        <span />
      </div>

      {WEEKDAYS.map((weekday) => {
        const row = dayRows.find((item) => item.day === weekday);
        if (!row) {
          return null;
        }

        const rowDisabled = disabled || !row.enabled;

        return (
          <div
            key={weekday}
            className="rounded-xl border border-zinc-800/60 bg-zinc-900/40 p-3 sm:p-4"
          >
            {row.intervals.map((interval, intervalIndex) => {
              const isPrimary = intervalIndex === 0;

              return (
                <div
                  key={`${weekday}-${intervalIndex}`}
                  className={cn(
                    "grid grid-cols-1 gap-3 sm:grid-cols-[40px_44px_minmax(0,1fr)_16px_minmax(0,1fr)_auto] sm:items-center",
                    intervalIndex > 0 && "mt-3 border-t border-zinc-800/50 pt-3 sm:pl-[84px]",
                  )}
                >
                  {isPrimary ? (
                    <span className="text-xs font-semibold uppercase tracking-wide text-zinc-300">
                      {WEEKDAY_LABELS[weekday]}
                    </span>
                  ) : (
                    <span className="hidden sm:block" />
                  )}

                  {isPrimary ? (
                    <DayToggle
                      checked={row.enabled}
                      disabled={disabled}
                      label={`Активировать ${WEEKDAY_LABELS[weekday]}`}
                      onChange={(enabled) => updateDay(weekday, { enabled })}
                    />
                  ) : (
                    <span className="hidden sm:block" />
                  )}

                  <TimeField
                    value={interval.start}
                    disabled={rowDisabled}
                    label={`Начало ${WEEKDAY_LABELS[weekday]} ${intervalIndex + 1}`}
                    onChange={(start) => updateInterval(weekday, intervalIndex, { start })}
                  />

                  <span className="hidden text-center text-xs text-zinc-600 sm:block">—</span>

                  <TimeField
                    value={interval.end}
                    disabled={rowDisabled}
                    label={`Конец ${WEEKDAY_LABELS[weekday]} ${intervalIndex + 1}`}
                    onChange={(end) => updateInterval(weekday, intervalIndex, { end })}
                  />

                  <div className="flex items-center justify-end gap-1.5">
                    {isPrimary ? (
                      <button
                        type="button"
                        disabled={disabled}
                        onClick={() => addInterval(weekday)}
                        className={cn(
                          "inline-flex h-9 w-9 items-center justify-center rounded-lg",
                          "bg-violet-600/20 text-violet-300 ring-1 ring-violet-500/40",
                          "transition hover:bg-violet-600/35 hover:text-violet-100 hover:shadow-glow-purple",
                          "disabled:opacity-40",
                        )}
                        aria-label={`Добавить интервал для ${WEEKDAY_LABELS[weekday]}`}
                      >
                        <Plus className="h-4 w-4" />
                      </button>
                    ) : (
                      <button
                        type="button"
                        disabled={disabled}
                        onClick={() => removeInterval(weekday, intervalIndex)}
                        className={cn(
                          "inline-flex h-9 w-9 items-center justify-center rounded-lg",
                          "border border-red-500/20 text-red-400 transition hover:bg-red-500/10",
                          "disabled:opacity-40",
                        )}
                        aria-label={`Удалить интервал ${intervalIndex + 1} для ${WEEKDAY_LABELS[weekday]}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

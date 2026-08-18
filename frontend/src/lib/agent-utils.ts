import type { DayScheduleUI, ScheduleConfig, Weekday } from "@/types/agent";
import { DEFAULT_DAY_INTERVAL, DEFAULT_SCHEDULE_WINDOWS, WEEKDAYS } from "@/types/agent";

export function normalizeScheduleConfig(raw: ScheduleConfig | Record<string, unknown>): ScheduleConfig {
  const config = raw as ScheduleConfig;
  let windows = Array.isArray(config.windows)
    ? config.windows.map((window) => ({
        day: String(window.day ?? "monday"),
        start: String(window.start ?? DEFAULT_DAY_INTERVAL.start),
        end: String(window.end ?? DEFAULT_DAY_INTERVAL.end),
      }))
    : [];

  if (windows.length === 0 && !config.day_enabled) {
    windows = [...DEFAULT_SCHEDULE_WINDOWS];
  }

  const dayEnabledRaw = config.day_enabled;
  const day_enabled: Partial<Record<Weekday, boolean>> = {};

  WEEKDAYS.forEach((day) => {
    if (dayEnabledRaw && typeof dayEnabledRaw[day] === "boolean") {
      day_enabled[day] = dayEnabledRaw[day];
      return;
    }
    const dayWindows = windows.filter((window) => window.day === day);
    day_enabled[day] = dayWindows.length > 0 || windows.length === 0;
  });

  return {
    enabled: Boolean(config.enabled),
    timezone: typeof config.timezone === "string" ? config.timezone : "Asia/Almaty",
    windows,
    day_enabled,
  };
}

export function buildDaySchedulesFromConfig(config: ScheduleConfig): DayScheduleUI[] {
  const normalized = normalizeScheduleConfig(config);

  return WEEKDAYS.map((day) => {
    const dayWindows = normalized.windows.filter((window) => window.day === day);
    const enabled = normalized.day_enabled?.[day] ?? dayWindows.length > 0;
    const intervals =
      dayWindows.length > 0
        ? dayWindows.map(({ start, end }) => ({ start, end }))
        : [{ ...DEFAULT_DAY_INTERVAL }];

    return { day, enabled, intervals };
  });
}

export function buildScheduleConfigFromDays(
  days: DayScheduleUI[],
  base: Pick<ScheduleConfig, "enabled" | "timezone">,
): ScheduleConfig {
  const windows: ScheduleConfig["windows"] = [];
  const day_enabled: Partial<Record<Weekday, boolean>> = {};

  days.forEach((row) => {
    day_enabled[row.day] = row.enabled;
    if (!row.enabled) {
      return;
    }

    row.intervals.forEach((interval) => {
      windows.push({
        day: row.day,
        start: interval.start || DEFAULT_DAY_INTERVAL.start,
        end: interval.end || DEFAULT_DAY_INTERVAL.end,
      });
    });
  });

  return {
    enabled: base.enabled,
    timezone: base.timezone,
    windows,
    day_enabled,
  };
}

export function getAvatarForBot(botId: string): string {
  const presets = ["🤖", "✨", "💬", "🚀", "🎯", "⚡"];
  const hash = botId.split("").reduce((acc, char) => acc + char.charCodeAt(0), 0);
  return presets[hash % presets.length] ?? "🤖";
}

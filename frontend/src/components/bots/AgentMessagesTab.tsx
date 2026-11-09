"use client";

import { useEffect, useMemo, useState } from "react";
import { HelpCircle, Info } from "lucide-react";

import { SaveBar } from "@/components/bots/SaveBar";
import { Toggle } from "@/components/ui/Toggle";
import { normalizeScheduleConfig } from "@/lib/agent-utils";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import type { BotAgentProfile, ScheduleConfig, Weekday } from "@/types/agent";
import { WEEKDAYS } from "@/types/agent";

interface AgentMessagesTabProps {
  botId: string;
  profile: BotAgentProfile;
}

const SPLIT_DELAY_OPTIONS = [0, 1, 2, 3, 5, 8, 10] as const;

function scheduleInterval(config: ScheduleConfig): { start: string; end: string } {
  const first = config.windows[0];
  return {
    start: first?.start || "00:00",
    end: first?.end || "23:59",
  };
}

function weekendsEnabled(config: ScheduleConfig): boolean {
  const sat = config.day_enabled?.saturday;
  const sun = config.day_enabled?.sunday;
  if (typeof sat === "boolean" || typeof sun === "boolean") {
    return Boolean(sat || sun);
  }
  return config.windows.some((window) => window.day === "saturday" || window.day === "sunday");
}

function buildMessagesSchedule(params: {
  enabled: boolean;
  timezone: string;
  start: string;
  end: string;
  weekends: boolean;
}): ScheduleConfig {
  const days: Weekday[] = params.weekends
    ? [...WEEKDAYS]
    : (WEEKDAYS.filter((day) => day !== "saturday" && day !== "sunday") as Weekday[]);
  const day_enabled = Object.fromEntries(
    WEEKDAYS.map((day) => [day, days.includes(day)]),
  ) as ScheduleConfig["day_enabled"];
  return {
    enabled: params.enabled,
    timezone: params.timezone,
    day_enabled,
    windows: days.map((day) => ({
      day,
      start: params.start || "00:00",
      end: params.end || "23:59",
    })),
  };
}

export function AgentMessagesTab({ botId, profile }: AgentMessagesTabProps) {
  const saveAgentSettings = useBotStore((state) => state.saveAgentSettings);
  const profileSaving = useBotStore((state) => state.profileSaving[botId] ?? false);
  const { showToast } = useToast();

  const extras = profile.message_extras ?? {};
  const initialSchedule = useMemo(
    () => normalizeScheduleConfig(profile.schedule_config),
    [profile.schedule_config],
  );
  const initialInterval = scheduleInterval(initialSchedule);

  const [messageSplit, setMessageSplit] = useState(profile.message_split);
  const [splitDelaySec, setSplitDelaySec] = useState(
    Number(extras.split_delay_seconds ?? 1),
  );
  const [bufferDelaySec, setBufferDelaySec] = useState(
    Math.round((profile.message_buffer_delay || 0) / 1000),
  );
  const [followUpEnabled, setFollowUpEnabled] = useState(Boolean(extras.follow_up_enabled));
  const [scheduleEnabled, setScheduleEnabled] = useState(initialSchedule.enabled);
  const [scheduleStart, setScheduleStart] = useState(initialInterval.start);
  const [scheduleEnd, setScheduleEnd] = useState(initialInterval.end);
  const [sendOnWeekends, setSendOnWeekends] = useState(
    extras.send_on_weekends ?? weekendsEnabled(initialSchedule),
  );

  useEffect(() => {
    const nextExtras = profile.message_extras ?? {};
    const nextSchedule = normalizeScheduleConfig(profile.schedule_config);
    const nextInterval = scheduleInterval(nextSchedule);
    setMessageSplit(profile.message_split);
    setSplitDelaySec(Number(nextExtras.split_delay_seconds ?? 1));
    setBufferDelaySec(Math.round((profile.message_buffer_delay || 0) / 1000));
    setFollowUpEnabled(Boolean(nextExtras.follow_up_enabled));
    setScheduleEnabled(nextSchedule.enabled);
    setScheduleStart(nextInterval.start);
    setScheduleEnd(nextInterval.end);
    setSendOnWeekends(nextExtras.send_on_weekends ?? weekendsEnabled(nextSchedule));
  }, [profile]);

  const timezone = profile.timezone || initialSchedule.timezone || "Asia/Almaty";

  const handleSave = async (): Promise<void> => {
    try {
      await saveAgentSettings(botId, {
        message_split: messageSplit,
        message_buffer_delay: Math.max(0, Math.min(60, bufferDelaySec)) * 1000,
        follow_up_enabled: followUpEnabled,
        split_delay_seconds: splitDelaySec,
        send_on_weekends: sendOnWeekends,
        schedule_config: buildMessagesSchedule({
          enabled: scheduleEnabled,
          timezone,
          start: scheduleStart,
          end: scheduleEnd,
          weekends: sendOnWeekends,
        }),
      });
      showToast("Настройки сообщений сохранены.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось сохранить настройки."), "error");
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-[1000px] flex-col gap-6 px-1 pb-28">
      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold text-zinc-50">Отправка сообщений</h2>
        <div className="flex flex-col gap-4 rounded-xl border border-zinc-800 bg-zinc-950/50 p-4">
          <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
            <Toggle
              checked={messageSplit}
              onChange={setMessageSplit}
              label="Разделение сообщений"
              description="Каждый абзац будет отправлен в отдельном сообщении"
            />
            {messageSplit ? (
              <div className="mt-4">
                <label className="mb-1.5 flex items-center gap-1.5 text-xs text-zinc-500">
                  Задержка в секундах
                  <span title="Пауза между абзацами при отправке">
                    <HelpCircle className="h-3.5 w-3.5" />
                  </span>
                </label>
                <select
                  value={splitDelaySec}
                  onChange={(event) => setSplitDelaySec(Number(event.target.value))}
                  className="w-full rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2.5 text-sm text-zinc-100"
                >
                  {SPLIT_DELAY_OPTIONS.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
          </div>

          <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
            <div className="mb-3">
              <p className="text-sm font-medium text-zinc-100">Буфер сообщений</p>
              <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                Минимальная пауза до ответа (не добавляется поверх времени LLM). При отправке
                файлов/фото буфер пропускается.
              </p>
            </div>
            <label className="mb-1.5 block text-xs text-zinc-500">Пауза до ответа, сек</label>
            <input
              type="number"
              min={0}
              max={60}
              value={bufferDelaySec}
              onChange={(event) => setBufferDelaySec(Number(event.target.value) || 0)}
              className="w-full rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2.5 text-sm text-zinc-100"
            />
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold text-zinc-50">Follow-up сообщения</h2>
        <div className="rounded-xl border border-zinc-800 bg-zinc-950/50 p-4">
          <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
            <Toggle
              checked={followUpEnabled}
              onChange={setFollowUpEnabled}
              label="Отложенная отправка"
              description="AI-агент автоматически отправляет повторные сообщения при отсутствии ответа"
            />
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold text-zinc-50">Расписание</h2>
        <div className="rounded-xl border border-zinc-800 bg-zinc-950/50 p-4">
          <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
            <Toggle
              checked={scheduleEnabled}
              onChange={setScheduleEnabled}
              label="Расписание"
              description="Включите расписание, чтобы задать рабочие часы отправки сообщений"
            />

            {scheduleEnabled ? (
              <div className="mt-4 space-y-4">
                <div>
                  <p className="mb-2 text-sm text-zinc-300">
                    Интервал отправки:{" "}
                    <span className="font-medium text-zinc-100">
                      {scheduleStart} - {scheduleEnd}
                    </span>
                  </p>
                  <div className="grid grid-cols-2 gap-3">
                    <input
                      type="time"
                      value={scheduleStart}
                      onChange={(event) => setScheduleStart(event.target.value)}
                      className={cn(
                        "rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2.5",
                        "text-sm tabular-nums text-zinc-100",
                      )}
                    />
                    <input
                      type="time"
                      value={scheduleEnd}
                      onChange={(event) => setScheduleEnd(event.target.value)}
                      className={cn(
                        "rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2.5",
                        "text-sm tabular-nums text-zinc-100",
                      )}
                    />
                  </div>
                </div>

                <label className="flex cursor-pointer items-center gap-3 text-sm text-zinc-200">
                  <input
                    type="checkbox"
                    checked={sendOnWeekends}
                    onChange={(event) => setSendOnWeekends(event.target.checked)}
                    className="h-4 w-4 rounded border-zinc-700 bg-zinc-900 accent-violet-500"
                  />
                  Отправлять сообщения в выходные
                </label>

                <div className="flex items-start gap-3 rounded-xl border border-violet-500/30 bg-violet-500/10 px-4 py-3">
                  <Info className="mt-0.5 h-4 w-4 shrink-0 text-violet-300" />
                  <p className="text-xs leading-relaxed text-zinc-300">
                    Отложенные сообщения отправляются только в указанный интервал (
                    {scheduleStart} - {scheduleEnd}, {timezone}). Если время попадает на
                    нерабочие часы, сообщение будет отправлено в начале следующего интервала.
                  </p>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </section>

      <SaveBar onSave={handleSave} saving={profileSaving} />
    </div>
  );
}

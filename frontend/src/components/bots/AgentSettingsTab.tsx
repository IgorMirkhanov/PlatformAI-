"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Camera, Loader2, User } from "lucide-react";

import { AgentSchedulerWidget } from "@/components/bots/AgentSchedulerWidget";
import { SaveBar } from "@/components/bots/SaveBar";
import { CursorDebugPanel } from "@/components/admin/CursorDebugPanel";
import { Toggle } from "@/components/ui/Toggle";
import { buildApiUrl, uploadBotAvatar } from "@/lib/api";
import { normalizeScheduleConfig } from "@/lib/agent-utils";
import { useAsyncAction } from "@/lib/hooks/use-async-action";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import { TIMEZONE_LABELS, TIMEZONE_OPTIONS } from "@/types/agent";
import type { BotAgentProfile, ScheduleConfig } from "@/types/agent";

interface AgentSettingsTabProps {
  botId: string;
  profile: BotAgentProfile;
}

function resolveAvatarSrc(avatarUrl: string | null | undefined): string | null {
  if (!avatarUrl) {
    return null;
  }
  if (
    avatarUrl.startsWith("blob:") ||
    avatarUrl.startsWith("http://") ||
    avatarUrl.startsWith("https://") ||
    avatarUrl.startsWith("/uploads/")
  ) {
    return avatarUrl;
  }
  return buildApiUrl(avatarUrl);
}

export function AgentSettingsTab({ botId, profile }: AgentSettingsTabProps) {
  const saveAgentSettings = useBotStore((state) => state.saveAgentSettings);
  const patchAgentScheduleConfig = useBotStore((state) => state.patchAgentScheduleConfig);
  const loadAgentProfile = useBotStore((state) => state.loadAgentProfile);
  const profileSaving = useBotStore((state) => state.profileSaving[botId] ?? false);
  const { showToast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [name, setName] = useState(profile.name);
  const [isActive, setIsActive] = useState(profile.is_active);
  const [defaultChatState, setDefaultChatState] = useState(profile.default_chat_state);
  const [timezone, setTimezone] = useState(profile.timezone || "Asia/Almaty");
  const [scheduleConfig, setScheduleConfig] = useState(
    normalizeScheduleConfig(profile.schedule_config),
  );
  const [avatarPreview, setAvatarPreview] = useState<string | null>(profile.avatar_url ?? null);
  const [avatarUploading, setAvatarUploading] = useState(false);
  const [nameSaving, setNameSaving] = useState(false);

  useEffect(() => {
    setName(profile.name);
    setIsActive(profile.is_active);
    setDefaultChatState(profile.default_chat_state);
    setTimezone(profile.timezone || "Asia/Almaty");
    setScheduleConfig(normalizeScheduleConfig(profile.schedule_config));
    setAvatarPreview(profile.avatar_url ?? null);
  }, [profile]);

  const avatarSrc = resolveAvatarSrc(avatarPreview);

  const handleScheduleChange = (config: ScheduleConfig): void => {
    setScheduleConfig(config);
    patchAgentScheduleConfig(botId, config);
  };

  const handleNameBlur = async (): Promise<void> => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setName(profile.name);
      showToast("Укажите название агента.", "error");
      return;
    }
    if (trimmedName === profile.name) {
      return;
    }

    setNameSaving(true);
    try {
      await saveAgentSettings(botId, { name: trimmedName });
      showToast("Название сохранено.", "settings");
    } catch (error) {
      setName(profile.name);
      showToast(getApiErrorMessage(error, "Не удалось сохранить название."), "error");
    } finally {
      setNameSaving(false);
    }
  };

  const persistActive = useCallback(
    async (next: boolean) => saveAgentSettings(botId, { is_active: next }),
    [botId, saveAgentSettings],
  );

  const { run: runActiveToggle, isPending: activeTogglePending } = useAsyncAction(persistActive, {
    successMessage: false,
    errorMessage: "Не удалось обновить статус бота.",
  });

  const handleActiveChange = async (next: boolean): Promise<void> => {
    const previous = isActive;
    setIsActive(next);
    const result = await runActiveToggle(next);
    if (!result.ok) {
      setIsActive(previous);
    }
  };

  const handleAvatarPick = (): void => {
    fileInputRef.current?.click();
  };

  const handleAvatarChange = async (event: React.ChangeEvent<HTMLInputElement>): Promise<void> => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }

    const localPreview = URL.createObjectURL(file);
    setAvatarPreview(localPreview);
    setAvatarUploading(true);

    try {
      const response = await uploadBotAvatar(botId, file);
      setAvatarPreview(response.avatar_url);
      await loadAgentProfile(botId);
      showToast("Аватар обновлён.", "settings");
    } catch (error) {
      setAvatarPreview(profile.avatar_url ?? null);
      showToast(getApiErrorMessage(error, "Не удалось загрузить аватар."), "error");
    } finally {
      setAvatarUploading(false);
      URL.revokeObjectURL(localPreview);
    }
  };

  const handleSave = async (): Promise<void> => {
    if (!name.trim()) {
      showToast("Укажите название агента.", "error");
      return;
    }

    try {
      await saveAgentSettings(botId, {
        name: name.trim(),
        is_active: isActive,
        default_chat_state: defaultChatState,
        timezone,
        schedule_config: {
          ...scheduleConfig,
          timezone,
        },
      });
      showToast("Настройки агента и расписание сохранены.", "settings");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось сохранить настройки."), "error");
    }
  };

  return (
    <div className="space-y-6 pb-28">
      <section className="moonai-panel">
        <h2 className="mb-6 text-sm font-semibold text-zinc-200">Общие настройки</h2>

        <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
          <div className="relative shrink-0">
            <div
              className={cn(
                "relative flex h-28 w-28 items-center justify-center overflow-hidden rounded-full",
                "bg-gradient-to-br from-zinc-800 to-zinc-950 ring-2 ring-zinc-700/80",
              )}
            >
              {avatarSrc ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={avatarSrc} alt="" className="h-full w-full object-cover" />
              ) : (
                <User className="h-12 w-12 text-zinc-600" />
              )}
              {avatarUploading && (
                <div className="absolute inset-0 flex items-center justify-center bg-black/50">
                  <Loader2 className="h-6 w-6 animate-spin text-violet-300" />
                </div>
              )}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/gif"
              className="hidden"
              onChange={(event) => void handleAvatarChange(event)}
            />
            <button
              type="button"
              onClick={handleAvatarPick}
              disabled={avatarUploading}
              className="mt-4 inline-flex w-full min-w-[8.5rem] items-center justify-center gap-2 rounded-xl border border-zinc-700/80 bg-zinc-900/80 px-4 py-2.5 text-sm font-medium text-zinc-200 transition hover:border-violet-500/40 hover:bg-zinc-800 disabled:opacity-50"
            >
              <Camera className="h-4 w-4 text-violet-400" />
              Выбрать аватар
            </button>
          </div>

          <div className="min-w-0 flex-1 space-y-5">
            <div>
              <label htmlFor="agent-name" className="text-sm font-medium text-zinc-300">
                Название
              </label>
              <div className="relative mt-2">
                <input
                  id="agent-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  onBlur={() => void handleNameBlur()}
                  placeholder="Новый ИИ-Агент"
                  className="w-full rounded-xl border border-zinc-800 bg-zinc-900/90 px-4 py-3 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500/30"
                />
                {nameSaving && (
                  <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-violet-400" />
                )}
              </div>
            </div>

            <div className="rounded-2xl border border-zinc-800/80 bg-black/20 px-4 py-4">
              <Toggle
                checked={isActive}
                onChange={(checked) => void handleActiveChange(checked)}
                isLoading={activeTogglePending}
                label="Статус бота"
                description="Активировать или деактивировать"
                hint="Когда бот выключен, он не отвечает на входящие сообщения."
              />
            </div>

            <div className="rounded-2xl border border-zinc-800/80 bg-black/20 px-4 py-4">
              <Toggle
                checked={defaultChatState}
                onChange={setDefaultChatState}
                label="Состояние чата по умолчанию"
                description="Активировать или деактивировать"
                hint="Определяет, перехватывает ли оператор входящие диалоги сразу, минуя бота."
              />
            </div>

            <div>
              <label htmlFor="timezone" className="text-sm font-medium text-zinc-300">
                Часовой пояс
              </label>
              <select
                id="timezone"
                value={timezone}
                onChange={(event) => {
                  const nextTimezone = event.target.value;
                  setTimezone(nextTimezone);
                  handleScheduleChange({ ...scheduleConfig, timezone: nextTimezone });
                }}
                className="mt-2 w-full rounded-xl border border-zinc-800 bg-zinc-900/90 px-4 py-3 text-sm text-zinc-100 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500/30"
              >
                {TIMEZONE_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {TIMEZONE_LABELS[option]}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      </section>

      <section className="moonai-panel">
        <Toggle
          checked={scheduleConfig.enabled}
          onChange={(enabled) => handleScheduleChange({ ...scheduleConfig, enabled })}
          label="Включить расписание"
          description="Настройте автоматическую активацию бота в определённое время. Указанное время зависит от выбранного часового пояса агента."
          hint="Расписание применяется только когда переключатель включён."
        />

        <AgentSchedulerWidget
          value={scheduleConfig}
          onChange={handleScheduleChange}
          disabled={!scheduleConfig.enabled}
        />
      </section>

      <section className="moonai-panel space-y-3">
        <div>
          <p className="text-sm font-semibold text-zinc-100">Расширенная диагностика</p>
          <p className="mt-1 text-xs text-zinc-500">
            Экспорт Error Vault и системных метрик для отладки в Cursor Composer.
          </p>
        </div>
        <CursorDebugPanel botId={botId} />
      </section>

      <SaveBar onSave={handleSave} saving={profileSaving} label="Сохранить настройки" />
    </div>
  );
}

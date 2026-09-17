"use client";

import { useEffect, useMemo, useState } from "react";
import { HelpCircle } from "lucide-react";

import { SaveBar } from "@/components/bots/SaveBar";
import { TagsChipInput } from "@/components/integrations/TagsChipInput";
import { Toggle } from "@/components/ui/Toggle";
import { useToast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import type { BotAgentProfile, BotControlConfig } from "@/types/agent";

type ControlSection = "history" | "operator" | "keywords";

const SECTIONS: Array<{ id: ControlSection; label: string }> = [
  { id: "history", label: "Оптимизация истории" },
  { id: "operator", label: "Контроль вмешательства оператора" },
  { id: "keywords", label: "Управление диалогом по ключевым фразам" },
];

const TIME_WINDOW_OPTIONS: Array<{ value: number; label: string }> = [
  { value: 1, label: "1 день" },
  { value: 3, label: "3 дня" },
  { value: 7, label: "1 неделя" },
  { value: 14, label: "2 недели" },
  { value: 30, label: "1 месяц" },
];

const HOUR_OPTIONS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0"));
const MINUTE_OPTIONS = ["00", "15", "30", "45"];

function defaultControlConfig(): BotControlConfig {
  return {
    history: { message_limit: 20, time_window_days: 7 },
    spam_protection: {
      enabled: false,
      limit_message: "Секунду, принимаю информацию...",
      message_count: 5,
      duration_seconds: 10,
    },
    operator_intervention: {
      pause_on_operator_message: true,
      ignore_first_operator_message: false,
      auto_resume_enabled: false,
      auto_resume_days: 0,
      auto_resume_hours: 3,
      auto_resume_minutes: 0,
      resume_message_enabled: false,
      resume_message: "Добрый день!",
      exception_phrases_enabled: false,
      exception_phrases: [],
    },
    keyword_dialog: {
      stop_enabled: false,
      stop_phrases: [],
      resume_enabled: false,
      resume_phrases: [],
    },
  };
}

function normalizeControlConfig(raw?: BotControlConfig | null): BotControlConfig {
  const base = defaultControlConfig();
  if (!raw) return base;
  return {
    history: {
      message_limit: Number(raw.history?.message_limit ?? base.history.message_limit),
      time_window_days: Number(raw.history?.time_window_days ?? base.history.time_window_days),
    },
    spam_protection: {
      ...base.spam_protection,
      ...raw.spam_protection,
      limit_message:
        raw.spam_protection?.limit_message ?? base.spam_protection.limit_message,
      message_count: Number(
        raw.spam_protection?.message_count ?? base.spam_protection.message_count,
      ),
      duration_seconds: Number(
        raw.spam_protection?.duration_seconds ?? base.spam_protection.duration_seconds,
      ),
    },
    operator_intervention: {
      ...base.operator_intervention,
      ...raw.operator_intervention,
      exception_phrases: Array.isArray(raw.operator_intervention?.exception_phrases)
        ? raw.operator_intervention.exception_phrases
        : [],
      resume_message:
        raw.operator_intervention?.resume_message ??
        base.operator_intervention.resume_message,
      auto_resume_days: Number(
        raw.operator_intervention?.auto_resume_days ??
          base.operator_intervention.auto_resume_days,
      ),
      auto_resume_hours: Number(
        raw.operator_intervention?.auto_resume_hours ??
          base.operator_intervention.auto_resume_hours,
      ),
      auto_resume_minutes: Number(
        raw.operator_intervention?.auto_resume_minutes ??
          base.operator_intervention.auto_resume_minutes,
      ),
    },
    keyword_dialog: {
      ...base.keyword_dialog,
      ...raw.keyword_dialog,
      stop_phrases: Array.isArray(raw.keyword_dialog?.stop_phrases)
        ? raw.keyword_dialog.stop_phrases
        : [],
      resume_phrases: Array.isArray(raw.keyword_dialog?.resume_phrases)
        ? raw.keyword_dialog.resume_phrases
        : [],
    },
  };
}

function FieldLabel({ label, hint }: { label: string; hint?: string }) {
  return (
    <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-zinc-300">
      {label}
      {hint ? (
        <span title={hint} className="inline-flex text-zinc-500">
          <HelpCircle className="h-3.5 w-3.5" />
        </span>
      ) : null}
    </label>
  );
}

function NumberInput(props: {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  className?: string;
}) {
  return (
    <input
      type="number"
      min={props.min}
      max={props.max}
      value={props.value}
      onChange={(event) => props.onChange(Number(event.target.value) || 0)}
      className={cn(
        "w-24 rounded-xl border border-zinc-800 bg-black/30 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/50",
        props.className,
      )}
    />
  );
}

interface AgentControlTabProps {
  botId: string;
  profile: BotAgentProfile;
}

export function AgentControlTab({ botId, profile }: AgentControlTabProps) {
  const saveAgentSettings = useBotStore((state) => state.saveAgentSettings);
  const profileSaving = useBotStore((state) => state.profileSaving[botId] ?? false);
  const { showToast } = useToast();
  const [section, setSection] = useState<ControlSection>("history");
  const [config, setConfig] = useState<BotControlConfig>(() =>
    normalizeControlConfig(profile.control_config),
  );

  useEffect(() => {
    setConfig(normalizeControlConfig(profile.control_config));
  }, [profile]);

  const dirty = useMemo(
    () => JSON.stringify(config) !== JSON.stringify(normalizeControlConfig(profile.control_config)),
    [config, profile.control_config],
  );

  const handleSave = async (): Promise<void> => {
    try {
      await saveAgentSettings(botId, { control_config: config });
      showToast("Настройки контроля сохранены.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось сохранить контроль."), "error");
    }
  };

  return (
    <div className="space-y-6">
      <nav className="flex flex-wrap gap-2">
        {SECTIONS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setSection(item.id)}
            className={cn(
              "rounded-xl px-3.5 py-2 text-sm transition",
              section === item.id
                ? "bg-zinc-100 font-medium text-zinc-900"
                : "bg-zinc-900/60 text-zinc-300 ring-1 ring-zinc-800 hover:bg-zinc-800/80",
            )}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {section === "history" ? (
        <section className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">Оптимизация истории</h2>
            <p className="mt-1 text-sm text-zinc-500">
              Ускорьте агента и экономьте токены, ограничивая число недавних сообщений в контексте.
            </p>
          </div>

          <div className="glass-card space-y-3">
            <div>
              <p className="text-sm font-medium text-zinc-100">Ограничение по количеству сообщений</p>
              <p className="mt-1 text-xs text-zinc-500">
                Агент учитывает только последние N сообщений в диалоге с клиентом.
              </p>
            </div>
            <div>
              <FieldLabel
                label="Кол-во сообщений"
                hint="Сколько последних реплик попадает в контекст LLM"
              />
              <NumberInput
                value={config.history.message_limit}
                min={1}
                max={200}
                onChange={(message_limit) =>
                  setConfig((prev) => ({
                    ...prev,
                    history: { ...prev.history, message_limit },
                  }))
                }
              />
            </div>
          </div>

          <div className="glass-card space-y-3">
            <div>
              <p className="text-sm font-medium text-zinc-100">Ограничение по времени</p>
              <p className="mt-1 text-xs text-zinc-500">
                Агент учитывает только сообщения за выбранный период.
              </p>
            </div>
            <div>
              <FieldLabel label="Временной промежуток" hint="Окно истории относительно текущего момента" />
              <select
                value={config.history.time_window_days}
                onChange={(event) =>
                  setConfig((prev) => ({
                    ...prev,
                    history: {
                      ...prev.history,
                      time_window_days: Number(event.target.value),
                    },
                  }))
                }
                className="w-full max-w-xs rounded-xl border border-zinc-800 bg-black/30 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
              >
                {TIME_WINDOW_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </section>
      ) : null}

      {section === "operator" ? (
        <section className="space-y-4">
          <div className="glass-card space-y-4">
            <Toggle
              checked={config.spam_protection.enabled}
              onChange={(enabled) =>
                setConfig((prev) => ({
                  ...prev,
                  spam_protection: { ...prev.spam_protection, enabled },
                }))
              }
              label="Защита от спама пользователя"
              description="Защищает агента от повторных и массовых сообщений."
            />
            {config.spam_protection.enabled ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <FieldLabel label="Сообщение при достижении лимита" />
                  <input
                    value={config.spam_protection.limit_message}
                    onChange={(event) =>
                      setConfig((prev) => ({
                        ...prev,
                        spam_protection: {
                          ...prev.spam_protection,
                          limit_message: event.target.value,
                        },
                      }))
                    }
                    className="w-full rounded-xl border border-zinc-800 bg-black/30 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
                  />
                </div>
                <div>
                  <FieldLabel label="Кол-во сообщений" />
                  <NumberInput
                    value={config.spam_protection.message_count}
                    min={1}
                    max={100}
                    onChange={(message_count) =>
                      setConfig((prev) => ({
                        ...prev,
                        spam_protection: { ...prev.spam_protection, message_count },
                      }))
                    }
                  />
                </div>
                <div>
                  <FieldLabel label="Длительность (сек)" />
                  <NumberInput
                    value={config.spam_protection.duration_seconds}
                    min={1}
                    max={3600}
                    onChange={(duration_seconds) =>
                      setConfig((prev) => ({
                        ...prev,
                        spam_protection: { ...prev.spam_protection, duration_seconds },
                      }))
                    }
                  />
                </div>
              </div>
            ) : null}
          </div>

          <div className="glass-card">
            <Toggle
              checked={config.operator_intervention.pause_on_operator_message}
              onChange={(pause_on_operator_message) =>
                setConfig((prev) => ({
                  ...prev,
                  operator_intervention: {
                    ...prev.operator_intervention,
                    pause_on_operator_message,
                  },
                }))
              }
              label="Пауза при вмешательстве оператора"
              description="Агент автоматически ставится на паузу, когда менеджер пишет в диалог."
            />
          </div>

          <div className="glass-card">
            <Toggle
              checked={config.operator_intervention.ignore_first_operator_message}
              onChange={(ignore_first_operator_message) =>
                setConfig((prev) => ({
                  ...prev,
                  operator_intervention: {
                    ...prev.operator_intervention,
                    ignore_first_operator_message,
                  },
                }))
              }
              label="Игнорировать первое сообщение в диалоге"
              description="Первое сообщение оператора не будет ставить агента на паузу."
            />
          </div>

          <div className="glass-card space-y-4">
            <Toggle
              checked={config.operator_intervention.auto_resume_enabled}
              onChange={(auto_resume_enabled) =>
                setConfig((prev) => ({
                  ...prev,
                  operator_intervention: {
                    ...prev.operator_intervention,
                    auto_resume_enabled,
                  },
                }))
              }
              label="Автовозобновление работы агента"
              description="Интервал после вмешательства оператора, по истечении которого ИИ снова отвечает."
            />
            {config.operator_intervention.auto_resume_enabled ? (
              <div className="grid gap-3 sm:grid-cols-3">
                <div>
                  <FieldLabel label="Дни" />
                  <NumberInput
                    value={config.operator_intervention.auto_resume_days}
                    min={0}
                    max={30}
                    onChange={(auto_resume_days) =>
                      setConfig((prev) => ({
                        ...prev,
                        operator_intervention: {
                          ...prev.operator_intervention,
                          auto_resume_days,
                        },
                      }))
                    }
                  />
                </div>
                <div>
                  <FieldLabel label="Часы" />
                  <select
                    value={String(config.operator_intervention.auto_resume_hours).padStart(2, "0")}
                    onChange={(event) =>
                      setConfig((prev) => ({
                        ...prev,
                        operator_intervention: {
                          ...prev.operator_intervention,
                          auto_resume_hours: Number(event.target.value),
                        },
                      }))
                    }
                    className="w-full rounded-xl border border-zinc-800 bg-black/30 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
                  >
                    {HOUR_OPTIONS.map((hour) => (
                      <option key={hour} value={hour}>
                        {hour}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <FieldLabel label="Минуты" />
                  <select
                    value={String(config.operator_intervention.auto_resume_minutes).padStart(2, "0")}
                    onChange={(event) =>
                      setConfig((prev) => ({
                        ...prev,
                        operator_intervention: {
                          ...prev.operator_intervention,
                          auto_resume_minutes: Number(event.target.value),
                        },
                      }))
                    }
                    className="w-full rounded-xl border border-zinc-800 bg-black/30 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
                  >
                    {MINUTE_OPTIONS.map((minute) => (
                      <option key={minute} value={minute}>
                        {minute}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            ) : null}
          </div>

          <div className="glass-card space-y-4">
            <Toggle
              checked={config.operator_intervention.resume_message_enabled}
              onChange={(resume_message_enabled) =>
                setConfig((prev) => ({
                  ...prev,
                  operator_intervention: {
                    ...prev.operator_intervention,
                    resume_message_enabled,
                  },
                }))
              }
              label="Сообщение при возобновлении работы ИИ-агента"
              description="ИИ отправит сообщение после возобновления работы."
            />
            {config.operator_intervention.resume_message_enabled ? (
              <div>
                <FieldLabel label="Сообщение" />
                <textarea
                  value={config.operator_intervention.resume_message}
                  onChange={(event) =>
                    setConfig((prev) => ({
                      ...prev,
                      operator_intervention: {
                        ...prev.operator_intervention,
                        resume_message: event.target.value,
                      },
                    }))
                  }
                  rows={3}
                  placeholder="Добрый день!"
                  className="w-full rounded-xl border border-zinc-800 bg-black/30 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
                />
              </div>
            ) : null}
          </div>

          <div className="glass-card space-y-4">
            <Toggle
              checked={config.operator_intervention.exception_phrases_enabled}
              onChange={(exception_phrases_enabled) =>
                setConfig((prev) => ({
                  ...prev,
                  operator_intervention: {
                    ...prev.operator_intervention,
                    exception_phrases_enabled,
                  },
                }))
              }
              label="Сообщения-исключения"
              description="ИИ не остановится, если оператор отправит эти фразы."
            />
            {config.operator_intervention.exception_phrases_enabled ? (
              <div>
                <FieldLabel label="Фраза" hint="Enter — добавить фразу" />
                <TagsChipInput
                  value={config.operator_intervention.exception_phrases}
                  onChange={(exception_phrases) =>
                    setConfig((prev) => ({
                      ...prev,
                      operator_intervention: {
                        ...prev.operator_intervention,
                        exception_phrases,
                      },
                    }))
                  }
                  placeholder="Новая фраза"
                />
                <p className="mt-1.5 text-xs text-zinc-600">Нажмите Enter, чтобы добавить фразу</p>
              </div>
            ) : null}
          </div>
        </section>
      ) : null}

      {section === "keywords" ? (
        <section className="space-y-4">
          <div className="glass-card space-y-4">
            <Toggle
              checked={config.keyword_dialog.stop_enabled}
              onChange={(stop_enabled) =>
                setConfig((prev) => ({
                  ...prev,
                  keyword_dialog: { ...prev.keyword_dialog, stop_enabled },
                }))
              }
              label="Останавливать диалог по ключевым фразам"
              description="ИИ-агент остановит работу, если клиент отправит эти фразы."
              hint="Совпадение по подстроке без учёта регистра"
            />
            {config.keyword_dialog.stop_enabled ? (
              <div>
                <FieldLabel label="Фраза" />
                <TagsChipInput
                  value={config.keyword_dialog.stop_phrases}
                  onChange={(stop_phrases) =>
                    setConfig((prev) => ({
                      ...prev,
                      keyword_dialog: { ...prev.keyword_dialog, stop_phrases },
                    }))
                  }
                  placeholder="Новая фраза"
                />
                <p className="mt-1.5 text-xs text-zinc-600">Нажмите Enter, чтобы добавить фразу</p>
              </div>
            ) : null}
          </div>

          <div className="glass-card space-y-4">
            <Toggle
              checked={config.keyword_dialog.resume_enabled}
              onChange={(resume_enabled) =>
                setConfig((prev) => ({
                  ...prev,
                  keyword_dialog: { ...prev.keyword_dialog, resume_enabled },
                }))
              }
              label="Возобновлять диалог по ключевым фразам"
              description="ИИ-агент возобновит работу, если клиент отправит эти фразы."
            />
            {config.keyword_dialog.resume_enabled ? (
              <div>
                <FieldLabel label="Фраза" />
                <TagsChipInput
                  value={config.keyword_dialog.resume_phrases}
                  onChange={(resume_phrases) =>
                    setConfig((prev) => ({
                      ...prev,
                      keyword_dialog: { ...prev.keyword_dialog, resume_phrases },
                    }))
                  }
                  placeholder="Новая фраза"
                />
                <p className="mt-1.5 text-xs text-zinc-600">Нажмите Enter, чтобы добавить фразу</p>
              </div>
            ) : null}
          </div>
        </section>
      ) : null}

      {(dirty || profileSaving) && <SaveBar onSave={handleSave} saving={profileSaving} />}
    </div>
  );
}

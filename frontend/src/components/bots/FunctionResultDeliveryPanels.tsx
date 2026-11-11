"use client";

import { Info } from "lucide-react";

import { FunctionKeyValueEditor } from "@/components/bots/FunctionKeyValueEditor";
import {
  emptyCustomApiConfig,
  emptyDelayedConfig,
  type FunctionCustomApiConfig,
  type FunctionCustomApiMethod,
  type FunctionDelayedConfig,
  type FunctionDelayedMode,
  type FunctionIntegrationKind,
} from "@/types/agent";

const fieldClass =
  "h-9 w-full rounded-lg border border-zinc-600 bg-[#0c0c0e] px-2.5 text-sm text-zinc-100 outline-none transition placeholder:text-zinc-500 focus:border-violet-500 focus:ring-1 focus:ring-violet-500/40";

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-zinc-400">
      {children}
    </label>
  );
}

function formatRuDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-");
  if (!y || !m || !d) return isoDate;
  return `${d}.${m}.${y}`;
}

export function FunctionResultDeliveryPanels({
  integrations,
  customApi,
  delayed,
  whatsappGroupId,
  onCustomApiChange,
  onDelayedChange,
  onWhatsappGroupChange,
}: {
  integrations: FunctionIntegrationKind[];
  customApi: FunctionCustomApiConfig | null | undefined;
  delayed: FunctionDelayedConfig | null | undefined;
  whatsappGroupId: string | null | undefined;
  onCustomApiChange: (next: FunctionCustomApiConfig) => void;
  onDelayedChange: (next: FunctionDelayedConfig) => void;
  onWhatsappGroupChange: (next: string) => void;
}) {
  const api = customApi ?? emptyCustomApiConfig();
  const delay = delayed ?? emptyDelayedConfig();

  return (
    <div className="space-y-4">
      {integrations.includes("whatsapp") ? (
        <div className="space-y-3 rounded-xl border border-zinc-600 bg-[#1a1a1e] p-4 text-zinc-100">
          <h4 className="text-sm font-semibold">WhatsApp-группа</h4>
          <div className="flex items-start gap-2 rounded-lg border border-sky-500/20 bg-sky-500/10 px-3 py-2 text-xs text-sky-100/90">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-sky-300" />
            <span>
              Чтобы агент отправлял результаты в группу, привяжите в настройках канала WhatsApp
            </span>
          </div>
          <div>
            <FieldLabel>Привязанная группа</FieldLabel>
            <input
              value={whatsappGroupId ?? ""}
              onChange={(e) => onWhatsappGroupChange(e.target.value)}
              placeholder="ID или название группы"
              className={fieldClass}
            />
          </div>
        </div>
      ) : null}

      {integrations.includes("custom_api") ? (
        <div className="space-y-3 rounded-xl border border-zinc-600 bg-[#1a1a1e] p-4 text-zinc-100">
          <h4 className="text-sm font-semibold">Custom API</h4>
          <div className="grid gap-3 sm:grid-cols-[140px_1fr]">
            <div>
              <FieldLabel>Метод</FieldLabel>
              <select
                value={api.method}
                onChange={(e) =>
                  onCustomApiChange({
                    ...api,
                    method: e.target.value as FunctionCustomApiMethod,
                  })
                }
                className={fieldClass}
              >
                {(["GET", "POST", "PUT", "PATCH", "DELETE"] as const).map((method) => (
                  <option key={method} value={method}>
                    {method}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <FieldLabel>URL</FieldLabel>
              <input
                value={api.url}
                onChange={(e) => onCustomApiChange({ ...api, url: e.target.value })}
                placeholder="https://example.com"
                className={fieldClass}
              />
            </div>
          </div>

          <FunctionKeyValueEditor
            title="Параметры вызова API (params)"
            rows={api.params}
            onChange={(params) => onCustomApiChange({ ...api, params })}
          />
          <FunctionKeyValueEditor
            title="Заголовки запроса (headers)"
            rows={api.headers}
            onChange={(headers) => onCustomApiChange({ ...api, headers })}
          />
          <FunctionKeyValueEditor
            title="Тело запроса (body)"
            rows={api.body}
            onChange={(body) => onCustomApiChange({ ...api, body })}
          />
        </div>
      ) : null}

      {integrations.includes("delayed") ? (
        <div className="space-y-4 rounded-xl border border-zinc-600 bg-[#1a1a1e] p-4 text-zinc-100">
          <h4 className="text-sm font-semibold">Режим планирования и параметры</h4>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <FieldLabel>Режим</FieldLabel>
              <select
                value={delay.mode}
                onChange={(e) =>
                  onDelayedChange({
                    ...delay,
                    mode: e.target.value as FunctionDelayedMode,
                  })
                }
                className={fieldClass}
              >
                <option value="absolute">Конкретные дата и время</option>
                <option value="relative">Через N минут</option>
              </select>
            </div>
            <div>
              <FieldLabel>Источник</FieldLabel>
              <select value={delay.source} disabled className={fieldClass}>
                <option value="static">Статично</option>
              </select>
            </div>
          </div>

          {delay.mode === "absolute" ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <FieldLabel>Дата</FieldLabel>
                <input
                  type="date"
                  value={delay.date ?? ""}
                  onChange={(e) => onDelayedChange({ ...delay, date: e.target.value })}
                  className={fieldClass}
                />
              </div>
              <div>
                <FieldLabel>Время</FieldLabel>
                <input
                  type="time"
                  value={delay.time ?? ""}
                  onChange={(e) => onDelayedChange({ ...delay, time: e.target.value })}
                  className={fieldClass}
                />
              </div>
            </div>
          ) : (
            <div>
              <FieldLabel>Минут до отправки</FieldLabel>
              <input
                type="number"
                min={1}
                max={10080}
                value={delay.delay_minutes ?? 5}
                onChange={(e) =>
                  onDelayedChange({
                    ...delay,
                    delay_minutes: Math.max(1, Number(e.target.value) || 1),
                  })
                }
                className={fieldClass}
              />
            </div>
          )}

          {delay.mode === "absolute" && delay.date && delay.time ? (
            <div className="rounded-lg border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-sm text-violet-100">
              Будет отправлено: {formatRuDate(delay.date)} в {delay.time}
            </div>
          ) : delay.mode === "relative" ? (
            <div className="rounded-lg border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-sm text-violet-100">
              Будет отправлено через {delay.delay_minutes ?? 5} мин. после вызова функции
            </div>
          ) : null}

          <div>
            <h4 className="mb-1 text-sm font-semibold">Содержимое</h4>
            <p className="mb-2 text-xs text-zinc-400">
              Что доставится в диалог в момент срабатывания
            </p>
            <FieldLabel>Режим</FieldLabel>
            <select value={delay.content_mode} disabled className={`${fieldClass} mb-3`}>
              <option value="message">Сообщение</option>
            </select>
            <FieldLabel>Сообщение</FieldLabel>
            <textarea
              value={delay.message}
              onChange={(e) => onDelayedChange({ ...delay, message: e.target.value })}
              rows={4}
              placeholder="Текст отложенного сообщения"
              className="w-full rounded-lg border border-zinc-600 bg-[#0c0c0e] px-2.5 py-2 text-sm text-zinc-100 outline-none transition placeholder:text-zinc-500 focus:border-violet-500 focus:ring-1 focus:ring-violet-500/40"
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

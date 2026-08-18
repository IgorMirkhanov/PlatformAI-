"use client";

import { useMemo, useState } from "react";
import { Check, Copy, ExternalLink, Loader2 } from "lucide-react";

import { Toggle } from "@/components/ui/Toggle";
import {
  hasFieldErrors,
  mapApiIssuesToFieldErrors,
  validateTelegramForm,
} from "@/lib/channel-validation";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";
import type { ChannelStatus, SetupChannelRequest, TelegramChannelFormValues } from "@/types/channels";

interface TelegramChannelFormProps {
  botId: string;
  status: ChannelStatus;
  saving: boolean;
  onSubmit: (payload: SetupChannelRequest) => Promise<void>;
}

function resolveWebhookPreview(
  botId: string,
  status: ChannelStatus,
  token: string,
): string {
  if (status.webhook_url) {
    return status.webhook_url;
  }
  if (!token.trim()) {
    return `${typeof window !== "undefined" ? window.location.origin : ""}/api/v1/webhooks/telegram/{token_hash}`;
  }
  return "Будет сгенерирован после проверки токена через BotFather";
}

export function TelegramChannelForm({
  botId,
  status,
  saving,
  onSubmit,
}: TelegramChannelFormProps) {
  const [values, setValues] = useState<TelegramChannelFormValues>({
    telegram_bot_token: "",
    telegram_active: status.active ?? true,
  });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [copied, setCopied] = useState(false);

  const webhookPreview = useMemo(
    () => resolveWebhookPreview(botId, status, values.telegram_bot_token),
    [botId, status, values.telegram_bot_token],
  );

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    const clientErrors = validateTelegramForm(values);
    setFieldErrors(clientErrors);
    if (hasFieldErrors(clientErrors)) {
      return;
    }

    try {
      await onSubmit({
        channel_type: "telegram",
        telegram_bot_token: values.telegram_bot_token.trim(),
        telegram_active: values.telegram_active,
      });
      setFieldErrors({});
    } catch (error) {
      if (error instanceof ApiError) {
        setFieldErrors(mapApiIssuesToFieldErrors(error.issues));
      }
      throw error;
    }
  };

  const handleCopyWebhook = async (): Promise<void> => {
    if (!status.webhook_url) {
      return;
    }
    await navigator.clipboard.writeText(status.webhook_url);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div>
        <label htmlFor="telegram-bot-token" className="text-xs text-zinc-500">
          Bot Token (BotFather)
        </label>
        <input
          id="telegram-bot-token"
          type="password"
          autoComplete="off"
          value={values.telegram_bot_token}
          onChange={(event) =>
            setValues((current) => ({ ...current, telegram_bot_token: event.target.value }))
          }
          placeholder="123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
          className={cn(
            "mt-1.5 w-full rounded-xl border bg-black/40 px-3 py-2.5 font-mono text-sm text-zinc-100 focus:outline-none",
            fieldErrors.telegram_bot_token
              ? "border-rose-500/60 focus:border-rose-500"
              : "border-zinc-800 focus:border-[#229ED9]",
          )}
        />
        {fieldErrors.telegram_bot_token ? (
          <p className="mt-1.5 text-xs text-rose-400">{fieldErrors.telegram_bot_token}</p>
        ) : (
          <p className="mt-1.5 text-xs text-zinc-500">
            Токен проверяется через Telegram Bot API и регистрирует webhook автоматически.
          </p>
        )}
      </div>

      <div className="rounded-xl border border-zinc-800/80 bg-zinc-950/50 p-4">
        <div className="mb-2 flex items-center justify-between gap-2">
          <p className="text-xs font-medium text-zinc-300">Webhook URL (preview)</p>
          {status.webhook_url ? (
            <button
              type="button"
              onClick={() => void handleCopyWebhook()}
              className="inline-flex items-center gap-1 text-[11px] text-zinc-400 hover:text-zinc-200"
            >
              {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
              {copied ? "Скопировано" : "Копировать"}
            </button>
          ) : null}
        </div>
        <code className="block break-all rounded-lg bg-black/50 px-3 py-2 text-[11px] leading-relaxed text-zinc-400">
          {webhookPreview}
        </code>
      </div>

      <div className="flex items-center justify-between rounded-xl border border-zinc-800/80 bg-zinc-950/40 px-4 py-3">
        <div>
          <p className="text-sm font-medium text-zinc-200">Активный канал</p>
          <p className="text-xs text-zinc-500">Отслеживание статуса и приём входящих сообщений</p>
        </div>
        <Toggle
          checked={values.telegram_active}
          onChange={(checked) =>
            setValues((current) => ({ ...current, telegram_active: checked }))
          }
        />
      </div>

      <button
        type="submit"
        disabled={saving}
        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#229ED9] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#1d8fc7] disabled:opacity-60"
      >
        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        {status.connected ? "Обновить Telegram" : "Подключить Telegram"}
      </button>

      {status.webhook_url ? (
        <a
          href={status.webhook_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-300"
        >
          <ExternalLink className="h-3 w-3" />
          Открыть webhook endpoint
        </a>
      ) : null}
    </form>
  );
}

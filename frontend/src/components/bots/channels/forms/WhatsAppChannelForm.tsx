"use client";

import { useState } from "react";
import { Check, Copy, Loader2 } from "lucide-react";

import {
  hasFieldErrors,
  mapApiIssuesToFieldErrors,
  validateWhatsAppForm,
} from "@/lib/channel-validation";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ChannelStatus, SetupChannelRequest, WhatsAppChannelFormValues } from "@/types/channels";

interface WhatsAppChannelFormProps {
  status: ChannelStatus;
  saving: boolean;
  onSubmit: (payload: SetupChannelRequest) => Promise<void>;
}

export function WhatsAppChannelForm({ status, saving, onSubmit }: WhatsAppChannelFormProps) {
  const [values, setValues] = useState<WhatsAppChannelFormValues>({
    whatsapp_phone_number_id: status.metadata?.whatsapp_phone_number_id ?? "",
    whatsapp_business_account_id: status.metadata?.whatsapp_business_account_id ?? "",
    whatsapp_access_token: "",
    whatsapp_verify_token: status.verify_token ?? "",
  });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [copiedField, setCopiedField] = useState<string | null>(null);

  const metaWebhook =
    status.webhook_url ??
    `${typeof window !== "undefined" ? window.location.origin : ""}/api/v1/webhooks/whatsapp/{token_hash}`;

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    const clientErrors = validateWhatsAppForm(values);
    setFieldErrors(clientErrors);
    if (hasFieldErrors(clientErrors)) {
      return;
    }

    try {
      await onSubmit({
        channel_type: "whatsapp",
        whatsapp_phone_number_id: values.whatsapp_phone_number_id.trim(),
        whatsapp_business_account_id: values.whatsapp_business_account_id.trim(),
        whatsapp_access_token: values.whatsapp_access_token.trim(),
        whatsapp_verify_token: values.whatsapp_verify_token.trim() || undefined,
      });
      setFieldErrors({});
    } catch (error) {
      if (error instanceof ApiError) {
        setFieldErrors(mapApiIssuesToFieldErrors(error.issues));
      }
      throw error;
    }
  };

  const copyValue = async (field: string, value: string): Promise<void> => {
    await navigator.clipboard.writeText(value);
    setCopiedField(field);
    window.setTimeout(() => setCopiedField(null), 2000);
  };

  const inputClass = (field: keyof WhatsAppChannelFormValues): string =>
    cn(
      "mt-1.5 w-full rounded-xl border bg-black/40 px-3 py-2.5 text-sm text-zinc-100 focus:outline-none",
      fieldErrors[field]
        ? "border-rose-500/60 focus:border-rose-500"
        : "border-zinc-800 focus:border-[#25D366]",
    );

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label htmlFor="wa-phone-id" className="text-xs text-zinc-500">
            Phone Number ID
          </label>
          <input
            id="wa-phone-id"
            value={values.whatsapp_phone_number_id}
            onChange={(event) =>
              setValues((current) => ({
                ...current,
                whatsapp_phone_number_id: event.target.value,
              }))
            }
            className={inputClass("whatsapp_phone_number_id")}
            placeholder="105678901234567"
          />
          {fieldErrors.whatsapp_phone_number_id ? (
            <p className="mt-1 text-xs text-rose-400">{fieldErrors.whatsapp_phone_number_id}</p>
          ) : null}
        </div>

        <div>
          <label htmlFor="wa-account-id" className="text-xs text-zinc-500">
            WABA Account ID
          </label>
          <input
            id="wa-account-id"
            value={values.whatsapp_business_account_id}
            onChange={(event) =>
              setValues((current) => ({
                ...current,
                whatsapp_business_account_id: event.target.value,
              }))
            }
            className={inputClass("whatsapp_business_account_id")}
            placeholder="102938475610203"
          />
          {fieldErrors.whatsapp_business_account_id ? (
            <p className="mt-1 text-xs text-rose-400">
              {fieldErrors.whatsapp_business_account_id}
            </p>
          ) : null}
        </div>
      </div>

      <div>
        <label htmlFor="wa-access-token" className="text-xs text-zinc-500">
          System Access Token
        </label>
        <input
          id="wa-access-token"
          type="password"
          autoComplete="off"
          value={values.whatsapp_access_token}
          onChange={(event) =>
            setValues((current) => ({ ...current, whatsapp_access_token: event.target.value }))
          }
          className={inputClass("whatsapp_access_token")}
          placeholder="EAAG..."
        />
        {fieldErrors.whatsapp_access_token ? (
          <p className="mt-1 text-xs text-rose-400">{fieldErrors.whatsapp_access_token}</p>
        ) : (
          <p className="mt-1 text-xs text-zinc-500">
            Permanent token из Meta Business Suite с правами whatsapp_business_messaging.
          </p>
        )}
      </div>

      <div>
        <label htmlFor="wa-verify-token" className="text-xs text-zinc-500">
          Meta Webhook Verification Token
        </label>
        <div className="relative">
          <input
            id="wa-verify-token"
            value={values.whatsapp_verify_token}
            onChange={(event) =>
              setValues((current) => ({
                ...current,
                whatsapp_verify_token: event.target.value,
              }))
            }
            className={inputClass("whatsapp_verify_token")}
            placeholder="Автогенерация при сохранении"
          />
          {values.whatsapp_verify_token ? (
            <button
              type="button"
              onClick={() => void copyValue("verify", values.whatsapp_verify_token)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-200"
            >
              {copiedField === "verify" ? (
                <Check className="h-4 w-4 text-emerald-400" />
              ) : (
                <Copy className="h-4 w-4" />
              )}
            </button>
          ) : null}
        </div>
        {fieldErrors.whatsapp_verify_token ? (
          <p className="mt-1 text-xs text-rose-400">{fieldErrors.whatsapp_verify_token}</p>
        ) : (
          <p className="mt-1 text-xs text-zinc-500">
            Используйте этот token при верификации webhook в Meta Developers.
          </p>
        )}
      </div>

      <div className="rounded-xl border border-zinc-800/80 bg-zinc-950/50 p-4">
        <div className="mb-2 flex items-center justify-between gap-2">
          <p className="text-xs font-medium text-zinc-300">Callback URL (Meta Webhook)</p>
          <button
            type="button"
            onClick={() => void copyValue("webhook", metaWebhook)}
            className="inline-flex items-center gap-1 text-[11px] text-zinc-400 hover:text-zinc-200"
          >
            {copiedField === "webhook" ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            Копировать
          </button>
        </div>
        <code className="block break-all rounded-lg bg-black/50 px-3 py-2 text-[11px] text-zinc-400">
          {metaWebhook}
        </code>
      </div>

      <button
        type="submit"
        disabled={saving}
        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#25D366] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#1fb855] disabled:opacity-60"
      >
        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        {status.connected ? "Обновить WABA" : "Подключить WhatsApp Cloud API"}
      </button>
    </form>
  );
}

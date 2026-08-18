"use client";

import { useState } from "react";
import { Check, Copy, Loader2 } from "lucide-react";

import {
  hasFieldErrors,
  mapApiIssuesToFieldErrors,
  validateInstagramForm,
} from "@/lib/channel-validation";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ChannelStatus, InstagramChannelFormValues, SetupChannelRequest } from "@/types/channels";

interface InstagramChannelFormProps {
  status: ChannelStatus;
  saving: boolean;
  onSubmit: (payload: SetupChannelRequest) => Promise<void>;
}

export function InstagramChannelForm({ status, saving, onSubmit }: InstagramChannelFormProps) {
  const [values, setValues] = useState<InstagramChannelFormValues>({
    instagram_page_id: status.metadata?.instagram_page_id ?? "",
    instagram_access_token: "",
  });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [copied, setCopied] = useState(false);

  const webhookUrl =
    status.webhook_url ??
    `${typeof window !== "undefined" ? window.location.origin : ""}/api/v1/webhooks/instagram/{token_hash}`;

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    const clientErrors = validateInstagramForm(values);
    setFieldErrors(clientErrors);
    if (hasFieldErrors(clientErrors)) {
      return;
    }

    try {
      await onSubmit({
        channel_type: "instagram",
        instagram_page_id: values.instagram_page_id.trim(),
        instagram_access_token: values.instagram_access_token.trim(),
      });
      setFieldErrors({});
    } catch (error) {
      if (error instanceof ApiError) {
        setFieldErrors(mapApiIssuesToFieldErrors(error.issues));
      }
      throw error;
    }
  };

  const inputClass = (field: keyof InstagramChannelFormValues): string =>
    cn(
      "mt-1.5 w-full rounded-xl border bg-black/40 px-3 py-2.5 text-sm text-zinc-100 focus:outline-none",
      fieldErrors[field]
        ? "border-rose-500/60 focus:border-rose-500"
        : "border-zinc-800 focus:border-[#E4405F]",
    );

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div>
        <label htmlFor="ig-page-id" className="text-xs text-zinc-500">
          Instagram Page ID
        </label>
        <input
          id="ig-page-id"
          value={values.instagram_page_id}
          onChange={(event) =>
            setValues((current) => ({ ...current, instagram_page_id: event.target.value }))
          }
          className={inputClass("instagram_page_id")}
          placeholder="17841400000000000"
        />
        {fieldErrors.instagram_page_id ? (
          <p className="mt-1 text-xs text-rose-400">{fieldErrors.instagram_page_id}</p>
        ) : (
          <p className="mt-1 text-xs text-zinc-500">
            ID Facebook/Instagram Page, связанной с Business Account.
          </p>
        )}
      </div>

      <div>
        <label htmlFor="ig-access-token" className="text-xs text-zinc-500">
          Page Access Token
        </label>
        <input
          id="ig-access-token"
          type="password"
          autoComplete="off"
          value={values.instagram_access_token}
          onChange={(event) =>
            setValues((current) => ({ ...current, instagram_access_token: event.target.value }))
          }
          className={inputClass("instagram_access_token")}
          placeholder="EAAG..."
        />
        {fieldErrors.instagram_access_token ? (
          <p className="mt-1 text-xs text-rose-400">{fieldErrors.instagram_access_token}</p>
        ) : null}
      </div>

      <div className="rounded-xl border border-zinc-800/80 bg-zinc-950/50 p-4">
        <div className="mb-2 flex items-center justify-between gap-2">
          <p className="text-xs font-medium text-zinc-300">Webhook endpoint</p>
          <button
            type="button"
            onClick={() => {
              void navigator.clipboard.writeText(webhookUrl);
              setCopied(true);
              window.setTimeout(() => setCopied(false), 2000);
            }}
            className="inline-flex items-center gap-1 text-[11px] text-zinc-400 hover:text-zinc-200"
          >
            {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            Копировать
          </button>
        </div>
        <code className="block break-all rounded-lg bg-black/50 px-3 py-2 text-[11px] text-zinc-400">
          {webhookUrl}
        </code>
        {status.verify_token ? (
          <p className="mt-3 text-xs text-zinc-500">
            Verify Token: <span className="font-mono text-zinc-300">{status.verify_token}</span>
          </p>
        ) : null}
      </div>

      <button
        type="submit"
        disabled={saving}
        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-[#FD5949] via-[#D6249F] to-[#285AEB] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
      >
        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        {status.connected ? "Обновить Instagram Direct" : "Подключить Instagram Direct"}
      </button>
    </form>
  );
}

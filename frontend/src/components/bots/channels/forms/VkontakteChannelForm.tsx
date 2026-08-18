"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import {
  hasFieldErrors,
  mapApiIssuesToFieldErrors,
  validateVkontakteForm,
} from "@/lib/channel-validation";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ChannelStatus, SetupChannelRequest, VkontakteChannelFormValues } from "@/types/channels";

interface VkontakteChannelFormProps {
  status: ChannelStatus;
  saving: boolean;
  onSubmit: (payload: SetupChannelRequest) => Promise<void>;
}

export function VkontakteChannelForm({ status, saving, onSubmit }: VkontakteChannelFormProps) {
  const [values, setValues] = useState<VkontakteChannelFormValues>({
    vk_group_id: status.metadata?.vk_group_id ?? "",
    vk_access_token: "",
  });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const callbackUrl =
    status.webhook_url ??
    `${typeof window !== "undefined" ? window.location.origin : ""}/api/v1/webhooks/vkontakte/{token_hash}`;

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    const clientErrors = validateVkontakteForm(values);
    setFieldErrors(clientErrors);
    if (hasFieldErrors(clientErrors)) {
      return;
    }

    try {
      await onSubmit({
        channel_type: "vkontakte",
        vk_group_id: values.vk_group_id.trim(),
        vk_access_token: values.vk_access_token.trim(),
      });
      setFieldErrors({});
    } catch (error) {
      if (error instanceof ApiError) {
        setFieldErrors(mapApiIssuesToFieldErrors(error.issues));
      }
      throw error;
    }
  };

  const inputClass = (field: keyof VkontakteChannelFormValues): string =>
    cn(
      "mt-1.5 w-full rounded-xl border bg-black/40 px-3 py-2.5 text-sm text-zinc-100 focus:outline-none",
      fieldErrors[field]
        ? "border-rose-500/60 focus:border-rose-500"
        : "border-zinc-800 focus:border-[#0077FF]",
    );

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div>
        <label htmlFor="vk-group-id" className="text-xs text-zinc-500">
          ID сообщества VK
        </label>
        <input
          id="vk-group-id"
          value={values.vk_group_id}
          onChange={(event) =>
            setValues((current) => ({ ...current, vk_group_id: event.target.value }))
          }
          className={inputClass("vk_group_id")}
          placeholder="-123456789"
        />
        {fieldErrors.vk_group_id ? (
          <p className="mt-1 text-xs text-rose-400">{fieldErrors.vk_group_id}</p>
        ) : (
          <p className="mt-1 text-xs text-zinc-500">
            Числовой ID группы из настроек сообщества VK.
          </p>
        )}
      </div>

      <div>
        <label htmlFor="vk-access-token" className="text-xs text-zinc-500">
          Access Token сообщества
        </label>
        <input
          id="vk-access-token"
          type="password"
          autoComplete="off"
          value={values.vk_access_token}
          onChange={(event) =>
            setValues((current) => ({ ...current, vk_access_token: event.target.value }))
          }
          className={inputClass("vk_access_token")}
          placeholder="vk1.a...."
        />
        {fieldErrors.vk_access_token ? (
          <p className="mt-1 text-xs text-rose-400">{fieldErrors.vk_access_token}</p>
        ) : (
          <p className="mt-1 text-xs text-zinc-500">
            Ключ доступа с правами messages и manage для Callback API.
          </p>
        )}
      </div>

      <div className="rounded-xl border border-zinc-800/80 bg-zinc-950/50 p-4">
        <p className="mb-2 text-xs font-medium text-zinc-300">Callback URL</p>
        <code className="block break-all rounded-lg bg-black/50 px-3 py-2 text-[11px] text-zinc-400">
          {callbackUrl}
        </code>
      </div>

      <button
        type="submit"
        disabled={saving}
        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#0077FF] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#006AE0] disabled:opacity-60"
      >
        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        {status.connected ? "Обновить VKontakte" : "Подключить VKontakte"}
      </button>
    </form>
  );
}

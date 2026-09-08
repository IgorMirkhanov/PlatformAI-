"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { HubProvider } from "@/types/integration-hub";

interface HubApiKeyConnectFormProps {
  provider: HubProvider | string;
  submitting: boolean;
  error?: string | null;
  onSubmit: (payload: Record<string, string>) => Promise<void>;
  onCancel?: () => void;
}

export function HubApiKeyConnectForm({
  provider,
  submitting,
  error,
  onSubmit,
  onCancel,
}: HubApiKeyConnectFormProps) {
  const isKaspi = provider === "kaspi_pay";
  const isBitrix = provider === "bitrix24";
  const [apiKey, setApiKey] = useState("");
  const [merchantId, setMerchantId] = useState("");
  const [secretKey, setSecretKey] = useState("");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  const handleSubmit = async (): Promise<void> => {
    setLocalError(null);
    if (isBitrix) {
      const url = webhookUrl.trim();
      if (!/^https?:\/\/.+/i.test(url) || !url.includes("/rest/")) {
        setLocalError("Укажите Incoming Webhook URL Bitrix24 (…/rest/1/xxxxx/).");
        return;
      }
      await onSubmit({ webhook_url: url.endsWith("/") ? url : `${url}/` });
      return;
    }
    if (isKaspi) {
      if (!merchantId.trim()) {
        setLocalError("Укажите Merchant ID.");
        return;
      }
      if (apiKey.trim().length < 8) {
        setLocalError("Merchant token слишком короткий.");
        return;
      }
      const payload: Record<string, string> = {
        merchant_id: merchantId.trim(),
        merchant_token: apiKey.trim(),
      };
      if (secretKey.trim()) payload.secret_key = secretKey.trim();
      await onSubmit(payload);
      return;
    }
    if (apiKey.trim().length < 8) {
      setLocalError("API-ключ слишком короткий.");
      return;
    }
    await onSubmit({ api_key: apiKey.trim() });
  };

  return (
    <form
      className="mt-4 space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit();
      }}
    >
      {isBitrix ? (
        <>
          <p className="text-xs leading-relaxed text-zinc-500">
            В Bitrix24: Разработчикам → Другое → Входящий вебхук. Права: CRM (сделки, контакты).
          </p>
          <label className="block text-xs font-medium text-zinc-400">
            Incoming Webhook URL
            <input
              value={webhookUrl}
              onChange={(event) => setWebhookUrl(event.target.value)}
              autoComplete="off"
              placeholder="https://your.bitrix24.ru/rest/1/xxxxxxxx/"
              className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
            />
          </label>
        </>
      ) : null}
      {isKaspi ? (
        <label className="block text-xs font-medium text-zinc-400">
          Merchant ID
          <input
            value={merchantId}
            onChange={(event) => setMerchantId(event.target.value)}
            autoComplete="off"
            className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
          />
        </label>
      ) : null}
      {!isBitrix ? (
      <label className="block text-xs font-medium text-zinc-400">
        {isKaspi ? "Merchant token" : "API-ключ"}
        <input
          type="password"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          autoComplete="off"
          className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
        />
      </label>
      ) : null}
      {isKaspi ? (
        <label className="block text-xs font-medium text-zinc-400">
          Webhook secret (HMAC, необязательно)
          <input
            type="password"
            value={secretKey}
            onChange={(event) => setSecretKey(event.target.value)}
            autoComplete="off"
            className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
          />
        </label>
      ) : null}
      {localError || error ? (
        <p className="text-xs text-rose-300">{localError || error}</p>
      ) : (
        <p className="text-[11px] text-zinc-500">
          {isBitrix
            ? "URL проверяется запросом profile.json и сохраняется только после успеха."
            : "Ключ проверяется через testConnection() и сохраняется только после успешной проверки."}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={submitting} className="bg-violet-600 text-white hover:bg-violet-500">
          {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Проверить и подключить
        </Button>
        {onCancel ? (
          <Button type="button" size="sm" variant="ghost" disabled={submitting} onClick={onCancel}>
            Отмена
          </Button>
        ) : null}
      </div>
    </form>
  );
}

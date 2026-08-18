"use client";

import { Loader2, X } from "lucide-react";

import { cn } from "@/lib/utils";
import type { CRMIntegrationDefinition } from "@/types/crm-integrations";

interface IntegrationConfigModalProps {
  open: boolean;
  definition: CRMIntegrationDefinition | null;
  amoDomain: string;
  amoClientId: string;
  amoClientSecret: string;
  amoAuthCode: string;
  bitrixWebhook: string;
  loading: boolean;
  onClose: () => void;
  onAmoDomainChange: (value: string) => void;
  onAmoClientIdChange: (value: string) => void;
  onAmoClientSecretChange: (value: string) => void;
  onAmoAuthCodeChange: (value: string) => void;
  onBitrixWebhookChange: (value: string) => void;
  onSubmit: (platform: CRMIntegrationDefinition["id"]) => void;
}

export function IntegrationConfigModal({
  open,
  definition,
  amoDomain,
  amoClientId,
  amoClientSecret,
  amoAuthCode,
  bitrixWebhook,
  loading,
  onClose,
  onAmoDomainChange,
  onAmoClientIdChange,
  onAmoClientSecretChange,
  onAmoAuthCodeChange,
  onBitrixWebhookChange,
  onSubmit,
}: IntegrationConfigModalProps) {
  if (!open || !definition) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/75 backdrop-blur-sm"
        onClick={onClose}
        aria-label="Close modal"
      />
      <div className="moonai-modal relative z-10 w-full max-w-xl">
        <div className="mb-5 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-zinc-50">{definition.title}</h2>
            <p className="mt-1 text-sm text-zinc-500">Введите учётные данные для подключения интеграции.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {definition.id === "amocrm" ? (
          <div className="grid gap-3 md:grid-cols-2">
            <div className="md:col-span-2">
              <label className="text-xs text-zinc-500">Base Domain</label>
              <input
                value={amoDomain}
                onChange={(event) => onAmoDomainChange(event.target.value)}
                placeholder="company.amocrm.ru"
                className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2.5 text-sm text-zinc-100"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500">Client ID</label>
              <input
                value={amoClientId}
                onChange={(event) => onAmoClientIdChange(event.target.value)}
                className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2.5 text-sm text-zinc-100"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500">Client Secret</label>
              <input
                type="password"
                value={amoClientSecret}
                onChange={(event) => onAmoClientSecretChange(event.target.value)}
                className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2.5 text-sm text-zinc-100"
              />
            </div>
            <div className="md:col-span-2">
              <label className="text-xs text-zinc-500">Authorization Code</label>
              <input
                value={amoAuthCode}
                onChange={(event) => onAmoAuthCodeChange(event.target.value)}
                className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2.5 text-sm text-zinc-100"
              />
            </div>
          </div>
        ) : (
          <div>
            <label className="text-xs text-zinc-500">Webhook Rest URL</label>
            <input
              value={bitrixWebhook}
              onChange={(event) => onBitrixWebhookChange(event.target.value)}
              placeholder="https://your-domain.bitrix24.ru/rest/1/xxxxxxxx/"
              className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2.5 text-sm text-zinc-100"
            />
          </div>
        )}

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-zinc-800 px-4 py-2.5 text-sm text-zinc-300 hover:bg-zinc-900"
          >
            Отмена
          </button>
          <button
            type="button"
            disabled={loading}
            onClick={() => onSubmit(definition.id)}
            className={cn(
              "inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-violet-500 disabled:opacity-50",
            )}
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Подключить
          </button>
        </div>
      </div>
    </div>
  );
}

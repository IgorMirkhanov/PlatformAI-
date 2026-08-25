"use client";

import { Loader2, X } from "lucide-react";

import type {
  AppIntegrationConnectPayload,
  AppIntegrationPlatformStatus,
  CRMIntegrationDefinition,
} from "@/types/crm-integrations";

interface IntegrationConfigModalProps {
  open: boolean;
  definition: CRMIntegrationDefinition | null;
  status: AppIntegrationPlatformStatus | undefined;
  saving: boolean;
  form: AppIntegrationConnectPayload;
  onFormChange: (next: AppIntegrationConnectPayload) => void;
  onClose: () => void;
  onConnect: () => void;
  onDisconnect: () => void;
  onGoogleOAuth: () => void;
}

function Field({
  label,
  value,
  onChange,
  password,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  password?: boolean;
  placeholder?: string;
}) {
  return (
    <label className="block text-xs font-medium text-zinc-400">
      {label}
      <input
        type={password ? "password" : "text"}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="mt-2 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none transition focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30"
      />
    </label>
  );
}

export function IntegrationConfigModal({
  open,
  definition,
  status,
  saving,
  form,
  onFormChange,
  onClose,
  onConnect,
  onDisconnect,
  onGoogleOAuth,
}: IntegrationConfigModalProps) {
  if (!open || !definition) return null;

  const connected = Boolean(status?.connected);
  const platform = definition.id;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/75 backdrop-blur-sm"
        onClick={onClose}
        aria-label="Закрыть"
      />
      <div className="moonai-modal relative z-10 flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden">
        <div className="flex items-start justify-between gap-3 border-b border-zinc-800/80 px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-zinc-50">{definition.title}</h2>
            <p className="mt-1 text-sm text-zinc-500">{definition.description}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
          {platform === "google_calendar" ? (
            <>
              <button
                type="button"
                onClick={onGoogleOAuth}
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#4285F4] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#3367D6]"
              >
                Войти через Google
              </button>
              <p className="text-center text-xs text-zinc-500">или введите Client ID / Secret вручную</p>
              <Field
                label="Client ID"
                value={form.client_id || ""}
                onChange={(value) => onFormChange({ ...form, client_id: value })}
              />
              <Field
                label="Client Secret"
                value={form.client_secret || ""}
                onChange={(value) => onFormChange({ ...form, client_secret: value })}
                password
              />
              <Field
                label="OAuth Refresh Token"
                value={form.refresh_token || ""}
                onChange={(value) => onFormChange({ ...form, refresh_token: value })}
                password
              />
              <Field
                label="Access Token (опционально)"
                value={form.access_token || ""}
                onChange={(value) => onFormChange({ ...form, access_token: value })}
                password
              />
              <Field
                label="Calendar ID"
                value={form.calendar_id || "primary"}
                onChange={(value) => onFormChange({ ...form, calendar_id: value })}
              />
            </>
          ) : null}

          {platform === "kaspi_receipts" ? (
            <Field
              label="Ключ OCR / API Token"
              value={form.api_key || ""}
              onChange={(value) => onFormChange({ ...form, api_key: value })}
              password
            />
          ) : null}

          {platform === "kaspi_pay" ? (
            <>
              <Field
                label="Merchant ID"
                value={form.merchant_id || ""}
                onChange={(value) => onFormChange({ ...form, merchant_id: value })}
              />
              <Field
                label="API Token"
                value={form.merchant_token || ""}
                onChange={(value) => onFormChange({ ...form, merchant_token: value })}
                password
              />
              <Field
                label="Webhook secret (HMAC)"
                value={form.secret_key || ""}
                onChange={(value) => onFormChange({ ...form, secret_key: value })}
                password
              />
            </>
          ) : null}

          {platform === "jivo" ? (
            <>
              <Field
                label="Jivo Bot Token"
                value={form.token || ""}
                onChange={(value) => onFormChange({ ...form, token: value })}
                password
              />
              <Field
                label="Provider ID"
                value={form.provider_id || "moonai"}
                onChange={(value) => onFormChange({ ...form, provider_id: value })}
              />
              {status?.webhook_url ? (
                <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-3">
                  <p className="mb-1 text-[10px] uppercase tracking-wide text-zinc-500">Webhook URL</p>
                  <code className="block break-all font-mono text-[11px] text-zinc-400">
                    {status.webhook_url}
                  </code>
                </div>
              ) : null}
            </>
          ) : null}

          {platform === "custom_webhook" ? (
            <>
              <Field
                label="Webhook URL"
                value={form.webhook_target_url || ""}
                onChange={(value) => onFormChange({ ...form, webhook_target_url: value })}
                placeholder="https://example.com/hooks/moonai"
              />
              <Field
                label="HMAC Secret"
                value={form.hmac_secret || ""}
                onChange={(value) => onFormChange({ ...form, hmac_secret: value })}
                password
              />
            </>
          ) : null}

          {platform === "uon" ? (
            <>
              <Field
                label="API Key U-ON"
                value={form.api_key || ""}
                onChange={(value) => onFormChange({ ...form, api_key: value })}
                password
              />
              <Field
                label="Base URL"
                value={form.base_url || "https://api.u-on.ru"}
                onChange={(value) => onFormChange({ ...form, base_url: value })}
              />
            </>
          ) : null}
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-zinc-800/80 px-5 py-4">
          {connected ? (
            <button
              type="button"
              onClick={onDisconnect}
              className="rounded-xl border border-rose-900/60 px-4 py-2.5 text-sm text-rose-300 hover:bg-rose-950/40"
            >
              Отключить
            </button>
          ) : null}
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-zinc-800 px-4 py-2.5 text-sm text-zinc-300 hover:bg-zinc-900"
          >
            Отмена
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={onConnect}
            className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-violet-500 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {connected ? "Сохранить" : "Подключить"}
          </button>
        </div>
      </div>
    </div>
  );
}

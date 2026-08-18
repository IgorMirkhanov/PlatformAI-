"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Plug, X } from "lucide-react";

import { AmoCrmModal } from "@/components/integrations/AmoCrmModal";
import { Bitrix24Modal } from "@/components/integrations/Bitrix24Modal";
import { CrmIntegrationCard } from "@/components/integrations/CrmIntegrationCard";
import {
  connectAppIntegration,
  disconnectAppIntegration,
  fetchAppIntegrationsStatus,
  patchAppIntegration,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { getApiErrorMessage } from "@/store/useBotStore";
import type { BotAgentProfile } from "@/types/agent";
import {
  CRM_INTEGRATION_DEFINITIONS,
  type AppIntegrationConnectPayload,
  type AppIntegrationPlatform,
  type AppIntegrationPlatformStatus,
  type CRMIntegrationDefinition,
} from "@/types/crm-integrations";
import type { CRMIntegrationPatchRequest, CRMPlatform } from "@/types/crm";

interface CrmIntegrationHubProps {
  botId: string;
  profile: BotAgentProfile;
}

type IntegrationFilter = "available" | "connected";

const LOGO: Record<string, string> = {
  amocrm: "amo",
  bitrix24: "B24",
  google_calendar: "G",
  kaspi_receipts: "K",
  kaspi_pay: "KP",
  jivo: "Jv",
  uon: "U",
};

export function CrmIntegrationHub({ botId, profile }: CrmIntegrationHubProps) {
  const { showToast } = useToast();
  const [platforms, setPlatforms] = useState<AppIntegrationPlatformStatus[]>([]);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [filter, setFilter] = useState<IntegrationFilter>("available");
  const [activeDefinition, setActiveDefinition] = useState<CRMIntegrationDefinition | null>(null);
  const [saving, setSaving] = useState(false);
  const [togglingPlatform, setTogglingPlatform] = useState<AppIntegrationPlatform | null>(null);
  const [form, setForm] = useState<AppIntegrationConnectPayload>({});

  const loadStatus = useCallback(async (): Promise<void> => {
    setLoadingStatus(true);
    try {
      const response = await fetchAppIntegrationsStatus(botId);
      setPlatforms(response.platforms as AppIntegrationPlatformStatus[]);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить статус интеграций."), "error");
    } finally {
      setLoadingStatus(false);
    }
  }, [botId, showToast]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const statusMap = useMemo(() => {
    const map = {} as Record<AppIntegrationPlatform, AppIntegrationPlatformStatus | undefined>;
    for (const item of platforms) {
      map[item.platform] = item;
    }
    return map;
  }, [platforms]);

  const connectedCount = CRM_INTEGRATION_DEFINITIONS.filter(
    (item) => statusMap[item.id]?.connected,
  ).length;

  const visibleDefinitions = useMemo(() => {
    if (filter === "connected") {
      return CRM_INTEGRATION_DEFINITIONS.filter((item) => statusMap[item.id]?.connected);
    }
    return CRM_INTEGRATION_DEFINITIONS.filter((item) => item.available);
  }, [filter, statusMap]);

  const handleCrmSave = async (
    platform: CRMPlatform,
    payload: CRMIntegrationPatchRequest,
  ): Promise<void> => {
    setSaving(true);
    try {
      const isConnect =
        Boolean(payload.authorization_code) || Boolean(payload.webhook_url);
      const response = isConnect
        ? await connectAppIntegration(botId, platform, payload as Record<string, unknown>)
        : await patchAppIntegration(botId, platform, payload as Record<string, unknown>);
      showToast(response.message, "success");
      await loadStatus();
      if (!isConnect || !payload.authorization_code) {
        setActiveDefinition(null);
      }
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось сохранить интеграцию."), "error");
      throw error;
    } finally {
      setSaving(false);
    }
  };

  const handleGenericConnect = async (): Promise<void> => {
    if (!activeDefinition) return;
    setSaving(true);
    try {
      const response = await connectAppIntegration(
        botId,
        activeDefinition.id,
        form as Record<string, unknown>,
      );
      showToast(response.message, "success");
      await loadStatus();
      setActiveDefinition(null);
      setForm({});
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось подключить интеграцию."), "error");
    } finally {
      setSaving(false);
    }
  };

  const handleToggleSync = async (
    platform: AppIntegrationPlatform,
    enabled: boolean,
  ): Promise<void> => {
    setTogglingPlatform(platform);
    try {
      await patchAppIntegration(botId, platform, { sync_enabled: enabled });
      showToast(enabled ? "Синхронизация включена." : "Синхронизация отключена.", "success");
      await loadStatus();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось обновить статус синхронизации."), "error");
    } finally {
      setTogglingPlatform(null);
    }
  };

  const handleDisconnect = async (platform: AppIntegrationPlatform): Promise<void> => {
    try {
      const response = await disconnectAppIntegration(botId, platform);
      showToast(response.message, "success");
      await loadStatus();
      setActiveDefinition(null);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось отключить интеграцию."), "error");
    }
  };

  const activePlatform = activeDefinition?.id ?? null;
  const activeStatus = activePlatform ? statusMap[activePlatform] : undefined;
  const isCrm = activePlatform === "amocrm" || activePlatform === "bitrix24";

  return (
    <div className="space-y-6">
      <section className="moonai-panel overflow-hidden">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-violet-500/10 ring-1 ring-violet-500/25">
              <Plug className="h-5 w-5 text-violet-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-zinc-50">Интеграции</h2>
              <p className="mt-1 max-w-2xl text-sm text-zinc-500">
                CRM, календарь, Kaspi, Jivo и U-ON для агента{" "}
                <span className="text-zinc-300">{profile.name}</span>.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setFilter("available")}
              className={cn(
                "rounded-xl px-4 py-2 text-sm font-medium transition",
                filter === "available"
                  ? "bg-violet-600 text-white shadow-glow-purple"
                  : "border border-zinc-800 bg-[#121214] text-zinc-400 hover:text-zinc-200",
              )}
            >
              Доступные {CRM_INTEGRATION_DEFINITIONS.length}
            </button>
            <button
              type="button"
              onClick={() => setFilter("connected")}
              className={cn(
                "rounded-xl px-4 py-2 text-sm font-medium transition",
                filter === "connected"
                  ? "bg-emerald-600 text-white"
                  : "border border-zinc-800 bg-[#121214] text-zinc-400 hover:text-zinc-200",
              )}
            >
              Подключенные {connectedCount}
            </button>
          </div>
        </div>
      </section>

      {loadingStatus && platforms.length === 0 ? (
        <div className="flex min-h-[320px] items-center justify-center rounded-2xl border border-zinc-800/80 bg-[#0b0b0d]/70">
          <div className="flex items-center gap-2 text-sm text-zinc-400">
            <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
            Загрузка интеграций…
          </div>
        </div>
      ) : visibleDefinitions.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-zinc-800 px-6 py-12 text-center">
          <p className="text-sm text-zinc-400">Подключённых интеграций пока нет.</p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {visibleDefinitions.map((definition) => (
            <CrmIntegrationCard
              key={definition.id}
              definition={definition}
              status={
                statusMap[definition.id]
                  ? {
                      platform: definition.id as CRMPlatform,
                      connected: Boolean(statusMap[definition.id]?.connected),
                      sync_enabled: Boolean(statusMap[definition.id]?.sync_enabled),
                      label: statusMap[definition.id]?.label || definition.title,
                      detail: statusMap[definition.id]?.detail ?? null,
                      pipeline_id: null,
                      stage_id: null,
                      default_tags: [],
                    }
                  : undefined
              }
              toggling={togglingPlatform === definition.id}
              onToggleSync={(enabled) => void handleToggleSync(definition.id, enabled)}
              onConfigure={() => {
                setForm({});
                setActiveDefinition(definition);
              }}
              logoOverride={LOGO[definition.id]}
            />
          ))}
        </div>
      )}

      <div className="rounded-2xl border border-zinc-800/80 bg-[#0a0a0c]/90 px-5 py-4">
        <p className="text-sm text-zinc-400">
          Не нашли нужную интеграцию? Напишите нам — добавим в план разработки.
        </p>
      </div>

      <AmoCrmModal
        open={activePlatform === "amocrm"}
        botId={botId}
        definition={activeDefinition}
        status={
          activeStatus
            ? {
                platform: "amocrm",
                connected: activeStatus.connected,
                sync_enabled: activeStatus.sync_enabled,
                label: activeStatus.label,
                detail: activeStatus.detail,
                pipeline_id: null,
                stage_id: null,
                default_tags: [],
              }
            : null
        }
        saving={saving}
        onClose={() => setActiveDefinition(null)}
        onSave={(payload) => handleCrmSave("amocrm", payload)}
      />

      <Bitrix24Modal
        open={activePlatform === "bitrix24"}
        botId={botId}
        definition={activeDefinition}
        status={
          activeStatus
            ? {
                platform: "bitrix24",
                connected: activeStatus.connected,
                sync_enabled: activeStatus.sync_enabled,
                label: activeStatus.label,
                detail: activeStatus.detail,
                pipeline_id: null,
                stage_id: null,
                default_tags: [],
              }
            : null
        }
        saving={saving}
        onClose={() => setActiveDefinition(null)}
        onSave={(payload) => handleCrmSave("bitrix24", payload)}
      />

      {!isCrm && activeDefinition ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            className="absolute inset-0 bg-black/75 backdrop-blur-sm"
            onClick={() => setActiveDefinition(null)}
            aria-label="Close modal"
          />
          <div className="moonai-modal relative z-10 w-full max-w-xl">
            <div className="mb-5 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-zinc-50">{activeDefinition.title}</h2>
                <p className="mt-1 text-sm text-zinc-500">Заполните данные для подключения.</p>
              </div>
              <button
                type="button"
                onClick={() => setActiveDefinition(null)}
                className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="grid gap-3">
              {activeDefinition.id === "google_calendar" ? (
                <>
                  <Field
                    label="OAuth Refresh Token"
                    value={form.refresh_token || ""}
                    onChange={(v) => setForm((s) => ({ ...s, refresh_token: v }))}
                  />
                  <Field
                    label="Access Token (опционально)"
                    value={form.access_token || ""}
                    onChange={(v) => setForm((s) => ({ ...s, access_token: v }))}
                  />
                  <Field
                    label="Calendar ID"
                    value={form.calendar_id || "primary"}
                    onChange={(v) => setForm((s) => ({ ...s, calendar_id: v }))}
                  />
                  <Field
                    label="Client ID"
                    value={form.client_id || ""}
                    onChange={(v) => setForm((s) => ({ ...s, client_id: v }))}
                  />
                  <Field
                    label="Client Secret"
                    value={form.client_secret || ""}
                    onChange={(v) => setForm((s) => ({ ...s, client_secret: v }))}
                    password
                  />
                </>
              ) : null}

              {activeDefinition.id === "kaspi_receipts" ? (
                <Field
                  label="API Key (опционально)"
                  value={form.api_key || ""}
                  onChange={(v) => setForm((s) => ({ ...s, api_key: v }))}
                />
              ) : null}

              {activeDefinition.id === "kaspi_pay" ? (
                <>
                  <Field
                    label="Merchant ID"
                    value={form.merchant_id || ""}
                    onChange={(v) => setForm((s) => ({ ...s, merchant_id: v }))}
                  />
                  <Field
                    label="Merchant Token"
                    value={form.merchant_token || ""}
                    onChange={(v) => setForm((s) => ({ ...s, merchant_token: v }))}
                    password
                  />
                </>
              ) : null}

              {activeDefinition.id === "jivo" ? (
                <>
                  <Field
                    label="Jivo Bot Token"
                    value={form.token || ""}
                    onChange={(v) => setForm((s) => ({ ...s, token: v }))}
                    password
                  />
                  <Field
                    label="Provider ID"
                    value={form.provider_id || "moonai"}
                    onChange={(v) => setForm((s) => ({ ...s, provider_id: v }))}
                  />
                  {activeStatus?.webhook_url ? (
                    <p className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 font-mono text-xs text-zinc-400">
                      Webhook: {activeStatus.webhook_url}
                    </p>
                  ) : null}
                </>
              ) : null}

              {activeDefinition.id === "uon" ? (
                <>
                  <Field
                    label="API Key U-ON"
                    value={form.api_key || ""}
                    onChange={(v) => setForm((s) => ({ ...s, api_key: v }))}
                    password
                  />
                  <Field
                    label="Base URL"
                    value={form.base_url || "https://api.u-on.ru"}
                    onChange={(v) => setForm((s) => ({ ...s, base_url: v }))}
                  />
                </>
              ) : null}
            </div>

            <div className="mt-6 flex flex-wrap justify-end gap-2">
              {activeStatus?.connected ? (
                <button
                  type="button"
                  onClick={() => void handleDisconnect(activeDefinition.id)}
                  className="rounded-xl border border-rose-900/60 px-4 py-2.5 text-sm text-rose-300 hover:bg-rose-950/40"
                >
                  Отключить
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => setActiveDefinition(null)}
                className="rounded-xl border border-zinc-800 px-4 py-2.5 text-sm text-zinc-300 hover:bg-zinc-900"
              >
                Отмена
              </button>
              <button
                type="button"
                disabled={saving}
                onClick={() => void handleGenericConnect()}
                className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-violet-500 disabled:opacity-50"
              >
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Подключить
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  password,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  password?: boolean;
}) {
  return (
    <div>
      <label className="text-xs text-zinc-500">{label}</label>
      <input
        type={password ? "password" : "text"}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2.5 text-sm text-zinc-100"
      />
    </div>
  );
}


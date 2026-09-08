"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Plug } from "lucide-react";

import { AmoCrmModal } from "@/components/integrations/AmoCrmModal";
import { Bitrix24Modal } from "@/components/integrations/Bitrix24Modal";
import { CrmIntegrationCard } from "@/components/integrations/CrmIntegrationCard";
import { HubConnectionGrid } from "@/components/integrations/hub/HubConnectionGrid";
import { IntegrationConfigModal } from "@/components/integrations/IntegrationConfigModal";
import { HUB_CARD_PROVIDER_IDS } from "@/lib/integrations/hubCatalog";
import {
  connectAppIntegration,
  disconnectAppIntegration,
  fetchAppIntegrationsStatus,
  fetchGoogleCalendarAuthUrl,
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
  kommo: "Km",
  bitrix24: "B24",
  google_calendar: "G",
  google_sheets: "GS",
  kaspi_receipts: "K",
  kaspi_pay: "KP",
  custom_webhook: "API",
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
  const [form, setForm] = useState<AppIntegrationConnectPayload>({});
  const [requestOpen, setRequestOpen] = useState(false);

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

  const catalogDefinitions = useMemo(
    () => CRM_INTEGRATION_DEFINITIONS.filter((item) => !HUB_CARD_PROVIDER_IDS.has(item.id)),
    [],
  );

  const connectedCount = catalogDefinitions.filter((item) => statusMap[item.id]?.connected).length;

  const availableCount = catalogDefinitions.filter((item) => !statusMap[item.id]?.connected).length;

  const visibleDefinitions = useMemo(() => {
    if (filter === "connected") {
      return catalogDefinitions.filter((item) => statusMap[item.id]?.connected);
    }
    return catalogDefinitions.filter((item) => !statusMap[item.id]?.connected);
  }, [catalogDefinitions, filter, statusMap]);

  const handleCrmSave = async (
    platform: CRMPlatform | "kommo",
    payload: CRMIntegrationPatchRequest,
  ): Promise<void> => {
    setSaving(true);
    try {
      const isConnect =
        Boolean(payload.authorization_code) || Boolean(payload.webhook_url);
      const connectPlatform = platform === "kommo" ? "kommo" : platform;
      const response = isConnect
        ? await connectAppIntegration(botId, connectPlatform, payload as Record<string, unknown>)
        : await patchAppIntegration(botId, connectPlatform, payload as Record<string, unknown>);
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
      const connected = Boolean(statusMap[activeDefinition.id]?.connected);
      const response = connected
        ? await patchAppIntegration(
            botId,
            activeDefinition.id,
            form as Record<string, unknown>,
          )
        : await connectAppIntegration(
            botId,
            activeDefinition.id,
            form as Record<string, unknown>,
          );
      showToast(response.message, "success");
      await loadStatus();
      setActiveDefinition(null);
      setForm({});
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось сохранить интеграцию."), "error");
    } finally {
      setSaving(false);
    }
  };

  const handleGoogleOAuth = async (purpose: "google" | "google_sheets" = "google"): Promise<void> => {
    try {
      const { auth_url } = await fetchGoogleCalendarAuthUrl(botId, purpose);
      window.location.href = auth_url;
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось запустить OAuth Google."), "error");
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
  const isCrm =
    activePlatform === "amocrm" ||
    activePlatform === "kommo" ||
    activePlatform === "bitrix24";

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
                CRM, мессенджеры, оплата, календарь, Jivo и U-ON для агента{" "}
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
              Доступные {availableCount}
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

      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-zinc-300">Подключения Integration Hub</h3>
        <HubConnectionGrid botId={botId} />
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
              onConfigure={() => {
                setForm({});
                setActiveDefinition(definition);
              }}
              onRequestAccess={() => {
                setActiveDefinition(definition);
                setRequestOpen(true);
              }}
              logoOverride={LOGO[definition.id]}
            />
          ))}
        </div>
      )}

      <div className="flex flex-col gap-4 rounded-2xl border border-zinc-800/80 bg-[#0a0a0c]/90 px-5 py-5 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-zinc-400">
          Не нашли нужную интеграцию? Сообщите нам, и мы добавим её в план разработки.
        </p>
        <button
          type="button"
          onClick={() => setRequestOpen(true)}
          className="shrink-0 rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-2.5 text-sm font-medium text-zinc-200 transition hover:border-violet-500/40 hover:bg-zinc-800"
        >
          Запросить интеграцию
        </button>
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

      <AmoCrmModal
        open={activePlatform === "kommo"}
        botId={botId}
        platform="kommo"
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
        onSave={(payload) => handleCrmSave("kommo", payload)}
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
        <IntegrationConfigModal
          open
          definition={activeDefinition}
          status={activeStatus}
          saving={saving}
          form={form}
          onFormChange={setForm}
          onClose={() => setActiveDefinition(null)}
          onConnect={() => void handleGenericConnect()}
          onDisconnect={() => void handleDisconnect(activeDefinition.id)}
          onGoogleOAuth={() =>
            void handleGoogleOAuth(
              activePlatform === "google_sheets" ? "google_sheets" : "google",
            )
          }
        />
      ) : null}

      {requestOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            className="absolute inset-0 bg-black/75 backdrop-blur-sm"
            onClick={() => {
              setRequestOpen(false);
              setActiveDefinition(null);
            }}
            aria-label="Close"
          />
          <div className="moonai-modal relative z-10 w-full max-w-md p-6">
            <h2 className="text-lg font-semibold text-zinc-50">Запрос интеграции</h2>
            <p className="mt-2 text-sm text-zinc-400">
              Опишите нужный сервис — мы добавим его в roadmap. Для Jivo и U-ON также можно
              оставить контакт менеджера.
            </p>
            <p className="mt-4 rounded-xl border border-zinc-800 bg-zinc-900/50 px-4 py-3 text-sm text-zinc-300">
              {activeDefinition?.title ?? "Новая интеграция"} · агент {profile.name}
            </p>
            <button
              type="button"
              onClick={() => {
                showToast("Заявка отправлена. Мы свяжемся с вами.", "success");
                setRequestOpen(false);
                setActiveDefinition(null);
              }}
              className="mt-5 w-full rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-violet-500"
            >
              Отправить заявку
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}


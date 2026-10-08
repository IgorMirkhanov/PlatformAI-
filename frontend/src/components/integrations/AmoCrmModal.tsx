"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Loader2 } from "lucide-react";

import { IntegrationModalShell } from "@/components/integrations/IntegrationModalShell";
import { PipelineMappingStep } from "@/components/integrations/PipelineMappingStep";
import { fetchCRMPipelines } from "@/lib/api";
import { fetchHubAuthorizeUrl } from "@/lib/integrations/hubApi";
import { openHubOAuthPopup } from "@/lib/integrations/hubOAuthPopup";
import { useOrganizationStore } from "@/lib/stores/use-organization-store";
import { cn } from "@/lib/utils";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import type { CRMIntegrationDefinition } from "@/types/crm-integrations";
import type {
  CRMIntegrationPatchRequest,
  CRMPipelineMappingForm,
  CRMPipelineStage,
  CRMPlatformStatus,
} from "@/types/crm";

interface AmoCrmModalProps {
  open: boolean;
  botId: string;
  definition: CRMIntegrationDefinition | null;
  status: CRMPlatformStatus | null;
  saving: boolean;
  platform?: "amocrm" | "kommo";
  onClose: () => void;
  onSave: (payload: CRMIntegrationPatchRequest) => Promise<void>;
  onConnected?: () => void | Promise<void>;
}

export function AmoCrmModal({
  open,
  botId,
  definition,
  status,
  saving,
  platform = "amocrm",
  onClose,
  onSave,
  onConnected,
}: AmoCrmModalProps) {
  const currentOrgId = useOrganizationStore((state) => state.currentOrgId);
  const activeCompanyId = useBotStore((state) => state.activeCompanyId);
  const workspaceId = currentOrgId || activeCompanyId;
  const [step, setStep] = useState<1 | 2>(1);
  const [connecting, setConnecting] = useState(false);
  const [mapping, setMapping] = useState<CRMPipelineMappingForm>({
    pipeline_id: "",
    stage_id: "",
    default_tags: [],
  });
  const [stages, setStages] = useState<CRMPipelineStage[]>([]);
  const [pipelinesLoading, setPipelinesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setStep(1);
      setError(null);
      return;
    }
    setMapping({
      pipeline_id: status?.pipeline_id ?? "",
      stage_id: status?.stage_id ?? "",
      default_tags: status?.default_tags ?? [],
    });
    setStep(status?.connected ? 2 : 1);
  }, [open, status]);

  const loadPipelines = async (): Promise<void> => {
    setPipelinesLoading(true);
    try {
      const response = await fetchCRMPipelines(botId, platform === "kommo" ? "amocrm" : platform);
      setStages(response.pipelines);
    } catch {
      setStages([]);
      setError(`Не удалось загрузить воронки ${platform === "kommo" ? "Kommo" : "amoCRM"}.`);
    } finally {
      setPipelinesLoading(false);
    }
  };

  useEffect(() => {
    if (open && step === 2) {
      void loadPipelines();
    }
  }, [open, step, botId]);

  const handleConnect = async (): Promise<void> => {
    setError(null);
    if (!workspaceId) {
      setError("Не выбран workspace.");
      return;
    }
    setConnecting(true);
    try {
      const authorizeUrl = await fetchHubAuthorizeUrl({
        provider: platform === "kommo" ? "kommo" : "amocrm",
        workspaceId,
        agentId: botId,
      });
      const result = await openHubOAuthPopup(authorizeUrl);
      if (result.status !== "connected") {
        setError(result.message || "Не удалось подключить amoCRM.");
        return;
      }
      await onConnected?.();
      setStep(2);
    } catch (connectError) {
      setError(getApiErrorMessage(connectError, "Не удалось открыть amoCRM."));
    } finally {
      setConnecting(false);
    }
  };

  const handleSaveMapping = async (): Promise<void> => {
    setError(null);
    if (!mapping.pipeline_id || !mapping.stage_id) {
      setError("Выберите воронку и этап создания сделки.");
      return;
    }

    await onSave({
      pipeline_id: mapping.pipeline_id,
      stage_id: mapping.stage_id,
      default_tags: mapping.default_tags,
      sync_enabled: true,
    });
  };

  const brandName = platform === "kommo" ? "Kommo" : "amoCRM";

  return (
    <IntegrationModalShell
      open={open}
      definition={definition}
      status={status}
      step={step}
      saving={saving}
      onClose={onClose}
    >
      <AnimatePresence mode="wait">
        {step === 1 ? (
          <motion.div
            key="amo-step-1"
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -12 }}
            className="space-y-4"
          >
            <p className="text-sm leading-relaxed text-zinc-400">
              Откроется {brandName}. Выберите аккаунт, к которому подключить агента.
            </p>

            {error ? <p className="text-xs text-rose-400">{error}</p> : null}

            <button
              type="button"
              disabled={saving || connecting}
              onClick={() => void handleConnect()}
              className={cn(
                "inline-flex w-full items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white",
                "bg-[#0061FF] hover:bg-[#0056e6] disabled:opacity-50",
              )}
            >
              {connecting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Подключить
            </button>
          </motion.div>
        ) : (
          <motion.div
            key="amo-step-2"
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -12 }}
            className="space-y-4"
          >
            <PipelineMappingStep
              stages={stages}
              loading={pipelinesLoading}
              value={mapping}
              onChange={setMapping}
              disabled={saving}
            />
            {error ? <p className="text-xs text-rose-400">{error}</p> : null}
            <div className="flex gap-2">
              <button
                type="button"
                disabled={saving}
                onClick={() => setStep(1)}
                className="rounded-xl border border-zinc-800 px-4 py-2.5 text-sm text-zinc-300 hover:bg-zinc-900"
              >
                Назад
              </button>
              <button
                type="button"
                disabled={saving}
                onClick={() => void handleSaveMapping()}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-violet-500 disabled:opacity-50"
              >
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Сохранить интеграцию
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </IntegrationModalShell>
  );
}

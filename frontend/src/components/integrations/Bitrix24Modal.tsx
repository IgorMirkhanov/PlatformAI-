"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Loader2 } from "lucide-react";

import { IntegrationModalShell } from "@/components/integrations/IntegrationModalShell";
import { PipelineMappingStep } from "@/components/integrations/PipelineMappingStep";
import { fetchCRMPipelines } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { CRMIntegrationDefinition } from "@/types/crm-integrations";
import type {
  Bitrix24CredentialsForm,
  CRMIntegrationPatchRequest,
  CRMPipelineMappingForm,
  CRMPipelineStage,
  CRMPlatformStatus,
} from "@/types/crm";

interface Bitrix24ModalProps {
  open: boolean;
  botId: string;
  definition: CRMIntegrationDefinition | null;
  status: CRMPlatformStatus | null;
  saving: boolean;
  onClose: () => void;
  onSave: (payload: CRMIntegrationPatchRequest) => Promise<void>;
}

export function Bitrix24Modal({
  open,
  botId,
  definition,
  status,
  saving,
  onClose,
  onSave,
}: Bitrix24ModalProps) {
  const [step, setStep] = useState<1 | 2>(1);
  const [credentials, setCredentials] = useState<Bitrix24CredentialsForm>({ webhook_url: "" });
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
    setCredentials({ webhook_url: status?.detail ?? "" });
    setMapping({
      pipeline_id: status?.pipeline_id ?? "",
      stage_id: status?.stage_id ?? "",
      default_tags: status?.default_tags ?? [],
    });
    setStep(status?.connected ? 2 : 1);
  }, [open, status]);

  useEffect(() => {
    if (open && step === 2) {
      setPipelinesLoading(true);
      void fetchCRMPipelines(botId, "bitrix24")
        .then((response) => setStages(response.pipelines))
        .catch(() => {
          setStages([]);
          setError("Не удалось загрузить воронки Bitrix24.");
        })
        .finally(() => setPipelinesLoading(false));
    }
  }, [open, step, botId]);

  const handleVerify = async (): Promise<void> => {
    setError(null);
    if (!credentials.webhook_url.trim()) {
      setError("Укажите incoming webhook URL Bitrix24.");
      return;
    }

    try {
      await onSave({
        webhook_url: credentials.webhook_url.trim(),
        sync_enabled: true,
      });
      setStep(2);
    } catch {
      // toast handled upstream
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
            key="bitrix-step-1"
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -12 }}
            className="space-y-4"
          >
            <div>
              <label className="text-xs text-zinc-500">Incoming Webhook REST URL</label>
              <input
                value={credentials.webhook_url}
                onChange={(event) =>
                  setCredentials({ webhook_url: event.target.value })
                }
                placeholder="https://your-domain.bitrix24.ru/rest/1/xxxxxxxx/"
                className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100"
              />
              <p className="mt-1.5 text-[11px] text-zinc-600">
                Webhook должен иметь права CRM, контактов и сделок для асинхронной очереди Celery.
              </p>
            </div>

            {error ? <p className="text-xs text-rose-400">{error}</p> : null}

            <button
              type="button"
              disabled={saving}
              onClick={() => void handleVerify()}
              className={cn(
                "inline-flex w-full items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white",
                "bg-[#2FC6F6] hover:bg-[#1fb8ea] disabled:opacity-50",
              )}
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Проверить webhook и продолжить
            </button>
          </motion.div>
        ) : (
          <motion.div
            key="bitrix-step-2"
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

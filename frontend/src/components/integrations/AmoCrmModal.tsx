"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ExternalLink, Loader2 } from "lucide-react";

import { IntegrationModalShell } from "@/components/integrations/IntegrationModalShell";
import { PipelineMappingStep } from "@/components/integrations/PipelineMappingStep";
import { fetchCRMPipelines } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { CRMIntegrationDefinition } from "@/types/crm-integrations";
import type {
  AmoCRMCredentialsForm,
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
}

const DEFAULT_CREDENTIALS: AmoCRMCredentialsForm = {
  base_domain: "company.amocrm.ru",
  client_id: "",
  client_secret: "",
  authorization_code: "",
  redirect_uri: "https://localhost/oauth",
};

export function AmoCrmModal({
  open,
  botId,
  definition,
  status,
  saving,
  platform = "amocrm",
  onClose,
  onSave,
}: AmoCrmModalProps) {
  const defaultDomain = platform === "kommo" ? "company.kommo.com" : "company.amocrm.ru";
  const [step, setStep] = useState<1 | 2>(1);
  const [credentials, setCredentials] = useState<AmoCRMCredentialsForm>({
    ...DEFAULT_CREDENTIALS,
    base_domain: defaultDomain,
  });
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
    setCredentials({ ...DEFAULT_CREDENTIALS, base_domain: defaultDomain });
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

  const handleVerify = async (): Promise<void> => {
    setError(null);
    if (
      !credentials.base_domain.trim() ||
      !credentials.client_id.trim() ||
      !credentials.client_secret.trim() ||
      !credentials.authorization_code.trim()
    ) {
      setError("Заполните все поля OAuth amoCRM.");
      return;
    }

    try {
      await onSave({
        base_domain: credentials.base_domain.trim(),
        client_id: credentials.client_id.trim(),
        client_secret: credentials.client_secret.trim(),
        authorization_code: credentials.authorization_code.trim(),
        redirect_uri: credentials.redirect_uri.trim(),
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

  const oauthUrl = `https://www.amocrm.ru/oauth?client_id=${encodeURIComponent(
    credentials.client_id || "CLIENT_ID",
  )}&redirect_uri=${encodeURIComponent(credentials.redirect_uri)}&response_type=code`;

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
            <div className="grid gap-3 md:grid-cols-2">
              <div className="md:col-span-2">
                <label className="text-xs text-zinc-500">Subdomain</label>
                <input
                  value={credentials.base_domain}
                  onChange={(event) =>
                    setCredentials((current) => ({ ...current, base_domain: event.target.value }))
                  }
                  placeholder="company.amocrm.ru"
                  className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100"
                />
              </div>
              <div>
                <label className="text-xs text-zinc-500">Client ID</label>
                <input
                  value={credentials.client_id}
                  onChange={(event) =>
                    setCredentials((current) => ({ ...current, client_id: event.target.value }))
                  }
                  className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100"
                />
              </div>
              <div>
                <label className="text-xs text-zinc-500">Client Secret</label>
                <input
                  type="password"
                  value={credentials.client_secret}
                  onChange={(event) =>
                    setCredentials((current) => ({ ...current, client_secret: event.target.value }))
                  }
                  className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100"
                />
              </div>
              <div className="md:col-span-2">
                <label className="text-xs text-zinc-500">Authorization Code</label>
                <input
                  value={credentials.authorization_code}
                  onChange={(event) =>
                    setCredentials((current) => ({
                      ...current,
                      authorization_code: event.target.value,
                    }))
                  }
                  className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100"
                />
              </div>
            </div>

            <a
              href={oauthUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-[#0061FF] hover:text-[#4d94ff]"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Открыть OAuth amoCRM
            </a>

            {error ? <p className="text-xs text-rose-400">{error}</p> : null}

            <button
              type="button"
              disabled={saving}
              onClick={() => void handleVerify()}
              className={cn(
                "inline-flex w-full items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white",
                "bg-[#0061FF] hover:bg-[#0056e6] disabled:opacity-50",
              )}
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Проверить и продолжить
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

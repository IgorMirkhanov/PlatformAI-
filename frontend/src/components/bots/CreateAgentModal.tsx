"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { Bot, Loader2, Sparkles, X } from "lucide-react";

import { getAgentTabPath } from "@/lib/agent-routes";
import {
  DEFAULT_NEW_AGENT_NAME,
  provisionNewAgent,
} from "@/lib/provision-agent";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import {
  AGENT_USE_CASE_TEMPLATES,
  type AgentUseCaseTemplateId,
} from "@/types/agent-templates";

interface CreateAgentModalProps {
  open: boolean;
  onClose: () => void;
  onCreated?: () => void;
}

export function CreateAgentModal({ open, onClose, onCreated }: CreateAgentModalProps) {
  const router = useRouter();
  const { showToast } = useToast();
  const setActiveBotId = useBotStore((state) => state.setActiveBotId);
  const loadAgentProfile = useBotStore((state) => state.loadAgentProfile);

  const [name, setName] = useState(DEFAULT_NEW_AGENT_NAME);
  const [useCase, setUseCase] = useState<AgentUseCaseTemplateId>("support_rag");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }

    setName(DEFAULT_NEW_AGENT_NAME);
    setUseCase("support_rag");
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape" && !creating) {
        onClose();
      }
    };

    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = "";
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [creating, onClose, open]);

  const handleSubmit = async (): Promise<void> => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      showToast("Укажите название агента.", "error");
      return;
    }

    setCreating(true);
    try {
      const { botId } = await provisionNewAgent(trimmedName, useCase);
      setActiveBotId(botId);
      await loadAgentProfile(botId);
      onCreated?.();
      showToast("Агент создан. Открываем настройки…", "success");
      onClose();
      router.push(getAgentTabPath(botId, "settings"));
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось создать агента."), "error");
    } finally {
      setCreating(false);
    }
  };

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <button
            type="button"
            aria-label="Закрыть"
            className="absolute inset-0"
            onClick={() => {
              if (!creating) {
                onClose();
              }
            }}
          />

          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-agent-title"
            className={cn(
              "relative z-10 w-full max-w-md max-h-[90vh] overflow-y-auto rounded-2xl",
              "border border-zinc-700/60 bg-zinc-950/80 p-6 shadow-glow-purple backdrop-blur-xl",
            )}
            initial={{ opacity: 0, y: 24, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 420, damping: 32 }}
          >
            <div className="mb-6 flex items-start justify-between gap-4">
              <div className="flex items-start gap-4">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-violet-500/15 ring-1 ring-violet-500/35">
                  <Bot className="h-6 w-6 text-violet-400" />
                </div>
                <div>
                  <h2 id="create-agent-title" className="text-xl font-semibold text-zinc-50">
                    Создать агента
                  </h2>
                  <p className="mt-1 text-sm text-zinc-500">
                    Укажите название и сферу — мы подготовим стартовый сценарий для тестового чата.
                  </p>
                </div>
              </div>
              <button
                type="button"
                disabled={creating}
                onClick={onClose}
                className="rounded-lg border border-zinc-800 p-2 text-zinc-400 transition hover:bg-zinc-900 hover:text-zinc-200 disabled:opacity-50"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-5">
              <div>
                <label htmlFor="agent-modal-name" className="text-sm font-medium text-zinc-300">
                  Название агента
                </label>
                <input
                  id="agent-modal-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Новый ИИ-Агент"
                  disabled={creating}
                  className="mt-2 w-full rounded-xl border border-zinc-800 bg-zinc-900/90 px-4 py-3 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500/30 disabled:opacity-60"
                />
              </div>

              <div>
                <label htmlFor="agent-modal-use-case" className="text-sm font-medium text-zinc-300">
                  Сфера деятельности
                </label>
                <select
                  id="agent-modal-use-case"
                  value={useCase}
                  onChange={(event) => setUseCase(event.target.value as AgentUseCaseTemplateId)}
                  disabled={creating}
                  className="mt-2 w-full rounded-xl border border-zinc-800 bg-zinc-900/90 px-4 py-3 text-sm text-zinc-100 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500/30 disabled:opacity-60"
                >
                  {AGENT_USE_CASE_TEMPLATES.map((template) => (
                    <option key={template.id} value={template.id}>
                      {template.label}
                    </option>
                  ))}
                </select>
                <p className="mt-2 text-xs text-zinc-500">
                  {AGENT_USE_CASE_TEMPLATES.find((item) => item.id === useCase)?.description}
                </p>
              </div>
            </div>

            <div className="mt-8 flex flex-wrap items-center justify-end gap-3">
              <button
                type="button"
                disabled={creating}
                onClick={onClose}
                className="rounded-xl border border-zinc-800 px-4 py-2.5 text-sm font-medium text-zinc-300 transition hover:bg-zinc-900 disabled:opacity-50"
              >
                Отмена
              </button>
              <button
                type="button"
                disabled={creating}
                onClick={() => void handleSubmit()}
                className={cn(
                  "inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:from-violet-500 hover:to-indigo-500 disabled:opacity-50",
                )}
              >
                {creating ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                {creating ? "Создание…" : "Создать"}
              </button>
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

"use client";

import { useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";
import type { CRMIntegrationDefinition } from "@/types/crm-integrations";
import type { CRMPlatformStatus } from "@/types/crm";

interface IntegrationModalShellProps {
  open: boolean;
  definition: CRMIntegrationDefinition | null;
  status: CRMPlatformStatus | null;
  step: number;
  saving?: boolean;
  onClose: () => void;
  children: React.ReactNode;
}

export function IntegrationModalShell({
  open,
  definition,
  status,
  step,
  saving = false,
  onClose,
  children,
}: IntegrationModalShellProps) {
  useEffect(() => {
    if (!open) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape" && !saving) {
        onClose();
      }
    };
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = "";
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose, open, saving]);

  return (
    <AnimatePresence>
      {open && definition ? (
        <motion.div
          className="fixed inset-0 z-[100] flex items-center justify-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <button
            type="button"
            aria-label="Закрыть"
            className="absolute inset-0 bg-black/80 backdrop-blur-md"
            onClick={() => {
              if (!saving) {
                onClose();
              }
            }}
          />

          <motion.div
            role="dialog"
            aria-modal="true"
            className="relative z-10 flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-zinc-800/80 bg-zinc-950/90 shadow-glow-purple backdrop-blur-xl"
            initial={{ opacity: 0, y: 24, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 420, damping: 32 }}
          >
            <div className="border-b border-zinc-800/80 px-5 py-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-lg font-semibold text-zinc-50">{definition.title}</h3>
                  <p className="mt-1 text-xs text-zinc-500">
                    Шаг {step} из 2 ·{" "}
                    {step === 1 ? "Авторизация и проверка доступа" : "Workflow automation mapping"}
                  </p>
                </div>
                <button
                  type="button"
                  disabled={saving}
                  onClick={onClose}
                  className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200 disabled:opacity-50"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <div className="mt-4 flex gap-2">
                {[1, 2].map((value) => (
                  <div
                    key={value}
                    className={cn(
                      "h-1 flex-1 rounded-full transition",
                      step >= value ? "bg-violet-500" : "bg-zinc-800",
                    )}
                  />
                ))}
              </div>

              {status?.detail ? (
                <p className="mt-3 truncate text-[11px] text-zinc-500">{status.detail}</p>
              ) : null}
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-5">{children}</div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

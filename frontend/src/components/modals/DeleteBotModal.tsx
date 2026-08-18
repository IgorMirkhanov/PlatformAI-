"use client";

import { useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, X } from "lucide-react";

import { Button } from "@/components/ui/button";

interface DeleteBotModalProps {
  open: boolean;
  botName: string;
  isLoading?: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export function DeleteBotModal({
  open,
  botName,
  isLoading = false,
  onClose,
  onConfirm,
}: DeleteBotModalProps) {
  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape" && !isLoading) {
        onClose();
      }
    };

    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = "";
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isLoading, onClose, open]);

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <button
            type="button"
            aria-label="Закрыть"
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            disabled={isLoading}
            onClick={() => {
              if (!isLoading) onClose();
            }}
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-bot-title"
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            className="relative z-10 w-full max-w-md rounded-2xl border border-red-500/20 bg-[#121214] p-5 shadow-2xl"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-start gap-3">
                <div className="rounded-xl bg-red-500/10 p-2 ring-1 ring-red-500/30">
                  <AlertTriangle className="h-5 w-5 text-red-400" />
                </div>
                <div>
                  <h2 id="delete-bot-title" className="text-lg font-semibold text-zinc-50">
                    Удалить бота?
                  </h2>
                  <p className="mt-1 text-sm text-zinc-400">
                    Вы собираетесь безвозвратно удалить{" "}
                    <span className="font-medium text-zinc-200">{botName}</span>.
                  </p>
                </div>
              </div>
              <button
                type="button"
                disabled={isLoading}
                onClick={onClose}
                className="rounded-lg p-1 text-zinc-500 transition hover:bg-zinc-800 hover:text-zinc-200 disabled:opacity-40"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-4 rounded-xl border border-red-500/15 bg-red-500/5 px-3 py-3 text-sm text-zinc-300">
              <p className="font-medium text-red-200">Это действие нельзя отменить.</p>
              <ul className="mt-2 list-disc space-y-1 pl-4 text-zinc-400">
                <li>WhatsApp-сессии и файлы авторизации будут остановлены и стёрты</li>
                <li>Сценарии (flows) и граф диалога будут удалены</li>
                <li>Диагностические логи и связанные записи использования LLM исчезнут</li>
                <li>Документы базы знаний и векторные эмбеддинги будут очищены</li>
              </ul>
            </div>

            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={isLoading}
                onClick={onClose}
              >
                Отмена
              </Button>
              <Button
                type="button"
                variant="destructive"
                isLoading={isLoading}
                onClick={onConfirm}
              >
                Да, удалить бота
              </Button>
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

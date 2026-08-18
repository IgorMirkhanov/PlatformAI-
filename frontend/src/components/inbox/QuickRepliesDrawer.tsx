"use client";

import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";

import { DEFAULT_QUICK_REPLIES } from "@/types/inbox";

interface QuickRepliesDrawerProps {
  open: boolean;
  onClose: () => void;
  onSelect: (text: string) => void;
}

export function QuickRepliesDrawer({
  open,
  onClose,
  onSelect,
}: QuickRepliesDrawerProps) {
  return (
    <AnimatePresence>
      {open ? (
        <>
          <motion.button
            type="button"
            aria-label="Закрыть быстрые ответы"
            className="fixed inset-0 z-40 bg-black/50 backdrop-blur-[1px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.div
            className="fixed bottom-24 left-1/2 z-50 w-[min(92vw,420px)] -translate-x-1/2 rounded-2xl border border-zinc-800 bg-zinc-950/95 p-4 shadow-glow-purple"
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.98 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
          >
            <div className="mb-3 flex items-center justify-between">
              <p className="text-sm font-semibold text-zinc-100">Быстрые ответы</p>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg p-1 text-zinc-500 hover:bg-zinc-900 hover:text-zinc-300"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-2">
              {DEFAULT_QUICK_REPLIES.map((template) => (
                <button
                  key={template.id}
                  type="button"
                  onClick={() => onSelect(template.text)}
                  className="w-full rounded-xl border border-zinc-800 bg-zinc-900/70 px-3 py-2.5 text-left transition hover:border-violet-500/40 hover:bg-zinc-900"
                >
                  <p className="text-xs font-medium text-violet-300">{template.label}</p>
                  <p className="mt-1 text-sm text-zinc-300">{template.text}</p>
                </button>
              ))}
            </div>
          </motion.div>
        </>
      ) : null}
    </AnimatePresence>
  );
}

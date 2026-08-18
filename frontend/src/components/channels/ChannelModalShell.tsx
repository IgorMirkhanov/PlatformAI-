"use client";

import { useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";

import { ChannelBrandIcon } from "@/components/bots/channels/ChannelBrandIcon";
import { ChannelStatusBadge } from "@/components/bots/channels/ChannelStatusBadge";
import type { ChannelDefinition, ChannelStatus } from "@/types/channels";

interface ChannelModalShellProps {
  open: boolean;
  definition: ChannelDefinition | null;
  status: ChannelStatus | null;
  saving?: boolean;
  onClose: () => void;
  children: React.ReactNode;
}

export function ChannelModalShell({
  open,
  definition,
  status,
  saving = false,
  onClose,
  children,
}: ChannelModalShellProps) {
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
      {open && definition && status ? (
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
            <div className="flex items-start justify-between gap-4 border-b border-zinc-800/80 px-5 py-5">
              <div className="flex items-start gap-3">
                <div
                  className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-black/40 ring-1 ring-white/5"
                  style={{ boxShadow: `0 0 28px ${definition.brandColor}44` }}
                >
                  <ChannelBrandIcon channelId={definition.id} className="h-7 w-7" />
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-lg font-semibold text-zinc-50">{definition.title}</h3>
                    <ChannelStatusBadge connected={status.connected} active={status.active} />
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-zinc-500">{definition.description}</p>
                </div>
              </div>
              <button
                type="button"
                disabled={saving}
                onClick={onClose}
                className="rounded-lg p-1.5 text-zinc-500 transition hover:bg-zinc-800 hover:text-zinc-200 disabled:opacity-50"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-5">{children}</div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

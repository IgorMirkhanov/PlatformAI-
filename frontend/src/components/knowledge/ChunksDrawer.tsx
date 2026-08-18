"use client";

import { useCallback } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Check, ClipboardCopy, Loader2, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import {
  formatSimilarityScore,
  similarityBadgeClassName,
  type KnowledgeChunk,
} from "@/types/knowledge";

interface ChunksDrawerProps {
  open: boolean;
  loading: boolean;
  fileName: string | null;
  chunks: KnowledgeChunk[];
  onClose: () => void;
}

function ChunkCopyButton({ text }: { text: string }) {
  const { showToast } = useToast();

  const handleCopy = useCallback(async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(text);
      showToast("Текст чанка скопирован.", "knowledge");
    } catch {
      showToast("Не удалось скопировать текст.", "error");
    }
  }, [showToast, text]);

  return (
    <button
      type="button"
      onClick={() => void handleCopy()}
      title="Скопировать текст чанка"
      aria-label="Скопировать текст чанка"
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-lg",
        "border border-zinc-800 bg-zinc-950/80 text-zinc-400 transition",
        "hover:border-violet-500/30 hover:bg-violet-500/10 hover:text-violet-200",
      )}
    >
      <ClipboardCopy className="h-3.5 w-3.5" />
    </button>
  );
}

export function ChunksDrawer({
  open,
  loading,
  fileName,
  chunks,
  onClose,
}: ChunksDrawerProps) {
  return (
    <AnimatePresence>
      {open ? (
        <>
          <motion.button
            type="button"
            aria-label="Закрыть просмотр чанков"
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            className={cn(
              "fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col",
              "border-l border-zinc-800 bg-zinc-950/80 shadow-glow-purple backdrop-blur-xl",
            )}
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 380, damping: 34 }}
          >
            <div className="flex items-center justify-between border-b border-zinc-800/90 px-5 py-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">
                  Semantic Chunks
                </p>
                <h3 className="mt-1 text-lg font-semibold text-zinc-100">
                  {fileName ?? "Документ"}
                </h3>
                <p className="mt-1 text-xs text-zinc-500">
                  Посмотреть чанки · {chunks.length} фрагмент(ов)
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg p-2 text-zinc-500 transition hover:bg-zinc-900 hover:text-zinc-300"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-5">
              {loading ? (
                <div className="flex h-full items-center justify-center">
                  <Loader2 className="h-6 w-6 animate-spin text-violet-300" />
                </div>
              ) : chunks.length === 0 ? (
                <p className="text-sm text-zinc-500">Чанки для этого документа не найдены.</p>
              ) : (
                <ul className="space-y-3">
                  {chunks.map((chunk) => {
                    const score = formatSimilarityScore(chunk.similarity_weight);

                    return (
                      <li
                        key={chunk.chunk_index}
                        className="rounded-2xl border border-zinc-800/90 bg-zinc-900/50 p-4 backdrop-blur-sm"
                      >
                        <div className="mb-3 flex items-start justify-between gap-3">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold uppercase tracking-wider text-violet-300">
                              Chunk #{chunk.chunk_index + 1}
                            </span>
                            {score.tier === "high" ? (
                              <Check className="h-3.5 w-3.5 text-emerald-400" />
                            ) : null}
                          </div>
                          <div className="flex items-center gap-2">
                            <span
                              className={cn(
                                "rounded-full px-2.5 py-1 text-[11px] font-semibold tabular-nums",
                                similarityBadgeClassName(score.tier),
                              )}
                            >
                              {score.label}
                            </span>
                            <ChunkCopyButton text={chunk.text} />
                          </div>
                        </div>
                        <p className="whitespace-pre-wrap font-mono text-[12px] leading-relaxed text-zinc-300">
                          {chunk.text}
                        </p>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </motion.aside>
        </>
      ) : null}
    </AnimatePresence>
  );
}

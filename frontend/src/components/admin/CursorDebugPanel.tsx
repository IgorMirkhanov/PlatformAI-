"use client";

import { useState } from "react";
import { ClipboardCopy, Loader2 } from "lucide-react";

import { exportCursorDiagnostics } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";

interface CursorDebugPanelProps {
  botId?: string | null;
  compact?: boolean;
  className?: string;
}

async function copyTextToClipboard(text: string): Promise<void> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

export function CursorDebugPanel({
  botId = null,
  compact = false,
  className,
}: CursorDebugPanelProps) {
  const { showToast } = useToast();
  const [loading, setLoading] = useState(false);

  const handleCopy = async (): Promise<void> => {
    setLoading(true);
    try {
      const dump = await exportCursorDiagnostics(botId ?? undefined);
      await copyTextToClipboard(dump.markdown);
      showToast(
        "Дамп диагностики скопирован! Вставьте его в Cursor Composer для мгновенного исправления ошибок.",
        "settings",
      );
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Не удалось скопировать диагностический дамп.";
      showToast(message, "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className={cn(
        compact
          ? "border-t border-zinc-800/80 px-3 py-2"
          : "rounded-2xl border border-zinc-800/80 bg-zinc-950/50 p-4",
        className,
      )}
    >
      {!compact ? (
        <div className="mb-3">
          <p className="text-sm font-semibold text-zinc-100">Cursor Diagnostic Exporter</p>
          <p className="mt-1 text-xs text-zinc-500">
            Снимок Error Vault + health/cache метаданных для Composer.
          </p>
        </div>
      ) : null}

      <button
        type="button"
        onClick={() => void handleCopy()}
        disabled={loading}
        className={cn(
          "inline-flex w-full items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-sm font-semibold transition disabled:opacity-50",
          compact
            ? "border border-amber-500/25 bg-gradient-to-r from-amber-950/40 to-violet-950/40 text-amber-100 hover:border-amber-500/40"
            : "bg-gradient-to-r from-amber-600/90 to-violet-600/90 text-white shadow-glow-purple hover:from-amber-500 hover:to-violet-500",
        )}
      >
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <ClipboardCopy className="h-4 w-4" />
        )}
        📋 Скопировать лог для Cursor
      </button>
    </div>
  );
}

"use client";

import { CheckCircle2, Info, X, XCircle } from "lucide-react";

import { cn } from "@/lib/utils";
import { useToastStore, type ToastVariant } from "@/hooks/useToast";

const VARIANT_STYLES: Record<ToastVariant, string> = {
  success:
    "border-violet-500/30 bg-gradient-to-r from-violet-950/55 to-fuchsia-950/40 text-violet-50 shadow-glow-purple backdrop-blur-xl",
  prompting:
    "border-amber-500/30 bg-gradient-to-r from-amber-950/50 to-violet-950/50 text-amber-100 shadow-glow-purple backdrop-blur-xl",
  settings:
    "border-amber-500/30 bg-gradient-to-r from-amber-950/50 to-violet-950/50 text-amber-100 shadow-glow-purple backdrop-blur-xl",
  knowledge:
    "border-violet-500/30 bg-gradient-to-r from-violet-950/55 to-zinc-950/55 text-violet-100 shadow-glow-purple backdrop-blur-xl",
  error: "border-red-500/30 bg-red-950/45 text-red-200 backdrop-blur-xl",
  info: "border-sky-500/30 bg-sky-950/45 text-sky-200 backdrop-blur-xl",
};

function ToastIcon({ variant }: { variant: ToastVariant }) {
  if (
    variant === "success" ||
    variant === "prompting" ||
    variant === "knowledge" ||
    variant === "settings"
  ) {
    return <CheckCircle2 className="h-4 w-4 shrink-0" />;
  }
  if (variant === "error") return <XCircle className="h-4 w-4 shrink-0" />;
  return <Info className="h-4 w-4 shrink-0" />;
}

export function ToastContainer() {
  const toasts = useToastStore((state) => state.toasts);
  const dismissToast = useToastStore((state) => state.dismissToast);

  if (toasts.length === 0) {
    return null;
  }

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={cn(
            "pointer-events-auto flex items-start gap-2 rounded-xl border px-4 py-3 text-sm shadow-node",
            VARIANT_STYLES[toast.variant],
          )}
        >
          <ToastIcon variant={toast.variant} />
          <p className="flex-1 leading-relaxed">{toast.message}</p>
          <button
            type="button"
            onClick={() => dismissToast(toast.id)}
            className="rounded p-0.5 opacity-70 hover:opacity-100"
            aria-label="Dismiss"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}

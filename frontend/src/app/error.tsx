"use client";

import { useEffect } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("AppErrorBoundary", error);
  }, [error]);

  return (
    <div className="flex min-h-[70vh] items-center justify-center px-4 py-16">
      <div className="w-full max-w-md rounded-2xl border border-zinc-800 bg-zinc-950/90 p-6 shadow-2xl shadow-black/40">
        <div className="flex items-start gap-3">
          <div className="rounded-xl bg-amber-500/10 p-2 ring-1 ring-amber-500/30">
            <AlertTriangle className="h-5 w-5 text-amber-300" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-zinc-50">Что-то пошло не так</h1>
            <p className="mt-1 text-sm text-zinc-400">
              Произошла непредвиденная ошибка на странице. Попробуйте перезагрузить — если
              проблема повторится, обратитесь в поддержку.
            </p>
            {error.digest ? (
              <p className="mt-2 font-mono text-[11px] text-zinc-600">код: {error.digest}</p>
            ) : null}
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            reset();
            if (typeof window !== "undefined") {
              window.location.reload();
            }
          }}
          className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-zinc-100 px-4 py-2.5 text-sm font-semibold text-zinc-950 transition hover:bg-white"
        >
          <RefreshCw className="h-4 w-4" />
          Перезагрузить страницу
        </button>
      </div>
    </div>
  );
}

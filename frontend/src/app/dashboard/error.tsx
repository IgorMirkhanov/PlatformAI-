"use client";

import { useEffect } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("DashboardErrorBoundary", error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-4 py-12">
      <div className="w-full max-w-md rounded-2xl border border-zinc-800 bg-[#0f0f11] p-6 shadow-xl">
        <div className="flex items-start gap-3">
          <div className="rounded-xl bg-rose-500/10 p-2 ring-1 ring-rose-500/25">
            <AlertTriangle className="h-5 w-5 text-rose-300" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-zinc-50">Что-то пошло не так</h1>
            <p className="mt-1 text-sm text-zinc-400">
              Не удалось отобразить раздел дашборда. Перезагрузите страницу или вернитесь позже.
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
          className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-2.5 text-sm font-semibold text-zinc-100 transition hover:border-zinc-500"
        >
          <RefreshCw className="h-4 w-4" />
          Перезагрузить страницу
        </button>
      </div>
    </div>
  );
}

"use client";

import Link from "next/link";
import { AlertOctagon, ShieldAlert } from "lucide-react";

import type { DiagnosticLogRead } from "@/types/dashboard";
import { cn } from "@/lib/utils";

interface ErrorVaultWidgetProps {
  logs: DiagnosticLogRead[];
  loading?: boolean;
}

const ERROR_LABELS: Record<DiagnosticLogRead["error_type"], string> = {
  LLM_TIMEOUT: "LLM Timeout",
  RAG_EMPTY: "RAG Empty",
  CRM_DISCONNECT: "CRM Disconnect",
  INSUFFICIENT_FUNDS: "Insufficient Funds",
  GOOGLE_SYNC_FAILED: "Google Sync Failed",
  MESSENGER_API_ERROR: "Messenger API Error",
};

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function ErrorVaultWidget({ logs, loading = false }: ErrorVaultWidgetProps) {
  const hasFundsError = logs.some((log) => log.error_type === "INSUFFICIENT_FUNDS");

  return (
    <section className="luxury-card flex h-full flex-col">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-rose-500/10 ring-1 ring-rose-500/20">
            <ShieldAlert className="h-5 w-5 text-rose-400" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-zinc-100">AI Error Vault</h3>
            <p className="text-xs text-zinc-500">
              Журнал критических событий BotDiagnosticLogs
            </p>
          </div>
        </div>
        <span className="rounded-full border border-zinc-800 bg-[#121214] px-2.5 py-1 text-[10px] uppercase tracking-wider text-zinc-500">
          {loading ? "…" : `${logs.length} events`}
        </span>
      </div>

      {hasFundsError ? (
        <Link
          href="/billing"
          className="mb-4 inline-flex w-fit items-center rounded-full bg-amber-500/15 px-3 py-1.5 text-xs font-semibold text-amber-300 ring-1 ring-amber-500/30 transition hover:bg-amber-500/25"
        >
          Пополните баланс
        </Link>
      ) : null}

      <div className="min-h-0 flex-1">
        {loading ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, index) => (
              <div
                key={index}
                className="h-16 animate-pulse rounded-xl border border-zinc-800/80 bg-zinc-900/40"
              />
            ))}
          </div>
        ) : logs.length === 0 ? (
          <div className="flex h-full min-h-[18rem] items-center gap-3 rounded-xl border border-emerald-500/15 bg-emerald-500/5 px-4 py-5">
            <AlertOctagon className="h-4 w-4 shrink-0 text-emerald-400" />
            <p className="text-sm text-emerald-100/90">
              Критических ошибок за последний период не обнаружено.
            </p>
          </div>
        ) : (
          <ul className="max-h-[22rem] space-y-3 overflow-y-auto pr-1">
            {logs.map((log) => (
              <li
                key={log.id}
                className="rounded-xl border border-zinc-800/80 bg-[#121214] px-4 py-3 transition hover:border-zinc-700"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-medium text-zinc-200">{log.bot_name || "Bot"}</span>
                    <span className="rounded-md bg-zinc-800/80 px-2 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400">
                      {ERROR_LABELS[log.error_type]}
                    </span>
                    {log.error_type === "INSUFFICIENT_FUNDS" ? (
                      <Link
                        href="/billing"
                        className="rounded-full bg-amber-500/15 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300 ring-1 ring-amber-500/30 transition hover:bg-amber-500/25"
                      >
                        Пополните баланс
                      </Link>
                    ) : null}
                  </div>
                  <time className="text-[11px] text-zinc-500">{formatTimestamp(log.created_at)}</time>
                </div>
                <p className={cn("mt-2 text-sm text-zinc-400", log.node_id && "mb-1")}>
                  {log.error_message}
                </p>
                {log.node_id ? (
                  <p className="text-[11px] text-zinc-600">
                    Node: <span className="font-mono text-zinc-500">{log.node_id}</span>
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

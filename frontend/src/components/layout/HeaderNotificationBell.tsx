"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { Bell, ExternalLink, Loader2, Trash2 } from "lucide-react";

import { fetchBillingNotifications, fetchDiagnosticLogs } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CursorDebugPanel } from "@/components/admin/CursorDebugPanel";
import { useBotStore } from "@/store/useBotStore";
import type { SystemNotificationRead } from "@/types/billing";
import type { DiagnosticErrorType, DiagnosticLogRead } from "@/types/dashboard";

const CRITICAL_ALERT_TYPES: DiagnosticErrorType[] = ["INSUFFICIENT_FUNDS", "CRM_DISCONNECT"];
const DISMISSED_STORAGE_KEY = "mpai-header-diagnostics-dismissed";
const SEEN_CRITICAL_STORAGE_KEY = "mpai-header-diagnostics-seen-critical";
const DISMISSED_NOTIFICATIONS_KEY = "mpai-header-system-notifications-dismissed";
const SEEN_NOTIFICATIONS_KEY = "mpai-header-system-notifications-seen";

const ERROR_LABELS: Record<DiagnosticErrorType, string> = {
  LLM_TIMEOUT: "LLM Timeout",
  RAG_EMPTY: "RAG Empty",
  CRM_DISCONNECT: "CRM Disconnect",
  INSUFFICIENT_FUNDS: "Insufficient Funds",
  GOOGLE_SYNC_FAILED: "Google Sync Failed",
  MESSENGER_API_ERROR: "Messenger API Error",
};

type UnifiedAlert =
  | {
      kind: "diagnostic";
      id: string;
      title: string;
      message: string;
      created_at: string;
      critical: boolean;
      href: string;
      badge: string;
    }
  | {
      kind: "notification";
      id: string;
      title: string;
      message: string;
      created_at: string;
      critical: boolean;
      href: string;
      badge: string;
    };

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function getDiagnosticLink(errorType: DiagnosticErrorType): string {
  return errorType === "INSUFFICIENT_FUNDS" ? "/billing" : "/dashboard";
}

function readIdSet(storageKey: string): Set<string> {
  if (typeof window === "undefined") {
    return new Set();
  }
  try {
    const raw = window.sessionStorage.getItem(storageKey);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

function writeIdSet(storageKey: string, ids: Set<string>): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.setItem(storageKey, JSON.stringify(Array.from(ids)));
}

function mapDiagnostics(logs: DiagnosticLogRead[] | null | undefined): UnifiedAlert[] {
  return (logs ?? []).map((log) => ({
    kind: "diagnostic" as const,
    id: `diag:${log.id}`,
    title: log.bot_name || "Bot",
    message: log.error_message,
    created_at: log.created_at,
    critical: CRITICAL_ALERT_TYPES.includes(log.error_type),
    href: getDiagnosticLink(log.error_type),
    badge: ERROR_LABELS[log.error_type],
  }));
}

function mapNotifications(items: SystemNotificationRead[] | null | undefined): UnifiedAlert[] {
  return (items ?? []).map((item) => ({
    kind: "notification" as const,
    id: `notif:${item.id}`,
    title: item.title,
    message: item.message,
    created_at: item.created_at,
    critical: item.severity === "CRITICAL",
    href: "/billing",
    badge: item.category === "BILLING_DEPOSIT" ? "Платеж" : "Система",
  }));
}

/** Header alert bell — illuminates for diagnostics and pending deposit reviews. */
export function HeaderAlertNotificationBell() {
  const containerRef = useRef<HTMLDivElement>(null);
  const activeBotId = useBotStore((state) => state.activeBotId);

  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [logs, setLogs] = useState<DiagnosticLogRead[]>([]);
  const [notifications, setNotifications] = useState<SystemNotificationRead[]>([]);
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(() => {
    const merged = readIdSet(DISMISSED_STORAGE_KEY);
    readIdSet(DISMISSED_NOTIFICATIONS_KEY).forEach((id) => merged.add(id));
    return merged;
  });
  const [seenCriticalIds, setSeenCriticalIds] = useState<Set<string>>(() => {
    const merged = readIdSet(SEEN_CRITICAL_STORAGE_KEY);
    readIdSet(SEEN_NOTIFICATIONS_KEY).forEach((id) => merged.add(id));
    return merged;
  });

  const loadAlerts = useCallback(async (): Promise<void> => {
    setLoading(true);
    try {
      const [diagnostics, billingAlerts] = await Promise.all([
        fetchDiagnosticLogs(undefined, 20).catch(() => ({ logs: [] })),
        fetchBillingNotifications(20).catch(() => ({
          notifications: [],
          total: 0,
          unread_critical: 0,
        })),
      ]);
      setLogs(diagnostics.logs ?? []);
      setNotifications(billingAlerts.notifications ?? []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAlerts();
    const interval = window.setInterval(() => {
      void loadAlerts();
    }, 60_000);
    return () => window.clearInterval(interval);
  }, [loadAlerts]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent): void => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const alerts = useMemo(() => {
    const combined = [...mapNotifications(notifications), ...mapDiagnostics(logs)];
    combined.sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    );
    return combined.filter((item) => !dismissedIds.has(item.id)).slice(0, 8);
  }, [dismissedIds, logs, notifications]);

  const unreadCritical = useMemo(
    () =>
      [...mapNotifications(notifications), ...mapDiagnostics(logs)].some(
        (item) => item.critical && !dismissedIds.has(item.id) && !seenCriticalIds.has(item.id),
      ),
    [dismissedIds, logs, notifications, seenCriticalIds],
  );

  const handleOpen = (): void => {
    setOpen((value) => {
      const nextOpen = !value;
      if (nextOpen) {
        const nextSeen = new Set(seenCriticalIds);
        [...mapNotifications(notifications), ...mapDiagnostics(logs)].forEach((item) => {
          if (item.critical) {
            nextSeen.add(item.id);
          }
        });
        setSeenCriticalIds(nextSeen);
        writeIdSet(SEEN_CRITICAL_STORAGE_KEY, nextSeen);
        writeIdSet(SEEN_NOTIFICATIONS_KEY, nextSeen);
      }
      return nextOpen;
    });
  };

  const handleClearAll = (): void => {
    const nextDismissed = new Set(dismissedIds);
    alerts.forEach((item) => nextDismissed.add(item.id));
    setDismissedIds(nextDismissed);
    writeIdSet(DISMISSED_STORAGE_KEY, nextDismissed);
    writeIdSet(DISMISSED_NOTIFICATIONS_KEY, nextDismissed);
    setOpen(false);
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={handleOpen}
        aria-label="Системные уведомления"
        className={cn(
          "relative inline-flex h-10 w-10 items-center justify-center rounded-xl border border-zinc-800/80",
          "bg-zinc-950/70 text-zinc-400 transition hover:border-zinc-700 hover:bg-zinc-900/80 hover:text-zinc-200",
          open && "border-violet-500/30 bg-violet-500/10 text-violet-200",
        )}
      >
        <Bell className="h-4 w-4" />
        {unreadCritical ? (
          <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.85)] animate-pulse" />
        ) : null}
      </button>

      <AnimatePresence>
        {open ? (
          <motion.div
            initial={{ opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.98 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="absolute right-0 top-[calc(100%+0.5rem)] z-50 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950/95 shadow-glow-purple backdrop-blur-xl"
          >
            <div className="flex items-center justify-between border-b border-zinc-800/80 px-4 py-3">
              <div>
                <p className="text-sm font-semibold text-zinc-100">Системные алерты</p>
                <p className="text-[11px] text-zinc-500">Платежи и критические события</p>
              </div>
              <button
                type="button"
                onClick={handleClearAll}
                disabled={alerts.length === 0}
                className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-medium text-zinc-400 transition hover:bg-zinc-900 hover:text-zinc-200 disabled:opacity-40"
              >
                <Trash2 className="h-3 w-3" />
                Очистить всё
              </button>
            </div>

            <div className="max-h-80 overflow-y-auto p-2">
              {loading ? (
                <div className="flex items-center justify-center py-10 text-zinc-500">
                  <Loader2 className="h-4 w-4 animate-spin" />
                </div>
              ) : alerts.length === 0 ? (
                <p className="px-3 py-8 text-center text-xs text-zinc-500">
                  Новых уведомлений нет.
                </p>
              ) : (
                <ul className="space-y-2">
                  {alerts.map((alert) => (
                    <li
                      key={alert.id}
                      className="rounded-xl border border-zinc-800/80 bg-black/30 px-3 py-2.5 transition hover:border-zinc-700"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="truncate text-xs font-medium text-zinc-200">
                              {alert.title}
                            </span>
                            <span
                              className={cn(
                                "rounded-md px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
                                alert.critical
                                  ? "bg-red-500/10 text-red-300 ring-1 ring-red-500/20"
                                  : "bg-zinc-800/80 text-zinc-400",
                              )}
                            >
                              {alert.badge}
                            </span>
                          </div>
                          <p className="mt-1 line-clamp-2 text-xs text-zinc-500">{alert.message}</p>
                          <time className="mt-1 block text-[10px] text-zinc-600">
                            {formatTimestamp(alert.created_at)}
                          </time>
                        </div>
                        <Link
                          href={alert.href}
                          onClick={() => setOpen(false)}
                          className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-zinc-800 px-2 py-1 text-[10px] font-medium text-violet-300 transition hover:border-violet-500/30 hover:bg-violet-500/10"
                        >
                          <ExternalLink className="h-3 w-3" />
                          {alert.kind === "notification" ? "Billing" : "Open"}
                        </Link>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <CursorDebugPanel botId={activeBotId} compact />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

/** @deprecated Prefer HeaderAlertNotificationBell — kept for existing AppShell imports. */
export const HeaderNotificationBell = HeaderAlertNotificationBell;

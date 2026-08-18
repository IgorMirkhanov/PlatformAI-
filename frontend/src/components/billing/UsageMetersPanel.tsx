"use client";

import { useEffect, useState } from "react";
import { Activity, Coins, MessageSquare } from "lucide-react";

import { fetchBillingUsage, fetchOrgAnalytics } from "@/lib/api";
import { cn } from "@/lib/utils";

interface UsageMetersPanelProps {
  organizationId?: string | null;
  className?: string;
  days?: number;
}

export function UsageMetersPanel({
  organizationId,
  className,
  days = 30,
}: UsageMetersPanelProps) {
  const [loading, setLoading] = useState(true);
  const [messageCount, setMessageCount] = useState(0);
  const [tokenCount, setTokenCount] = useState(0);
  const [estimatedCost, setEstimatedCost] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        if (organizationId) {
          const summary = await fetchOrgAnalytics(organizationId, days);
          if (cancelled) return;
          setMessageCount(summary.message_count);
          setTokenCount(summary.metrics?.LLM_TOKENS?.quantity ?? 0);
          setEstimatedCost(summary.estimated_cost);
        } else {
          const usage = await fetchBillingUsage(days);
          if (cancelled) return;
          const msgIn = usage.metrics?.MESSAGE_IN?.quantity ?? 0;
          const msgOut = usage.metrics?.MESSAGE_OUT?.quantity ?? 0;
          setMessageCount(msgIn + msgOut);
          setTokenCount(usage.metrics?.LLM_TOKENS?.quantity ?? 0);
          setEstimatedCost(
            Object.values(usage.metrics || {}).reduce((sum, m) => sum + (m.cost || 0), 0),
          );
        }
      } catch {
        if (!cancelled) setError("Не удалось загрузить usage meters.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [days, organizationId]);

  const cards = [
    {
      label: "Сообщения",
      value: messageCount.toLocaleString("ru-RU"),
      icon: MessageSquare,
      hint: `${days} дн.`,
    },
    {
      label: "LLM токены",
      value: tokenCount.toLocaleString("ru-RU"),
      icon: Activity,
      hint: `${days} дн.`,
    },
    {
      label: "Оценка spend",
      value: estimatedCost.toFixed(2),
      icon: Coins,
      hint: "из UsageEvent",
    },
  ];

  return (
    <section
      className={cn(
        "rounded-2xl border border-zinc-800/80 bg-zinc-950/50 p-5",
        className,
      )}
    >
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-zinc-100">Usage analytics</h2>
        <span className="text-[11px] uppercase tracking-wide text-zinc-500">
          last {days}d
        </span>
      </div>
      {error ? (
        <p className="text-sm text-amber-300">{error}</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-3">
          {cards.map((card) => (
            <div
              key={card.label}
              className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 px-4 py-3"
            >
              <div className="flex items-center gap-2 text-zinc-500">
                <card.icon className="h-3.5 w-3.5" />
                <span className="text-[11px] font-medium uppercase tracking-wide">
                  {card.label}
                </span>
              </div>
              <p className="mt-2 text-xl font-semibold tabular-nums text-zinc-50">
                {loading ? "…" : card.value}
              </p>
              <p className="mt-1 text-[11px] text-zinc-600">{card.hint}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

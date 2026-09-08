"use client";

import { useAgentWorkspace } from "@/hooks/useAgentWorkspace";
import { useParams } from "next/navigation";
import { Shield } from "lucide-react";
import { PageSkeleton } from "@/components/ui/Skeleton";

export default function AgentControlPage() {
  const params = useParams<{ id: string }>();
  const botId = params.id;
  const { profile, loading } = useAgentWorkspace(botId);

  if (loading && !profile) return <PageSkeleton />;
  if (!profile) {
    return (
      <div className="moonai-panel text-center text-sm text-[var(--canvas-muted)]">
        Профиль агента недоступен.
      </div>
    );
  }

  return (
    <section className="moonai-panel space-y-4">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/10 ring-1 ring-violet-500/25">
          <Shield className="h-5 w-5 text-violet-400" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-[var(--canvas-fg)]">Контроль</h2>
          <p className="mt-1 text-sm text-[var(--canvas-muted)]">
            Статус агента <span className="text-[var(--canvas-fg)]">{profile.name}</span>, расписание и
            быстрые флаги безопасности.
          </p>
        </div>
      </div>
      <dl className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-[var(--canvas-border)] bg-[var(--canvas)] px-4 py-3">
          <dt className="text-[10px] uppercase tracking-wider text-[var(--canvas-muted)]">Статус</dt>
          <dd className="mt-1 text-sm font-medium text-[var(--canvas-fg)]">
            {profile.is_active ? "Активен" : "Выключен"}
          </dd>
        </div>
        <div className="rounded-xl border border-[var(--canvas-border)] bg-[var(--canvas)] px-4 py-3">
          <dt className="text-[10px] uppercase tracking-wider text-[var(--canvas-muted)]">Часовой пояс</dt>
          <dd className="mt-1 text-sm font-medium text-[var(--canvas-fg)]">{profile.timezone}</dd>
        </div>
        <div className="rounded-xl border border-[var(--canvas-border)] bg-[var(--canvas)] px-4 py-3 sm:col-span-2">
          <dt className="text-[10px] uppercase tracking-wider text-[var(--canvas-muted)]">Расписание</dt>
          <dd className="mt-1 text-sm text-[var(--canvas-fg)]">
            {profile.schedule_config?.enabled
              ? `Включено · ${profile.schedule_config.windows?.length ?? 0} окон`
              : "Круглосуточно (расписание выключено)"}
          </dd>
        </div>
      </dl>
    </section>
  );
}

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Workflow } from "lucide-react";

import { getAgentTabPath } from "@/lib/agent-routes";
import { fetchDashboardStats } from "@/lib/api";
import { useBotStore } from "@/store/useBotStore";

export default function IntegrationsPage() {
  const router = useRouter();
  const activeBotId = useBotStore((state) => state.activeBotId);

  useEffect(() => {
    if (activeBotId) {
      router.replace(getAgentTabPath(activeBotId, "channels"));
      return;
    }

    void fetchDashboardStats()
      .then((stats) => {
        const firstBot = stats.agents[0];
        if (firstBot) {
          router.replace(getAgentTabPath(firstBot.bot_id, "channels"));
          return;
        }
        router.replace("/flow-builder");
      })
      .catch(() => {
        router.replace("/flow-builder");
      });
  }, [activeBotId, router]);

  return (
    <div className="mx-auto flex min-h-[60vh] max-w-lg flex-col items-center justify-center p-6 text-center lg:p-8">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-violet-500/10 ring-1 ring-violet-500/20">
        <Workflow className="h-7 w-7 text-violet-400" />
      </div>
      <h1 className="text-xl font-semibold text-zinc-100">Переход в конструктор…</h1>
      <p className="mt-2 text-sm leading-relaxed text-zinc-500">
        Сначала соберите сценарий агента в конструкторе, затем подключите каналы в профиле бота.
      </p>
      <Link
        href="/flow-builder"
        className="mt-6 inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-violet-500"
      >
        <Workflow className="h-4 w-4" />
        Открыть конструктор
      </Link>
    </div>
  );
}

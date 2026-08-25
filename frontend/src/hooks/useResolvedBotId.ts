"use client";

import { useEffect, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { useBotStore } from "@/store/useBotStore";

/**
 * Resolves the active agent id from ?botId= query, store, or first profile.
 * Keeps ?botId= in the URL when on dashboard workspace pages.
 */
export function useResolvedBotId(syncToUrl = true): string | null {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const activeBotId = useBotStore((s) => s.activeBotId);
  const agentProfiles = useBotStore((s) => s.agentProfiles);
  const connection = useBotStore((s) => s.connection);
  const setActiveBotId = useBotStore((s) => s.setActiveBotId);

  const botId = useMemo(() => {
    return (
      searchParams.get("botId") ||
      activeBotId ||
      connection?.botId ||
      Object.keys(agentProfiles)[0] ||
      null
    );
  }, [activeBotId, agentProfiles, connection?.botId, searchParams]);

  useEffect(() => {
    if (!botId) return;
    setActiveBotId(botId);
    if (!syncToUrl) return;
    if (searchParams.get("botId") === botId) return;
    const params = new URLSearchParams(searchParams.toString());
    params.set("botId", botId);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }, [botId, pathname, router, searchParams, setActiveBotId, syncToUrl]);

  return botId;
}

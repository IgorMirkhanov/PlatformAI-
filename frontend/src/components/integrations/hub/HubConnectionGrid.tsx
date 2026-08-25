"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { HubProviderCard } from "@/components/integrations/hub/HubProviderCard";
import { fetchHubConnections } from "@/lib/integrations/hubApi";
import { HUB_CARD_PROVIDERS, pickHubConnection } from "@/lib/integrations/hubCatalog";
import { useToast } from "@/hooks/useToast";
import { useOrganizationStore } from "@/lib/stores/use-organization-store";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import type { HubConnection } from "@/types/integration-hub";

interface HubConnectionGridProps {
  botId: string;
}

export function HubConnectionGrid({ botId }: HubConnectionGridProps) {
  const { showToast } = useToast();
  const currentOrgId = useOrganizationStore((state) => state.currentOrgId);
  const activeCompanyId = useBotStore((state) => state.activeCompanyId);
  const workspaceId = currentOrgId || activeCompanyId;
  const [connections, setConnections] = useState<HubConnection[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (): Promise<void> => {
    try {
      const rows = await fetchHubConnections();
      setConnections(rows);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить подключения Integration Hub."), "error");
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && connections.length === 0) {
    return (
      <div className="flex min-h-[180px] items-center justify-center rounded-2xl border border-zinc-800/80 bg-[#0b0b0d]/70">
        <div className="flex items-center gap-2 text-sm text-zinc-400">
          <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
          Загрузка подключений…
        </div>
      </div>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-2">
      {HUB_CARD_PROVIDERS.map((definition) => (
        <HubProviderCard
          key={definition.id}
          definition={definition}
          connection={pickHubConnection(connections, definition.id, botId)}
          botId={botId}
          workspaceId={workspaceId}
          onChanged={load}
        />
      ))}
    </div>
  );
}

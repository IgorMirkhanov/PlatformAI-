"use client";

import { Suspense } from "react";

import {
  AgentWorkspaceLayout,
  useAgentWorkspaceContext,
} from "@/components/bots/AgentWorkspaceLayout";
import { CrmIntegrationHub } from "@/components/integrations/CrmIntegrationHub";
import { PageSkeleton } from "@/components/ui/Skeleton";

function IntegrationsDashboardContent() {
  const { botId, profile } = useAgentWorkspaceContext();
  return <CrmIntegrationHub botId={botId} profile={profile} />;
}

export default function DashboardIntegrationsPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <AgentWorkspaceLayout emptyMessage="Создайте агента, чтобы настроить интеграции.">
        <IntegrationsDashboardContent />
      </AgentWorkspaceLayout>
    </Suspense>
  );
}

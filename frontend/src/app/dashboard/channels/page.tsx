"use client";

import { Suspense } from "react";

import {
  AgentWorkspaceLayout,
  useAgentWorkspaceContext,
} from "@/components/bots/AgentWorkspaceLayout";
import { HubChannelGrid } from "@/components/channel-hub/HubChannelGrid";
import { PageSkeleton } from "@/components/ui/Skeleton";

function ChannelsDashboardContent() {
  const { botId, profile } = useAgentWorkspaceContext();
  return <HubChannelGrid botId={botId} profile={profile} />;
}

export default function DashboardChannelsPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <AgentWorkspaceLayout emptyMessage="Создайте агента, чтобы подключить каналы.">
        <ChannelsDashboardContent />
      </AgentWorkspaceLayout>
    </Suspense>
  );
}

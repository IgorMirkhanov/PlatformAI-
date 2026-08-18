"use client";

import { createContext, useContext } from "react";

import type { HubChannelStatusItem, HubChannelType } from "@/types/channel-hub";

export interface ChannelHubContextValue {
  botId: string;
  statuses: Record<HubChannelType, HubChannelStatusItem>;
  refreshStatuses: () => Promise<void>;
}

export const ChannelHubContext = createContext<ChannelHubContextValue | null>(null);

export function useChannelHub(): ChannelHubContextValue {
  const ctx = useContext(ChannelHubContext);
  if (!ctx) {
    throw new Error("useChannelHub must be used within ChannelsAgentLayout");
  }
  return ctx;
}

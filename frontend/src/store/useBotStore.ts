import { create } from "zustand";
import { persist } from "zustand/middleware";

import {
  ApiError,
  fetchBillingStatus,
  fetchBillingTransactions,
  fetchBotChannels,
  fetchBotProfile,
  fetchCurrentUser,
  fetchOrganizations,
  patchBotChannel as patchBotChannelApi,
  subscribeToPlan,
  topUpBalance,
  updateBotFunctions,
  updateBotLlmConfig,
  updateBotPrompting,
  updateBotSettings,
  updateCurrentUserProfile,
} from "@/lib/api";
import type { SetupChannelRequest, SetupChannelResponse } from "@/lib/api";
import type {
  ChannelIntegrationType,
  ChannelStatus,
  PatchChannelRequest,
} from "@/types/channels";
import { mergeChannelStatuses } from "@/types/channels";
import type {
  BotAgentProfile,
  BotFunctionsUpdate,
  BotLLMConfigUpdate,
  BotPromptingUpdate,
  BotSettingsUpdate,
  ScheduleConfig,
} from "@/types/agent";
import type {
  BillingStatusResponse,
  BillingTransaction,
  BillingTransactionListResponse,
  SubscribeResponse,
  SubscriptionPlanName,
} from "@/types/billing";
import type { BotHealthTelemetry, PlatformType } from "@/types/bot";
import type { CurrentUser, CompanyWorkspace } from "@/types/team";

export interface BotConnection {
  botId: string;
  botName: string;
  platformType: PlatformType;
  tokenHash: string | null;
  telegramUsername: string | null;
  webhookUrl: string | null;
  health: BotHealthTelemetry | null;
}

interface BotStoreState {
  connection: BotConnection | null;
  activeBotId: string | null;
  currentUser: CurrentUser | null;
  currentUserLoading: boolean;
  activeCompanyId: string | null;
  organizations: CompanyWorkspace[];
  organizationsLoading: boolean;
  billing: BillingStatusResponse | null;
  billingLoading: boolean;
  billingTransactions: BillingTransaction[];
  billingTransactionsLoading: boolean;
  billingTransactionsTotal: number;
  agentProfiles: Record<string, BotAgentProfile>;
  profileLoading: Record<string, boolean>;
  profileSaving: Record<string, boolean>;
  channelStatuses: Record<string, Record<ChannelIntegrationType, ChannelStatus>>;
  channelsLoading: Record<string, boolean>;
  channelSaving: Record<string, boolean>;
  avatarByBotId: Record<string, string>;
  setConnection: (connection: BotConnection) => void;
  setActiveBotId: (botId: string | null) => void;
  loadCurrentUser: () => Promise<CurrentUser | null>;
  setCurrentUser: (user: CurrentUser) => void;
  loadOrganizations: () => Promise<CompanyWorkspace[]>;
  switchOrganization: (companyId: string) => Promise<void>;
  createOrganization: (name: string) => Promise<CompanyWorkspace>;
  updateAccountProfile: (payload: {
    company_name?: string;
    full_name?: string;
    timezone?: string;
  }) => Promise<CurrentUser>;
  clearWorkspaceCache: () => void;
  signOut: () => void;
  updateHealth: (health: BotHealthTelemetry) => void;
  clearConnection: () => void;
  loadBilling: () => Promise<BillingStatusResponse | null>;
  loadBillingTransactions: () => Promise<BillingTransactionListResponse | null>;
  subscribe: (plan: SubscriptionPlanName) => Promise<BillingStatusResponse>;
  topUp: (amount: number) => Promise<BillingStatusResponse>;
  loadAgentProfile: (botId: string) => Promise<BotAgentProfile | null>;
  setAgentProfile: (profile: BotAgentProfile) => void;
  patchAgentScheduleConfig: (botId: string, scheduleConfig: ScheduleConfig) => void;
  setAvatar: (botId: string, avatar: string) => void;
  saveAgentSettings: (botId: string, payload: BotSettingsUpdate) => Promise<BotAgentProfile>;
  saveAgentPrompting: (botId: string, payload: BotPromptingUpdate) => Promise<BotAgentProfile>;
  saveAgentLlmConfig: (botId: string, payload: BotLLMConfigUpdate) => Promise<BotAgentProfile>;
  saveAgentFunctions: (botId: string, payload: BotFunctionsUpdate) => Promise<BotAgentProfile>;
  loadBotChannels: (botId: string) => Promise<Record<ChannelIntegrationType, ChannelStatus>>;
  setupBotChannel: (
    botId: string,
    payload: SetupChannelRequest,
  ) => Promise<import("@/lib/api").SetupChannelResponse>;
  patchBotChannel: (
    botId: string,
    channelType: ChannelIntegrationType,
    payload: PatchChannelRequest,
  ) => Promise<SetupChannelResponse>;
}

function applyChannelResponse(
  botId: string,
  channelType: ChannelIntegrationType,
  response: SetupChannelResponse,
  previousMap: Record<ChannelIntegrationType, ChannelStatus>,
): Record<ChannelIntegrationType, ChannelStatus> {
  const previous = previousMap[channelType];
  return {
    ...previousMap,
    [channelType]: {
      ...previous,
      channel_type: channelType,
      connected: response.channel_connected,
      active: response.channel_active,
      webhook_url: response.webhook_url,
      verify_token: response.verify_token ?? previous.verify_token,
      embed_script: response.embed_script ?? previous.embed_script,
      telegram_username: response.telegram_username ?? previous.telegram_username,
    },
  };
}

function mapBillingFromSubscribe(
  subscription: SubscribeResponse["subscription"],
): BillingStatusResponse {
  return {
    user_id: subscription.user_id,
    plan_name: subscription.plan_name,
    balance: subscription.balance,
    bonus_balance: 0,
    currency: "KZT",
    status: subscription.status,
    expires_at: subscription.expires_at,
    days_remaining: null,
    active_agents_limit: subscription.plan_name === "PRO" ? 10 : subscription.plan_name === "ENTERPRISE" ? 999 : 1,
    message: "Subscription updated.",
  };
}

export const useBotStore = create<BotStoreState>()(
  persist(
    (set, get) => ({
      connection: null,
      activeBotId: null,
      currentUser: null,
      currentUserLoading: false,
      activeCompanyId: null,
      organizations: [],
      organizationsLoading: false,
      billing: null,
      billingLoading: false,
      billingTransactions: [],
      billingTransactionsLoading: false,
      billingTransactionsTotal: 0,
      agentProfiles: {},
      profileLoading: {},
      profileSaving: {},
      channelStatuses: {},
      channelsLoading: {},
      channelSaving: {},
      avatarByBotId: {},

      setConnection: (connection) => set({ connection }),

      setActiveBotId: (botId) => set({ activeBotId: botId }),

      loadCurrentUser: async () => {
        set({ currentUserLoading: true });
        try {
          const currentUser = await fetchCurrentUser();
          set({
            currentUser,
            activeCompanyId: get().activeCompanyId ?? currentUser.company_id,
            currentUserLoading: false,
          });
          const { applyUserPlatformRole } = await import("@/lib/auth/session");
          applyUserPlatformRole(currentUser);
          return currentUser;
        } catch {
          set({ currentUserLoading: false });
          return null;
        }
      },

      setCurrentUser: (currentUser) => {
        void import("@/lib/auth/session").then(({ applyUserPlatformRole }) => {
          applyUserPlatformRole(currentUser);
        });
        return set({
          currentUser,
          activeCompanyId: get().activeCompanyId ?? currentUser.company_id,
        });
      },

      loadOrganizations: async () => {
        set({ organizationsLoading: true });
        try {
          const response = await fetchOrganizations();
          set({
            organizations: response.organizations,
            activeCompanyId: response.active_company_id,
            organizationsLoading: false,
          });
          return response.organizations;
        } catch {
          set({ organizationsLoading: false });
          return [];
        }
      },

      switchOrganization: async (companyId) => {
        // Canonical switch path lives in organization store (JWT remint + persistence).
        const { useOrganizationStore } = await import("@/lib/stores/use-organization-store");
        await useOrganizationStore.getState().switchOrganization(companyId);
      },

      createOrganization: async (name) => {
        const { useOrganizationStore } = await import("@/lib/stores/use-organization-store");
        return useOrganizationStore.getState().createOrganization(name);
      },

      updateAccountProfile: async (payload) => {
        const profile = await updateCurrentUserProfile(payload);
        set({ currentUser: profile });
        if (payload.company_name) {
          set((state) => ({
            organizations: state.organizations.map((org) =>
              org.id === profile.company_id ? { ...org, name: profile.company_name } : org,
            ),
          }));
        }
        return profile;
      },

      clearWorkspaceCache: () =>
        set({
          connection: null,
          activeBotId: null,
          agentProfiles: {},
          profileLoading: {},
          profileSaving: {},
          channelStatuses: {},
          channelsLoading: {},
          channelSaving: {},
          billing: null,
          billingTransactions: [],
          billingTransactionsTotal: 0,
        }),

      signOut: () => {
        get().clearWorkspaceCache();
        set({
          currentUser: null,
          activeCompanyId: null,
          organizations: [],
          avatarByBotId: {},
        });
        useBotStore.persist.clearStorage();
        void import("@/lib/auth/session").then(({ signOutLocal }) => {
          signOutLocal();
        });
        if (typeof window !== "undefined") {
          window.location.href = "/login";
        }
      },

      updateHealth: (health) =>
        set((state) =>
          state.connection
            ? {
                connection: {
                  ...state.connection,
                  health,
                  botName: health.bot_name,
                },
              }
            : state,
        ),

      clearConnection: () => set({ connection: null }),

      loadBilling: async () => {
        set({ billingLoading: true });
        try {
          const billing = await fetchBillingStatus();
          set({ billing, billingLoading: false });
          return billing;
        } catch {
          set({ billingLoading: false });
          return null;
        }
      },

      loadBillingTransactions: async () => {
        set({ billingTransactionsLoading: true });
        try {
          const response = await fetchBillingTransactions({ limit: 100, offset: 0 });
          set({
            billingTransactions: response.transactions,
            billingTransactionsTotal: response.total,
            billingTransactionsLoading: false,
          });
          return response;
        } catch {
          set({ billingTransactionsLoading: false });
          return null;
        }
      },

      subscribe: async (plan) => {
        const response = await subscribeToPlan({ plan_name: plan });
        const billing = await fetchBillingStatus();
        set({ billing: billing ?? mapBillingFromSubscribe(response.subscription) });
        void get().loadBillingTransactions();
        return billing ?? mapBillingFromSubscribe(response.subscription);
      },

      topUp: async (amount) => {
        await topUpBalance({ amount });
        const billing = await fetchBillingStatus();
        set({ billing });
        void get().loadBillingTransactions();
        return billing;
      },

      loadAgentProfile: async (botId) => {
        set((state) => ({
          profileLoading: { ...state.profileLoading, [botId]: true },
        }));
        try {
          const profile = await fetchBotProfile(botId);
          set((state) => ({
            agentProfiles: { ...state.agentProfiles, [botId]: profile },
            profileLoading: { ...state.profileLoading, [botId]: false },
          }));
          return profile;
        } catch {
          set((state) => ({
            profileLoading: { ...state.profileLoading, [botId]: false },
          }));
          return null;
        }
      },

      setAgentProfile: (profile) =>
        set((state) => ({
          agentProfiles: { ...state.agentProfiles, [profile.id]: profile },
        })),

      patchAgentScheduleConfig: (botId, scheduleConfig) =>
        set((state) => {
          const profile = state.agentProfiles[botId];
          if (!profile) {
            return state;
          }
          return {
            agentProfiles: {
              ...state.agentProfiles,
              [botId]: { ...profile, schedule_config: scheduleConfig },
            },
          };
        }),

      setAvatar: (botId, avatar) =>
        set((state) => ({
          avatarByBotId: { ...state.avatarByBotId, [botId]: avatar },
        })),

      saveAgentSettings: async (botId, payload) => {
        set((state) => ({
          profileSaving: { ...state.profileSaving, [botId]: true },
        }));
        try {
          const profile = await updateBotSettings(botId, payload);
          get().setAgentProfile(profile);
          return profile;
        } finally {
          set((state) => ({
            profileSaving: { ...state.profileSaving, [botId]: false },
          }));
        }
      },

      saveAgentPrompting: async (botId, payload) => {
        set((state) => ({
          profileSaving: { ...state.profileSaving, [botId]: true },
        }));
        try {
          const profile = await updateBotPrompting(botId, payload);
          get().setAgentProfile(profile);
          return profile;
        } finally {
          set((state) => ({
            profileSaving: { ...state.profileSaving, [botId]: false },
          }));
        }
      },

      saveAgentLlmConfig: async (botId, payload) => {
        set((state) => ({
          profileSaving: { ...state.profileSaving, [botId]: true },
        }));
        try {
          const profile = await updateBotLlmConfig(botId, payload);
          get().setAgentProfile(profile);
          return profile;
        } finally {
          set((state) => ({
            profileSaving: { ...state.profileSaving, [botId]: false },
          }));
        }
      },

      saveAgentFunctions: async (botId, payload) => {
        set((state) => ({
          profileSaving: { ...state.profileSaving, [botId]: true },
        }));
        try {
          const profile = await updateBotFunctions(botId, payload);
          get().setAgentProfile(profile);
          return profile;
        } finally {
          set((state) => ({
            profileSaving: { ...state.profileSaving, [botId]: false },
          }));
        }
      },

      loadBotChannels: async (botId) => {
        set((state) => ({
          channelsLoading: { ...state.channelsLoading, [botId]: true },
        }));
        try {
          const response = await fetchBotChannels(botId);
          const map = mergeChannelStatuses(response.channels);
          set((state) => ({
            channelStatuses: { ...state.channelStatuses, [botId]: map },
            channelsLoading: { ...state.channelsLoading, [botId]: false },
          }));
          return map;
        } catch {
          const fallback = mergeChannelStatuses([]);
          set((state) => ({
            channelStatuses: { ...state.channelStatuses, [botId]: fallback },
            channelsLoading: { ...state.channelsLoading, [botId]: false },
          }));
          return fallback;
        }
      },

      setupBotChannel: async (botId, payload) => {
        if (!payload.channel_type) {
          throw new Error("channel_type is required.");
        }
        return get().patchBotChannel(botId, payload.channel_type, payload);
      },

      patchBotChannel: async (botId, channelType, payload) => {
        set((state) => ({
          channelSaving: { ...state.channelSaving, [botId]: true },
        }));
        try {
          const response = await patchBotChannelApi(botId, channelType, payload);
          set((state) => {
            const current = state.channelStatuses[botId] ?? mergeChannelStatuses([]);
            const nextMap = applyChannelResponse(botId, channelType, response, current);
            return { channelStatuses: { ...state.channelStatuses, [botId]: nextMap } };
          });
          await get().loadBotChannels(botId);
          return response;
        } finally {
          set((state) => ({
            channelSaving: { ...state.channelSaving, [botId]: false },
          }));
        }
      },
    }),
    {
      name: "ai-bot-platform-store",
      partialize: (state) => ({
        connection: state.connection,
        activeBotId: state.activeBotId,
        activeCompanyId: state.activeCompanyId,
        currentUser: state.currentUser,
        avatarByBotId: state.avatarByBotId,
      }),
    },
  ),
);

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.status === 402) {
      return error.message || "Лимит тарифа исчерпан. Обновите план в Billing.";
    }
    if (error.status === 429) {
      return error.message || "Слишком много запросов. Подождите немного и попробуйте снова.";
    }
    if (error.status === 422 && error.issues.length > 0) {
      const fields = error.issues
        .map((issue) => (issue.field ? `${issue.field}: ${issue.message}` : issue.message))
        .join("; ");
      return fields || error.message || fallback;
    }
    return error.message || fallback;
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return fallback;
}

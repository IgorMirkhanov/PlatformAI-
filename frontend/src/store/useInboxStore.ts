import { create } from "zustand";

import { fetchActiveChats, fetchClientMessages } from "@/lib/api";
import type { ActiveChatSummary, ChatMessage, ClientInboxProfile } from "@/types/inbox";

interface InboxState {
  chats: ActiveChatSummary[];
  selectedClientId: string | null;
  messages: Record<string, ChatMessage[]>;
  unreadByClient: Record<string, number>;
  wsConnected: boolean;
  operatorId: string | null;
  setOperatorId: (operatorId: string) => void;
  setWsConnected: (connected: boolean) => void;
  setChats: (chats: ActiveChatSummary[]) => void;
  selectClient: (clientId: string | null) => void;
  setMessages: (clientId: string, messages: ChatMessage[]) => void;
  appendMessage: (clientId: string, message: ChatMessage) => void;
  upsertChatFromWs: (summary: Partial<ActiveChatSummary> & { client_id: string }) => void;
  markClientRead: (clientId: string) => void;
  incrementUnread: (clientId: string) => void;
  updateClientPauseState: (
    clientId: string,
    isPaused: boolean,
    stateLabel: string,
  ) => void;
  clientProfiles: Record<string, ClientInboxProfile>;
  setClientProfile: (profile: ClientInboxProfile) => void;
  resyncInbox: () => Promise<void>;
}

export const useInboxStore = create<InboxState>((set, get) => ({
  chats: [],
  selectedClientId: null,
  messages: {},
  unreadByClient: {},
  wsConnected: false,
  operatorId: null,
  clientProfiles: {},

  setOperatorId: (operatorId) => set({ operatorId }),
  setWsConnected: (connected) => set({ wsConnected: connected }),

  setChats: (chats) => set({ chats }),

  selectClient: (clientId) => {
    set({ selectedClientId: clientId });
    if (clientId) {
      get().markClientRead(clientId);
    }
  },

  setMessages: (clientId, messages) =>
    set((state) => ({
      messages: { ...state.messages, [clientId]: messages },
    })),

  appendMessage: (clientId, message) =>
    set((state) => {
      const existing = state.messages[clientId] ?? [];
      if (existing.some((item) => item.id === message.id)) {
        return state;
      }
      return {
        messages: {
          ...state.messages,
          [clientId]: [...existing, message],
        },
      };
    }),

  upsertChatFromWs: (summary) =>
    set((state) => {
      const index = state.chats.findIndex(
        (chat) => chat.client_id === summary.client_id,
      );

      if (index === -1) {
        const newChat: ActiveChatSummary = {
          client_id: summary.client_id,
          bot_id: summary.bot_id ?? "",
          bot_name: summary.bot_name ?? "Bot",
          platform_type: summary.platform_type ?? "TELEGRAM",
          external_id: summary.external_id ?? "",
          username: summary.username ?? "",
          first_name: summary.first_name ?? "",
          phone: summary.phone ?? null,
          tags: summary.tags ?? [],
          current_step_id: summary.current_step_id ?? "",
          state_label: summary.state_label ?? "Active",
          is_paused_by_operator: summary.is_paused_by_operator ?? false,
          is_closed: summary.is_closed ?? false,
          last_message_text: summary.last_message_text ?? "",
          last_message_sender: summary.last_message_sender ?? null,
          last_message_at: summary.last_message_at ?? new Date().toISOString(),
          unread_count: summary.unread_count ?? 0,
        };
        return { chats: [newChat, ...state.chats] };
      }

      const updated = [...state.chats];
      updated[index] = { ...updated[index], ...summary };
      updated.sort((a, b) => {
        const aTime = a.last_message_at ? new Date(a.last_message_at).getTime() : 0;
        const bTime = b.last_message_at ? new Date(b.last_message_at).getTime() : 0;
        return bTime - aTime;
      });
      return { chats: updated };
    }),

  markClientRead: (clientId) =>
    set((state) => ({
      unreadByClient: { ...state.unreadByClient, [clientId]: 0 },
      chats: state.chats.map((chat) =>
        chat.client_id === clientId ? { ...chat, unread_count: 0 } : chat,
      ),
    })),

  incrementUnread: (clientId) =>
    set((state) => {
      const current = state.unreadByClient[clientId] ?? 0;
      return {
        unreadByClient: { ...state.unreadByClient, [clientId]: current + 1 },
        chats: state.chats.map((chat) =>
          chat.client_id === clientId
            ? { ...chat, unread_count: current + 1 }
            : chat,
        ),
      };
    }),

  updateClientPauseState: (clientId, isPaused, stateLabel) =>
    set((state) => ({
      chats: state.chats.map((chat) =>
        chat.client_id === clientId
          ? {
              ...chat,
              is_paused_by_operator: isPaused,
              state_label: stateLabel,
            }
          : chat,
      ),
      clientProfiles:
        state.clientProfiles[clientId] !== undefined
          ? {
              ...state.clientProfiles,
              [clientId]: {
                ...state.clientProfiles[clientId],
                is_paused_by_operator: isPaused,
                state_label: stateLabel,
              },
            }
          : state.clientProfiles,
    })),

  setClientProfile: (profile) =>
    set((state) => ({
      clientProfiles: {
        ...state.clientProfiles,
        [profile.client_id]: profile,
      },
    })),

  resyncInbox: async () => {
    try {
      const response = await fetchActiveChats();
      set({ chats: response.chats });

      const selected = get().selectedClientId;
      if (selected) {
        const thread = await fetchClientMessages(selected);
        set((state) => ({
          messages: { ...state.messages, [selected]: thread },
        }));
      }
    } catch {
      // best-effort resync after reconnect
    }
  },
}));

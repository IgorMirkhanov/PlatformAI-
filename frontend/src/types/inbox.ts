export type MessageSender = "CLIENT" | "BOT" | "OPERATOR";

export type PlatformType =
  | "TELEGRAM"
  | "WHATSAPP"
  | "INSTAGRAM"
  | "VKONTAKTE"
  | "WEB_WIDGET";

export type InboxFilterTab = "all" | "mine" | "bot" | "closed";

export type MessageDeliveryStatus = "sent" | "delivered" | "read";

export type ChatRoutingMode = "operator" | "bot";

export interface ChatMessage {
  id: string;
  client_id: string;
  sender: MessageSender;
  message_text: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ActiveChatSummary {
  client_id: string;
  bot_id: string;
  bot_name: string;
  platform_type: PlatformType;
  external_id: string;
  username: string;
  first_name: string;
  phone: string | null;
  tags: string[];
  current_step_id: string;
  state_label: string;
  is_paused_by_operator: boolean;
  is_closed: boolean;
  last_message_text: string;
  last_message_sender: MessageSender | null;
  last_message_at: string | null;
  unread_count: number;
}

export interface ActiveChatsResponse {
  chats: ActiveChatSummary[];
  total: number;
}

export interface ToggleOperatorResponse {
  client_id: string;
  is_paused_by_operator: boolean;
  state_label: string;
  message: string;
}

export interface InterceptChatRequest {
  action?: "intercept" | "release";
}

export interface InterceptChatResponse {
  session_id: string;
  client_id: string;
  is_paused_by_operator: boolean;
  state_label: string;
  routing_mode: ChatRoutingMode;
  message: string;
}

export interface CrmPlatformLinkage {
  connected: boolean;
  sync_enabled: boolean;
  lead_id: string | null;
  deal_id: string | null;
  stage_label: string | null;
  pipeline_label: string | null;
}

export interface CrmLinkageCard {
  amocrm: CrmPlatformLinkage | null;
  bitrix24: CrmPlatformLinkage | null;
}

export interface ClientInboxProfile {
  client_id: string;
  bot_id: string;
  bot_name: string;
  platform_type: PlatformType;
  display_name: string;
  phone: string | null;
  username: string;
  external_id: string;
  tags: string[];
  is_paused_by_operator: boolean;
  state_label: string;
  is_closed: boolean;
  crm: CrmLinkageCard;
}

export interface CreateCrmDealResponse {
  success: boolean;
  platform: string | null;
  lead_id: string | null;
  deal_id: string | null;
  message: string;
}

export interface OperatorContext {
  operator_id: string;
  company_id: string;
}

export interface QuickReplyTemplate {
  id: string;
  label: string;
  text: string;
}

export const INBOX_FILTER_TABS: ReadonlyArray<{
  id: InboxFilterTab;
  label: string;
}> = [
  { id: "all", label: "Все" },
  { id: "mine", label: "Мои" },
  { id: "bot", label: "Бот (ИИ)" },
  { id: "closed", label: "Закрытые" },
];

export const DEFAULT_QUICK_REPLIES: QuickReplyTemplate[] = [
  {
    id: "greeting",
    label: "Приветствие",
    text: "Здравствуйте! Я подключился к диалогу и помогу вам.",
  },
  {
    id: "wait",
    label: "Ожидание",
    text: "Спасибо за сообщение! Мне нужна минута, чтобы уточнить детали.",
  },
  {
    id: "closing",
    label: "Завершение",
    text: "Рад был помочь! Если появятся вопросы — напишите снова.",
  },
];

export function getMessageDeliveryStatus(
  message: ChatMessage,
): MessageDeliveryStatus {
  const raw = message.payload.delivery_status;
  if (raw === "read" || raw === "delivered" || raw === "sent") {
    return raw;
  }
  if (message.sender === "CLIENT") {
    return "delivered";
  }
  if (message.payload.source === "operator_panel") {
    return "delivered";
  }
  return "sent";
}

export function getClientDisplayName(chat: ActiveChatSummary): string {
  if (chat.first_name.trim()) {
    return chat.first_name.trim();
  }
  if (chat.username.trim()) {
    return chat.username.startsWith("@") ? chat.username : `@${chat.username}`;
  }
  return chat.external_id;
}

export function filterInboxChats(
  chats: ActiveChatSummary[],
  tab: InboxFilterTab,
  searchQuery: string,
): ActiveChatSummary[] {
  const normalizedQuery = searchQuery.trim().toLowerCase();

  return chats.filter((chat) => {
    if (tab === "mine" && !chat.is_paused_by_operator) {
      return false;
    }
    if (tab === "bot" && chat.is_paused_by_operator) {
      return false;
    }
    if (tab === "closed" && !chat.is_closed) {
      return false;
    }

    if (!normalizedQuery) {
      return true;
    }

    const haystack = [
      chat.first_name,
      chat.username,
      chat.external_id,
      chat.last_message_text,
      chat.bot_name,
      chat.phone ?? "",
    ]
      .join(" ")
      .toLowerCase();

    return haystack.includes(normalizedQuery);
  });
}

export function formatRelativeTimestamp(iso: string | null): string {
  if (!iso) {
    return "";
  }

  const date = new Date(iso);
  const diffMs = Date.now() - date.getTime();
  const diffMinutes = Math.floor(diffMs / 60000);

  if (diffMinutes < 1) {
    return "только что";
  }
  if (diffMinutes < 60) {
    return `${diffMinutes} мин назад`;
  }

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) {
    return `${diffHours} ч назад`;
  }

  const diffDays = Math.floor(diffHours / 24);
  if (diffDays === 1) {
    return "вчера";
  }
  if (diffDays < 7) {
    return `${diffDays} дн назад`;
  }

  return date.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "short",
  });
}

export function formatBubbleTimestamp(iso: string): string {
  return new Date(iso).toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

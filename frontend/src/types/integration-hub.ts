/**
 * Integration Hub CRMAdapter — frontend contract (architecture §3).
 * Runtime implementations live in the Python backend adapters.
 */

export type HubProvider =
  | "bitrix24"
  | "amocrm"
  | "wazzup"
  | "whatsapp"
  | "kaspi_pay";

export type HubConnectionStatus =
  | "disconnected"
  | "pending"
  | "connected"
  | "expired"
  | "revoked"
  | "error";

/** UI states from architecture §7. */
export type HubCardState = "not_connected" | "connecting" | "connected" | "expired" | "error";

export type HubAuthKind = "oauth" | "api_key" | "webhook";

export const HUB_OAUTH_MESSAGE_TYPE = "mpai:hub-oauth";

export interface HubOAuthMessage {
  type: typeof HUB_OAUTH_MESSAGE_TYPE;
  provider: string;
  status: "connected" | "error" | "cancelled" | string;
  connectionId?: string | null;
  message?: string | null;
}

export interface CRMContact {
  id: string;
  name?: string | null;
  phone?: string | null;
  email?: string | null;
}

export interface CRMDeal {
  id: string;
  title?: string | null;
  stageId?: string | null;
  contactId?: string | null;
}

export interface CreateContactInput {
  name: string;
  phone?: string;
  email?: string;
}

export interface UpdateContactInput {
  name?: string;
  phone?: string;
  email?: string;
}

export interface FindContactQuery {
  phone?: string;
  email?: string;
  query?: string;
}

export interface CreateDealInput {
  title: string;
  contactId?: string;
  stageId?: string;
}

export interface HubConnection {
  id: string;
  provider: HubProvider | string;
  status: HubConnectionStatus | string;
  workspaceId?: string;
  agentId?: string | null;
  botId?: string | null;
  externalAccountId?: string | null;
  oauthExpiresAt?: string | null;
  lastError?: string | null;
  config?: Record<string, unknown>;
  metadata?: {
    channels?: WazzupChannel[];
    merchant_id?: string;
    [key: string]: unknown;
  };
}

export interface WazzupChannel {
  channelId?: string;
  channel_id: string;
  transport?: string;
  kind?: "whatsapp" | "telegram" | "instagram" | string;
  plain_id?: string | null;
  state?: string | null;
}

export interface MessageReceived {
  type: "message.received";
  provider: "wazzup";
  connectionId?: string | null;
  channelId: string;
  channelType: "whatsapp" | "telegram" | "instagram" | string;
  chatId: string;
  messageId: string;
  text: string;
  contentUri?: string | null;
  from: { id: string; name: string };
  timestamp?: string;
  isEcho: boolean;
}

/**
 * MessagingAdapter — Wazzup (API key). WhatsApp MVP is this adapter only.
 */
export interface MessagingAdapter {
  connect(apiKey: string): Promise<HubConnection>;
  parseIncomingWebhook(payload: unknown): MessageReceived[];
  sendMessage(input: {
    chatId: string;
    text: string;
    channelId?: string;
    channelType?: string;
  }): Promise<void>;
}

export interface PaymentInvoice {
  id: string;
  amount: string;
  currency?: string;
  description?: string;
  status: string;
  paymentUrl?: string | null;
  callbackUrl: string;
  orderId?: string | null;
}

export interface PaymentStatusEvent {
  type: "payment.updated" | "payment.paid" | "payment.failed" | "payment.cancelled" | string;
  provider: "kaspi_pay";
  connectionId?: string | null;
  invoiceId: string;
  orderId?: string;
  status: string;
  amount?: string | null;
  transactionId?: string | null;
}

/**
 * KaspiPayAdapter — merchant invoice + payment status webhook.
 * Does not verify customer-uploaded receipts (no official Kaspi API; architecture §5).
 */
export interface KaspiPayAdapter {
  connect(input: { merchantId: string; merchantToken: string; secretKey?: string }): Promise<HubConnection>;
  createInvoice(input: {
    amount: number;
    description: string;
    callbackUrl?: string;
    orderId?: string;
  }): Promise<PaymentInvoice>;
  parseIncomingWebhook(payload: unknown): PaymentStatusEvent;
}

/**
 * Agent-facing CRM surface. Secrets never appear in these payloads.
 */
export interface CRMAdapter {
  testConnection(): Promise<boolean>;
  createContact(input: CreateContactInput): Promise<CRMContact>;
  updateContact(id: string, patch: UpdateContactInput): Promise<CRMContact>;
  findContact(query: FindContactQuery): Promise<CRMContact | null>;
  createDeal(input: CreateDealInput): Promise<CRMDeal>;
  updateDealStage(dealId: string, stageId: string): Promise<CRMDeal>;
  addNote(entityType: "contact" | "deal", entityId: string, text: string): Promise<void>;
  refreshToken(): Promise<void>;
}

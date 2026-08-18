export type WSEventType =
  | "NEW_MESSAGE"
  | "CHAT_ASSIGNED"
  | "BOT_TOGGLED"
  | "OPERATOR_INTERCEPT"
  | "STATE_UPDATED"
  | "PING"
  | "PONG"
  | "CONNECTED"
  | "ERROR"
  | "SUBSCRIBE_BOT"
  | "UNSUBSCRIBE_BOT"
  | "CRM_DEAL_CREATED"
  | "CRM_DEAL_UPDATED"
  | "CRM_DEAL_CLOSED";

export interface WSMessagePayload {
  client_id: string;
  bot_id?: string;
  message: {
    id: string;
    client_id: string;
    sender: "CLIENT" | "BOT" | "OPERATOR";
    message_text: string;
    payload: Record<string, unknown>;
    created_at: string;
  };
  client: {
    client_id: string;
    bot_id: string;
    external_id: string;
    username: string;
    first_name: string;
    current_step_id: string;
    state_label: string;
    is_paused_by_operator: boolean;
  };
}

export interface WSOperatorInterceptPayload {
  client_id: string;
  session_id?: string;
  bot_id?: string;
  is_paused_by_operator: boolean;
  state_label: string;
  routing_mode?: "operator" | "bot";
}

/** @deprecated Prefer WSOperatorInterceptPayload / OPERATOR_INTERCEPT */
export type WSBOTTOGGLEDPayload = WSOperatorInterceptPayload;

export interface WSStateUpdatedPayload {
  client_id: string;
  is_paused_by_operator: boolean;
  state_label: string;
}

export interface WSConnectedPayload {
  operator_id: string;
  company_id: string;
  active_connections?: number;
  message?: string;
}

export interface WSErrorPayload {
  message: string;
}

/** Native CRM kanban payloads (topic ``crm``, tenant = organization_id). */
export interface WSCrmDealCreatedPayload {
  topic: "crm";
  type: "deal.created";
  organization_id: string;
  actor_id?: string | null;
  deal: import("@/lib/crm/types").CrmDeal;
}

export interface WSCrmDealUpdatedPayload {
  topic: "crm";
  type: "deal.updated";
  organization_id: string;
  deal_id: string;
  stage_id: string;
  pipeline_id?: string | null;
  actor_id?: string | null;
}

export interface WSCrmDealClosedPayload {
  topic: "crm";
  type: "deal.closed";
  organization_id: string;
  deal_id: string;
  status: "won" | "lost" | string;
  actor_id?: string | null;
}

export interface WSEvent<TPayload = unknown> {
  event: WSEventType;
  payload: TPayload;
}

const WS_EVENT_TYPES: ReadonlySet<string> = new Set([
  "NEW_MESSAGE",
  "CHAT_ASSIGNED",
  "BOT_TOGGLED",
  "OPERATOR_INTERCEPT",
  "STATE_UPDATED",
  "PING",
  "PONG",
  "CONNECTED",
  "ERROR",
  "SUBSCRIBE_BOT",
  "UNSUBSCRIBE_BOT",
  "CRM_DEAL_CREATED",
  "CRM_DEAL_UPDATED",
  "CRM_DEAL_CLOSED",
]);

export function isWSEvent(data: unknown): data is WSEvent {
  if (typeof data !== "object" || data === null) {
    return false;
  }
  if (!("event" in data) || !("payload" in data)) {
    return false;
  }
  const event = (data as { event: unknown }).event;
  return typeof event === "string" && WS_EVENT_TYPES.has(event);
}

export function isNewMessageEvent(
  event: WSEvent,
): event is WSEvent<WSMessagePayload> {
  return event.event === "NEW_MESSAGE";
}

export function isOperatorInterceptEvent(
  event: WSEvent,
): event is WSEvent<WSOperatorInterceptPayload> {
  return (
    event.event === "OPERATOR_INTERCEPT" ||
    event.event === "BOT_TOGGLED" ||
    event.event === "STATE_UPDATED"
  );
}

/** @deprecated Use isOperatorInterceptEvent */
export function isBotToggledEvent(
  event: WSEvent,
): event is WSEvent<WSOperatorInterceptPayload> {
  return isOperatorInterceptEvent(event);
}

export function isPingEvent(event: WSEvent): event is WSEvent<Record<string, never>> {
  return event.event === "PING";
}

export function isConnectedEvent(
  event: WSEvent,
): event is WSEvent<WSConnectedPayload> {
  return event.event === "CONNECTED";
}

export function isErrorEvent(event: WSEvent): event is WSEvent<WSErrorPayload> {
  return event.event === "ERROR";
}

export function isCrmDealCreatedEvent(
  event: WSEvent,
): event is WSEvent<WSCrmDealCreatedPayload> {
  return event.event === "CRM_DEAL_CREATED";
}

export function isCrmDealUpdatedEvent(
  event: WSEvent,
): event is WSEvent<WSCrmDealUpdatedPayload> {
  return event.event === "CRM_DEAL_UPDATED";
}

export function isCrmDealClosedEvent(
  event: WSEvent,
): event is WSEvent<WSCrmDealClosedPayload> {
  return event.event === "CRM_DEAL_CLOSED";
}

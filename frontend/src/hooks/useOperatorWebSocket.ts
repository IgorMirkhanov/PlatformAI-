"use client";

import { useEffect, useRef } from "react";

import { fetchOperatorContext, getOperatorWsUrl } from "@/lib/api";
import { useCrmStore } from "@/store/useCrmStore";
import { useInboxStore } from "@/store/useInboxStore";
import {
  isConnectedEvent,
  isCrmDealClosedEvent,
  isCrmDealCreatedEvent,
  isCrmDealUpdatedEvent,
  isErrorEvent,
  isNewMessageEvent,
  isOperatorInterceptEvent,
  isPingEvent,
  isWSEvent,
  type WSEvent,
} from "@/types/ws";

const MAX_RECONNECT_DELAY_MS = 30000;
const BASE_RECONNECT_DELAY_MS = 1000;

/** Module singleton so ConversationPanel + DialogListPanel can both call the hook safely. */
let sharedSocket: WebSocket | null = null;
let sharedSubscriberCount = 0;
let sharedReconnectAttempt = 0;
let sharedReconnectTimer: number | null = null;
let sharedDisposed = true;

function applyWsEvent(event: WSEvent, socket: WebSocket): void {
  if (isPingEvent(event)) {
    socket.send(JSON.stringify({ event: "PONG", payload: {} }));
    return;
  }

  if (isConnectedEvent(event) || isErrorEvent(event)) {
    if (isErrorEvent(event)) {
      console.warn("[Operator WS]", event.payload);
    }
    return;
  }

  const store = useInboxStore.getState();

  if (isNewMessageEvent(event)) {
    const { client_id, message, client } = event.payload;
    store.appendMessage(client_id, message);
    store.upsertChatFromWs({
      ...client,
      client_id,
      last_message_text: message.message_text,
      last_message_sender: message.sender,
      last_message_at: message.created_at,
    });

    if (
      store.selectedClientId !== client_id &&
      message.sender === "CLIENT"
    ) {
      store.incrementUnread(client_id);
    }
    return;
  }

  if (isOperatorInterceptEvent(event)) {
    store.updateClientPauseState(
      event.payload.client_id,
      event.payload.is_paused_by_operator,
      event.payload.state_label,
    );
    return;
  }

  const crm = useCrmStore.getState();
  if (isCrmDealCreatedEvent(event)) {
    crm.handleWsDealCreated(event.payload);
    return;
  }
  if (isCrmDealUpdatedEvent(event)) {
    crm.handleWsDealUpdated(event.payload);
    return;
  }
  if (isCrmDealClosedEvent(event)) {
    crm.handleWsDealClosed(event.payload);
  }
}

function clearSharedReconnectTimer(): void {
  if (sharedReconnectTimer !== null) {
    window.clearTimeout(sharedReconnectTimer);
    sharedReconnectTimer = null;
  }
}

function connectSharedSocket(operatorId: string): void {
  if (sharedDisposed) {
    return;
  }

  if (
    sharedSocket &&
    (sharedSocket.readyState === WebSocket.OPEN ||
      sharedSocket.readyState === WebSocket.CONNECTING)
  ) {
    return;
  }

  const url = getOperatorWsUrl(operatorId);
  const socket = new WebSocket(url);
  sharedSocket = socket;

  socket.onopen = () => {
    sharedReconnectAttempt = 0;
    useInboxStore.getState().setWsConnected(true);
    void useInboxStore.getState().resyncInbox();
  };

  socket.onmessage = (messageEvent) => {
    try {
      const data: unknown = JSON.parse(String(messageEvent.data));
      if (isWSEvent(data)) {
        applyWsEvent(data, socket);
      }
    } catch {
      // ignore malformed payloads
    }
  };

  socket.onclose = () => {
    useInboxStore.getState().setWsConnected(false);
    if (sharedDisposed || sharedSubscriberCount <= 0) {
      return;
    }

    const delay = Math.min(
      BASE_RECONNECT_DELAY_MS * 2 ** sharedReconnectAttempt,
      MAX_RECONNECT_DELAY_MS,
    );
    sharedReconnectAttempt += 1;
    clearSharedReconnectTimer();
    sharedReconnectTimer = window.setTimeout(
      () => connectSharedSocket(operatorId),
      delay,
    );
  };

  socket.onerror = () => {
    socket.close();
  };
}

export function useOperatorWebSocket(): { connected: boolean } {
  const operatorId = useInboxStore((state) => state.operatorId);
  const setOperatorId = useInboxStore((state) => state.setOperatorId);
  const connected = useInboxStore((state) => state.wsConnected);

  useEffect(() => {
    let cancelled = false;

    const bootstrap = async (): Promise<void> => {
      if (!operatorId) {
        const context = await fetchOperatorContext();
        if (!cancelled) {
          setOperatorId(context.operator_id);
        }
      }
    };

    void bootstrap();

    return () => {
      cancelled = true;
    };
  }, [operatorId, setOperatorId]);

  useEffect(() => {
    if (!operatorId) {
      return;
    }

    sharedSubscriberCount += 1;
    sharedDisposed = false;
    connectSharedSocket(operatorId);

    const handleVisibility = (): void => {
      if (
        document.visibilityState === "visible" &&
        sharedSocket?.readyState !== WebSocket.OPEN
      ) {
        sharedSocket?.close();
        connectSharedSocket(operatorId);
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
      sharedSubscriberCount = Math.max(0, sharedSubscriberCount - 1);
      if (sharedSubscriberCount === 0) {
        sharedDisposed = true;
        clearSharedReconnectTimer();
        sharedSocket?.close();
        sharedSocket = null;
        useInboxStore.getState().setWsConnected(false);
      }
    };
  }, [operatorId]);

  return { connected };
}

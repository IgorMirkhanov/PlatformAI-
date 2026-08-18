"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getSandboxWsUrl } from "@/lib/api";
import type {
  ExecutionTrace,
  SandboxConnectionState,
  SandboxRuntimeLog,
  SandboxWsOutbound,
} from "@/types/sandbox";
import { createEmptyTrace, isSandboxWsOutbound, normalizeExecutionTrace } from "@/types/sandbox";

const MAX_RECONNECT_DELAY_MS = 15000;
const BASE_RECONNECT_DELAY_MS = 1000;

interface UseSandboxWebSocketOptions {
  botId: string;
  onResponse?: (payload: SandboxWsOutbound) => void;
}

interface UseSandboxWebSocketResult {
  connected: boolean;
  connecting: boolean;
  error: string | null;
  sessionId: string | null;
  lastTrace: ExecutionTrace;
  runtimeLogs: SandboxRuntimeLog[];
  sendMessage: (text: string) => void;
  reconnect: () => void;
}

export function useSandboxWebSocket({
  botId,
  onResponse,
}: UseSandboxWebSocketOptions): UseSandboxWebSocketResult {
  const [connection, setConnection] = useState<SandboxConnectionState>({
    connected: false,
    connecting: true,
    error: null,
  });
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [lastTrace, setLastTrace] = useState<ExecutionTrace>(createEmptyTrace());
  const [runtimeLogs, setRuntimeLogs] = useState<SandboxRuntimeLog[]>([]);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectAttempt = useRef(0);
  const reconnectTimer = useRef<number | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const onResponseRef = useRef(onResponse);

  useEffect(() => {
    onResponseRef.current = onResponse;
  }, [onResponse]);

  const appendLog = useCallback((level: SandboxRuntimeLog["level"], message: string): void => {
    setRuntimeLogs((current) => [
      ...current.slice(-49),
      {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        level,
        message,
        timestamp: Date.now(),
      },
    ]);
  }, []);

  const reconnect = useCallback((): void => {
    socketRef.current?.close();
    reconnectAttempt.current = 0;
  }, []);

  useEffect(() => {
    let disposed = false;

    const connect = (): void => {
      if (disposed) {
        return;
      }

      setConnection({ connected: false, connecting: true, error: null });

      try {
        const socket = new WebSocket(getSandboxWsUrl(botId));
        socketRef.current = socket;

        socket.onopen = () => {
          reconnectAttempt.current = 0;
          setConnection({ connected: true, connecting: false, error: null });
          appendLog("info", "Sandbox channel connected.");
        };

        socket.onmessage = (event) => {
          try {
            const data: unknown = JSON.parse(String(event.data));
            if (!isSandboxWsOutbound(data)) {
              appendLog("error", "Received malformed sandbox payload.");
              return;
            }

            setSessionId(data.session_id);
            sessionIdRef.current = data.session_id;
            setLastTrace(normalizeExecutionTrace(data.trace));

            if (data.error) {
              appendLog("error", data.error);
            } else {
              appendLog("info", "Trace updated from sandbox runtime.");
            }

            onResponseRef.current?.(data);
          } catch (error) {
            appendLog(
              "error",
              error instanceof Error ? error.message : "Failed to parse sandbox response.",
            );
          }
        };

        socket.onclose = () => {
          setConnection((current) => ({
            ...current,
            connected: false,
            connecting: false,
          }));

          if (disposed) {
            return;
          }

          const delay = Math.min(
            BASE_RECONNECT_DELAY_MS * 2 ** reconnectAttempt.current,
            MAX_RECONNECT_DELAY_MS,
          );
          reconnectAttempt.current += 1;
          reconnectTimer.current = window.setTimeout(connect, delay);
        };

        socket.onerror = () => {
          setConnection((current) => ({
            ...current,
            error: "Sandbox WebSocket connection error.",
          }));
          socket.close();
        };
      } catch (error) {
        setConnection({
          connected: false,
          connecting: false,
          error: error instanceof Error ? error.message : "Unable to open sandbox channel.",
        });
      }
    };

    connect();

    return () => {
      disposed = true;
      if (reconnectTimer.current !== null) {
        window.clearTimeout(reconnectTimer.current);
      }
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [appendLog, botId]);

  const sendMessage = useCallback(
    (text: string): void => {
      const trimmed = text.trim();
      if (!trimmed) {
        return;
      }

      const socket = socketRef.current;
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        appendLog("error", "Sandbox channel is not connected.");
        return;
      }

      try {
        socket.send(
          JSON.stringify({
            type: "message",
            text: trimmed,
            session_id: sessionIdRef.current,
          }),
        );
      } catch (error) {
        appendLog(
          "error",
          error instanceof Error ? error.message : "Failed to send sandbox message.",
        );
      }
    },
    [appendLog],
  );

  return {
    connected: connection.connected,
    connecting: connection.connecting,
    error: connection.error,
    sessionId,
    lastTrace,
    runtimeLogs,
    sendMessage,
    reconnect,
  };
}

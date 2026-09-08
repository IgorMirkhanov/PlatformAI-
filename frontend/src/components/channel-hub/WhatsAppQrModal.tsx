"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, QrCode, RefreshCw, X } from "lucide-react";

import {
  fetchWhatsAppSession,
  getWhatsAppQrWsUrl,
  refreshWhatsAppQr,
  startWhatsAppSession,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import type { WhatsAppQrWsFrame } from "@/types/channel-hub";

interface WhatsAppQrModalProps {
  open: boolean;
  botId: string;
  onClose: () => void;
  onConnected: (meta?: { phone?: string | null; pushName?: string | null }) => void;
}

type ScanPhase = "connecting" | "waiting" | "scanning" | "connected" | "failed" | "expired";

const PHASE_LABEL: Record<ScanPhase, string> = {
  connecting: "Connecting to server…",
  waiting: "Waiting for scan…",
  scanning: "Scan detected…",
  connected: "Session connected",
  failed: "Connection failed",
  expired: "QR expired",
};

const HEARTBEAT_MS = 25_000;
const QR_TTL_SECONDS = 30;
const POLL_MS = 2_000;

function normalizeEvent(frame: WhatsAppQrWsFrame): string {
  return String(frame.event || frame.legacy_event || "");
}

/**
 * Live QR pairing modal with 30s expiry countdown + Refresh QR.
 * Primary path: authenticated WebSocket. Fallback: HTTP session poll for qr_base64.
 */
export function WhatsAppQrModal({ open, botId, onClose, onConnected }: WhatsAppQrModalProps) {
  const [qrBase64, setQrBase64] = useState<string | null>(null);
  const [phase, setPhase] = useState<ScanPhase>("connecting");
  const [message, setMessage] = useState<string | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(QR_TTL_SECONDS);
  const [refreshing, setRefreshing] = useState(false);

  const socketRef = useRef<WebSocket | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onConnectedRef = useRef(onConnected);
  const connectedNotifiedRef = useRef(false);
  const intentionalCloseRef = useRef(false);

  useEffect(() => {
    onConnectedRef.current = onConnected;
  }, [onConnected]);

  const clearCountdown = useCallback(() => {
    if (countdownRef.current) {
      clearInterval(countdownRef.current);
      countdownRef.current = null;
    }
  }, []);

  const startCountdown = useCallback(() => {
    clearCountdown();
    setSecondsLeft(QR_TTL_SECONDS);
    countdownRef.current = setInterval(() => {
      setSecondsLeft((prev) => {
        if (prev <= 1) {
          clearCountdown();
          setPhase((p) => (p === "connected" ? p : "expired"));
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, [clearCountdown]);

  const applyQr = useCallback(
    (next: string | null | undefined) => {
      if (!next) return;
      setQrBase64((prev) => (prev === next ? prev : next));
      setPhase((p) => (p === "connected" || p === "scanning" ? p : "waiting"));
      startCountdown();
    },
    [startCountdown],
  );

  const notifyConnected = useCallback((phone?: string | null, pushName?: string | null) => {
    setPhase("connected");
    clearCountdown();
    if (!connectedNotifiedRef.current) {
      connectedNotifiedRef.current = true;
      onConnectedRef.current({ phone, pushName });
    }
  }, [clearCountdown]);

  const handleRefreshQr = useCallback(async () => {
    setRefreshing(true);
    setPhase("waiting");
    setMessage("Refreshing QR code…");
    setQrBase64(null);
    try {
      await refreshWhatsAppQr(botId);
      startCountdown();
    } catch {
      setPhase("failed");
      setMessage("Failed to refresh QR. Try again.");
    } finally {
      setRefreshing(false);
    }
  }, [botId, startCountdown]);

  useEffect(() => {
    if (!open) {
      intentionalCloseRef.current = true;
      if (heartbeatRef.current) {
        clearInterval(heartbeatRef.current);
        heartbeatRef.current = null;
      }
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      clearCountdown();
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
      setQrBase64(null);
      setPhase("connecting");
      setMessage(null);
      setSecondsLeft(QR_TTL_SECONDS);
      connectedNotifiedRef.current = false;
      return;
    }

    intentionalCloseRef.current = false;
    connectedNotifiedRef.current = false;
    setPhase("connecting");
    setMessage("Connecting to server…");

    void startWhatsAppSession(botId).catch(() => {
      /* WS / poll will surface errors */
    });

    const pollOnce = async () => {
      try {
        const live = await fetchWhatsAppSession(botId);
        if (live.qr_base64) {
          applyQr(live.qr_base64);
          setMessage("Отсканируйте QR-код в WhatsApp → Связанные устройства.");
        }
        if (live.status === "connected") {
          notifyConnected(live.phone, live.push_name);
        }
      } catch {
        /* ignore transient poll errors */
      }
    };

    void pollOnce();
    pollRef.current = setInterval(() => {
      void pollOnce();
    }, POLL_MS);

    if (socketRef.current) {
      return () => {
        intentionalCloseRef.current = true;
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      };
    }

    const url = getWhatsAppQrWsUrl(botId);
    const socket = new WebSocket(url);
    socketRef.current = socket;

    socket.onopen = () => {
      setPhase((p) => (p === "connected" ? p : "waiting"));
      setMessage((m) => m || "Waiting for scan…");
      if (heartbeatRef.current) {
        clearInterval(heartbeatRef.current);
      }
      heartbeatRef.current = setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "ping", ts: Date.now() }));
        }
      }, HEARTBEAT_MS);
    };

    socket.onmessage = (event) => {
      try {
        const frame = JSON.parse(String(event.data)) as WhatsAppQrWsFrame & {
          type?: string;
        };
        if (frame.type === "pong") {
          return;
        }
        if (frame.qr_base64) {
          applyQr(frame.qr_base64);
        }
        if (frame.message) {
          setMessage(frame.message);
        }
        const ev = normalizeEvent(frame);
        if (ev === "QR_READY" || ev === "qr_code_ready") {
          setPhase("waiting");
        } else if (ev === "scanning_detected") {
          setPhase("scanning");
        } else if (ev === "CONNECTED" || ev === "session_connected") {
          notifyConnected(frame.reference_id, frame.push_name);
        } else if (
          ev === "AUTH_FAILURE" ||
          ev === "DISCONNECTED" ||
          ev === "connection_failed"
        ) {
          setPhase("failed");
          clearCountdown();
        }
      } catch {
        // ignore malformed frames
      }
    };

    socket.onerror = () => {
      // Keep polling fallback — do not mark failed solely on WS errors.
      setMessage((m) => m || "WebSocket unavailable — using HTTP fallback…");
    };

    socket.onclose = (event) => {
      socketRef.current = null;
      if (heartbeatRef.current) {
        clearInterval(heartbeatRef.current);
        heartbeatRef.current = null;
      }
      if (
        !intentionalCloseRef.current &&
        !connectedNotifiedRef.current &&
        event.code === 1008
      ) {
        setMessage("WebSocket auth failed — using HTTP fallback for QR…");
      }
    };

    return () => {
      intentionalCloseRef.current = true;
      clearCountdown();
      if (heartbeatRef.current) {
        clearInterval(heartbeatRef.current);
        heartbeatRef.current = null;
      }
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
    };
  }, [applyQr, botId, clearCountdown, notifyConnected, open]);

  if (!open) return null;

  const showQr = Boolean(qrBase64) && phase !== "connected" && phase !== "failed";

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/75 px-4 backdrop-blur-sm">
      <div className="w-full max-w-md overflow-hidden rounded-2xl border border-zinc-800 bg-[#0d0d0f] shadow-2xl">
        <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
          <div className="flex items-center gap-2">
            <QrCode className="h-4 w-4 text-[#25D366]" />
            <h2 className="text-sm font-semibold text-zinc-100">WhatsApp QR</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-900 hover:text-zinc-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 p-5">
          <p className="text-sm text-zinc-400">{PHASE_LABEL[phase]}</p>
          {message ? <p className="text-xs text-zinc-500">{message}</p> : null}

          <div className="flex flex-col items-center gap-3">
            {showQr ? (
              <>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`data:image/png;base64,${qrBase64}`}
                  alt="WhatsApp QR"
                  className="h-56 w-56 rounded-xl bg-white p-2"
                />
                <p
                  className={cn(
                    "text-sm font-semibold tabular-nums",
                    secondsLeft <= 5 ? "text-amber-300" : "text-zinc-300",
                    phase === "expired" && "text-red-300",
                  )}
                >
                  {phase === "expired"
                    ? "QR expired"
                    : `Expires in ${secondsLeft}s`}
                </p>
              </>
            ) : phase === "connecting" || phase === "waiting" ? (
              <Loader2 className="h-8 w-8 animate-spin text-[#25D366]" />
            ) : null}

            {(phase === "expired" || phase === "failed" || phase === "waiting") && (
              <button
                type="button"
                onClick={() => void handleRefreshQr()}
                disabled={refreshing}
                className="inline-flex items-center gap-2 rounded-xl border border-zinc-700 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-900 disabled:opacity-50"
              >
                {refreshing ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                Refresh QR
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

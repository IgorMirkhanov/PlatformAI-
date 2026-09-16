"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, QrCode, RefreshCw, X } from "lucide-react";

import {
  fetchWhatsAppSession,
  getWhatsAppQrWsUrl,
  refreshWhatsAppQr,
  startWhatsAppSession,
  stopWhatsAppSession,
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
  connecting: "Подключение к серверу…",
  waiting: "Ожидание сканирования…",
  scanning: "Сканирование подтверждено…",
  connected: "WhatsApp подключён",
  failed: "Ошибка подключения",
  expired: "QR истёк",
};

const HEARTBEAT_MS = 25_000;
const QR_TTL_SECONDS = 45;
const POLL_MS = 2_000;

function normalizeEvent(frame: WhatsAppQrWsFrame): string {
  return String(frame.event || frame.legacy_event || "");
}

function formatPhone(phone?: string | null): string {
  const digits = String(phone || "").replace(/\D/g, "");
  if (!digits) return "";
  return digits.startsWith("7") ? `+${digits}` : `+${digits}`;
}

/**
 * Live QR pairing. If a Baileys session is already open, show that instead of
 * flashing CONNECTED and closing — otherwise the user never sees a QR.
 */
export function WhatsAppQrModal({ open, botId, onClose, onConnected }: WhatsAppQrModalProps) {
  const [qrBase64, setQrBase64] = useState<string | null>(null);
  const [phase, setPhase] = useState<ScanPhase>("connecting");
  const [message, setMessage] = useState<string | null>(null);
  const [phone, setPhone] = useState<string | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(QR_TTL_SECONDS);
  const [refreshing, setRefreshing] = useState(false);

  const socketRef = useRef<WebSocket | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onConnectedRef = useRef(onConnected);
  const connectedNotifiedRef = useRef(false);
  const intentionalCloseRef = useRef(false);
  const scannedThisOpenRef = useRef(false);

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
      setPhase((p) => (p === "scanning" ? p : "waiting"));
      startCountdown();
    },
    [startCountdown],
  );

  const markConnected = useCallback(
    (nextPhone?: string | null, pushName?: string | null) => {
      setPhase("connected");
      setPhone(nextPhone || null);
      clearCountdown();
      if (!connectedNotifiedRef.current) {
        connectedNotifiedRef.current = true;
        onConnectedRef.current({ phone: nextPhone, pushName });
      }
    },
    [clearCountdown],
  );

  const handlePairAgain = useCallback(async (): Promise<void> => {
    setRefreshing(true);
    setPhase("connecting");
    setMessage("Сбрасываем сессию и генерируем новый QR…");
    setQrBase64(null);
    setPhone(null);
    connectedNotifiedRef.current = false;
    scannedThisOpenRef.current = true;
    try {
      await stopWhatsAppSession(botId);
      await startWhatsAppSession(botId);
      startCountdown();
    } catch {
      setPhase("failed");
      setMessage("Не удалось сбросить сессию. Попробуйте ещё раз.");
    } finally {
      setRefreshing(false);
    }
  }, [botId, startCountdown]);

  const handleRefreshQr = useCallback(async (): Promise<void> => {
    setRefreshing(true);
    setPhase("waiting");
    setMessage("Обновляем QR-код…");
    setQrBase64(null);
    try {
      await refreshWhatsAppQr(botId);
      startCountdown();
    } catch {
      setPhase("failed");
      setMessage("Не удалось обновить QR. Попробуйте ещё раз.");
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
      setPhone(null);
      setSecondsLeft(QR_TTL_SECONDS);
      connectedNotifiedRef.current = false;
      scannedThisOpenRef.current = false;
      return;
    }

    intentionalCloseRef.current = false;
    connectedNotifiedRef.current = false;
    scannedThisOpenRef.current = false;
    setPhase("connecting");
    setMessage("Подключаемся к WhatsApp-сервису…");

    void startWhatsAppSession(botId).catch(() => {
      /* WS / poll will surface errors */
    });

    const pollOnce = async () => {
      try {
        const live = await fetchWhatsAppSession(botId);
        if (live.status === "connected") {
          markConnected(live.phone, live.push_name);
          if (!scannedThisOpenRef.current) {
            setMessage(
              live.phone
                ? `Номер уже подключён: ${formatPhone(live.phone)}. Новый QR не нужен.`
                : "WhatsApp уже подключён на этом агенте.",
            );
          }
          return;
        }
        if (live.qr_base64) {
          scannedThisOpenRef.current = true;
          applyQr(live.qr_base64);
          setMessage("Отсканируйте QR в WhatsApp → Связанные устройства.");
        }
      } catch {
        /* ignore transient poll errors */
      }
    };

    void pollOnce();
    pollRef.current = setInterval(() => {
      void pollOnce();
    }, POLL_MS);

    const url = getWhatsAppQrWsUrl(botId);
    const socket = new WebSocket(url);
    socketRef.current = socket;

    socket.onopen = () => {
      setPhase((p) => (p === "connected" ? p : "waiting"));
      setMessage((m) => m || "Ожидание QR-кода…");
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
          status?: string;
        };
        if (frame.type === "pong") {
          return;
        }
        if (frame.qr_base64) {
          scannedThisOpenRef.current = true;
          applyQr(frame.qr_base64);
        }
        if (frame.message) {
          setMessage(frame.message);
        }
        const ev = normalizeEvent(frame);
        if (ev === "QR_READY" || ev === "qr_code_ready") {
          setPhase((p) => (p === "connected" ? p : "waiting"));
        } else if (ev === "scanning_detected") {
          scannedThisOpenRef.current = true;
          setPhase("scanning");
        } else if (ev === "CONNECTED" || ev === "session_connected") {
          markConnected(frame.reference_id, frame.push_name);
        } else if (ev === "AUTH_FAILURE") {
          setPhase("failed");
          clearCountdown();
        } else if (ev === "DISCONNECTED" || ev === "connection_failed") {
          if (String(frame.status || "") === "failed") {
            setPhase("failed");
            clearCountdown();
          }
        }
      } catch {
        // ignore malformed frames
      }
    };

    socket.onerror = () => {
      setMessage((m) => m || "WebSocket недоступен — ждём QR по HTTP…");
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
        setMessage("Ошибка авторизации WebSocket — ждём QR по HTTP…");
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
  }, [applyQr, botId, clearCountdown, markConnected, open]);

  if (!open) return null;

  const showQr = Boolean(qrBase64) && phase !== "connected" && phase !== "failed";
  const alreadyLinked = phase === "connected" && !scannedThisOpenRef.current;

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
            {phase === "connected" ? (
              <div className="w-full rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-center">
                <p className="text-sm font-medium text-emerald-200">
                  {phone ? formatPhone(phone) : "Сессия активна"}
                </p>
                <p className="mt-1 text-xs text-zinc-400">
                  {alreadyLinked
                    ? "QR не показывается, пока номер уже связан. Чтобы сменить номер — сбросьте сессию."
                    : "Можно писать агенту в WhatsApp."}
                </p>
              </div>
            ) : null}

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
                  {phase === "expired" ? "QR истёк" : `Истекает через ${secondsLeft}с`}
                </p>
              </>
            ) : phase === "connecting" || phase === "waiting" || phase === "scanning" ? (
              <Loader2 className="h-8 w-8 animate-spin text-[#25D366]" />
            ) : null}

            <div className="flex w-full flex-col gap-2">
              {phase === "connected" ? (
                <>
                  <button
                    type="button"
                    onClick={onClose}
                    className="inline-flex items-center justify-center rounded-xl bg-[#25D366] px-3 py-2 text-sm font-semibold text-black hover:bg-[#20b858]"
                  >
                    Готово
                  </button>
                  <button
                    type="button"
                    onClick={() => void handlePairAgain()}
                    disabled={refreshing}
                    className="inline-flex items-center justify-center gap-2 rounded-xl border border-zinc-700 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-900 disabled:opacity-50"
                  >
                    {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                    Отключить и показать новый QR
                  </button>
                </>
              ) : null}

              {(phase === "expired" || phase === "failed" || (phase === "waiting" && showQr)) && (
                <button
                  type="button"
                  onClick={() => void handleRefreshQr()}
                  disabled={refreshing}
                  className="inline-flex items-center justify-center gap-2 rounded-xl border border-zinc-700 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-900 disabled:opacity-50"
                >
                  {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  Обновить QR
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

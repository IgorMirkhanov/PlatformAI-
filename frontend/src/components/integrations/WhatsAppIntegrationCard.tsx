"use client";

import { useCallback, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  MessageCircle,
  ShieldCheck,
} from "lucide-react";

import { ApiError, createBot, fetchBotHealth, setupChannelCredentials } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useBotStore } from "@/store/useBotStore";

type SetupStatus = "idle" | "loading" | "success" | "error";

export function WhatsAppIntegrationCard() {
  const connection = useBotStore((state) => state.connection);
  const setConnection = useBotStore((state) => state.setConnection);
  const clearConnection = useBotStore((state) => state.clearConnection);

  const [botName, setBotName] = useState("My WhatsApp Bot");
  const [phoneNumberId, setPhoneNumberId] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [verifyToken, setVerifyToken] = useState("dev-verify");
  const [status, setStatus] = useState<SetupStatus>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const isWhatsAppConnection = connection?.platformType === "WHATSAPP";

  const showToast = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 4000);
  }, []);

  const handleConnect = useCallback(async (): Promise<void> => {
    const trimmedPhoneId = phoneNumberId.trim();
    const trimmedToken = accessToken.trim();

    if (!trimmedPhoneId) {
      setErrorMessage("Phone number ID is required.");
      setStatus("error");
      return;
    }
    if (!trimmedToken) {
      setErrorMessage("Access token is required.");
      setStatus("error");
      return;
    }

    setStatus("loading");
    setErrorMessage(null);

    try {
      const created = await createBot({
        name: botName.trim() || "WhatsApp Bot",
        platform_type: "WHATSAPP",
      });

      const channel = await setupChannelCredentials(created.bot_id, {
        whatsapp_phone_number_id: trimmedPhoneId,
        whatsapp_access_token: trimmedToken,
        whatsapp_verify_token: verifyToken.trim() || "dev-verify",
      });

      const health = await fetchBotHealth(created.bot_id);

      setConnection({
        botId: created.bot_id,
        botName: created.name,
        platformType: "WHATSAPP",
        tokenHash: channel.token_hash,
        telegramUsername: null,
        webhookUrl: channel.webhook_url,
        health,
      });

      setAccessToken("");
      setStatus("success");
      showToast(channel.message);
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Could not connect to the backend. Is the API running?";
      setErrorMessage(message);
      setStatus("error");
    }
  }, [
    accessToken,
    botName,
    phoneNumberId,
    setConnection,
    showToast,
    verifyToken,
  ]);

  return (
    <div className="relative overflow-hidden rounded-2xl border border-emerald-500/20 bg-gradient-to-br from-emerald-950/40 via-surface-raised to-surface shadow-node">
      {toast && (
        <div className="absolute right-4 top-4 z-10 flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300 shadow-glow">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          {toast}
        </div>
      )}

      <div className="border-b border-surface-border/80 p-6">
        <div className="flex items-start gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-500/15 ring-1 ring-emerald-500/30">
            <MessageCircle className="h-7 w-7 text-emerald-400" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-xl font-semibold text-zinc-100">WhatsApp</h2>
              <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-400">
                Stub
              </span>
              {isWhatsAppConnection && (
                <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-400">
                  Connected
                </span>
              )}
            </div>
            <p className="mt-1 text-sm text-zinc-400">
              Store Meta Cloud API credentials and register a webhook stub. Live
              message routing uses the same published flow graph as Telegram.
            </p>
          </div>
        </div>
      </div>

      <div className="space-y-5 p-6">
        {isWhatsAppConnection && connection ? (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <InfoTile label="Bot name" value={connection.botName} />
              <InfoTile label="Platform bot ID" value={connection.botId} mono />
              <InfoTile
                label="Webhook stub"
                value={connection.webhookUrl ?? "—"}
                mono
                truncate
              />
            </div>

            {connection.health && (
              <HealthTelemetryBlock health={connection.health} />
            )}

            <button
              type="button"
              onClick={() => {
                clearConnection();
                setStatus("idle");
                showToast("WhatsApp connection cleared.");
              }}
              className="rounded-lg border border-red-500/30 px-3 py-2 text-sm text-red-300 hover:bg-red-500/10"
            >
              Disconnect
            </button>
          </div>
        ) : (
          <>
            <div>
              <label
                htmlFor="wa-bot-name"
                className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-zinc-500"
              >
                Display name
              </label>
              <input
                id="wa-bot-name"
                type="text"
                value={botName}
                onChange={(event) => setBotName(event.target.value)}
                className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500/40"
                placeholder="WhatsApp Support"
              />
            </div>

            <div>
              <label
                htmlFor="wa-phone-id"
                className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-zinc-500"
              >
                Phone number ID
              </label>
              <input
                id="wa-phone-id"
                type="text"
                value={phoneNumberId}
                onChange={(event) => setPhoneNumberId(event.target.value)}
                className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2.5 font-mono text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500/40"
                placeholder="123456789012345"
              />
            </div>

            <div>
              <label
                htmlFor="wa-token"
                className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-zinc-500"
              >
                <ShieldCheck className="h-3.5 w-3.5" />
                Access token
              </label>
              <input
                id="wa-token"
                type="password"
                value={accessToken}
                onChange={(event) => {
                  setAccessToken(event.target.value);
                  if (status === "error") {
                    setStatus("idle");
                    setErrorMessage(null);
                  }
                }}
                className={cn(
                  "w-full rounded-lg border bg-surface px-3 py-2.5 font-mono text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-1",
                  errorMessage
                    ? "border-red-500/50 focus:border-red-500 focus:ring-red-500/30"
                    : "border-surface-border focus:border-emerald-500 focus:ring-emerald-500/40",
                )}
                placeholder="EAA..."
                autoComplete="off"
              />
            </div>

            {errorMessage && (
              <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                {errorMessage}
              </div>
            )}

            <button
              type="button"
              onClick={() => void handleConnect()}
              disabled={status === "loading"}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {status === "loading" ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Connecting…
                </>
              ) : (
                "Connect WhatsApp (stub)"
              )}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function InfoTile({
  label,
  value,
  mono = false,
  truncate = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
  truncate?: boolean;
}) {
  return (
    <div className="rounded-lg border border-surface-border bg-surface/60 px-3 py-2.5">
      <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-500">
        {label}
      </p>
      <p
        className={cn(
          "mt-1 text-sm text-zinc-200",
          mono && "font-mono text-xs",
          truncate && "truncate",
        )}
        title={value}
      >
        {value}
      </p>
    </div>
  );
}

function HealthTelemetryBlock({
  health,
}: {
  health: NonNullable<ReturnType<typeof useBotStore.getState>["connection"]>["health"];
}) {
  if (!health) {
    return null;
  }

  return (
    <div className="rounded-lg border border-surface-border bg-surface/50 p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
        Deployment telemetry
      </p>
      <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
        <span className="text-zinc-500">Flow status</span>
        <span
          className={cn(
            "font-medium",
            health.validation_status === "valid"
              ? "text-emerald-400"
              : health.validation_status === "missing"
                ? "text-amber-400"
                : "text-red-400",
          )}
        >
          {health.validation_status}
        </span>
        <span className="text-zinc-500">Published nodes</span>
        <span className="text-zinc-200">{health.node_count}</span>
        <span className="text-zinc-500">Channel</span>
        <span className="text-zinc-200">
          {health.channel_connected ? "Connected" : "Not connected"}
        </span>
      </div>
    </div>
  );
}

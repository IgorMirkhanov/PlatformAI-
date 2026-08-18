"use client";

import { useCallback, useState } from "react";
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Send,
  ShieldCheck,
} from "lucide-react";

import { ApiError, createBot, fetchBotHealth, setupChannelCredentials } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useBotStore } from "@/store/useBotStore";

type SetupStatus = "idle" | "loading" | "success" | "error";

const TELEGRAM_TOKEN_PATTERN = /^\d{8,10}:[A-Za-z0-9_-]{30,}$/;

export function TelegramIntegrationCard() {
  const connection = useBotStore((state) => state.connection);
  const setConnection = useBotStore((state) => state.setConnection);
  const clearConnection = useBotStore((state) => state.clearConnection);

  const [botToken, setBotToken] = useState("");
  const [botName, setBotName] = useState("My Telegram Bot");
  const [status, setStatus] = useState<SetupStatus>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const showToast = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 4000);
  }, []);

  const validateToken = useCallback((token: string): string | null => {
    const trimmed = token.trim();
    if (!trimmed) {
      return "Bot token is required.";
    }
    if (!TELEGRAM_TOKEN_PATTERN.test(trimmed)) {
      return "Token format looks invalid. Copy the full token from @BotFather (e.g. 123456789:ABCdef...).";
    }
    return null;
  }, []);

  const handleConnect = useCallback(async (): Promise<void> => {
    const validationError = validateToken(botToken);
    if (validationError) {
      setErrorMessage(validationError);
      setStatus("error");
      return;
    }

    setStatus("loading");
    setErrorMessage(null);

    try {
      const created = await createBot({
        name: botName.trim() || "Telegram Bot",
        platform_type: "TELEGRAM",
      });

      const channel = await setupChannelCredentials(created.bot_id, {
        telegram_bot_token: botToken.trim(),
      });

      const health = await fetchBotHealth(created.bot_id);

      setConnection({
        botId: created.bot_id,
        botName: created.name,
        platformType: "TELEGRAM",
        tokenHash: channel.token_hash,
        telegramUsername: channel.telegram_username ?? null,
        webhookUrl: channel.webhook_url,
        health,
      });

      setBotToken("");
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
  }, [botName, botToken, setConnection, showToast, validateToken]);

  return (
    <div className="relative overflow-hidden rounded-2xl border border-sky-500/20 bg-gradient-to-br from-sky-950/40 via-surface-raised to-surface shadow-node">
      {toast && (
        <div className="absolute right-4 top-4 z-10 flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300 shadow-glow">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          {toast}
        </div>
      )}

      <div className="absolute -right-8 -top-8 h-32 w-32 rounded-full bg-sky-500/10 blur-2xl" />

      <div className="border-b border-surface-border/80 p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-sky-500/15 ring-1 ring-sky-500/30">
              <Send className="h-7 w-7 text-sky-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-semibold text-zinc-100">Telegram</h2>
                {connection?.platformType === "TELEGRAM" && (
                  <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-400">
                    Connected
                  </span>
                )}
              </div>
              <p className="mt-1 text-sm text-zinc-400">
                Connect your BotFather token. We register the webhook and route
                messages through your published flow.
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="space-y-5 p-6">
        {connection?.platformType === "TELEGRAM" ? (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <InfoTile label="Bot name" value={connection.botName} />
              <InfoTile
                label="Telegram username"
                value={
                  connection.telegramUsername
                    ? `@${connection.telegramUsername}`
                    : "—"
                }
              />
              <InfoTile label="Platform bot ID" value={connection.botId} mono />
              <InfoTile
                label="Webhook"
                value={connection.webhookUrl ?? "—"}
                mono
                truncate
              />
            </div>

            {connection.health && (
              <div className="rounded-lg border border-surface-border bg-surface/50 p-3">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                  Deployment telemetry
                </p>
                <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                  <span className="text-zinc-500">Flow status</span>
                  <span
                    className={cn(
                      "font-medium",
                      connection.health.validation_status === "valid"
                        ? "text-emerald-400"
                        : connection.health.validation_status === "missing"
                          ? "text-amber-400"
                          : "text-red-400",
                    )}
                  >
                    {connection.health.validation_status}
                  </span>
                  <span className="text-zinc-500">Published nodes</span>
                  <span className="text-zinc-200">{connection.health.node_count}</span>
                  <span className="text-zinc-500">Channel</span>
                  <span className="text-zinc-200">
                    {connection.health.channel_connected ? "Connected" : "Not connected"}
                  </span>
                </div>
              </div>
            )}

            <div className="flex flex-wrap gap-3">
              <a
                href="https://t.me/BotFather"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 rounded-lg border border-surface-border px-3 py-2 text-sm text-zinc-300 hover:bg-surface-overlay"
              >
                <ExternalLink className="h-4 w-4" />
                Open BotFather
              </a>
              <button
                type="button"
                onClick={() => {
                  clearConnection();
                  setStatus("idle");
                  showToast("Telegram connection cleared.");
                }}
                className="rounded-lg border border-red-500/30 px-3 py-2 text-sm text-red-300 hover:bg-red-500/10"
              >
                Disconnect
              </button>
            </div>
          </div>
        ) : (
          <>
            <div>
              <label
                htmlFor="bot-name"
                className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-zinc-500"
              >
                Display name
              </label>
              <input
                id="bot-name"
                type="text"
                value={botName}
                onChange={(event) => setBotName(event.target.value)}
                className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500/40"
                placeholder="Support Bot"
              />
            </div>

            <div>
              <label
                htmlFor="bot-token"
                className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-zinc-500"
              >
                <ShieldCheck className="h-3.5 w-3.5" />
                Bot token
              </label>
              <input
                id="bot-token"
                type="password"
                value={botToken}
                onChange={(event) => {
                  setBotToken(event.target.value);
                  if (status === "error") {
                    setStatus("idle");
                    setErrorMessage(null);
                  }
                }}
                className={cn(
                  "w-full rounded-lg border bg-surface px-3 py-2.5 font-mono text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-1",
                  errorMessage
                    ? "border-red-500/50 focus:border-red-500 focus:ring-red-500/30"
                    : "border-surface-border focus:border-sky-500 focus:ring-sky-500/40",
                )}
                placeholder="123456789:AAH..."
                autoComplete="off"
              />
              <p className="mt-2 text-xs text-zinc-500">
                Create a bot via{" "}
                <a
                  href="https://t.me/BotFather"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sky-400 hover:underline"
                >
                  @BotFather
                </a>{" "}
                and paste the HTTP API token here.
              </p>
            </div>

            {errorMessage && (
              <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2.5 text-sm text-red-300">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                {errorMessage}
              </div>
            )}

            <button
              type="button"
              onClick={() => void handleConnect()}
              disabled={status === "loading"}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-sky-600 px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {status === "loading" ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Connecting & registering webhook…
                </>
              ) : (
                <>
                  <Bot className="h-4 w-4" />
                  Connect Telegram Bot
                </>
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

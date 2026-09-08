"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, Loader2, Plug, RefreshCw, Settings2, Unplug } from "lucide-react";

import { HubApiKeyConnectForm } from "@/components/integrations/hub/HubApiKeyConnectForm";
import { HubOAuthConnectForm } from "@/components/integrations/hub/HubOAuthConnectForm";
import { Button } from "@/components/ui/button";
import {
  connectHubProvider,
  disconnectHubConnection,
  fetchHubAuthorizeUrl,
  testHubConnection,
} from "@/lib/integrations/hubApi";
import { hubAccountLabel, mapHubCardState, type HubCardProvider } from "@/lib/integrations/hubCatalog";
import { openHubOAuthPopup } from "@/lib/integrations/hubOAuthPopup";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/store/useBotStore";
import type { HubCardState, HubConnection } from "@/types/integration-hub";

interface HubProviderCardProps {
  definition: HubCardProvider;
  connection?: HubConnection | null;
  botId: string;
  workspaceId: string | null;
  onChanged: () => Promise<void> | void;
}

const STATE_LABEL: Record<HubCardState, string> = {
  not_connected: "Не подключен",
  connecting: "Подключение…",
  connected: "Подключен",
  expired: "Истёк",
  error: "Ошибка",
};

export function HubProviderCard({
  definition,
  connection,
  botId,
  workspaceId,
  onChanged,
}: HubProviderCardProps) {
  const [panel, setPanel] = useState<"idle" | "connect" | "settings">("idle");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  /** OAuth popup cancel/network failure → card shows `error`, never stuck `connecting`. */
  const [oauthUiError, setOauthUiError] = useState(false);

  const uiState = mapHubCardState(
    connection?.status,
    busy && panel !== "settings",
    oauthUiError || Boolean(formError && !busy && panel === "idle" && connection?.status !== "connected"),
  );
  const needsOAuthField = definition.id === "amocrm";
  const account = useMemo(
    () =>
      hubAccountLabel({
        externalAccountId: connection?.externalAccountId,
        config: connection?.config,
        metadata: connection?.metadata,
      }),
    [connection],
  );
  const channels = connection?.metadata?.channels || connection?.config?.channels;
  const channelList = Array.isArray(channels) ? channels : [];

  const handleOAuth = async (extra: { subdomain?: string; domain?: string }): Promise<void> => {
    if (!workspaceId) {
      setFormError("Не выбран workspace.");
      setOauthUiError(true);
      return;
    }
    setBusy(true);
    setFormError(null);
    setOauthUiError(false);
    try {
      const authorizeUrl = await fetchHubAuthorizeUrl({
        provider: definition.id,
        workspaceId,
        agentId: botId,
        subdomain: extra.subdomain,
        domain: extra.domain,
      });
      const result = await openHubOAuthPopup(authorizeUrl);
      if (result.status === "cancelled") {
        setFormError(result.message || "Авторизация отменена.");
        setOauthUiError(true);
        return;
      }
      if (result.status !== "connected") {
        setFormError(result.message || "Не удалось подключить интеграцию.");
        setOauthUiError(true);
        return;
      }
      setOauthUiError(false);
      setPanel("idle");
      await onChanged();
    } catch (error) {
      setFormError(getApiErrorMessage(error, "Не удалось открыть авторизацию."));
      setOauthUiError(true);
    } finally {
      setBusy(false);
    }
  };

  const handleApiKey = async (payload: Record<string, string>): Promise<void> => {
    setBusy(true);
    setFormError(null);
    setOauthUiError(false);
    try {
      await testHubConnection(definition.id, payload);
      await connectHubProvider(definition.id, payload, botId);
      setPanel("idle");
      await onChanged();
    } catch (error) {
      setFormError(getApiErrorMessage(error, "Ключ не прошёл проверку."));
      setOauthUiError(true);
    } finally {
      setBusy(false);
    }
  };

  const handleDisconnect = async (): Promise<void> => {
    if (!connection?.id) return;
    setBusy(true);
    try {
      await disconnectHubConnection(connection.id);
      setPanel("idle");
      setOauthUiError(false);
      setFormError(null);
      await onChanged();
    } catch (error) {
      setFormError(getApiErrorMessage(error, "Не удалось отключить интеграцию."));
    } finally {
      setBusy(false);
    }
  };

  /** Expired → full OAuth / API-key / webhook flow again (never silent token refresh). */
  const startConnect = () => {
    setFormError(null);
    setOauthUiError(false);
    if (definition.auth === "oauth" && !needsOAuthField) {
      void handleOAuth({});
      return;
    }
    setPanel("connect");
  };

  return (
    <article
      className={cn(
        "group relative flex min-h-[240px] flex-col overflow-hidden rounded-2xl border p-5 transition duration-300",
        "border-zinc-800/80 bg-[#0b0b0d]/90 hover:border-zinc-700/80",
        uiState === "connected" && "border-emerald-500/25",
        uiState === "expired" && "border-amber-500/40",
        uiState === "error" && "border-rose-500/40",
      )}
      style={
        uiState === "connected"
          ? { boxShadow: `0 0 36px ${definition.brandColor}22` }
          : undefined
      }
    >
      <div
        className={cn(
          "pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b opacity-90",
          definition.brandGradient,
        )}
      />

      <div className="relative flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div
            className={cn(
              "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-black/35 text-sm font-bold ring-1",
              definition.accentRing,
            )}
            style={{ color: definition.brandColor }}
          >
            {definition.logo}
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold text-zinc-50">{definition.title}</h3>
            <span
              className={cn(
                "mt-1.5 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                uiState === "connected" && "bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/30",
                uiState === "connecting" && "bg-violet-500/10 text-violet-200 ring-1 ring-violet-500/30",
                uiState === "expired" && "bg-amber-500/10 text-amber-200 ring-1 ring-amber-500/30",
                uiState === "error" && "bg-rose-500/10 text-rose-200 ring-1 ring-rose-500/30",
                uiState === "not_connected" && "bg-zinc-800/80 text-zinc-500 ring-1 ring-zinc-700/60",
              )}
            >
              {uiState === "connecting" ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <span
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    uiState === "connected" && "bg-emerald-400",
                    uiState === "expired" && "bg-amber-400",
                    uiState === "error" && "bg-rose-400",
                    uiState === "not_connected" && "bg-zinc-500",
                  )}
                />
              )}
              {STATE_LABEL[uiState]}
            </span>
          </div>
        </div>

        {(uiState === "not_connected" || uiState === "error") && panel === "idle" ? (
          <Button
            size="sm"
            onClick={startConnect}
            disabled={busy}
            className="shrink-0 text-white"
            style={{ backgroundColor: `${definition.brandColor}cc` }}
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plug className="h-3.5 w-3.5" />}
            {uiState === "error" ? "Повторить" : "Подключить"}
          </Button>
        ) : null}
      </div>

      {uiState === "expired" ? (
        <div className="relative mt-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-3">
          <p className="flex items-start gap-2 text-sm text-amber-100">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            Сессия истекла. Агент не может вызывать API, пока вы не переподключите аккаунт.
          </p>
          {panel === "idle" ? (
            <Button
              size="sm"
              className="mt-3 bg-amber-500 text-zinc-950 hover:bg-amber-400"
              disabled={busy}
              onClick={startConnect}
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              Переподключить
            </Button>
          ) : null}
        </div>
      ) : null}

      {uiState === "error" && (connection?.lastError || formError) ? (
        <p className="relative mt-3 text-xs text-rose-300">{connection?.lastError || formError}</p>
      ) : null}

      {uiState === "connected" ? (
        <div className="relative mt-4 space-y-3">
          {account ? (
            <p className="truncate font-mono text-xs text-zinc-400">{account}</p>
          ) : null}
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500">Разрешения</p>
            <ul className="mt-1.5 flex flex-wrap gap-1.5">
              {definition.permissions.map((item) => (
                <li
                  key={item}
                  className="rounded-full bg-zinc-800/80 px-2 py-0.5 text-[11px] text-zinc-300 ring-1 ring-zinc-700/60"
                >
                  {item}
                </li>
              ))}
            </ul>
          </div>
          {channelList.length > 0 ? (
            <p className="text-[11px] text-zinc-500">
              Каналы:{" "}
              {channelList
                .map((row) => {
                  const item = row as { kind?: string; channel_id?: string };
                  return item.kind || item.channel_id;
                })
                .filter(Boolean)
                .join(", ")}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={() => setPanel(panel === "settings" ? "idle" : "settings")}>
              <Settings2 className="h-3.5 w-3.5" />
              Настроить
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void handleDisconnect()}>
              <Unplug className="h-3.5 w-3.5" />
              Отключить
            </Button>
          </div>
        </div>
      ) : (uiState === "not_connected" || uiState === "connecting") && panel === "idle" ? (
        <p className="relative mt-4 line-clamp-3 flex-1 text-sm leading-relaxed text-zinc-400">
          {definition.description}
        </p>
      ) : null}

      {panel === "connect" ? (
        definition.auth === "oauth" ? (
          <HubOAuthConnectForm
            provider={definition.id}
            hint={definition.oauthHint}
            submitting={busy}
            error={formError}
            onSubmit={handleOAuth}
            onCancel={() => setPanel("idle")}
          />
        ) : (
          <HubApiKeyConnectForm
            provider={definition.id}
            submitting={busy}
            error={formError}
            onSubmit={handleApiKey}
            onCancel={() => setPanel("idle")}
          />
        )
      ) : null}

      {panel === "settings" && uiState === "connected" ? (
        <div className="relative mt-4 rounded-xl border border-zinc-800 bg-black/30 p-3">
          <p className="text-xs text-zinc-400">
            {definition.auth === "oauth"
              ? "Чтобы сменить аккаунт, переподключите OAuth."
              : definition.auth === "webhook"
                ? "Можно заменить Incoming Webhook URL — он снова пройдёт проверку."
                : "Можно заменить ключ — он снова пройдёт testConnection()."}
          </p>
          {definition.auth === "oauth" ? (
            <Button size="sm" className="mt-3" onClick={startConnect} disabled={busy}>
              Переподключить
            </Button>
          ) : (
            <HubApiKeyConnectForm
              provider={definition.id}
              submitting={busy}
              error={formError}
              onSubmit={handleApiKey}
              onCancel={() => setPanel("idle")}
            />
          )}
        </div>
      ) : null}

      {formError && panel === "idle" && uiState !== "error" ? (
        <p className="relative mt-3 text-xs text-rose-300">{formError}</p>
      ) : null}
    </article>
  );
}

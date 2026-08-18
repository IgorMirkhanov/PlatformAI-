"use client";

import { useState } from "react";

import { ChannelActionButtons } from "@/components/channel-hub/ChannelActionButtons";
import { ChannelSetupPanel } from "@/components/channel-hub/ChannelSetupPanel";
import { useChannelHub } from "@/components/channel-hub/ChannelHubContext";
import { useToast } from "@/hooks/useToast";
import { connectHubChannel, disconnectHubChannel } from "@/lib/api";
import { getApiErrorMessage } from "@/store/useBotStore";

export default function ApiChannelPage() {
  const { botId, statuses, refreshStatuses } = useChannelHub();
  const status = statuses.api;
  const { showToast } = useToast();
  const [apiKey, setApiKey] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConnect = async () => {
    setIsPending(true);
    setError(null);
    try {
      const response = await connectHubChannel(botId, "api", {
        api_key: apiKey.trim() || undefined,
      });
      showToast(response.message || "API-канал подключён.", "success");
      setApiKey("");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось подключить API-канал.");
      setError(msg);
      showToast(msg, "error");
    } finally {
      setIsPending(false);
    }
  };

  const handleDisconnect = async () => {
    setIsPending(true);
    setError(null);
    try {
      const response = await disconnectHubChannel(botId, "api");
      showToast(response.message || "API-канал отключён.", "success");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось отключить API-канал.");
      setError(msg);
      showToast(msg, "error");
    } finally {
      setIsPending(false);
    }
  };

  return (
    <ChannelSetupPanel
      title="API"
      subtitle="HTTP-вход для CRM, сайта и приложений"
      accent="#6366F1"
      status={status}
      error={error}
      instructions={
        <>
          <p>1. Подключите канал — ключ будет в ответе (сохраните его).</p>
          <p>2. POST на webhook URL с заголовком X-Api-Key.</p>
          <p>3. Тело: {"{"} external_id, message_text, callback_url? {"}"}.</p>
        </>
      }
    >
      <label className="block text-xs font-medium text-zinc-400">
        API Key (оставьте пустым — сгенерируем)
        <input
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2.5 text-sm text-zinc-100"
          placeholder="optional-custom-key"
        />
      </label>
      {status.webhook_url ? (
        <p className="rounded-lg border border-zinc-800 bg-zinc-950/50 p-3 font-mono text-[11px] text-zinc-400">
          {status.webhook_url}
        </p>
      ) : null}
      <ChannelActionButtons
        connected={status.connected}
        isPending={isPending}
        onConnect={() => void handleConnect()}
        onDisconnect={() => void handleDisconnect()}
      />
    </ChannelSetupPanel>
  );
}


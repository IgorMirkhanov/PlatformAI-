"use client";

import { useState } from "react";

import { ChannelActionButtons } from "@/components/channel-hub/ChannelActionButtons";
import { ChannelSetupPanel } from "@/components/channel-hub/ChannelSetupPanel";
import { useChannelHub } from "@/components/channel-hub/ChannelHubContext";
import { useToast } from "@/hooks/useToast";
import { connectHubChannel, disconnectHubChannel } from "@/lib/api";
import { getApiErrorMessage } from "@/store/useBotStore";

export default function CallsChannelPage() {
  const { botId, statuses, refreshStatuses } = useChannelHub();
  const status = statuses.calls;
  const { showToast } = useToast();
  const [sipUri, setSipUri] = useState("");
  const [token, setToken] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConnect = async () => {
    if (!sipUri.trim() && !token.trim()) {
      setError("Укажите SIP URI или токен телефонии.");
      return;
    }
    setIsPending(true);
    setError(null);
    try {
      const response = await connectHubChannel(botId, "calls", {
        reference_id: sipUri.trim() || undefined,
        token: token.trim() || undefined,
        meta_data: { provider: "sip", sip_uri: sipUri.trim() },
      });
      showToast(response.message || "Канал звонков подключён.", "success");
      setToken("");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось подключить звонки.");
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
      const response = await disconnectHubChannel(botId, "calls");
      showToast(response.message || "Канал звонков отключён.", "success");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось отключить звонки.");
      setError(msg);
      showToast(msg, "error");
    } finally {
      setIsPending(false);
    }
  };

  return (
    <ChannelSetupPanel
      title="Звонки"
      subtitle="SIP / АТС → транскрипт → ИИ-агент"
      accent="#F59E0B"
      status={status}
      error={error}
      instructions={
        <>
          <p>1. Укажите SIP URI или токен провайдера телефонии.</p>
          <p>2. Настройте webhook АТС на URL из статуса подключения.</p>
          <p>3. Отправляйте transcript / DTMF в поле text — агент ответит в Redis.</p>
        </>
      }
    >
      <label className="block text-xs font-medium text-zinc-400">
        SIP URI
        <input
          value={sipUri}
          onChange={(e) => setSipUri(e.target.value)}
          className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2.5 text-sm text-zinc-100"
          placeholder="sip:agent@pbx.example.com"
        />
      </label>
      <label className="block text-xs font-medium text-zinc-400">
        Токен провайдера
        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2.5 text-sm text-zinc-100"
          placeholder="optional"
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


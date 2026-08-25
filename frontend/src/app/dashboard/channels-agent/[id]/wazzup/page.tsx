"use client";

import { useState } from "react";

import { ChannelActionButtons } from "@/components/channel-hub/ChannelActionButtons";
import { ChannelSetupPanel } from "@/components/channel-hub/ChannelSetupPanel";
import { useChannelHub } from "@/components/channel-hub/ChannelHubContext";
import { useToast } from "@/hooks/useToast";
import { connectHubChannel, disconnectHubChannel } from "@/lib/api";
import { validateHubWazzupForm } from "@/lib/channel-validation";
import { getApiErrorMessage } from "@/store/useBotStore";

export default function WazzupChannelPage() {
  const { botId, statuses, refreshStatuses } = useChannelHub();
  const status = statuses.wazzup;
  const { showToast } = useToast();
  const [apiKey, setApiKey] = useState("");
  const [referenceId, setReferenceId] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConnect = async () => {
    const validationError = validateHubWazzupForm({
      api_key: apiKey,
      channel_id: referenceId,
    });
    if (validationError) {
      setError(validationError);
      return;
    }

    setIsPending(true);
    setError(null);
    try {
      const response = await connectHubChannel(botId, "wazzup", {
        api_key: apiKey.trim(),
        reference_id: referenceId.trim(),
      });
      showToast(response.message || "Wazzup подключён.", "success");
      setApiKey("");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось подключить Wazzup.");
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
      const response = await disconnectHubChannel(botId, "wazzup");
      showToast(response.message || "Wazzup отключён.", "success");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось отключить Wazzup.");
      setError(msg);
      showToast(msg, "error");
    } finally {
      setIsPending(false);
    }
  };

  return (
    <ChannelSetupPanel
      title="Wazzup"
      subtitle="Агрегатор WhatsApp / Telegram / Instagram"
      accent="#7C3AED"
      status={status}
      error={error}
      instructions={
        <>
          <p>1. Войдите в кабинет Wazzup24.</p>
          <p>2. Создайте API-ключ в разделе интеграций.</p>
          <p>3. Укажите Channel ID из кабинета Wazzup.</p>
          <p>4. Пропишите webhook URL из статуса подключения в настройках Wazzup.</p>
        </>
      }
    >
      <label className="block text-xs font-medium text-zinc-400">
        API Key
        <input
          type="password"
          value={apiKey}
          disabled={isPending}
          onChange={(event) => {
            setApiKey(event.target.value);
            if (error) setError(null);
          }}
          className="mt-2 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/20 disabled:opacity-50"
        />
      </label>
      <label className="block text-xs font-medium text-zinc-400">
        Channel ID
        <input
          value={referenceId}
          disabled={isPending}
          onChange={(event) => setReferenceId(event.target.value)}
          className="mt-2 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/20 disabled:opacity-50"
        />
      </label>
      <ChannelActionButtons
        isPending={isPending}
        canConnect={!isPending}
        canDisconnect={status.connected}
        onConnect={() => void handleConnect()}
        onDisconnect={() => void handleDisconnect()}
        connectClassName="bg-violet-600 shadow-[0_0_24px_rgba(124,58,237,0.35)]"
      />
    </ChannelSetupPanel>
  );
}

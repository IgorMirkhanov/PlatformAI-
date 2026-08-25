"use client";

import { useState } from "react";

import { ChannelActionButtons } from "@/components/channel-hub/ChannelActionButtons";
import { ChannelSetupPanel } from "@/components/channel-hub/ChannelSetupPanel";
import { useChannelHub } from "@/components/channel-hub/ChannelHubContext";
import { useToast } from "@/hooks/useToast";
import { connectHubChannel, disconnectHubChannel } from "@/lib/api";
import { validateHubInstagramForm } from "@/lib/channel-validation";
import { getApiErrorMessage } from "@/store/useBotStore";

export default function InstagramChannelPage() {
  const { botId, statuses, refreshStatuses } = useChannelHub();
  const status = statuses.instagram;
  const { showToast } = useToast();
  const [instanceId, setInstanceId] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clearError = () => {
    if (error) setError(null);
  };

  const handleConnect = async () => {
    const validationError = validateHubInstagramForm({
      instance_id: instanceId,
      api_token: apiToken,
    });
    if (validationError) {
      setError(validationError);
      return;
    }

    setIsPending(true);
    setError(null);
    try {
      const response = await connectHubChannel(botId, "instagram", {
        reference_id: instanceId.trim(),
        api_key: apiToken.trim(),
        access_token: apiToken.trim(),
        token: apiToken.trim(),
      });
      showToast(response.message || "Instagram подключён.", "success");
      setApiToken("");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось подключить Instagram.");
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
      const response = await disconnectHubChannel(botId, "instagram");
      showToast(response.message || "Instagram отключён.", "success");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось отключить Instagram.");
      setError(msg);
      showToast(msg, "error");
    } finally {
      setIsPending(false);
    }
  };

  return (
    <ChannelSetupPanel
      title="Instagram"
      subtitle="Direct Messages через Green API"
      accent="#E4405F"
      status={status}
      error={error}
      instructions={
        <>
          <p>1. Создайте инстанс Instagram в кабинете Green API.</p>
          <p>2. Скопируйте Instance ID (idInstance) и API Token (apiTokenInstance).</p>
          <p>3. Укажите webhook URL из статуса подключения в настройках инстанса.</p>
        </>
      }
    >
      <label className="block text-xs font-medium text-zinc-400">
        Instance ID
        <input
          value={instanceId}
          disabled={isPending}
          onChange={(event) => {
            setInstanceId(event.target.value);
            clearError();
          }}
          className="mt-2 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-[#E4405F]/50 focus:ring-2 focus:ring-[#E4405F]/20 disabled:opacity-50"
        />
      </label>
      <label className="block text-xs font-medium text-zinc-400">
        API Token
        <input
          type="password"
          value={apiToken}
          disabled={isPending}
          onChange={(event) => {
            setApiToken(event.target.value);
            clearError();
          }}
          className="mt-2 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-[#E4405F]/50 focus:ring-2 focus:ring-[#E4405F]/20 disabled:opacity-50"
        />
      </label>
      <ChannelActionButtons
        isPending={isPending}
        canConnect={!isPending}
        canDisconnect={status.connected}
        onConnect={() => void handleConnect()}
        onDisconnect={() => void handleDisconnect()}
        connectClassName="bg-gradient-to-r from-[#F58529] via-[#E4405F] to-[#833AB4]"
      />
    </ChannelSetupPanel>
  );
}

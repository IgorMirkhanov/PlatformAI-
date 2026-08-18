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
  const [pageId, setPageId] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clearError = () => {
    if (error) setError(null);
  };

  const handleConnect = async () => {
    const validationError = validateHubInstagramForm({
      page_id: pageId,
      access_token: accessToken,
    });
    if (validationError) {
      setError(validationError);
      return;
    }

    setIsPending(true);
    setError(null);
    try {
      const response = await connectHubChannel(botId, "instagram", {
        page_id: pageId.trim(),
        access_token: accessToken.trim(),
      });
      showToast(response.message || "Instagram подключён.", "success");
      setPageId("");
      setAccessToken("");
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
      subtitle="Direct Messages через Meta Graph API"
      accent="#E4405F"
      status={status}
      error={error}
      instructions={
        <>
          <p>1. Создайте Meta App и подключите Instagram Graph API.</p>
          <p>2. Получите Page ID связанной Facebook Page.</p>
          <p>3. Выпустите Page Access Token с правами instagram_manage_messages.</p>
          <p>4. Укажите webhook URL из статуса подключения в Meta Developer Console.</p>
        </>
      }
    >
      <label className="block text-xs font-medium text-zinc-400">
        Instagram / Page ID
        <input
          value={pageId}
          disabled={isPending}
          onChange={(event) => {
            setPageId(event.target.value);
            clearError();
          }}
          className="mt-2 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-[#E4405F]/50 focus:ring-2 focus:ring-[#E4405F]/20 disabled:opacity-50"
        />
      </label>
      <label className="block text-xs font-medium text-zinc-400">
        Access Token
        <input
          type="password"
          value={accessToken}
          disabled={isPending}
          onChange={(event) => {
            setAccessToken(event.target.value);
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

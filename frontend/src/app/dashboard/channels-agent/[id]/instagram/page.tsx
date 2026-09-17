"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { ChannelActionButtons } from "@/components/channel-hub/ChannelActionButtons";
import { ChannelSetupPanel } from "@/components/channel-hub/ChannelSetupPanel";
import { useChannelHub } from "@/components/channel-hub/ChannelHubContext";
import { useToast } from "@/hooks/useToast";
import { disconnectHubChannel, startInstagramOAuth } from "@/lib/api";
import { rememberInstagramOAuthReturn } from "@/lib/integrations/hubOAuthPopup";
import { getApiErrorMessage } from "@/store/useBotStore";

export default function InstagramChannelPage() {
  const { botId, statuses, refreshStatuses } = useChannelHub();
  const status = statuses.instagram;
  const { showToast } = useToast();
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConnect = async () => {
    setIsPending(true);
    setError(null);
    try {
      const { authorize_url } = await startInstagramOAuth(botId);
      rememberInstagramOAuthReturn(botId);
      window.location.assign(authorize_url);
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось открыть вход Instagram.");
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
      subtitle="Direct Messages через вход в Instagram"
      accent="#E4405F"
      status={status}
      error={error}
      instructions={
        <>
          <p>1. Нажмите «Войти через Instagram» — откроется instagram.com.</p>
          <p>2. Войдите в бизнес-аккаунт и разрешите сообщения.</p>
          <p>3. После возврата канал появится как подключённый.</p>
        </>
      }
    >
      <button
        type="button"
        disabled={isPending}
        onClick={() => void handleConnect()}
        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-[#F58529] via-[#E4405F] to-[#833AB4] px-4 py-2.5 text-sm font-semibold text-white hover:opacity-95 disabled:opacity-50"
      >
        {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        Войти через Instagram
      </button>
      <ChannelActionButtons
        isPending={isPending}
        canConnect={false}
        canDisconnect={Boolean(status.connected)}
        onDisconnect={() => void handleDisconnect()}
      />
    </ChannelSetupPanel>
  );
}

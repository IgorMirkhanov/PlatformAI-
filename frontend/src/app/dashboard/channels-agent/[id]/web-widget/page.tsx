"use client";

import { useState } from "react";

import { ChannelActionButtons } from "@/components/channel-hub/ChannelActionButtons";
import { ChannelSetupPanel } from "@/components/channel-hub/ChannelSetupPanel";
import { useChannelHub } from "@/components/channel-hub/ChannelHubContext";
import { useToast } from "@/hooks/useToast";
import { connectHubChannel, disconnectHubChannel } from "@/lib/api";
import { getApiErrorMessage } from "@/store/useBotStore";

export default function WebWidgetChannelPage() {
  const { botId, statuses, refreshStatuses } = useChannelHub();
  const status = statuses.web_widget;
  const { showToast } = useToast();
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const embed =
    typeof status.meta_data?.embed_script === "string"
      ? status.meta_data.embed_script
      : `<script src="${typeof window !== "undefined" ? window.location.origin : ""}/widget.js?id=${botId}" async></script>`;

  const handleConnect = async () => {
    setIsPending(true);
    setError(null);
    try {
      const response = await connectHubChannel(botId, "web_widget", {});
      showToast(response.message || "Виджет подключён.", "success");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось подключить виджет.");
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
      const response = await disconnectHubChannel(botId, "web_widget");
      showToast(response.message || "Виджет отключён.", "success");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось отключить виджет.");
      setError(msg);
      showToast(msg, "error");
    } finally {
      setIsPending(false);
    }
  };

  return (
    <ChannelSetupPanel
      title="Чат для сайта"
      subtitle="Встраиваемый виджет MoonAI"
      accent="#8B5CF6"
      status={status}
      error={error}
      instructions={
        <>
          <p>1. Нажмите «Подключить» — сгенерируется embed-скрипт.</p>
          <p>2. Вставьте скрипт перед &lt;/body&gt; на сайте.</p>
          <p>3. Клиенты будут писать агенту прямо из браузера.</p>
        </>
      }
    >
      {status.connected ? (
        <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-3">
          <p className="mb-2 text-xs font-medium text-zinc-400">Embed script</p>
          <code className="block whitespace-pre-wrap break-all font-mono text-[11px] text-violet-200">
            {embed}
          </code>
        </div>
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


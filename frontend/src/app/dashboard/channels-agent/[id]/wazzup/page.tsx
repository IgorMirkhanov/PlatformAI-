"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { ChannelActionButtons } from "@/components/channel-hub/ChannelActionButtons";
import { ChannelSetupPanel } from "@/components/channel-hub/ChannelSetupPanel";
import { useChannelHub } from "@/components/channel-hub/ChannelHubContext";
import { useToast } from "@/hooks/useToast";
import {
  connectHubChannel,
  disconnectHubChannel,
  previewWazzupChannels,
  type WazzupPreviewChannel,
} from "@/lib/api";
import { validateHubWazzupForm } from "@/lib/channel-validation";
import { getApiErrorMessage } from "@/store/useBotStore";

export default function WazzupChannelPage() {
  const { botId, statuses, refreshStatuses } = useChannelHub();
  const status = statuses.wazzup;
  const { showToast } = useToast();
  const [apiKey, setApiKey] = useState("");
  const [referenceId, setReferenceId] = useState("");
  const [channels, setChannels] = useState<WazzupPreviewChannel[]>([]);
  const [loadingChannels, setLoadingChannels] = useState(false);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleLoadChannels = async () => {
    const validationError = validateHubWazzupForm({ api_key: apiKey });
    if (validationError) {
      setError(validationError);
      return;
    }
    setLoadingChannels(true);
    setError(null);
    try {
      const response = await previewWazzupChannels(botId, apiKey.trim());
      const next = response.channels ?? [];
      setChannels(next);
      if (next.length === 0) {
        setError("В аккаунте Wazzup нет каналов.");
        return;
      }
      const preferred =
        next.find((item) => String(item.state || "").toLowerCase() === "active") ?? next[0];
      if (preferred?.channel_id) setReferenceId(preferred.channel_id);
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось загрузить каналы Wazzup.");
      setError(msg);
      showToast(msg, "error");
    } finally {
      setLoadingChannels(false);
    }
  };

  const handleConnect = async () => {
    const validationError = validateHubWazzupForm({
      api_key: apiKey,
      channel_id: referenceId,
      require_channel_id: channels.length > 0,
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
        reference_id: referenceId.trim() || undefined,
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
          <p>1. Войдите в кабинет Wazzup24 и создайте API-ключ.</p>
          <p>2. Вставьте ключ ниже и нажмите «Загрузить каналы».</p>
          <p>3. Выберите канал из списка и нажмите «Подключить».</p>
          <p>4. Webhook зарегистрируется автоматически.</p>
        </>
      }
    >
      <label className="block text-xs font-medium text-zinc-400">
        API-ключ
        <input
          type="password"
          value={apiKey}
          disabled={isPending || loadingChannels}
          onChange={(event) => {
            setApiKey(event.target.value);
            if (error) setError(null);
          }}
          className="mt-2 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/20 disabled:opacity-50"
        />
      </label>
      <button
        type="button"
        disabled={isPending || loadingChannels}
        onClick={() => void handleLoadChannels()}
        className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-violet-500/30 bg-violet-500/10 px-4 py-2.5 text-sm font-medium text-violet-100 hover:bg-violet-500/15 disabled:opacity-50"
      >
        {loadingChannels ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        Загрузить каналы
      </button>
      {channels.length > 0 ? (
        <label className="block text-xs font-medium text-zinc-400">
          Канал
          <select
            value={referenceId}
            disabled={isPending}
            onChange={(event) => setReferenceId(event.target.value)}
            className="mt-2 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-violet-500/50 disabled:opacity-50"
          >
            {channels.map((item) => (
              <option key={item.channel_id} value={item.channel_id}>
                {[item.name || item.channel_id, item.kind || item.transport, item.state]
                  .filter(Boolean)
                  .join(" · ")}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <ChannelActionButtons
        connected={Boolean(status?.connected)}
        isPending={isPending}
        onConnect={() => void handleConnect()}
        onDisconnect={() => void handleDisconnect()}
      />
    </ChannelSetupPanel>
  );
}

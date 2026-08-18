"use client";

import { useState } from "react";

import { ChannelActionButtons } from "@/components/channel-hub/ChannelActionButtons";
import { ChannelSetupPanel } from "@/components/channel-hub/ChannelSetupPanel";
import { useChannelHub } from "@/components/channel-hub/ChannelHubContext";
import { useToast } from "@/hooks/useToast";
import { connectHubChannel, disconnectHubChannel } from "@/lib/api";
import { validateHubTelegramToken } from "@/lib/channel-validation";
import { getApiErrorMessage } from "@/store/useBotStore";

export default function TelegramChannelPage() {
  const { botId, statuses, refreshStatuses } = useChannelHub();
  const status = statuses.telegram;
  const { showToast } = useToast();
  const [token, setToken] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConnect = async () => {
    const validationError = validateHubTelegramToken(token);
    if (validationError) {
      setError(validationError);
      return;
    }

    setIsPending(true);
    setError(null);
    try {
      const response = await connectHubChannel(botId, "telegram", { token: token.trim() });
      showToast(response.message || "Telegram подключён.", "success");
      setToken("");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось подключить Telegram.");
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
      const response = await disconnectHubChannel(botId, "telegram");
      showToast(response.message || "Telegram отключён.", "success");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось отключить Telegram.");
      setError(msg);
      showToast(msg, "error");
    } finally {
      setIsPending(false);
    }
  };

  return (
    <ChannelSetupPanel
      title="Telegram"
      subtitle="Подключение официального бота через Bot API"
      accent="#229ED9"
      status={status}
      error={error}
      instructions={
        <>
          <p>1. Откройте @BotFather в Telegram.</p>
          <p>2. Отправьте /newbot и следуйте инструкциям.</p>
          <p>3. Скопируйте токен вида 123456:ABC-DEF…</p>
          <p>4. Вставьте токен ниже и нажмите «Подключить».</p>
          <p>Платформа автоматически зарегистрирует webhook на ваш публичный URL.</p>
        </>
      }
    >
      <label className="block text-xs font-medium text-zinc-400">
        Токен бота
        <input
          type="password"
          value={token}
          disabled={isPending}
          onChange={(event) => {
            setToken(event.target.value);
            if (error) setError(null);
          }}
          placeholder="123456789:AAH…"
          className="mt-2 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none transition focus:border-[#229ED9]/50 focus:ring-2 focus:ring-[#229ED9]/20 disabled:opacity-50"
        />
      </label>

      <ChannelActionButtons
        isPending={isPending}
        canConnect={!isPending}
        canDisconnect={status.connected}
        onConnect={() => void handleConnect()}
        onDisconnect={() => void handleDisconnect()}
        connectClassName="bg-[#229ED9] shadow-[0_0_24px_rgba(34,158,217,0.35)] hover:brightness-110"
      />
    </ChannelSetupPanel>
  );
}

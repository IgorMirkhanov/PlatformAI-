"use client";

import { useState } from "react";

import { ChannelActionButtons } from "@/components/channel-hub/ChannelActionButtons";
import { ChannelSetupPanel } from "@/components/channel-hub/ChannelSetupPanel";
import { useChannelHub } from "@/components/channel-hub/ChannelHubContext";
import { useToast } from "@/hooks/useToast";
import { connectHubChannel, disconnectHubChannel } from "@/lib/api";
import { validateHubTelegramToken } from "@/lib/channel-validation";
import { getApiErrorMessage } from "@/store/useBotStore";

export default function TelegramBusinessPage() {
  const { botId, statuses, refreshStatuses } = useChannelHub();
  const status = statuses.telegram_business;
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
      const response = await connectHubChannel(botId, "telegram_business", {
        token: token.trim(),
      });
      showToast(response.message || "Telegram Business подключён.", "success");
      setToken("");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось подключить Telegram Business.");
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
      const response = await disconnectHubChannel(botId, "telegram_business");
      showToast(response.message || "Канал отключён.", "success");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось отключить канал.");
      setError(msg);
      showToast(msg, "error");
    } finally {
      setIsPending(false);
    }
  };

  return (
    <ChannelSetupPanel
      title="Telegram Business"
      subtitle="Секретарь для личного Premium-аккаунта"
      accent="#5AC8FA"
      status={status}
      error={error}
      instructions={
        <>
          <p>1. Создайте бота через @BotFather.</p>
          <p>2. В Telegram Premium: Настройки → Telegram Business → Чат-боты.</p>
          <p>3. Добавьте бота как бизнес-ассистента.</p>
          <p>4. Вставьте токен и активируйте канал.</p>
        </>
      }
    >
      <label className="block text-xs font-medium text-zinc-400">
        Токен бизнес-бота
        <input
          type="password"
          value={token}
          disabled={isPending}
          onChange={(event) => {
            setToken(event.target.value);
            if (error) setError(null);
          }}
          placeholder="Токен от @BotFather"
          className="mt-2 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none transition focus:border-[#5AC8FA]/50 focus:ring-2 focus:ring-[#5AC8FA]/20 disabled:opacity-50"
        />
      </label>

      <ChannelActionButtons
        isPending={isPending}
        canConnect={!isPending}
        canDisconnect={status.connected}
        connectLabel="Активировать"
        onConnect={() => void handleConnect()}
        onDisconnect={() => void handleDisconnect()}
        connectClassName="bg-[#5AC8FA] text-zinc-950 hover:brightness-110"
      />
    </ChannelSetupPanel>
  );
}

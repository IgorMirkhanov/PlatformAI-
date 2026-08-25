"use client";

import { useState } from "react";

import { ChannelActionButtons } from "@/components/channel-hub/ChannelActionButtons";
import { ChannelSetupPanel } from "@/components/channel-hub/ChannelSetupPanel";
import { useChannelHub } from "@/components/channel-hub/ChannelHubContext";
import { useToast } from "@/hooks/useToast";
import { connectHubChannel, disconnectHubChannel } from "@/lib/api";
import { validateHubWabaForm } from "@/lib/channel-validation";
import { getApiErrorMessage } from "@/store/useBotStore";

export default function WabaChannelPage() {
  const { botId, statuses, refreshStatuses } = useChannelHub();
  const status = statuses.waba;
  const { showToast } = useToast();
  const [phoneNumberId, setPhoneNumberId] = useState("");
  const [businessAccountId, setBusinessAccountId] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [verifyToken, setVerifyToken] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clearError = () => {
    if (error) setError(null);
  };

  const handleConnect = async () => {
    const validationError = validateHubWabaForm({
      phone_number_id: phoneNumberId,
      business_account_id: businessAccountId,
      access_token: accessToken,
      verify_token: verifyToken,
    });
    if (validationError) {
      setError(validationError);
      return;
    }

    setIsPending(true);
    setError(null);
    try {
      const response = await connectHubChannel(botId, "waba", {
        phone_number_id: phoneNumberId.trim(),
        business_account_id: businessAccountId.trim() || undefined,
        access_token: accessToken.trim(),
        verify_token: verifyToken.trim() || undefined,
      });
      showToast(response.message || "WABA подключён.", "success");
      setAccessToken("");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось подключить WABA.");
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
      const response = await disconnectHubChannel(botId, "waba");
      showToast(response.message || "WABA отключён.", "success");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось отключить WABA.");
      setError(msg);
      showToast(msg, "error");
    } finally {
      setIsPending(false);
    }
  };

  return (
    <ChannelSetupPanel
      title="WABA"
      subtitle="Официальный WhatsApp Business API (Meta Cloud)"
      accent="#128C7E"
      status={status}
      error={error}
      instructions={
        <>
          <p>1. Создайте приложение в Meta for Developers.</p>
          <p>2. Добавьте продукт WhatsApp и получите Phone Number ID.</p>
          <p>3. Скопируйте постоянный Access Token. Business Account ID — по желанию.</p>
          <p>4. Укажите Verify Token и пропишите webhook URL в Meta Console.</p>
        </>
      }
    >
      <label className="block text-xs font-medium text-zinc-400">
        Phone Number ID
        <input
          value={phoneNumberId}
          disabled={isPending}
          onChange={(event) => {
            setPhoneNumberId(event.target.value);
            clearError();
          }}
          className="mt-2 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-emerald-500/40 focus:ring-2 focus:ring-emerald-500/20 disabled:opacity-50"
        />
      </label>
      <label className="block text-xs font-medium text-zinc-400">
        Business Account ID (опционально)
        <input
          value={businessAccountId}
          disabled={isPending}
          onChange={(event) => {
            setBusinessAccountId(event.target.value);
            clearError();
          }}
          className="mt-2 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-emerald-500/40 focus:ring-2 focus:ring-emerald-500/20 disabled:opacity-50"
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
          className="mt-2 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-emerald-500/40 focus:ring-2 focus:ring-emerald-500/20 disabled:opacity-50"
        />
      </label>
      <label className="block text-xs font-medium text-zinc-400">
        Verify Token
        <input
          value={verifyToken}
          disabled={isPending}
          onChange={(event) => {
            setVerifyToken(event.target.value);
            clearError();
          }}
          placeholder="Опционально — сгенерируем автоматически"
          className="mt-2 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-emerald-500/40 focus:ring-2 focus:ring-emerald-500/20 disabled:opacity-50"
        />
      </label>
      <ChannelActionButtons
        isPending={isPending}
        canConnect={!isPending}
        canDisconnect={status.connected}
        onConnect={() => void handleConnect()}
        onDisconnect={() => void handleDisconnect()}
        connectClassName="bg-[#128C7E] shadow-[0_0_24px_rgba(18,140,126,0.35)]"
      />
    </ChannelSetupPanel>
  );
}

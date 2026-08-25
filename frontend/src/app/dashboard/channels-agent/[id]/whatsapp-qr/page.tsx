"use client";

import { useCallback, useState } from "react";
import { QrCode } from "lucide-react";

import { ChannelActionButtons } from "@/components/channel-hub/ChannelActionButtons";
import { ChannelSetupPanel } from "@/components/channel-hub/ChannelSetupPanel";
import { useChannelHub } from "@/components/channel-hub/ChannelHubContext";
import { WhatsAppQrModal } from "@/components/channel-hub/WhatsAppQrModal";
import { useToast } from "@/hooks/useToast";
import { connectHubChannel, disconnectHubChannel } from "@/lib/api";
import { validateHubGreenApiForm } from "@/lib/channel-validation";
import { getApiErrorMessage } from "@/store/useBotStore";

export default function WhatsAppQrChannelPage() {
  const { botId, statuses, refreshStatuses } = useChannelHub();
  const status = statuses.whatsapp_qr;
  const { showToast } = useToast();
  const [modalOpen, setModalOpen] = useState(false);
  const [instanceId, setInstanceId] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGreenApiConnect = async () => {
    const validationError = validateHubGreenApiForm({
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
      const response = await connectHubChannel(botId, "whatsapp_qr", {
        reference_id: instanceId.trim(),
        api_key: apiToken.trim(),
        access_token: apiToken.trim(),
        token: apiToken.trim(),
      });
      showToast(response.message || "WhatsApp подключён через Green API.", "success");
      setApiToken("");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось подключить WhatsApp.");
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
      const response = await disconnectHubChannel(botId, "whatsapp_qr");
      showToast(response.message || "WhatsApp отключён.", "success");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось отключить WhatsApp.");
      setError(msg);
      showToast(msg, "error");
    } finally {
      setIsPending(false);
    }
  };

  const handleConnected = useCallback(() => {
    showToast("WhatsApp успешно подключён через QR.", "success");
    void refreshStatuses();
  }, [refreshStatuses, showToast]);

  return (
    <>
      <ChannelSetupPanel
        title="WhatsApp"
        subtitle="Green API (Instance ID + Token) или QR-сессия"
        accent="#25D366"
        status={status}
        error={error}
        instructions={
          <>
            <p>Рекомендуемый путь — Green API: Instance ID и API Token инстанса WhatsApp.</p>
            <p>Альтернатива: QR-код в WhatsApp → Связанные устройства.</p>
            <p>Пропишите webhook URL из статуса подключения в кабинете Green API.</p>
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
              if (error) setError(null);
            }}
            placeholder="1101xxxxxxxx"
            className="mt-2 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-emerald-500/40 focus:ring-2 focus:ring-emerald-500/20 disabled:opacity-50"
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
              if (error) setError(null);
            }}
            className="mt-2 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-emerald-500/40 focus:ring-2 focus:ring-emerald-500/20 disabled:opacity-50"
          />
        </label>
        <ChannelActionButtons
          isPending={isPending}
          canConnect={!isPending}
          canDisconnect={status.connected}
          onConnect={() => void handleGreenApiConnect()}
          onDisconnect={() => void handleDisconnect()}
          connectClassName="bg-[#25D366] text-zinc-950 shadow-[0_0_28px_rgba(37,211,102,0.35)] hover:brightness-110"
        />

        <div className="rounded-xl border border-emerald-500/20 bg-gradient-to-br from-[#25D366]/15 via-transparent to-transparent p-5">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#25D366]/15 ring-1 ring-[#25D366]/30">
              <QrCode className="h-5 w-5 text-[#25D366]" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-zinc-100">Или QR-код</h3>
              <p className="mt-1 text-sm text-zinc-500">
                Без токена Green API — отсканируйте код в WhatsApp на телефоне.
              </p>
            </div>
          </div>
          <ChannelActionButtons
            isPending={isPending}
            canDisconnect={false}
            connectLabel="Подключить через QR"
            onConnect={() => {
              setError(null);
              setModalOpen(true);
            }}
            connectClassName="bg-transparent border border-emerald-500/40 text-emerald-200 hover:bg-emerald-500/10"
          />
        </div>
      </ChannelSetupPanel>

      <WhatsAppQrModal
        open={modalOpen}
        botId={botId}
        onClose={() => setModalOpen(false)}
        onConnected={handleConnected}
      />
    </>
  );
}

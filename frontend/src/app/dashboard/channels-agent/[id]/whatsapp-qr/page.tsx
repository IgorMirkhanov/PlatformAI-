"use client";

import { useCallback, useState } from "react";
import { QrCode } from "lucide-react";

import { ChannelActionButtons } from "@/components/channel-hub/ChannelActionButtons";
import { ChannelSetupPanel } from "@/components/channel-hub/ChannelSetupPanel";
import { useChannelHub } from "@/components/channel-hub/ChannelHubContext";
import { WhatsAppQrModal } from "@/components/channel-hub/WhatsAppQrModal";
import { useToast } from "@/hooks/useToast";
import { disconnectHubChannel } from "@/lib/api";
import { getApiErrorMessage } from "@/store/useBotStore";

export default function WhatsAppQrChannelPage() {
  const { botId, statuses, refreshStatuses } = useChannelHub();
  const status = statuses.whatsapp_qr;
  const { showToast } = useToast();
  const [modalOpen, setModalOpen] = useState(false);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleDisconnect = async () => {
    setIsPending(true);
    setError(null);
    try {
      const response = await disconnectHubChannel(botId, "whatsapp_qr");
      showToast(response.message || "WhatsApp QR отключён.", "success");
      await refreshStatuses();
    } catch (err) {
      const msg = getApiErrorMessage(err, "Не удалось отключить WhatsApp QR.");
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
        title="WhatsApp QR"
        subtitle="Обычный WhatsApp через QR-сессию (Web pairing)"
        accent="#25D366"
        status={status}
        error={error}
        instructions={
          <>
            <p>Подходит для личного или небольшого бизнес-номера без официального WABA.</p>
            <p>1. Нажмите «Подключить через QR».</p>
            <p>2. Отсканируйте код в WhatsApp → Связанные устройства.</p>
            <p>3. Дождитесь статуса «Сессия подключена».</p>
            <p>Сессия Baileys хранится на сервере; закрытие модалки её не уничтожает.</p>
          </>
        }
      >
        <div className="rounded-xl border border-emerald-500/20 bg-gradient-to-br from-[#25D366]/15 via-transparent to-transparent p-5">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#25D366]/15 ring-1 ring-[#25D366]/30">
              <QrCode className="h-5 w-5 text-[#25D366]" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-zinc-100">Быстрое подключение</h3>
              <p className="mt-1 text-sm text-zinc-500">
                Без Cloud API токенов — достаточно отсканировать QR с телефона.
              </p>
            </div>
          </div>

          <ChannelActionButtons
            isPending={isPending}
            canDisconnect={status.connected}
            connectLabel="Подключить через QR"
            onConnect={() => {
              setError(null);
              setModalOpen(true);
            }}
            onDisconnect={() => void handleDisconnect()}
            connectClassName="bg-[#25D366] text-zinc-950 shadow-[0_0_28px_rgba(37,211,102,0.35)] hover:brightness-110"
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

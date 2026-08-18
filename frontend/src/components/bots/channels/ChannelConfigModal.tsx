"use client";

import { Loader2, X } from "lucide-react";

import { ChannelBrandIcon } from "@/components/bots/channels/ChannelBrandIcon";
import { InstagramChannelForm } from "@/components/bots/channels/forms/InstagramChannelForm";
import { TelegramChannelForm } from "@/components/bots/channels/forms/TelegramChannelForm";
import { VkontakteChannelForm } from "@/components/bots/channels/forms/VkontakteChannelForm";
import { WebWidgetChannelForm } from "@/components/bots/channels/forms/WebWidgetChannelForm";
import { WhatsAppChannelForm } from "@/components/bots/channels/forms/WhatsAppChannelForm";
import { ChannelStatusBadge } from "@/components/bots/channels/ChannelStatusBadge";
import type {
  ChannelDefinition,
  ChannelStatus,
  SetupChannelRequest,
} from "@/types/channels";

interface ChannelConfigModalProps {
  open: boolean;
  botId: string;
  definition: ChannelDefinition | null;
  status: ChannelStatus | null;
  saving: boolean;
  onClose: () => void;
  onSubmit: (payload: SetupChannelRequest) => Promise<void>;
}

export function ChannelConfigModal({
  open,
  botId,
  definition,
  status,
  saving,
  onClose,
  onSubmit,
}: ChannelConfigModalProps) {
  if (!open || !definition || !status) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/80 backdrop-blur-sm"
        onClick={onClose}
        aria-label="Закрыть"
      />

      <div className="moonai-modal relative flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden">
        <div className="mb-5 flex items-start justify-between gap-4 border-b border-zinc-800/80 pb-5">
          <div className="flex items-start gap-3">
            <div
              className="flex h-12 w-12 items-center justify-center rounded-xl bg-black/40 ring-1"
              style={{ boxShadow: `0 0 24px ${definition.brandColor}33` }}
            >
              <ChannelBrandIcon channelId={definition.id} className="h-7 w-7" />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-lg font-semibold text-zinc-50">{definition.title}</h3>
                <ChannelStatusBadge connected={status.connected} active={status.active} />
              </div>
              <p className="mt-1 text-xs text-zinc-500">{definition.description}</p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="relative flex-1 overflow-y-auto pr-1">
          {saving ? (
            <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-black/40 backdrop-blur-[1px]">
              <div className="flex items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-950/90 px-4 py-3 text-sm text-zinc-200">
                <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
                Сохранение и проверка канала…
              </div>
            </div>
          ) : null}

          {definition.id === "telegram" ? (
            <TelegramChannelForm
              botId={botId}
              status={status}
              saving={saving}
              onSubmit={onSubmit}
            />
          ) : null}

          {definition.id === "whatsapp" ? (
            <WhatsAppChannelForm status={status} saving={saving} onSubmit={onSubmit} />
          ) : null}

          {definition.id === "instagram" ? (
            <InstagramChannelForm status={status} saving={saving} onSubmit={onSubmit} />
          ) : null}

          {definition.id === "vkontakte" ? (
            <VkontakteChannelForm status={status} saving={saving} onSubmit={onSubmit} />
          ) : null}

          {definition.id === "web_widget" ? (
            <WebWidgetChannelForm
              botId={botId}
              status={status}
              saving={saving}
              onSubmit={onSubmit}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}

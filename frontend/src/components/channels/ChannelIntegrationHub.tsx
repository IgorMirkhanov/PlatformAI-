"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Radio } from "lucide-react";

import { ChannelIntegrationCard } from "@/components/channels/ChannelIntegrationCard";
import { InstagramChannelModal } from "@/components/channels/InstagramChannelModal";
import { TelegramChannelModal } from "@/components/channels/TelegramChannelModal";
import { VkontakteChannelModal } from "@/components/channels/VkontakteChannelModal";
import { WebWidgetModal } from "@/components/channels/WebWidgetModal";
import { WhatsAppChannelModal } from "@/components/channels/WhatsAppChannelModal";
import { useToast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import type { BotAgentProfile } from "@/types/agent";
import {
  OMNICHANNEL_DEFINITIONS,
  buildDefaultChannelMap,
  mergeChannelStatuses,
  type ChannelIntegrationType,
  type SetupChannelRequest,
} from "@/types/channels";

interface ChannelIntegrationHubProps {
  botId: string;
  profile: BotAgentProfile;
}

type ChannelFilter = "available" | "connected";

export function ChannelIntegrationHub({ botId, profile }: ChannelIntegrationHubProps) {
  const loadBotChannels = useBotStore((state) => state.loadBotChannels);
  const patchBotChannel = useBotStore((state) => state.patchBotChannel);
  const channelMap = useBotStore((state) => state.channelStatuses[botId]);
  const channelsLoading = useBotStore((state) => state.channelsLoading[botId] ?? false);
  const channelSaving = useBotStore((state) => state.channelSaving[botId] ?? false);
  const { showToast } = useToast();

  const [filter, setFilter] = useState<ChannelFilter>("available");
  const [activeChannelId, setActiveChannelId] = useState<ChannelIntegrationType | null>(null);

  useEffect(() => {
    void loadBotChannels(botId);
  }, [botId, loadBotChannels]);

  const statuses = useMemo(
    () => channelMap ?? mergeChannelStatuses([]),
    [channelMap],
  );

  const connectedCount = useMemo(
    () => OMNICHANNEL_DEFINITIONS.filter((item) => statuses[item.id]?.connected).length,
    [statuses],
  );

  const visibleDefinitions = useMemo(() => {
    if (filter === "connected") {
      return OMNICHANNEL_DEFINITIONS.filter((item) => statuses[item.id]?.connected);
    }
    return OMNICHANNEL_DEFINITIONS;
  }, [filter, statuses]);

  const activeDefinition = useMemo(
    () => OMNICHANNEL_DEFINITIONS.find((item) => item.id === activeChannelId) ?? null,
    [activeChannelId],
  );

  const activeStatus = activeChannelId ? statuses[activeChannelId] : null;

  const handleSubmit = useCallback(
    async (payload: SetupChannelRequest): Promise<void> => {
      if (!payload.channel_type) {
        showToast("Не указан тип канала.", "error");
        return;
      }

      const { channel_type, ...body } = payload;

      try {
        const response = await patchBotChannel(botId, channel_type, body);
        showToast(response.message, "success");
        setActiveChannelId(null);
      } catch (error) {
        showToast(getApiErrorMessage(error, "Не удалось настроить канал."), "error");
        throw error;
      }
    },
    [botId, patchBotChannel, showToast],
  );

  const modalProps = {
    saving: channelSaving,
    onClose: () => setActiveChannelId(null),
    onSubmit: handleSubmit,
  };

  return (
    <div className="space-y-6">
      <section className="moonai-panel overflow-hidden">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-violet-500/10 ring-1 ring-violet-500/25">
              <Radio className="h-5 w-5 text-violet-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-zinc-50">Omnichannel Integration Hub</h2>
              <p className="mt-1 max-w-2xl text-sm text-zinc-500">
                Подключите мессенджеры и web-виджет для агента{" "}
                <span className="text-zinc-300">{profile.name}</span>. Каждый канал синхронизируется
                через PATCH и мгновенно обновляет статус в шапке и боковой панели.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setFilter("available")}
              className={cn(
                "rounded-xl px-4 py-2 text-sm font-medium transition",
                filter === "available"
                  ? "bg-violet-600 text-white shadow-glow-purple"
                  : "border border-zinc-800 bg-[#121214] text-zinc-400 hover:text-zinc-200",
              )}
            >
              Доступные {OMNICHANNEL_DEFINITIONS.length}
            </button>
            <button
              type="button"
              onClick={() => setFilter("connected")}
              className={cn(
                "rounded-xl px-4 py-2 text-sm font-medium transition",
                filter === "connected"
                  ? "bg-emerald-600 text-white"
                  : "border border-zinc-800 bg-[#121214] text-zinc-400 hover:text-zinc-200",
              )}
            >
              Подключенные {connectedCount}
            </button>
          </div>
        </div>
      </section>

      {channelsLoading && !channelMap ? (
        <div className="flex min-h-[320px] items-center justify-center rounded-2xl border border-zinc-800/80 bg-[#0b0b0d]/70">
          <div className="flex items-center gap-2 text-sm text-zinc-400">
            <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
            Загрузка каналов для {profile.name}…
          </div>
        </div>
      ) : visibleDefinitions.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-zinc-800 px-6 py-12 text-center">
          <p className="text-sm text-zinc-400">Подключённых каналов пока нет.</p>
          <button
            type="button"
            onClick={() => setFilter("available")}
            className="mt-3 text-sm font-medium text-violet-300 hover:text-violet-200"
          >
            Показать доступные интеграции
          </button>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {visibleDefinitions.map((definition) => {
            const status = statuses[definition.id] ?? buildDefaultChannelMap()[definition.id];

            return (
              <ChannelIntegrationCard
                key={definition.id}
                botId={botId}
                definition={definition}
                status={status}
                onConfigure={() => setActiveChannelId(definition.id)}
              />
            );
          })}
        </div>
      )}

      <TelegramChannelModal
        botId={botId}
        open={activeChannelId === "telegram"}
        definition={activeChannelId === "telegram" ? activeDefinition : null}
        status={activeChannelId === "telegram" ? activeStatus : null}
        {...modalProps}
      />
      <WhatsAppChannelModal
        open={activeChannelId === "whatsapp"}
        definition={activeChannelId === "whatsapp" ? activeDefinition : null}
        status={activeChannelId === "whatsapp" ? activeStatus : null}
        {...modalProps}
      />
      <InstagramChannelModal
        open={activeChannelId === "instagram"}
        definition={activeChannelId === "instagram" ? activeDefinition : null}
        status={activeChannelId === "instagram" ? activeStatus : null}
        {...modalProps}
      />
      <VkontakteChannelModal
        open={activeChannelId === "vkontakte"}
        definition={activeChannelId === "vkontakte" ? activeDefinition : null}
        status={activeChannelId === "vkontakte" ? activeStatus : null}
        {...modalProps}
      />
      <WebWidgetModal
        botId={botId}
        open={activeChannelId === "web_widget"}
        definition={activeChannelId === "web_widget" ? activeDefinition : null}
        status={activeChannelId === "web_widget" ? activeStatus : null}
        {...modalProps}
      />
    </div>
  );
}

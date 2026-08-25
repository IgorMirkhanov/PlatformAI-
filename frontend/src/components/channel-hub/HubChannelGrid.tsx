"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Radio, Settings2 } from "lucide-react";

import { ChannelConfigModal } from "@/components/channel-hub/ChannelConfigModal";
import { Toggle } from "@/components/ui/Toggle";
import { useToast } from "@/hooks/useToast";
import { fetchHubChannels, patchHubChannelEnabled } from "@/lib/api";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/store/useBotStore";
import type { BotAgentProfile } from "@/types/agent";
import {
  HUB_CHANNEL_NAV,
  isHubChannelConnected,
  mergeHubStatuses,
  type HubChannelNavItem,
  type HubChannelStatusItem,
  type HubChannelType,
} from "@/types/channel-hub";

interface HubChannelGridProps {
  botId: string;
  profile: BotAgentProfile;
}

export function HubChannelGrid({ botId, profile }: HubChannelGridProps) {
  const { showToast } = useToast();
  const [statuses, setStatuses] = useState<Record<HubChannelType, HubChannelStatusItem> | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [busyChannel, setBusyChannel] = useState<HubChannelType | null>(null);
  const [configChannel, setConfigChannel] = useState<HubChannelNavItem | null>(null);

  const refresh = useCallback(
    async (opts?: { silent?: boolean }) => {
      if (!opts?.silent) {
        setLoading(true);
      }
      try {
        const response = await fetchHubChannels(botId);
        setStatuses(mergeHubStatuses(response.channels));
      } catch (error) {
        showToast(getApiErrorMessage(error, "Не удалось загрузить каналы."), "error");
        setStatuses(mergeHubStatuses([]));
      } finally {
        setLoading(false);
      }
    },
    [botId, showToast],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const connectedCount = useMemo(
    () => Object.values(statuses ?? {}).filter((item) => isHubChannelConnected(item)).length,
    [statuses],
  );

  const openConfig = (item: HubChannelNavItem): void => {
    setConfigChannel(item);
  };

  const closeConfig = (): void => {
    setConfigChannel(null);
    void refresh({ silent: true });
  };

  const handleToggle = async (item: HubChannelNavItem, enabled: boolean): Promise<void> => {
    const status = statuses?.[item.id];
    if (!isHubChannelConnected(status)) {
      openConfig(item);
      return;
    }

    setBusyChannel(item.id);
    try {
      await patchHubChannelEnabled(botId, item.id, enabled);
      showToast(enabled ? "Канал включён." : "Канал приостановлен.", "success");
      await refresh({ silent: true });
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось изменить статус канала."), "error");
    } finally {
      setBusyChannel(null);
    }
  };

  return (
    <div className="space-y-6">
      <section className="moonai-panel overflow-hidden">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-500/10 ring-1 ring-emerald-500/25">
              <Radio className="h-5 w-5 text-emerald-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-zinc-50">Каналы связи</h2>
              <p className="mt-1 max-w-2xl text-sm text-zinc-500">
                Omnichannel Hub для агента{" "}
                <span className="text-zinc-300">{profile.name}</span> — 9 транспортов в одной
                сетке.
              </p>
            </div>
          </div>
          <div className="rounded-2xl border border-zinc-800/80 bg-[#0b0b0d]/90 px-4 py-3 text-right">
            <p className="text-[10px] uppercase tracking-wider text-zinc-500">Подключено</p>
            <p className="mt-1 text-lg font-semibold text-zinc-100">
              {loading ? "…" : `${connectedCount} / ${HUB_CHANNEL_NAV.length}`}
            </p>
          </div>
        </div>
      </section>

      {loading && !statuses ? (
        <div className="flex min-h-[320px] items-center justify-center rounded-2xl border border-zinc-800/80 bg-[#0b0b0d]/70">
          <Loader2 className="h-5 w-5 animate-spin text-violet-400" />
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {HUB_CHANNEL_NAV.map((item) => {
            const status = statuses?.[item.id];
            const connected = isHubChannelConnected(status);
            const enabled = status?.meta_data?.enabled !== false;
            const busy = busyChannel === item.id;

            return (
              <article
                key={item.id}
                className={cn(
                  "relative flex min-h-[240px] flex-col overflow-hidden rounded-2xl border p-5 transition",
                  "border-zinc-800/80 bg-[#0b0b0d]/90 hover:border-zinc-700/80",
                  connected && enabled && "shadow-[0_0_36px_rgba(16,185,129,0.06)]",
                )}
                style={
                  connected && enabled
                    ? { borderColor: `${item.accent}33`, boxShadow: `0 0 32px ${item.accent}22` }
                    : undefined
                }
              >
                <div
                  className="pointer-events-none absolute inset-x-0 top-0 h-24 opacity-80"
                  style={{
                    background: `linear-gradient(180deg, ${item.accent}22 0%, transparent 100%)`,
                  }}
                />
                <div className="relative flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3">
                    <div
                      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-xs font-bold ring-1 ring-zinc-800"
                      style={{ color: item.accent, backgroundColor: `${item.accent}18` }}
                    >
                      {item.shortLabel}
                    </div>
                    <div>
                      <h3 className="text-base font-semibold text-zinc-50">{item.label}</h3>
                      <span
                        className={cn(
                          "mt-1 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
                          connected
                            ? "bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/30"
                            : "bg-zinc-800/80 text-zinc-500 ring-1 ring-zinc-700/60",
                        )}
                      >
                        {connected ? "Подключен" : "Не подключен"}
                      </span>
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => openConfig(item)}
                      className={cn(
                        "inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[11px] font-semibold disabled:opacity-50",
                        connected
                          ? "border border-zinc-700 bg-zinc-800 text-zinc-200 hover:bg-zinc-700"
                          : "bg-violet-600 text-white hover:bg-violet-500",
                      )}
                    >
                      {connected ? (
                        <>
                          <Settings2 className="h-3 w-3" />
                          Настройки
                        </>
                      ) : (
                        "Подключить"
                      )}
                    </button>
                    <Toggle
                      checked={connected && enabled}
                      disabled={busy}
                      onChange={(value) => void handleToggle(item, value)}
                      label=""
                      description=""
                    />
                  </div>
                </div>
                <p className="relative mt-4 flex-1 text-sm leading-relaxed text-zinc-400">
                  {item.description}
                </p>
              </article>
            );
          })}
        </div>
      )}

      <ChannelConfigModal
        open={Boolean(configChannel)}
        botId={botId}
        channel={configChannel}
        status={configChannel ? (statuses?.[configChannel.id] ?? null) : null}
        onClose={closeConfig}
        onSaved={() => void refresh({ silent: true })}
      />
    </div>
  );
}

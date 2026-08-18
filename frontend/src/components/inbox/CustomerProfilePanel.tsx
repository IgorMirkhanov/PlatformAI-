"use client";

import { useEffect, useState } from "react";
import { Bot, Loader2, Phone, Tag, User } from "lucide-react";

import { ChannelIndicator } from "@/components/inbox/ChannelIndicator";
import { CrmLinkageCardPanel } from "@/components/inbox/CrmLinkageCardPanel";
import {
  ApiError,
  createInboxCrmDeal,
  fetchClientInboxProfile,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useInboxStore } from "@/store/useInboxStore";
import { getClientDisplayName } from "@/types/inbox";

function TagChip({
  label,
  interactive = true,
}: {
  label: string;
  interactive?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-xs text-zinc-300",
        interactive && "transition hover:border-violet-500/40 hover:text-violet-200",
      )}
    >
      <Tag className="h-3 w-3" />
      {label}
    </span>
  );
}

export function CustomerProfilePanel() {
  const selectedClientId = useInboxStore((state) => state.selectedClientId);
  const chats = useInboxStore((state) => state.chats);
  const clientProfiles = useInboxStore((state) => state.clientProfiles);
  const setClientProfile = useInboxStore((state) => state.setClientProfile);

  const [loading, setLoading] = useState(false);
  const [crmLoading, setCrmLoading] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const selectedChat = chats.find((chat) => chat.client_id === selectedClientId);
  const profile = selectedClientId ? clientProfiles[selectedClientId] : undefined;

  useEffect(() => {
    if (!selectedClientId) {
      return;
    }

    let cancelled = false;

    const loadProfile = async (): Promise<void> => {
      setLoading(true);
      try {
        const nextProfile = await fetchClientInboxProfile(selectedClientId);
        if (!cancelled) {
          setClientProfile(nextProfile);
        }
      } catch {
        // profile panel falls back to chat summary data
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void loadProfile();

    return () => {
      cancelled = true;
    };
  }, [selectedClientId, setClientProfile]);

  if (!selectedClientId || !selectedChat) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center">
        <p className="text-sm text-zinc-500">Профиль клиента появится после выбора диалога</p>
      </div>
    );
  }

  const displayName = profile?.display_name ?? getClientDisplayName(selectedChat);
  const phone = profile?.phone ?? selectedChat.phone;
  const username = profile?.username ?? selectedChat.username;
  const tags = profile?.tags ?? selectedChat.tags;
  const crm = profile?.crm ?? { amocrm: null, bitrix24: null };

  const handleCreateDeal = async (): Promise<void> => {
    setCrmLoading(true);
    setFeedback(null);
    try {
      const response = await createInboxCrmDeal(selectedClientId);
      setFeedback(response.message);
      if (response.success) {
        const refreshed = await fetchClientInboxProfile(selectedClientId);
        setClientProfile(refreshed);
      }
    } catch (error) {
      setFeedback(error instanceof ApiError ? error.message : "Ошибка CRM.");
    } finally {
      setCrmLoading(false);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-zinc-950/40 p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Профиль клиента
          </p>
          <h3 className="mt-1 text-lg font-semibold text-zinc-100">{displayName}</h3>
        </div>
        {loading ? <Loader2 className="h-4 w-4 animate-spin text-zinc-500" /> : null}
      </div>

      <div className="mt-5 space-y-4">
        <div className="rounded-2xl border border-zinc-800 bg-zinc-950/70 p-4">
          <dl className="space-y-3 text-sm">
            <div className="flex items-start gap-3">
              <User className="mt-0.5 h-4 w-4 text-zinc-500" />
              <div>
                <dt className="text-[10px] uppercase tracking-wider text-zinc-500">Имя</dt>
                <dd className="mt-0.5 text-zinc-200">{displayName}</dd>
              </div>
            </div>

            <div className="flex items-start gap-3">
              <Phone className="mt-0.5 h-4 w-4 text-zinc-500" />
              <div>
                <dt className="text-[10px] uppercase tracking-wider text-zinc-500">Телефон</dt>
                <dd className="mt-0.5 text-zinc-200">{phone || "—"}</dd>
              </div>
            </div>

            <div>
              <dt className="text-[10px] uppercase tracking-wider text-zinc-500">
                Username / ID
              </dt>
              <dd className="mt-0.5 font-mono text-xs text-zinc-300">
                {username ? `@${username.replace(/^@/, "")}` : selectedChat.external_id}
              </dd>
            </div>

            <div>
              <dt className="text-[10px] uppercase tracking-wider text-zinc-500">Канал</dt>
              <dd className="mt-1">
                <ChannelIndicator platform={selectedChat.platform_type} showLabel size="md" />
              </dd>
            </div>
          </dl>
        </div>

        <div className="rounded-2xl border border-zinc-800 bg-zinc-950/70 p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Системные теги
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {tags.length > 0 ? (
              tags.map((tag) => <TagChip key={tag} label={tag} />)
            ) : (
              <p className="text-xs text-zinc-500">Теги не назначены</p>
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-zinc-800 bg-zinc-950/70 p-4">
          <div className="flex items-center gap-2">
            <Bot className="h-4 w-4 text-violet-400" />
            <p className="text-sm font-medium text-zinc-100">Активный агент</p>
          </div>
          <p className="mt-2 text-sm text-zinc-300">{selectedChat.bot_name}</p>
          <p className="mt-1 text-xs text-zinc-500">{selectedChat.state_label}</p>
        </div>

        <CrmLinkageCardPanel
          crm={crm}
          creating={crmLoading}
          onCreateDeal={() => void handleCreateDeal()}
        />

        {feedback ? (
          <p className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-xs text-zinc-400">
            {feedback}
          </p>
        ) : null}
      </div>
    </div>
  );
}

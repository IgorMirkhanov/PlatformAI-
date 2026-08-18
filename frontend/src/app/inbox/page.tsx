"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Inbox, RefreshCw, Wifi, WifiOff } from "lucide-react";

import { ConversationPanel } from "@/components/inbox/ConversationPanel";
import { CustomerProfilePanel } from "@/components/inbox/CustomerProfilePanel";
import { DialogListPanel } from "@/components/inbox/DialogListPanel";
import { useOperatorWebSocket } from "@/hooks/useOperatorWebSocket";
import { fetchActiveChats, fetchClientMessages } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useInboxStore } from "@/store/useInboxStore";

function InboxPageInner() {
  const { connected } = useOperatorWebSocket();
  const searchParams = useSearchParams();
  const deepLinkClientId = searchParams.get("clientId");

  const setChats = useInboxStore((state) => state.setChats);
  const setMessages = useInboxStore((state) => state.setMessages);
  const selectedClientId = useInboxStore((state) => state.selectedClientId);
  const selectClient = useInboxStore((state) => state.selectClient);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadInbox = useCallback(async (): Promise<void> => {
    setRefreshing(true);
    try {
      const response = await fetchActiveChats();
      setChats(response.chats);
      if (deepLinkClientId) {
        selectClient(deepLinkClientId);
      } else if (response.chats.length > 0 && !selectedClientId) {
        selectClient(response.chats[0].client_id);
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [deepLinkClientId, selectedClientId, selectClient, setChats]);

  useEffect(() => {
    void loadInbox();
  }, [loadInbox]);

  useEffect(() => {
    if (deepLinkClientId) {
      selectClient(deepLinkClientId);
    }
  }, [deepLinkClientId, selectClient]);

  useEffect(() => {
    if (!selectedClientId) {
      return;
    }

    const loadThread = async (): Promise<void> => {
      const thread = await fetchClientMessages(selectedClientId);
      setMessages(selectedClientId, thread);
    };

    void loadThread();
  }, [selectedClientId, setMessages]);

  return (
    <div className="flex h-[calc(100vh-0px)] flex-col bg-zinc-950 lg:h-screen">
      <header className="flex shrink-0 items-center justify-between border-b border-zinc-800 bg-zinc-950/90 px-5 py-4 backdrop-blur">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-violet-500/20 bg-violet-500/10">
            <Inbox className="h-5 w-5 text-violet-300" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-zinc-100">Live Inbox</h1>
            <p className="text-xs text-zinc-500">
              Панель оператора — мониторинг и перехват диалогов в реальном времени
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span
            className={cn(
              "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
              connected
                ? "bg-emerald-500/10 text-emerald-400 ring-1 ring-emerald-500/20"
                : "bg-red-500/10 text-red-400 ring-1 ring-red-500/20",
            )}
          >
            {connected ? (
              <Wifi className="h-3.5 w-3.5" />
            ) : (
              <WifiOff className="h-3.5 w-3.5" />
            )}
            {connected ? "Live · Redis Pub/Sub" : "Переподключение…"}
          </span>

          <button
            type="button"
            onClick={() => void loadInbox()}
            disabled={refreshing}
            className="flex items-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-900/70 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-zinc-700 hover:text-zinc-100 disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
            Обновить
          </button>
        </div>
      </header>

      {loading ? (
        <div className="flex flex-1 items-center justify-center">
          <p className="text-sm text-zinc-500">Загрузка диалогов…</p>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 xl:grid-cols-[320px_minmax(0,1fr)_320px]">
          <aside className="hidden min-h-0 border-r border-zinc-800 xl:block">
            <DialogListPanel />
          </aside>

          <main className="min-h-0 border-r border-zinc-800">
            <ConversationPanel />
          </main>

          <aside className="hidden min-h-0 xl:block">
            <CustomerProfilePanel />
          </aside>
        </div>
      )}

      <div className="border-t border-zinc-800 xl:hidden">
        <DialogListPanel />
      </div>
    </div>
  );
}

export default function InboxPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-screen items-center justify-center text-sm text-zinc-500">
          Загрузка inbox…
        </div>
      }
    >
      <InboxPageInner />
    </Suspense>
  );
}

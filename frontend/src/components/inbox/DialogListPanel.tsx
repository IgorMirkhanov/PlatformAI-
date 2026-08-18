"use client";

import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Search, User } from "lucide-react";

import { ChannelIndicator } from "@/components/inbox/ChannelIndicator";
import { useOperatorWebSocket } from "@/hooks/useOperatorWebSocket";
import { cn } from "@/lib/utils";
import { useInboxStore } from "@/store/useInboxStore";
import {
  filterInboxChats,
  formatRelativeTimestamp,
  getClientDisplayName,
  INBOX_FILTER_TABS,
  type ActiveChatSummary,
  type InboxFilterTab,
} from "@/types/inbox";

function DialogListItem({
  chat,
  selected,
  unread,
  onSelect,
}: {
  chat: ActiveChatSummary;
  selected: boolean;
  unread: number;
  onSelect: () => void;
}) {
  const displayName = getClientDisplayName(chat);

  return (
    <motion.li
      layout
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -8 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
    >
      <button
        type="button"
        onClick={onSelect}
        className={cn(
          "flex w-full gap-3 px-4 py-3 text-left transition-colors",
          selected
            ? "bg-violet-500/10 ring-1 ring-inset ring-violet-500/20"
            : "hover:bg-zinc-900/70",
        )}
      >
        <div className="relative shrink-0">
          <div className="flex h-11 w-11 items-center justify-center rounded-full border border-zinc-800 bg-zinc-900 text-zinc-300">
            <User className="h-5 w-5" />
          </div>
          <span className="absolute -bottom-0.5 -right-0.5">
            <ChannelIndicator platform={chat.platform_type} />
          </span>
          {unread > 0 ? (
            <motion.span
              key={unread}
              initial={{ scale: 0.7, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-violet-600 px-1 text-[10px] font-bold text-white shadow-glow-purple"
            >
              {unread > 99 ? "99+" : unread}
            </motion.span>
          ) : null}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <p className="truncate text-sm font-medium text-zinc-100">{displayName}</p>
            <span className="shrink-0 text-[10px] text-zinc-500">
              {formatRelativeTimestamp(chat.last_message_at)}
            </span>
          </div>

          <p className="mt-0.5 truncate text-xs text-zinc-500">
            {chat.last_message_text || "Нет сообщений"}
          </p>

          <div className="mt-2 flex items-center gap-2">
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-[10px] font-medium",
                chat.is_paused_by_operator
                  ? "bg-amber-500/10 text-amber-300"
                  : "bg-emerald-500/10 text-emerald-300",
              )}
            >
              {chat.is_paused_by_operator ? "Оператор" : "ИИ-бот"}
            </span>
            {chat.is_closed ? (
              <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-[10px] text-zinc-400">
                Закрыт
              </span>
            ) : null}
          </div>
        </div>
      </button>
    </motion.li>
  );
}

export function DialogListPanel() {
  // Shared singleton WS — unread pills + snippet updates stream into Zustand.
  useOperatorWebSocket();

  const chats = useInboxStore((state) => state.chats);
  const selectedClientId = useInboxStore((state) => state.selectedClientId);
  const selectClient = useInboxStore((state) => state.selectClient);
  const unreadByClient = useInboxStore((state) => state.unreadByClient);

  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<InboxFilterTab>("all");

  const filteredChats = useMemo(
    () => filterInboxChats(chats, activeTab, searchQuery),
    [activeTab, chats, searchQuery],
  );

  return (
    <div className="flex h-full flex-col bg-zinc-950/40">
      <div className="space-y-3 border-b border-zinc-800 p-4">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Поиск по диалогам…"
            className="h-10 w-full rounded-xl border border-zinc-800 bg-zinc-900/80 pl-10 pr-3 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500/40 focus:outline-none focus:ring-2 focus:ring-violet-500/15"
          />
        </div>

        <div className="flex flex-wrap gap-1.5">
          {INBOX_FILTER_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "rounded-lg px-2.5 py-1.5 text-xs font-medium transition",
                activeTab === tab.id
                  ? "bg-violet-600/20 text-violet-200 ring-1 ring-violet-500/30"
                  : "text-zinc-500 hover:bg-zinc-900 hover:text-zinc-300",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {filteredChats.length === 0 ? (
        <div className="flex flex-1 items-center justify-center p-6 text-center">
          <p className="text-sm text-zinc-500">Диалоги не найдены</p>
        </div>
      ) : (
        <ul className="flex-1 divide-y divide-zinc-900 overflow-y-auto">
          <AnimatePresence initial={false}>
            {filteredChats.map((chat) => (
              <DialogListItem
                key={chat.client_id}
                chat={chat}
                selected={selectedClientId === chat.client_id}
                unread={unreadByClient[chat.client_id] ?? chat.unread_count}
                onSelect={() => selectClient(chat.client_id)}
              />
            ))}
          </AnimatePresence>
        </ul>
      )}
    </div>
  );
}

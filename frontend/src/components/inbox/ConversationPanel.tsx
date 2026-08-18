"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Bot, Loader2, User } from "lucide-react";

import { ChannelIndicator, getPlatformLabel } from "@/components/inbox/ChannelIndicator";
import { MessageBubble } from "@/components/inbox/MessageBubble";
import { MessageComposer } from "@/components/inbox/MessageComposer";
import { useOperatorWebSocket } from "@/hooks/useOperatorWebSocket";
import { ApiError, interceptChatSession, sendManualMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useInboxStore } from "@/store/useInboxStore";
import { getClientDisplayName } from "@/types/inbox";

export function ConversationPanel() {
  // Shared singleton WS feed — keeps intercept button in sync via OPERATOR_INTERCEPT.
  useOperatorWebSocket();

  const selectedClientId = useInboxStore((state) => state.selectedClientId);
  const messages = useInboxStore((state) => state.messages);
  const appendMessage = useInboxStore((state) => state.appendMessage);
  const chats = useInboxStore((state) => state.chats);
  const updateClientPauseState = useInboxStore((state) => state.updateClientPauseState);

  const [interceptLoading, setInterceptLoading] = useState(false);
  const [interceptFeedback, setInterceptFeedback] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const selectedChat = chats.find((chat) => chat.client_id === selectedClientId);
  const thread = selectedClientId ? messages[selectedClientId] ?? [] : [];

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [thread, selectedClientId]);

  const handleInterceptToggle = async (): Promise<void> => {
    if (!selectedClientId || !selectedChat) {
      return;
    }

    setInterceptLoading(true);
    setInterceptFeedback(null);

    try {
      const action = selectedChat.is_paused_by_operator ? "release" : "intercept";
      const response = await interceptChatSession(selectedClientId, action);
      updateClientPauseState(
        selectedClientId,
        response.is_paused_by_operator,
        response.state_label,
      );
      setInterceptFeedback(response.message);
    } catch (error) {
      setInterceptFeedback(
        error instanceof ApiError ? error.message : "Не удалось изменить режим диалога.",
      );
    } finally {
      setInterceptLoading(false);
    }
  };

  const handleSend = async (text: string): Promise<void> => {
    if (!selectedClientId) {
      return;
    }

    setSending(true);
    try {
      const sent = await sendManualMessage(selectedClientId, text);
      appendMessage(selectedClientId, sent);
    } finally {
      setSending(false);
    }
  };

  if (!selectedClientId || !selectedChat) {
    return (
      <div className="flex h-full flex-col items-center justify-center bg-zinc-950/20 text-center">
        <div className="rounded-2xl border border-zinc-800 bg-zinc-950/70 px-8 py-10">
          <Bot className="mx-auto h-8 w-8 text-zinc-600" />
          <p className="mt-3 text-sm text-zinc-400">
            Выберите диалог слева, чтобы открыть окно переписки
          </p>
        </div>
      </div>
    );
  }

  const displayName = getClientDisplayName(selectedChat);
  const manualControl = selectedChat.is_paused_by_operator;

  return (
    <div className="flex h-full flex-col bg-zinc-950/20">
      <div className="flex items-center justify-between gap-4 border-b border-zinc-800 bg-zinc-950/60 px-5 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-zinc-800 bg-zinc-900 text-zinc-300">
            <User className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-zinc-100">{displayName}</p>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <ChannelIndicator platform={selectedChat.platform_type} showLabel />
              <span className="text-xs text-zinc-500">
                {getPlatformLabel(selectedChat.platform_type)} · {selectedChat.state_label}
              </span>
            </div>
          </div>
        </div>

        <button
          type="button"
          onClick={() => void handleInterceptToggle()}
          disabled={interceptLoading}
          className={cn(
            "inline-flex shrink-0 items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white shadow-glow-purple transition disabled:opacity-50",
            manualControl
              ? "bg-zinc-800 hover:bg-zinc-700"
              : "bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-500 hover:to-purple-500",
          )}
        >
          {interceptLoading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : manualControl ? (
            <>🤖 Вернуть боту</>
          ) : (
            <>🛑 Перехватить диалог</>
          )}
        </button>
      </div>

      {interceptFeedback ? (
        <div className="border-b border-zinc-800 bg-violet-500/5 px-5 py-2 text-xs text-violet-200">
          {interceptFeedback}
        </div>
      ) : null}

      <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-5">
        {thread.length === 0 ? (
          <p className="text-center text-sm text-zinc-500">Сообщений пока нет</p>
        ) : (
          <AnimatePresence initial={false}>
            {thread.map((message) => (
              <motion.div
                key={message.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.16, ease: "easeOut" }}
              >
                <MessageBubble message={message} />
              </motion.div>
            ))}
          </AnimatePresence>
        )}
      </div>

      <MessageComposer
        disabled={!manualControl}
        sending={sending}
        onSend={handleSend}
      />

      {!manualControl ? (
        <p className="border-t border-zinc-900 px-5 py-2 text-center text-[11px] text-zinc-600">
          Перехватите диалог, чтобы отправлять сообщения от имени оператора
        </p>
      ) : null}
    </div>
  );
}

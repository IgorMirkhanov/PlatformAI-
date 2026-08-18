"use client";

import { Check, CheckCheck } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  formatBubbleTimestamp,
  getMessageDeliveryStatus,
  type ChatMessage,
} from "@/types/inbox";

interface MessageBubbleProps {
  message: ChatMessage;
}

function DeliveryStatusIcon({ message }: { message: ChatMessage }) {
  if (message.sender === "CLIENT") {
    return null;
  }

  const status = getMessageDeliveryStatus(message);

  if (status === "read") {
    return <CheckCheck className="h-3.5 w-3.5 text-violet-300" aria-label="Прочитано" />;
  }

  if (status === "delivered") {
    return <CheckCheck className="h-3.5 w-3.5 text-zinc-400" aria-label="Доставлено" />;
  }

  return <Check className="h-3.5 w-3.5 text-zinc-500" aria-label="Отправлено" />;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isClient = message.sender === "CLIENT";
  const isBot = message.sender === "BOT";
  const isOperator = message.sender === "OPERATOR";

  return (
    <div
      className={cn(
        "flex w-full",
        isOperator ? "justify-end" : "justify-start",
      )}
    >
      <div
        className={cn(
          "max-w-[min(78%,520px)] rounded-2xl px-4 py-3 text-sm shadow-sm",
          isClient &&
            "rounded-bl-md border border-zinc-800 bg-zinc-900/90 text-zinc-100",
          isBot &&
            "rounded-bl-md border border-violet-500/30 bg-violet-950/30 text-violet-50",
          isOperator &&
            "rounded-br-md bg-gradient-to-br from-violet-600 to-purple-700 text-white shadow-glow-purple",
        )}
      >
        <div className="mb-1 flex items-center gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-wider opacity-70">
            {isClient ? "Клиент" : isBot ? "ИИ-бот" : "Оператор"}
          </span>
          {Boolean(message.payload.ai_generated) && (
            <span className="rounded bg-white/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide">
              AI
            </span>
          )}
        </div>

        <p className="whitespace-pre-wrap leading-relaxed">{message.message_text}</p>

        <div className="mt-2 flex items-center justify-end gap-1.5 text-[10px] opacity-70">
          <span>{formatBubbleTimestamp(message.created_at)}</span>
          <DeliveryStatusIcon message={message} />
        </div>
      </div>
    </div>
  );
}

"use client";

import { Check, CheckCheck, FileText } from "lucide-react";

import { buildApiUrl } from "@/lib/api/baseUrl";
import { cn } from "@/lib/utils";
import {
  formatBubbleTimestamp,
  getMessageDeliveryStatus,
  type ChatMessage,
} from "@/types/inbox";

interface MessageBubbleProps {
  message: ChatMessage;
}

type MediaAttachmentPayload = {
  url?: string;
  media_type?: string;
  filename?: string | null;
  caption?: string | null;
};

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

function resolveMediaUrl(url: string): string {
  if (url.startsWith("http://") || url.startsWith("https://")) {
    return url;
  }
  if (url.startsWith("/")) {
    return buildApiUrl(url);
  }
  return url;
}

function getMediaAttachments(message: ChatMessage): MediaAttachmentPayload[] {
  const raw = message.payload.media_attachments;
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.filter(
    (item): item is MediaAttachmentPayload =>
      Boolean(item) && typeof item === "object" && typeof (item as MediaAttachmentPayload).url === "string",
  );
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isClient = message.sender === "CLIENT";
  const isBot = message.sender === "BOT";
  const isOperator = message.sender === "OPERATOR";
  const media = getMediaAttachments(message);
  const text = (message.message_text || "").trim();

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

        {media.length > 0 ? (
          <div className="mb-2 space-y-2">
            {media.map((item, index) => {
              const url = resolveMediaUrl(String(item.url));
              const isImage = (item.media_type || "").toLowerCase() === "image";
              if (isImage) {
                return (
                  <a
                    key={`${url}-${index}`}
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                    className="block overflow-hidden rounded-xl border border-white/10"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={url}
                      alt={item.caption || item.filename || "Вложение"}
                      className="max-h-72 w-full object-cover"
                      loading="lazy"
                    />
                  </a>
                );
              }
              return (
                <a
                  key={`${url}-${index}`}
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-xs hover:bg-black/30"
                >
                  <FileText className="h-4 w-4 shrink-0 opacity-80" />
                  <span className="min-w-0 truncate">{item.filename || url}</span>
                </a>
              );
            })}
          </div>
        ) : null}

        {text ? <p className="whitespace-pre-wrap leading-relaxed">{text}</p> : null}
        {!text && media.length === 0 ? (
          <p className="whitespace-pre-wrap leading-relaxed opacity-60">Пустое сообщение</p>
        ) : null}

        <div className="mt-2 flex items-center justify-end gap-1.5 text-[10px] opacity-70">
          <span>{formatBubbleTimestamp(message.created_at)}</span>
          <DeliveryStatusIcon message={message} />
        </div>
      </div>
    </div>
  );
}

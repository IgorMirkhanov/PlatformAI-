"use client";

import { useRef, useState } from "react";
import { Loader2, MessageSquareQuote, Paperclip, Send } from "lucide-react";

import { QuickRepliesDrawer } from "@/components/inbox/QuickRepliesDrawer";
import { cn } from "@/lib/utils";

interface MessageComposerProps {
  disabled?: boolean;
  sending?: boolean;
  onSend: (text: string) => Promise<void>;
}

export function MessageComposer({
  disabled = false,
  sending = false,
  onSend,
}: MessageComposerProps) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [quickRepliesOpen, setQuickRepliesOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSend = async (): Promise<void> => {
    if (!draft.trim() || disabled || sending) {
      return;
    }

    setError(null);
    try {
      await onSend(draft.trim());
      setDraft("");
    } catch {
      setError("Не удалось отправить сообщение.");
    }
  };

  return (
    <div className="border-t border-zinc-800 bg-zinc-950/80 p-4">
      <QuickRepliesDrawer
        open={quickRepliesOpen}
        onClose={() => setQuickRepliesOpen(false)}
        onSelect={(text) => {
          setDraft(text);
          setQuickRepliesOpen(false);
        }}
      />

      {error ? <p className="mb-2 text-xs text-red-400">{error}</p> : null}

      <div className="flex items-end gap-2">
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          onChange={() => {
            if (fileInputRef.current) {
              fileInputRef.current.value = "";
            }
          }}
        />

        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/80 text-zinc-400 transition hover:border-zinc-700 hover:text-zinc-200 disabled:opacity-40"
          title="Прикрепить файл"
        >
          <Paperclip className="h-4 w-4" />
        </button>

        <button
          type="button"
          onClick={() => setQuickRepliesOpen(true)}
          disabled={disabled}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/80 text-zinc-400 transition hover:border-violet-500/40 hover:text-violet-300 disabled:opacity-40"
          title="Быстрые ответы"
        >
          <MessageSquareQuote className="h-4 w-4" />
        </button>

        <div className="min-w-0 flex-1">
          <input
            type="text"
            value={draft}
            disabled={disabled}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void handleSend();
              }
            }}
            placeholder="Напишите ответ клиенту…"
            className={cn(
              "h-11 w-full rounded-xl border border-zinc-800 bg-zinc-900/80 px-4 text-sm text-zinc-100",
              "placeholder:text-zinc-600 focus:border-violet-500/50 focus:outline-none focus:ring-2 focus:ring-violet-500/20",
            )}
          />
        </div>

        <button
          type="button"
          onClick={() => void handleSend()}
          disabled={disabled || sending || !draft.trim()}
          className="flex h-11 items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-purple-600 px-4 text-sm font-medium text-white shadow-glow-purple transition hover:from-violet-500 hover:to-purple-500 disabled:opacity-40"
        >
          {sending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" />
          )}
          Отправить
        </button>
      </div>
    </div>
  );
}

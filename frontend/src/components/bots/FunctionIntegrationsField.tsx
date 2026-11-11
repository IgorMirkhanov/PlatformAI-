"use client";

import { useEffect, useRef, useState } from "react";
import {
  Ban,
  Braces,
  Check,
  Clock3,
  Code2,
  Copy,
  ExternalLink,
  FileUp,
  MessageCircle,
  Plus,
  Send,
  Tag,
  Trash2,
  X,
} from "lucide-react";

import { cn } from "@/lib/utils";
import {
  FUNCTION_INTEGRATION_OPTIONS,
  FUNCTION_RESULT_INTEGRATION_MENU,
  type FunctionIntegrationKind,
  type TelegramReportChat,
} from "@/types/agent";

const MENU_ICONS: Record<string, { icon: typeof Send; className: string }> = {
  telegram: { icon: Send, className: "text-sky-400" },
  whatsapp: { icon: MessageCircle, className: "text-emerald-400" },
  custom_api: { icon: Braces, className: "text-violet-300" },
  file: { icon: FileUp, className: "text-zinc-200" },
  delayed: { icon: Clock3, className: "text-fuchsia-300" },
  python: { icon: Code2, className: "text-amber-300" },
  tags: { icon: Tag, className: "text-zinc-200" },
};

function integrationLabel(id: FunctionIntegrationKind): string {
  return FUNCTION_INTEGRATION_OPTIONS.find((item) => item.id === id)?.label ?? id;
}

function formatConnected(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("ru-RU");
}

export function FunctionIntegrationPicker({
  selected,
  onToggle,
  onClear,
}: {
  selected: FunctionIntegrationKind[];
  onToggle: (id: FunctionIntegrationKind) => void;
  onClear: () => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent): void => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    return () => document.removeEventListener("mousedown", onPointer);
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <div className="flex min-h-10 items-center gap-1.5 rounded-lg border border-zinc-600 bg-[#0c0c0e] px-2 py-1.5">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
          {selected.length === 0 ? (
            <span className="px-1 text-sm text-zinc-500">Выберите интеграции</span>
          ) : (
            selected.map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => onToggle(id)}
                className="inline-flex items-center gap-1 rounded-md bg-zinc-800 px-2 py-1 text-xs font-medium text-zinc-100 hover:bg-zinc-700"
              >
                {integrationLabel(id)}
                <span aria-hidden className="text-zinc-400">
                  ×
                </span>
              </button>
            ))
          )}
        </div>
        <button
          type="button"
          aria-label="Добавить интеграцию"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-zinc-300 hover:bg-zinc-800 hover:text-white"
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>

      {open ? (
        <div
          role="listbox"
          aria-label="Интеграции"
          className="absolute right-0 z-30 mt-1 w-56 overflow-hidden rounded-xl border border-zinc-600 bg-[#1c1c21] py-1 shadow-lg"
        >
          {FUNCTION_RESULT_INTEGRATION_MENU.map((item) => {
            const visual = MENU_ICONS[item.id];
            const Icon = visual?.icon ?? Braces;
            const active = selected.includes(item.id);
            return (
              <button
                key={item.id}
                type="button"
                role="option"
                aria-selected={active}
                onClick={() => onToggle(item.id)}
                className={cn(
                  "flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-zinc-100 hover:bg-zinc-800",
                  active && "bg-zinc-800/80",
                )}
              >
                <Icon className={cn("h-4 w-4 shrink-0", visual?.className)} />
                <span className="min-w-0 flex-1">{item.label}</span>
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => {
              onClear();
              setOpen(false);
            }}
            className="flex w-full items-center gap-2.5 border-t border-zinc-700 px-3 py-2 text-left text-sm text-zinc-300 hover:bg-zinc-800"
          >
            <Ban className="h-4 w-4 shrink-0 text-zinc-400" />
            Отключить все
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function TelegramReportChatCard({
  chats,
  selectedChatId,
  onSelect,
  onConnect,
  onDelete,
  onIssueBind,
  onRefreshChats,
  onBound,
  connecting,
}: {
  chats: TelegramReportChat[];
  selectedChatId: string | null;
  onSelect: (chatId: string) => void;
  onConnect: (chatId: string) => Promise<void>;
  onDelete: (chatId: string) => Promise<void>;
  onIssueBind: () => Promise<{ command: string; expires_at: string; telegram_url: string; bot_username: string | null }>;
  onRefreshChats: () => Promise<TelegramReportChat[]>;
  onBound: (chatId: string) => void;
  connecting: boolean;
}) {
  const [bindOpen, setBindOpen] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [chatId, setChatId] = useState("");
  const [bind, setBind] = useState<{ command: string; expires_at: string; telegram_url: string; bot_username: string | null } | null>(null);
  const [bindError, setBindError] = useState("");
  const [copied, setCopied] = useState(false);
  const knownChats = useRef<Set<string>>(new Set());

  return (
    <div className="space-y-3 rounded-xl border border-zinc-600 bg-[#1a1a1e] p-4 text-zinc-100">
      <div className="flex items-center gap-2">
        <Send className="h-4 w-4 text-sky-400" />
        <h4 className="text-sm font-semibold">Telegram</h4>
      </div>
      <p className="text-xs text-zinc-400">Выберите чат для уведомлений или отчётов</p>

      {chats.length === 0 ? (
        <p className="text-xs text-zinc-500">
          Чатов пока нет. Нажмите «Подключить новый чат» и отправьте команду в нужный чат.
        </p>
      ) : (
        <div className="space-y-2">
          {chats.map((chat) => {
            const connected = formatConnected(chat.connected_at);
            return (
              <label
                key={chat.chat_id}
                className="flex cursor-pointer items-start gap-3 rounded-lg border border-zinc-700 bg-[#121214] px-3 py-2.5"
              >
                <input
                  type="radio"
                  name="telegram-report-chat"
                  checked={selectedChatId === chat.chat_id}
                  onChange={() => onSelect(chat.chat_id)}
                  className="mt-1 h-4 w-4 border-zinc-500 text-violet-600 focus:ring-violet-500/40"
                />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm text-zinc-50">{chat.chat_id}</span>
                    {chat.active !== false ? (
                      <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-300">
                        Активное
                      </span>
                    ) : null}
                  </span>
                  <span className="mt-0.5 block text-[11px] text-zinc-500">
                    Telegram-чат{connected ? ` · Подключено ${connected}` : ""}
                  </span>
                </span>
                <button
                  type="button"
                  aria-label="Отключить чат"
                  onClick={(event) => {
                    event.preventDefault();
                    void onDelete(chat.chat_id);
                  }}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-rose-300 hover:bg-rose-500/10"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </label>
            );
          })}
        </div>
      )}

      <button
        type="button"
        onClick={() => {
          knownChats.current = new Set(chats.map((chat) => chat.chat_id));
          setBind(null);
          setBindError("");
          setManualOpen(false);
          setBindOpen(true);
          void onIssueBind()
            .then((issued) => setBind(issued))
            .catch((error: unknown) => {
              setBindError(error instanceof Error ? error.message : "Не удалось создать команду.");
            });
        }}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-zinc-200 hover:text-white"
      >
        <Plus className="h-4 w-4" />
        Подключить новый чат
      </button>

      {bindOpen ? (
        <TelegramBindDialog
          bind={bind}
          error={bindError}
          copied={copied}
          manualOpen={manualOpen}
          chatId={chatId}
          connecting={connecting}
          onChatId={setChatId}
          onManual={() => setManualOpen(true)}
          onClose={() => setBindOpen(false)}
          onCopy={() => {
            if (!bind) return;
            void navigator.clipboard.writeText(bind.command).then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            });
          }}
          onConnectManual={() => {
            const value = chatId.trim();
            if (!value || connecting) return;
            void onConnect(value)
              .then(() => {
                setChatId("");
                setBindOpen(false);
              })
              .catch(() => undefined);
          }}
          onRefresh={async () => {
            const next = await onRefreshChats();
            const added = next.find((chat) => !knownChats.current.has(chat.chat_id));
            if (!added) return;
            onSelect(added.chat_id);
            onBound(added.chat_id);
            setBindOpen(false);
          }}
        />
      ) : null}
    </div>
  );
}

function TelegramBindDialog({
  bind,
  error,
  copied,
  manualOpen,
  chatId,
  connecting,
  onChatId,
  onManual,
  onClose,
  onCopy,
  onConnectManual,
  onRefresh,
}: {
  bind: { command: string; expires_at: string; telegram_url: string; bot_username: string | null } | null;
  error: string;
  copied: boolean;
  manualOpen: boolean;
  chatId: string;
  connecting: boolean;
  onChatId: (value: string) => void;
  onManual: () => void;
  onClose: () => void;
  onCopy: () => void;
  onConnectManual: () => void;
  onRefresh: () => Promise<void>;
}) {
  const [now, setNow] = useState(() => Date.now());
  const refreshRef = useRef(onRefresh);
  refreshRef.current = onRefresh;

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!bind) return;
    const timer = window.setInterval(() => {
      void refreshRef.current().catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [bind]);

  const remaining = bind ? Math.max(0, new Date(bind.expires_at).getTime() - now) : 0;
  const minutes = Math.floor(remaining / 60000);
  const seconds = Math.floor((remaining % 60000) / 1000);
  const countdown = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  const botHandle = bind?.bot_username ? `@${bind.bot_username}` : "бота";

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4">
      <div
        role="dialog"
        aria-labelledby="telegram-bind-title"
        className="w-full max-w-md rounded-2xl border border-zinc-600 bg-[#1a1a1e] p-5 text-zinc-100 shadow-lg"
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <h4 id="telegram-bind-title" className="text-base font-semibold">
            Подключение Telegram
          </h4>
          <button type="button" aria-label="Закрыть" onClick={onClose} className="text-zinc-400 hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="text-sm text-zinc-300">Привяжите личный чат, группу или канал через бота</p>
        <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm text-zinc-300">
          <li>Скопируйте команду с уникальным кодом.</li>
          <li>Откройте нужный чат в Telegram и добавьте в него {botHandle}.</li>
          <li>Отправьте команду в чат. Подключение определится автоматически.</li>
        </ol>

        <div className="mt-4 flex items-center justify-between gap-3 text-xs text-zinc-400">
          <span>Команда подключения</span>
          <span>{bind && remaining > 0 ? `Код действует ещё ${countdown}` : bind ? "Код истёк" : ""}</span>
        </div>
        <div className="mt-2 flex items-center gap-2 rounded-lg border border-zinc-600 bg-[#0c0c0e] px-3 py-2">
          <code className="min-w-0 flex-1 truncate font-mono text-sm text-zinc-100">
            {bind?.command ?? (error || "Создаём команду…")}
          </code>
          <button
            type="button"
            aria-label="Скопировать команду"
            disabled={!bind}
            onClick={onCopy}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-zinc-300 hover:bg-zinc-800 hover:text-white disabled:opacity-40"
          >
            {copied ? <Check className="h-4 w-4 text-emerald-300" /> : <Copy className="h-4 w-4" />}
          </button>
        </div>
        {error ? <p className="mt-2 text-xs text-rose-300">{error}</p> : null}

        {bind ? (
          <a
            href={bind.telegram_url}
            target="_blank"
            rel="noreferrer"
            className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl border border-zinc-500 px-4 py-2.5 text-sm font-medium text-zinc-100 hover:bg-zinc-800"
          >
            <ExternalLink className="h-4 w-4" />
            Открыть в Telegram
          </a>
        ) : null}

        {manualOpen ? (
          <form
            className="mt-4 space-y-2"
            onSubmit={(event) => {
              event.preventDefault();
              onConnectManual();
            }}
          >
            <input
              value={chatId}
              onChange={(event) => onChatId(event.target.value)}
              placeholder="-100…"
              className="h-9 w-full rounded-lg border border-zinc-600 bg-[#0c0c0e] px-2.5 font-mono text-sm outline-none focus:border-violet-500"
            />
            <button
              type="submit"
              disabled={connecting || !chatId.trim()}
              className="rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
            >
              {connecting ? "Подключение…" : "Подключить по ID"}
            </button>
          </form>
        ) : (
          <button type="button" onClick={onManual} className="mt-3 text-xs text-zinc-500 hover:text-zinc-300">
            Указать ID вручную
          </button>
        )}
      </div>
    </div>
  );
}

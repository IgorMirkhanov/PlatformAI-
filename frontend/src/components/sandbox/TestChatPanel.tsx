"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Eraser, Loader2, Send, TestTube2 } from "lucide-react";
import type { FormEvent, JSX } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, clearSandboxSession, sendSandboxMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  ExecutionTrace,
  SandboxChatMessage,
  SandboxRuntimeLog,
} from "@/types/sandbox";
import {
  createEmptyTrace,
  createSandboxMessage,
  normalizeExecutionTrace,
  summarizeTraceForConsole,
} from "@/types/sandbox";

interface TestChatPanelProps {
  botId: string;
  botName?: string;
  className?: string;
  onTraceChange?: (trace: ExecutionTrace) => void;
  onRuntimeLogsChange?: (logs: SandboxRuntimeLog[]) => void;
}

function TypingBubble(): JSX.Element {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 4, scale: 0.98 }}
      transition={{ duration: 0.2 }}
      className="flex justify-start"
    >
      <div className="inline-flex items-center gap-2.5 rounded-2xl rounded-bl-md border border-violet-500/20 bg-gradient-to-r from-zinc-900/90 to-violet-950/40 px-4 py-2.5 text-xs text-zinc-300 shadow-[0_0_24px_rgba(139,92,246,0.12)] backdrop-blur-md">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-violet-400/70 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-violet-400" />
        </span>
        <span className="animate-pulse font-medium tracking-wide text-violet-100/90">
          Бот печатает...
        </span>
        <span className="flex items-center gap-1">
          {[0, 1, 2].map((dot) => (
            <motion.span
              key={dot}
              className="h-1.5 w-1.5 rounded-full bg-violet-300/80"
              animate={{ opacity: [0.35, 1, 0.35], y: [0, -2, 0] }}
              transition={{
                duration: 0.9,
                repeat: Infinity,
                delay: dot * 0.15,
                ease: "easeInOut",
              }}
            />
          ))}
        </span>
      </div>
    </motion.div>
  );
}

export function TestChatPanel({
  botId,
  botName,
  className,
  onTraceChange,
  onRuntimeLogsChange,
}: TestChatPanelProps) {
  const [messages, setMessages] = useState<SandboxChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [runtimeLogs, setRuntimeLogs] = useState<SandboxRuntimeLog[]>([]);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const sessionIdRef = useRef<string | null>(null);

  const appendLog = useCallback((level: SandboxRuntimeLog["level"], message: string): void => {
    setRuntimeLogs((current) => {
      const next = [
        ...current.slice(-49),
        {
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          level,
          message,
          timestamp: Date.now(),
        },
      ];
      return next;
    });
  }, []);

  useEffect(() => {
    onRuntimeLogsChange?.(runtimeLogs);
  }, [onRuntimeLogsChange, runtimeLogs]);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node) {
      return;
    }
    node.scrollTo({ top: node.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  const publishTrace = useCallback(
    (trace: ExecutionTrace): void => {
      const normalized = normalizeExecutionTrace(trace);
      onTraceChange?.(normalized);
      appendLog("info", summarizeTraceForConsole(normalized));
    },
    [appendLog, onTraceChange],
  );

  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed || sending) {
      return;
    }

    // Instant user-layer render before the network round-trip completes.
    const optimistic = createSandboxMessage("user", trimmed, { pending: true });
    setMessages((current) => [...current, optimistic]);
    setDraft("");
    setSending(true);

    try {
      const response = await sendSandboxMessage(botId, {
        text: trimmed,
        session_id: sessionIdRef.current,
      });

      setSessionId(response.session_id);
      sessionIdRef.current = response.session_id;
      publishTrace(response.trace);

      setMessages((current) => {
        const withoutPendingFlag = current.map((message) =>
          message.id === optimistic.id ? { ...message, pending: false } : message,
        );
        if (!response.message.trim()) {
          return withoutPendingFlag;
        }
        return [...withoutPendingFlag, createSandboxMessage("bot", response.message)];
      });
    } catch (error) {
      const detail =
        error instanceof ApiError
          ? error.message
          : error instanceof Error
            ? error.message
            : "Не удалось отправить сообщение в sandbox.";
      appendLog("error", detail);
      onTraceChange?.(
        normalizeExecutionTrace({
          ...createEmptyTrace(),
          errors: [detail],
        }),
      );
      setMessages((current) => [
        ...current.map((message) =>
          message.id === optimistic.id ? { ...message, pending: false } : message,
        ),
        createSandboxMessage("system", detail),
      ]);
    } finally {
      setSending(false);
    }
  };

  const handleClearSession = async (): Promise<void> => {
    setClearing(true);
    try {
      const result = await clearSandboxSession(botId, sessionIdRef.current ?? undefined);
      setSessionId(result.session_id);
      sessionIdRef.current = result.session_id;
      setDraft("");
      setMessages([createSandboxMessage("system", result.message || "Чат очищен.")]);
      const empty = createEmptyTrace();
      onTraceChange?.(empty);
      appendLog("info", "Sandbox session reset.");
    } catch (error) {
      const detail =
        error instanceof Error ? error.message : "Не удалось очистить sandbox-сессию.";
      appendLog("error", detail);
      setMessages((current) => [...current, createSandboxMessage("system", detail)]);
    } finally {
      setClearing(false);
    }
  };

  return (
    <section
      className={cn(
        "flex min-h-[560px] flex-col overflow-hidden rounded-2xl border border-zinc-800/80 bg-[#070708]",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3 border-b border-zinc-800/80 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <TestTube2 className="h-4 w-4 shrink-0 text-violet-300" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-zinc-100">Live Chat Simulator</p>
            <p className="truncate text-[11px] text-zinc-500">
              {botName ? `${botName} · ` : ""}
              Session {sessionId ? sessionId.slice(0, 8) : "новая"}
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={() => void handleClearSession()}
          disabled={clearing || sending}
          className="inline-flex shrink-0 items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-xs font-semibold text-zinc-300 transition hover:border-zinc-700 hover:text-white disabled:opacity-60"
        >
          {clearing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Eraser className="h-3.5 w-3.5" />
          )}
          Очистить чат
        </button>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {messages.length === 0 && !sending ? (
          <div className="flex h-full min-h-[320px] flex-col items-center justify-center text-center">
            <p className="text-sm text-zinc-400">
              Отправьте сообщение, чтобы запустить трассировку.
            </p>
            <p className="mt-1 text-xs text-zinc-600">
              Симулятор использует опубликованный сценарий и in-memory историю.
            </p>
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {messages.map((message) => (
              <motion.div
                key={message.id}
                layout
                initial={{ opacity: 0, y: 10, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.18, ease: "easeOut" }}
                className={cn(
                  "flex",
                  message.role === "user" ? "justify-end" : "justify-start",
                )}
              >
                <div
                  className={cn(
                    "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm",
                    message.role === "user" && "rounded-br-md bg-violet-600 text-white",
                    message.role === "bot" &&
                      "rounded-bl-md border border-zinc-800 bg-zinc-900/80 text-zinc-100",
                    message.role === "system" &&
                      "border border-amber-500/20 bg-amber-500/5 text-amber-100/90",
                    message.pending && "opacity-90",
                  )}
                >
                  <p className="whitespace-pre-wrap break-words">{message.text}</p>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        )}

        <AnimatePresence>{sending ? <TypingBubble /> : null}</AnimatePresence>
      </div>

      <form
        onSubmit={(event) => {
          void handleSubmit(event);
        }}
        className="border-t border-zinc-800/80 bg-zinc-950/50 p-4"
      >
        <div className="flex items-end gap-2">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={2}
            placeholder="Напишите тестовое сообщение…"
            disabled={sending || clearing}
            className="min-h-[52px] flex-1 resize-none rounded-xl border border-zinc-800 bg-black/60 px-3 py-2.5 text-sm text-zinc-100 outline-none ring-violet-500/30 placeholder:text-zinc-600 focus:border-violet-500/40 focus:ring-2 disabled:opacity-60"
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <button
            type="submit"
            disabled={!draft.trim() || sending || clearing}
            className="inline-flex h-[52px] w-[52px] items-center justify-center rounded-xl bg-violet-600 text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="Отправить"
          >
            {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </button>
        </div>
      </form>
    </section>
  );
}

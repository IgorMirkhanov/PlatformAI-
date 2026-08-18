"use client";

import { Loader2, Radio, Send } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { useSandboxWebSocket } from "@/hooks/useSandboxWebSocket";
import { useToast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";
import { useFlowStore } from "@/store/useFlowStore";
import type { SandboxWsOutbound } from "@/types/sandbox";

interface ChatLine {
  id: string;
  role: "user" | "bot" | "system";
  text: string;
}

interface FlowPreviewPaneProps {
  botId: string;
  className?: string;
}

/**
 * Live sandbox preview for the flow builder (WebSocket → /api/v1/sandbox/ws).
 */
export function FlowPreviewPane({ botId, className }: FlowPreviewPaneProps) {
  const [input, setInput] = useState("");
  const [lines, setLines] = useState<ChatLine[]>([]);
  const runGraphValidation = useFlowStore((state) => state.runGraphValidation);
  const { showToast } = useToast();

  const onResponse = useCallback((payload: SandboxWsOutbound) => {
    const text = payload.message || payload.error || "";
    if (!text) return;
    setLines((prev) => [
      ...prev,
      {
        id: `${Date.now()}-bot`,
        role: payload.type === "error" ? "system" : "bot",
        text,
      },
    ]);
  }, []);

  const { connected, connecting, error, sendMessage, lastTrace, reconnect } =
    useSandboxWebSocket({ botId, onResponse });

  useEffect(() => {
    if (!botId) return;
    setLines([
      {
        id: "welcome",
        role: "system",
        text: "Preview uses the published/saved graph via sandbox WebSocket.",
      },
    ]);
  }, [botId]);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const text = input.trim();
    if (!text) return;

    const issues = runGraphValidation();
    if (issues.length > 0) {
      showToast(
        issues[0]?.message ?? "Исправьте ошибки графа перед тестом бота.",
        "settings",
      );
      return;
    }

    setLines((prev) => [...prev, { id: `${Date.now()}-u`, role: "user", text }]);
    setInput("");
    sendMessage(text);
  };

  const traceHint =
    lastTrace?.nodes_triggered?.length > 0
      ? lastTrace.nodes_triggered.map((s) => s.node_type || s.node_id).filter(Boolean).join(" → ")
      : null;

  return (
    <aside
      className={cn(
        "flex w-full flex-col overflow-hidden rounded-2xl border border-zinc-800/90 bg-[#0d0d0f]/95 xl:w-80",
        className,
      )}
    >
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-zinc-100">Test Bot</h2>
          <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-zinc-500">
            <Radio
              className={cn(
                "h-3 w-3",
                connected ? "text-emerald-400" : connecting ? "text-amber-400" : "text-zinc-600",
              )}
            />
            {connected ? "WS connected" : connecting ? "Connecting…" : "Disconnected"}
          </p>
        </div>
        {!connected && (
          <button
            type="button"
            onClick={reconnect}
            className="rounded-md px-2 py-1 text-[11px] text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
          >
            Reconnect
          </button>
        )}
      </div>

      {error && (
        <div className="border-b border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-300">
          {error}
        </div>
      )}

      <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-3">
        {lines.map((line) => (
          <div
            key={line.id}
            className={cn(
              "rounded-xl px-3 py-2 text-xs leading-relaxed",
              line.role === "user" && "ml-6 bg-sky-500/15 text-sky-100",
              line.role === "bot" && "mr-6 bg-zinc-900 text-zinc-200",
              line.role === "system" && "bg-transparent text-zinc-600",
            )}
          >
            {line.text}
          </div>
        ))}
      </div>

      {traceHint && (
        <div className="border-t border-zinc-800/80 px-3 py-2 text-[10px] text-zinc-500">
          Trace: {traceHint}
        </div>
      )}

      <form onSubmit={onSubmit} className="flex gap-2 border-t border-zinc-800 p-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Test message…"
          className="min-w-0 flex-1 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-zinc-600"
        />
        <button
          type="submit"
          disabled={!connected || !input.trim()}
          className="inline-flex items-center justify-center rounded-lg bg-accent px-3 text-white disabled:opacity-40"
          aria-label="Send"
        >
          {connecting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        </button>
      </form>
    </aside>
  );
}

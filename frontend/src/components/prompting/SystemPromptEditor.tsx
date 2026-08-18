"use client";

import { motion } from "framer-motion";
import { Loader2, Sparkles } from "lucide-react";

import { cn } from "@/lib/utils";

interface SystemPromptEditorProps {
  value: string;
  onChange: (value: string) => void;
  onEnhance: () => Promise<void>;
  enhancing: boolean;
  revealing: boolean;
  disabled?: boolean;
  agentName: string;
}

export function SystemPromptEditor({
  value,
  onChange,
  onEnhance,
  enhancing,
  revealing,
  disabled = false,
  agentName,
}: SystemPromptEditorProps) {
  return (
    <section className="moonai-panel flex min-h-[640px] flex-col">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3 border-b border-zinc-800/80 pb-4">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-violet-300/70">
            System Instruction Arena
          </p>
          <h3 className="mt-1 text-lg font-semibold text-zinc-50">System Prompt</h3>
          <p className="mt-1 text-xs text-zinc-500">
            Моноширинный редактор для {agentName}. Промпт передаётся в OpenAI / Local LLM pipeline.
          </p>
        </div>

        <button
          type="button"
          disabled={disabled || enhancing || revealing}
          onClick={() => void onEnhance()}
          className={cn(
            "inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 via-fuchsia-600 to-amber-500",
            "px-4 py-2.5 text-xs font-semibold text-white shadow-glow-purple transition",
            "hover:from-violet-500 hover:via-fuchsia-500 hover:to-amber-400 disabled:opacity-50",
          )}
        >
          {enhancing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          {enhancing ? "Улучшение…" : "✨ Улучшить промпт через ИИ"}
        </button>
      </div>

      <motion.div
        className="relative min-h-0 flex-1"
        animate={{ opacity: revealing ? 0.72 : 1 }}
        transition={{ duration: 0.25 }}
      >
        <textarea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled || enhancing || revealing}
          rows={24}
          spellCheck={false}
          placeholder={"# Role\nYou are a senior AI agent for MP.AI...\n\n# Rules\n- Be concise\n- Use RAG when relevant"}
          className={cn(
            "h-full min-h-[520px] w-full resize-y rounded-2xl border px-4 py-4",
            "border-zinc-800 bg-zinc-950/80 font-mono text-[13px] leading-relaxed text-zinc-100",
            "placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500/30",
            (enhancing || revealing) && "opacity-80",
          )}
        />
        {(enhancing || revealing) && (
          <div className="pointer-events-none absolute inset-0 rounded-2xl bg-gradient-to-b from-violet-500/5 to-transparent" />
        )}
      </motion.div>

      <p className="mt-2 text-xs text-zinc-600">
        {value.length.toLocaleString("ru-RU")} / 50 000 символов
      </p>
    </section>
  );
}

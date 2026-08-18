"use client";

import Link from "next/link";
import { Bot, Database, Sparkles } from "lucide-react";

interface KnowledgeRagPickerProps {
  botId: string;
}

export function KnowledgeRagPicker({ botId }: KnowledgeRagPickerProps) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-zinc-50">База знаний</h2>
        <p className="mt-1 text-sm text-zinc-500">
          Выберите, как агент будет использовать знания: всегда в контексте или по условию вызова.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Link
          href={`/bots/${botId}/knowledge-base/direct`}
          className="group rounded-2xl border border-zinc-800/90 bg-[#0d0d0f] p-6 transition hover:border-violet-500/40 hover:bg-violet-500/5"
        >
          <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-violet-500/10 ring-1 ring-violet-500/25">
            <Database className="h-5 w-5 text-violet-300" />
          </div>
          <h3 className="text-base font-semibold text-zinc-50">Прямой RAG</h3>
          <p className="mt-2 text-sm leading-relaxed text-zinc-500">
            Заполните данные вручную. ИИ проходит по всему массиву знаний.
          </p>
          <p className="mt-4 text-xs font-medium text-violet-300 group-hover:underline">
            Открыть прямой RAG →
          </p>
        </Link>

        <Link
          href={`/bots/${botId}/knowledge-base/agent-rag`}
          className="group rounded-2xl border border-zinc-800/90 bg-[#0d0d0f] p-6 transition hover:border-emerald-500/40 hover:bg-emerald-500/5"
        >
          <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-500/10 ring-1 ring-emerald-500/25">
            <Bot className="h-5 w-5 text-emerald-300" />
          </div>
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-zinc-50">Агентный RAG</h3>
            <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
          </div>
          <p className="mt-2 text-sm leading-relaxed text-zinc-500">
            Загрузите файл с данными. ИИ вызывает знания в зависимости от условия.
          </p>
          <p className="mt-4 text-xs font-medium text-emerald-300 group-hover:underline">
            Настроить коллекции →
          </p>
        </Link>
      </div>
    </div>
  );
}

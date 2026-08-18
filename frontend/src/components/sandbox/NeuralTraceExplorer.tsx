"use client";

import { useMemo, useState } from "react";
import { Activity, BrainCircuit, Coins, FileText, Route } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ExecutionTrace, SandboxTraceTab } from "@/types/sandbox";
import { createEmptyTrace, formatKztCost, formatSimilarityScore, normalizeExecutionTrace } from "@/types/sandbox";

const TABS: Array<{ id: SandboxTraceTab; label: string; icon: typeof Route }> = [
  { id: "graph", label: "Путь графа", icon: Route },
  { id: "rag", label: "Контекст RAG", icon: FileText },
  { id: "tokens", label: "Токены & Стоимость", icon: Coins },
];

interface NeuralTraceExplorerProps {
  trace: ExecutionTrace;
  runtimeLogs?: Array<{ id: string; level: "info" | "error"; message: string }>;
}

export function NeuralTraceExplorer({ trace, runtimeLogs = [] }: NeuralTraceExplorerProps) {
  const [activeTab, setActiveTab] = useState<SandboxTraceTab>("graph");
  const resolvedTrace = normalizeExecutionTrace(trace ?? createEmptyTrace());

  const nodeSummary = useMemo(
    () =>
      resolvedTrace.nodes_triggered.map((node, index) => ({
        ...node,
        order: index + 1,
      })),
    [resolvedTrace.nodes_triggered],
  );

  return (
    <aside className="flex h-full min-h-0 flex-col rounded-2xl border border-zinc-800/80 bg-[#050506]">
      <div className="border-b border-zinc-800/80 px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-500/10 ring-1 ring-violet-500/20">
            <BrainCircuit className="h-4 w-4 text-violet-300" />
          </div>
          <div>
            <p className="text-sm font-semibold text-zinc-100">Neural Trace Explorer</p>
            <p className="text-[11px] text-zinc-500">Runtime diagnostics · simulation mode</p>
          </div>
        </div>
      </div>

      <div className="flex gap-1 border-b border-zinc-800/80 px-3 py-2">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-[11px] font-semibold transition",
                isActive
                  ? "bg-violet-500/12 text-violet-100 ring-1 ring-violet-500/25"
                  : "text-zinc-500 hover:bg-zinc-900/70 hover:text-zinc-200",
              )}
            >
              <Icon className="h-3.5 w-3.5 shrink-0" />
              <span className="hidden xl:inline">{tab.label}</span>
            </button>
          );
        })}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4 font-mono text-[12px] leading-relaxed text-zinc-300">
        {activeTab === "graph" && (
          <div className="space-y-3">
            {resolvedTrace.current_node_id ? (
              <div className="rounded-xl border border-violet-500/20 bg-violet-500/5 px-3 py-2 text-[11px] text-violet-100">
                Current node:{" "}
                <span className="font-semibold break-all">{resolvedTrace.current_node_id}</span>
              </div>
            ) : null}

            {resolvedTrace.transitions.length > 0 ? (
              <div className="space-y-2 rounded-xl border border-zinc-800/70 bg-zinc-950/40 p-3">
                <p className="text-[10px] uppercase tracking-wider text-zinc-500">Transitions</p>
                {resolvedTrace.transitions.map((transition, index) => (
                  <p
                    key={`${transition.from_node_id}-${transition.to_node_id}-${index}`}
                    className="break-all text-[11px] text-zinc-400"
                  >
                    <span className="text-zinc-300">{transition.from_node_id.slice(0, 8)}</span>
                    {" → "}
                    <span className="text-violet-300">{transition.to_node_id.slice(0, 8)}</span>
                    {transition.via_handle ? (
                      <span className="text-zinc-500"> via {transition.via_handle}</span>
                    ) : null}
                  </p>
                ))}
              </div>
            ) : null}

            {nodeSummary.length === 0 ? (
              <p className="text-zinc-500">Узлы ещё не выполнялись. Отправьте сообщение в симулятор.</p>
            ) : (
              nodeSummary.map((node) => (
                <div
                  key={`${node.node_id}-${node.order}`}
                  className="rounded-xl border border-zinc-800/70 bg-zinc-950/60 p-3"
                >
                  <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-zinc-500">
                    <Activity className="h-3 w-3 text-emerald-400" />
                    Step {node.order}
                  </div>
                  <p className="mt-2 text-sm font-semibold text-zinc-100">{node.node_type}</p>
                  <p className="mt-1 break-all text-[11px] text-violet-300/90">{node.node_id}</p>
                  {node.label ? (
                    <p className="mt-2 whitespace-pre-wrap text-[11px] text-zinc-400">{node.label}</p>
                  ) : null}
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === "rag" && (
          <div className="space-y-3">
            {resolvedTrace.rag_context.length === 0 ? (
              <p className="text-zinc-500">RAG-контекст не был извлечён для последнего ответа.</p>
            ) : (
              resolvedTrace.rag_context.map((chunk, index) => (
                <div
                  key={`${chunk.document_id ?? "doc"}-${chunk.chunk_index ?? index}`}
                  className="rounded-xl border border-zinc-800/70 bg-zinc-950/60 p-3"
                >
                  <div className="flex flex-wrap items-center gap-2 text-[10px] text-zinc-500">
                    <span className="rounded bg-emerald-500/10 px-2 py-0.5 text-emerald-300">
                      {formatSimilarityScore(chunk.similarity_score)}
                    </span>
                    {chunk.file_name ? <span>{chunk.file_name}</span> : null}
                    {chunk.chunk_index != null ? <span>chunk #{chunk.chunk_index}</span> : null}
                  </div>
                  <pre className="mt-3 whitespace-pre-wrap break-words text-[11px] text-zinc-300">
                    {chunk.text}
                  </pre>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === "tokens" && (
          <div className="space-y-4">
            {resolvedTrace.llm_metrics ? (
              <>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    ["Input", resolvedTrace.llm_metrics.input_tokens],
                    ["Output", resolvedTrace.llm_metrics.output_tokens],
                    ["Total", resolvedTrace.llm_metrics.total_tokens],
                    ["Cost", formatKztCost(resolvedTrace.llm_metrics.cost_kzt)],
                  ].map(([label, value]) => (
                    <div
                      key={String(label)}
                      className="rounded-xl border border-zinc-800/70 bg-zinc-950/60 px-3 py-2"
                    >
                      <p className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</p>
                      <p className="mt-1 text-sm font-semibold text-zinc-100">{value}</p>
                    </div>
                  ))}
                </div>

                <div className="rounded-xl border border-zinc-800/70 bg-zinc-950/60 p-3">
                  <p className="text-[10px] uppercase tracking-wider text-zinc-500">Model</p>
                  <p className="mt-1 text-sm text-zinc-100">{resolvedTrace.llm_metrics.model_name}</p>
                  <p className="mt-3 text-[10px] uppercase tracking-wider text-zinc-500">
                    Temperature
                  </p>
                  <p className="mt-1 text-sm text-zinc-100">
                    {resolvedTrace.llm_metrics.temperature}
                  </p>
                  <p className="mt-3 text-[10px] uppercase tracking-wider text-zinc-500">
                    Redis cache
                  </p>
                  <p className="mt-1 text-sm text-zinc-100">
                    {resolvedTrace.llm_metrics.cache_hit ? "HIT" : "MISS"}
                  </p>
                </div>

                <div className="rounded-xl border border-zinc-800/70 bg-zinc-950/60 p-3">
                  <p className="text-[10px] uppercase tracking-wider text-zinc-500">System prompt</p>
                  <pre className="mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap break-words text-[11px] text-zinc-400">
                    {resolvedTrace.llm_metrics.system_prompt}
                  </pre>
                </div>

                <div className="rounded-xl border border-zinc-800/70 bg-zinc-950/60 p-3">
                  <p className="text-[10px] uppercase tracking-wider text-zinc-500">User query</p>
                  <pre className="mt-2 whitespace-pre-wrap break-words text-[11px] text-zinc-300">
                    {resolvedTrace.llm_metrics.user_query}
                  </pre>
                </div>

                <div className="rounded-xl border border-zinc-800/70 bg-zinc-950/60 p-3">
                  <p className="text-[10px] uppercase tracking-wider text-zinc-500">Raw response</p>
                  <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap break-words text-[11px] text-emerald-200/90">
                    {resolvedTrace.llm_metrics.raw_response}
                  </pre>
                </div>
              </>
            ) : (
              <p className="text-zinc-500">LLM-метрики появятся после ответа AI-агента.</p>
            )}
          </div>
        )}

        {resolvedTrace.errors.length > 0 && (
          <div className="mt-4 rounded-xl border border-rose-500/20 bg-rose-500/5 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-rose-300">
              Trace errors
            </p>
            <ul className="mt-2 space-y-1 text-[11px] text-rose-200/90">
              {resolvedTrace.errors.map((entry) => (
                <li key={entry}>{entry}</li>
              ))}
            </ul>
          </div>
        )}

        {runtimeLogs.length > 0 && (
          <div className="mt-4 rounded-xl border border-zinc-800/70 bg-zinc-950/40 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              Runtime log
            </p>
            <ul className="mt-2 space-y-1">
              {runtimeLogs.slice(-8).map((entry) => (
                <li
                  key={entry.id}
                  className={cn(
                    "text-[11px]",
                    entry.level === "error" ? "text-rose-300" : "text-zinc-500",
                  )}
                >
                  {entry.message}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </aside>
  );
}

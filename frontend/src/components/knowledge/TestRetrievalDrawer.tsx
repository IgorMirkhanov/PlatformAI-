"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Search, X } from "lucide-react";

import { testKnowledgeSearch, type KnowledgeTestSearchChunk } from "@/lib/api";
import { cn } from "@/lib/utils";

interface TestRetrievalDrawerProps {
  open: boolean;
  kbId: string | null;
  onClose: () => void;
}

export function TestRetrievalDrawer({ open, kbId, onClose }: TestRetrievalDrawerProps) {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(4);
  const [loading, setLoading] = useState(false);
  const [chunks, setChunks] = useState<KnowledgeTestSearchChunk[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setChunks([]);
      setError(null);
      setQuery("");
    }
  }, [open]);

  const runSearch = useCallback(async () => {
    if (!kbId || !query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await testKnowledgeSearch(kbId, { query: query.trim(), top_k: topK });
      setChunks(result.chunks);
    } catch (err) {
      setChunks([]);
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setLoading(false);
    }
  }, [kbId, query, topK]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Close drawer"
        className="absolute inset-0 bg-black/50 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <aside className="relative flex h-full w-full max-w-lg flex-col border-l border-zinc-800 bg-[#0c0c0e] shadow-2xl">
        <header className="flex items-center justify-between border-b border-zinc-800 px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-zinc-100">Test Retrieval</h2>
            <p className="mt-0.5 text-xs text-zinc-500">
              Embed a question and inspect ranked Chroma chunks
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-zinc-400 transition hover:bg-zinc-800 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="space-y-3 border-b border-zinc-800 px-5 py-4">
          <label className="block text-xs font-medium text-zinc-400">
            Test question
            <textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              rows={3}
              placeholder="e.g. What is the refund policy?"
              className="mt-1.5 w-full resize-none rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-violet-500/40 placeholder:text-zinc-600 focus:ring-2"
            />
          </label>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-zinc-400">
              top_k
              <input
                type="number"
                min={1}
                max={20}
                value={topK}
                onChange={(e) => setTopK(Math.max(1, Math.min(20, Number(e.target.value) || 4)))}
                className="w-16 rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
              />
            </label>
            <button
              type="button"
              disabled={loading || !query.trim() || !kbId}
              onClick={() => void runSearch()}
              className="ml-auto inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-violet-500 disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
              Search
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
          {error ? (
            <p className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
              {error}
            </p>
          ) : null}
          {!loading && !error && chunks.length === 0 ? (
            <p className="text-center text-xs text-zinc-500">Run a search to see retrieved context.</p>
          ) : null}
          {chunks.map((chunk, index) => (
            <article
              key={`${chunk.document_id ?? "doc"}-${chunk.chunk_index ?? index}`}
              className="rounded-xl border border-zinc-800 bg-zinc-950/80 p-3"
            >
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="rounded-md bg-emerald-500/15 px-2 py-0.5 text-[11px] font-semibold text-emerald-300">
                  {chunk.match_percent}% Match
                </span>
                {chunk.file_name ? (
                  <span className="rounded-md bg-zinc-800 px-2 py-0.5 text-[11px] text-zinc-300">
                    {chunk.file_name}
                  </span>
                ) : null}
                {chunk.page_number != null ? (
                  <span className="rounded-md bg-zinc-800 px-2 py-0.5 text-[11px] text-zinc-400">
                    p.{chunk.page_number}
                  </span>
                ) : null}
                {chunk.section ? (
                  <span className="rounded-md bg-zinc-800 px-2 py-0.5 text-[11px] text-zinc-400">
                    {chunk.section}
                  </span>
                ) : null}
              </div>
              <div className="mb-2 h-1.5 overflow-hidden rounded-full bg-zinc-800">
                <div
                  className={cn(
                    "h-full rounded-full transition-all",
                    chunk.match_percent >= 70
                      ? "bg-emerald-500"
                      : chunk.match_percent >= 40
                        ? "bg-amber-500"
                        : "bg-zinc-500",
                  )}
                  style={{ width: `${Math.max(4, Math.min(100, chunk.match_percent))}%` }}
                />
              </div>
              <p className="text-xs leading-relaxed text-zinc-300 whitespace-pre-wrap">{chunk.text}</p>
              <p className="mt-2 text-[10px] text-zinc-600">
                cosine distance {chunk.cosine_distance.toFixed(4)} · score{" "}
                {chunk.similarity_score.toFixed(4)}
              </p>
            </article>
          ))}
        </div>
      </aside>
    </div>
  );
}

"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  Database,
  FlaskConical,
  Loader2,
  Trash2,
  UploadCloud,
} from "lucide-react";

import { TestRetrievalDrawer } from "@/components/knowledge/TestRetrievalDrawer";
import { useToast } from "@/hooks/useToast";
import {
  deleteKnowledgeDocument,
  fetchKnowledgeDocuments,
  uploadKnowledgeDocumentAsync,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import type { KnowledgeAsset, KnowledgeDocumentStatus } from "@/types/knowledge";

const ACCEPT = ".pdf,.txt,.docx,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function StatusBadge({ asset }: { asset: KnowledgeAsset }) {
  const status: KnowledgeDocumentStatus = asset.status ?? "INDEXED";

  if (status === "INDEXED") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-2.5 py-1 text-[11px] font-semibold text-emerald-300 ring-1 ring-emerald-500/30">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        INDEXED
      </span>
    );
  }

  if (status === "PARSING" || status === "PENDING") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/15 px-2.5 py-1 text-[11px] font-semibold text-amber-200 ring-1 ring-amber-500/30">
        <Loader2 className="h-3 w-3 animate-spin" />
        {status}
        {typeof asset.progress === "number" ? ` ${asset.progress}%` : ""}
      </span>
    );
  }

  return (
    <span
      title={asset.error_message || "Indexing failed"}
      className="group relative inline-flex items-center gap-1.5 rounded-full bg-red-500/15 px-2.5 py-1 text-[11px] font-semibold text-red-300 ring-1 ring-red-500/30"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-red-400" />
      FAILED
      {asset.error_message ? (
        <span className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-2 hidden w-56 -translate-x-1/2 rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-[10px] font-normal normal-case text-zinc-300 shadow-lg group-hover:block">
          {asset.error_message}
        </span>
      ) : null}
    </span>
  );
}

function KnowledgeDashboardInner() {
  const searchParams = useSearchParams();
  const { showToast } = useToast();
  const activeBotId = useBotStore((s) => s.activeBotId);
  const agentProfiles = useBotStore((s) => s.agentProfiles);
  const connection = useBotStore((s) => s.connection);

  const kbId = useMemo(() => {
    return (
      searchParams.get("botId") ||
      searchParams.get("kbId") ||
      activeBotId ||
      connection?.botId ||
      Object.keys(agentProfiles)[0] ||
      null
    );
  }, [activeBotId, agentProfiles, connection?.botId, searchParams]);

  const botName = kbId ? agentProfiles[kbId]?.name ?? "Agent" : null;

  const [assets, setAssets] = useState<KnowledgeAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [dragging, setDragging] = useState(false);

  const loadAssets = useCallback(async () => {
    if (!kbId) {
      setAssets([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const response = await fetchKnowledgeDocuments(kbId);
      setAssets(response.documents);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Failed to load knowledge base."), "error");
    } finally {
      setLoading(false);
    }
  }, [kbId, showToast]);

  useEffect(() => {
    void loadAssets();
  }, [loadAssets]);

  // Poll while any document is pending/parsing.
  useEffect(() => {
    const busy = assets.some(
      (a) => a.status === "PENDING" || a.status === "PARSING",
    );
    if (!busy || !kbId) return;
    const timer = window.setInterval(() => {
      void loadAssets();
    }, 2500);
    return () => window.clearInterval(timer);
  }, [assets, kbId, loadAssets]);

  const onUploadFile = async (file: File) => {
    if (!kbId) return;
    setUploading(true);
    try {
      await uploadKnowledgeDocumentAsync(kbId, { file });
      showToast("Document queued for indexing.", "success");
      await loadAssets();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Upload failed."), "error");
    } finally {
      setUploading(false);
    }
  };

  const onDelete = async (asset: KnowledgeAsset) => {
    if (!kbId) return;
    setDeletingId(asset.id);
    try {
      await deleteKnowledgeDocument(kbId, asset.id);
      showToast("Document and vectors removed.", "success");
      await loadAssets();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Delete failed."), "error");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 text-xs font-medium text-zinc-500">
            <Database className="h-3.5 w-3.5" />
            Knowledge Base
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">
            Documents &amp; retrieval
          </h1>
          <p className="mt-1 text-sm text-zinc-400">
            {kbId
              ? `Indexing for ${botName} · collection org_* + bot filter`
              : "Select an agent to manage its knowledge base."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!kbId}
            onClick={() => setDrawerOpen(true)}
            className="inline-flex items-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-2 text-xs font-semibold text-zinc-100 transition hover:border-zinc-500 disabled:opacity-40"
          >
            <FlaskConical className="h-3.5 w-3.5" />
            Test Retrieval
          </button>
          <Link
            href="/dashboard"
            className="inline-flex items-center rounded-xl border border-zinc-800 px-4 py-2 text-xs font-medium text-zinc-400 hover:text-zinc-200"
          >
            Back
          </Link>
        </div>
      </div>

      {!kbId ? (
        <div className="rounded-2xl border border-dashed border-zinc-800 px-6 py-16 text-center text-sm text-zinc-500">
          Open an agent workspace or pass{" "}
          <code className="text-zinc-300">?botId=</code> to manage documents.
        </div>
      ) : (
        <>
          <section
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              const file = e.dataTransfer.files?.[0];
              if (file) void onUploadFile(file);
            }}
            className={cn(
              "rounded-2xl border border-dashed px-6 py-10 text-center transition",
              dragging
                ? "border-violet-500/60 bg-violet-500/5"
                : "border-zinc-800 bg-[#0d0d0f]/80",
            )}
          >
            <UploadCloud className="mx-auto mb-3 h-8 w-8 text-zinc-500" />
            <p className="text-sm font-medium text-zinc-200">Drop PDF, TXT, or DOCX</p>
            <p className="mt-1 text-xs text-zinc-500">
              Files are processed in the background (PENDING → PARSING → INDEXED)
            </p>
            <label className="mt-4 inline-flex cursor-pointer items-center gap-2 rounded-xl bg-violet-600 px-4 py-2 text-xs font-semibold text-white hover:bg-violet-500">
              {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              Choose file
              <input
                type="file"
                accept={ACCEPT}
                className="hidden"
                disabled={uploading}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void onUploadFile(file);
                  e.target.value = "";
                }}
              />
            </label>
          </section>

          <section className="overflow-hidden rounded-2xl border border-zinc-800 bg-[#0d0d0f]/90">
            <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
              <h2 className="text-sm font-semibold text-zinc-100">Documents</h2>
              <button
                type="button"
                onClick={() => void loadAssets()}
                className="text-xs text-zinc-500 hover:text-zinc-300"
              >
                Refresh
              </button>
            </div>
            {loading ? (
              <div className="flex items-center justify-center gap-2 py-16 text-sm text-zinc-500">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading…
              </div>
            ) : assets.length === 0 ? (
              <p className="py-16 text-center text-sm text-zinc-500">No documents yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full text-left text-sm">
                  <thead className="bg-zinc-950/80 text-[11px] uppercase tracking-wide text-zinc-500">
                    <tr>
                      <th className="px-4 py-3 font-medium">File</th>
                      <th className="px-4 py-3 font-medium">Status</th>
                      <th className="px-4 py-3 font-medium">Chunks</th>
                      <th className="px-4 py-3 font-medium">Created</th>
                      <th className="px-4 py-3 font-medium" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800/80">
                    {assets.map((asset) => (
                      <tr key={asset.id} className="hover:bg-zinc-900/40">
                        <td className="px-4 py-3">
                          <p className="font-medium text-zinc-100">{asset.file_name}</p>
                          <p className="text-[11px] text-zinc-500">{asset.source_type}</p>
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge asset={asset} />
                        </td>
                        <td className="px-4 py-3 text-zinc-300">{asset.chunk_count}</td>
                        <td className="px-4 py-3 text-xs text-zinc-500">
                          {new Date(asset.created_at).toLocaleString()}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            disabled={deletingId === asset.id}
                            onClick={() => void onDelete(asset)}
                            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-red-300 transition hover:bg-red-500/10 disabled:opacity-50"
                          >
                            {deletingId === asset.id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Trash2 className="h-3.5 w-3.5" />
                            )}
                            Delete
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}

      <TestRetrievalDrawer
        open={drawerOpen}
        kbId={kbId}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}

export default function KnowledgeDashboardPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center py-24 text-sm text-zinc-500">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading knowledge…
        </div>
      }
    >
      <KnowledgeDashboardInner />
    </Suspense>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Database, Loader2 } from "lucide-react";

import {
  advanceUploadStage,
  getStageProgress,
  KbDropzone,
} from "@/components/knowledge/KbDropzone";
import { KbAssetsTable } from "@/components/knowledge/KbAssetsTable";
import { KbChunksDrawer } from "@/components/knowledge/KbChunksDrawer";
import { useToast } from "@/hooks/useToast";
import {
  deleteKnowledgeAsset,
  fetchKnowledgeAssets,
  fetchKnowledgeChunks,
  reindexKnowledgeAsset,
  toggleKnowledgeAsset,
  uploadKnowledgeAsset,
} from "@/lib/api";
import { getApiErrorMessage } from "@/store/useBotStore";
import type { BotAgentProfile } from "@/types/agent";
import type { KnowledgeAsset, KnowledgeChunk, KnowledgeUploadStage } from "@/types/knowledge";

interface KnowledgeBaseManagerProps {
  botId: string;
  profile: BotAgentProfile;
  mode?: "direct" | "all";
  collectionId?: string;
  documentIds?: string[];
  onDocumentUploaded?: (documentId: string) => void;
  showTextTab?: boolean;
}

export function KnowledgeBaseManager({
  botId,
  profile,
  mode = "all",
  documentIds,
  onDocumentUploaded,
  showTextTab = false,
}: KnowledgeBaseManagerProps) {
  const { showToast } = useToast();
  const stageTimerRef = useRef<number | null>(null);

  const [assets, setAssets] = useState<KnowledgeAsset[]>([]);
  const [loadingAssets, setLoadingAssets] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadStage, setUploadStage] = useState<KnowledgeUploadStage>("idle");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [reindexingId, setReindexingId] = useState<string | null>(null);
  const [viewingChunksId, setViewingChunksId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [drawerFileName, setDrawerFileName] = useState<string | null>(null);
  const [drawerChunks, setDrawerChunks] = useState<KnowledgeChunk[]>([]);

  const clearStageTimer = (): void => {
    if (stageTimerRef.current !== null) {
      window.clearInterval(stageTimerRef.current);
      stageTimerRef.current = null;
    }
  };

  const startStageSimulation = (): void => {
    clearStageTimer();
    setUploadStage("uploading");
    setUploadProgress(getStageProgress("uploading"));

    stageTimerRef.current = window.setInterval(() => {
      setUploadStage((current) => {
        if (current === "complete" || current === "idle") {
          return current;
        }
        const next = advanceUploadStage(current);
        setUploadProgress(getStageProgress(next));
        return next;
      });
    }, 900);
  };

  const finishStageSimulation = (): void => {
    clearStageTimer();
    setUploadStage("complete");
    setUploadProgress(100);
    window.setTimeout(() => {
      setUploadStage("idle");
      setUploadProgress(0);
    }, 900);
  };

  useEffect(() => {
    return () => {
      clearStageTimer();
    };
  }, []);

  const loadAssets = useCallback(async (): Promise<void> => {
    setLoadingAssets(true);
    try {
      const response = await fetchKnowledgeAssets(botId);
      setAssets(response.documents);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить базу знаний."), "error");
    } finally {
      setLoadingAssets(false);
    }
  }, [botId, showToast]);

  useEffect(() => {
    void loadAssets();
  }, [loadAssets]);

  const handleUpload = async (payload: {
    file?: File;
    url?: string;
    text?: string;
    file_name?: string;
    crawl_depth?: number;
  }): Promise<void> => {
    setUploading(true);
    startStageSimulation();

    try {
      const response = await uploadKnowledgeAsset(botId, payload, (percent) => {
        if (percent >= 70) {
          setUploadStage("indexing");
          setUploadProgress((current) => Math.max(current, percent));
        }
      });

      finishStageSimulation();
      if (response.document_id) {
        onDocumentUploaded?.(response.document_id);
      }
      showToast(
        `${response.file_name}: ${response.chunks_stored} фрагментов проиндексировано в ChromaDB.`,
        "knowledge",
      );
      await loadAssets();
    } catch (error) {
      clearStageTimer();
      setUploadStage("idle");
      setUploadProgress(0);
      showToast(getApiErrorMessage(error, "Не удалось загрузить документ."), "error");
    } finally {
      setUploading(false);
    }
  };

  const handleToggle = async (asset: KnowledgeAsset, nextValue: boolean): Promise<void> => {
    setTogglingId(asset.id);
    try {
      const response = await toggleKnowledgeAsset(botId, {
        document_id: asset.id,
        is_context_active: nextValue,
      });
      setAssets((current) =>
        current.map((item) =>
          item.id === asset.id
            ? { ...item, is_context_active: response.is_context_active }
            : item,
        ),
      );
      showToast(
        nextValue
          ? `"${asset.file_name}" снова участвует в RAG-поиске.`
          : `"${asset.file_name}" исключён из similarity search.`,
        "knowledge",
      );
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось обновить статус документа."), "error");
    } finally {
      setTogglingId(null);
    }
  };

  const handleDelete = async (asset: KnowledgeAsset): Promise<void> => {
    setDeletingId(asset.id);
    try {
      const response = await deleteKnowledgeAsset(botId, asset.id);
      setAssets((current) => current.filter((item) => item.id !== asset.id));
      showToast(
        `${asset.file_name}: удалено ${response.vectors_removed} vector chunks.`,
        "knowledge",
      );
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось удалить документ."), "error");
    } finally {
      setDeletingId(null);
    }
  };

  const handleReindex = async (asset: KnowledgeAsset): Promise<void> => {
    setReindexingId(asset.id);
    try {
      const response = await reindexKnowledgeAsset(botId, asset.id, { crawl_depth: 1 });
      setAssets((current) =>
        current.map((item) =>
          item.id === asset.id
            ? {
                ...item,
                character_count: response.character_count,
                chunk_count: response.chunks_stored,
              }
            : item,
        ),
      );
      showToast(
        `${response.file_name}: переиндексировано ${response.chunks_stored} фрагментов.`,
        "knowledge",
      );
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось переиндексировать документ."), "error");
    } finally {
      setReindexingId(null);
    }
  };

  const handleViewChunks = async (asset: KnowledgeAsset): Promise<void> => {
    setViewingChunksId(asset.id);
    setDrawerOpen(true);
    setDrawerLoading(true);
    setDrawerFileName(asset.file_name);
    setDrawerChunks([]);

    try {
      const response = await fetchKnowledgeChunks(botId, asset.id);
      setDrawerChunks(response.chunks);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить чанки."), "error");
      setDrawerOpen(false);
    } finally {
      setDrawerLoading(false);
      setViewingChunksId(null);
    }
  };

  const visibleAssets =
    documentIds != null
      ? assets.filter((asset) => documentIds.includes(asset.id))
      : mode === "direct"
        ? assets
        : assets;

  return (
    <div className="space-y-6">
      {mode === "all" ? (
      <section className="rounded-2xl border border-zinc-800/90 bg-[#0d0d0f]/95 p-5 backdrop-blur-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <Database className="h-4 w-4 text-violet-300" />
              <h2 className="text-base font-semibold text-zinc-100">RAG Context Manager</h2>
            </div>
            <p className="mt-1 text-xs text-zinc-500">
              Векторная база знаний агента{" "}
              <span className="text-zinc-300">{profile.name}</span> · ChromaDB collection bound
              to bot id
            </p>
            <p className="mt-2 font-mono text-[11px] text-zinc-600">{botId}</p>
          </div>
          {loadingAssets ? <Loader2 className="h-4 w-4 animate-spin text-zinc-500" /> : null}
        </div>
      </section>
      ) : null}

      <KbDropzone
        uploading={uploading}
        uploadStage={uploadStage}
        uploadProgress={uploadProgress}
        showTextTab={showTextTab}
        onUploadFile={(file) => handleUpload({ file })}
        onUploadUrl={(url, crawlDepth) => handleUpload({ url, crawl_depth: crawlDepth })}
        onUploadText={(text, fileName) => handleUpload({ text, file_name: fileName })}
      />

      <KbAssetsTable
        assets={visibleAssets}
        loading={loadingAssets}
        togglingId={togglingId}
        deletingId={deletingId}
        reindexingId={reindexingId}
        viewingChunksId={viewingChunksId}
        onToggleActive={(asset, nextValue) => void handleToggle(asset, nextValue)}
        onViewChunks={(asset) => void handleViewChunks(asset)}
        onReindex={(asset) => void handleReindex(asset)}
        onDelete={(asset) => void handleDelete(asset)}
      />

      <KbChunksDrawer
        open={drawerOpen}
        loading={drawerLoading}
        fileName={drawerFileName}
        chunks={drawerChunks}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}

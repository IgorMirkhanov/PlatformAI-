export type KnowledgeSourceType = "file" | "text" | "web" | "google_drive";

export type KnowledgeDocumentStatus = "PENDING" | "PARSING" | "INDEXED" | "FAILED";

export type KnowledgeSyncStatus = "synced" | "indexing" | "disabled";

export type KnowledgeUploadStage =
  | "idle"
  | "uploading"
  | "chunking"
  | "indexing"
  | "complete";

export interface KnowledgeAsset {
  id: string;
  bot_id: string;
  file_name: string;
  source_type: KnowledgeSourceType;
  format?: string | null;
  character_count: number;
  chunk_count: number;
  is_context_active: boolean;
  status?: KnowledgeDocumentStatus;
  progress?: number;
  error_message?: string | null;
  created_at: string;
}

export interface KnowledgeAssetListResponse {
  bot_id: string;
  knowledge_base_id: string;
  documents: KnowledgeAsset[];
  total: number;
}

export interface KnowledgeUploadResponse {
  knowledge_base_id: string;
  document_id: string;
  file_name: string;
  character_count: number;
  chunks_stored: number;
  message: string;
  source_type: KnowledgeSourceType;
}

export interface KnowledgeToggleRequest {
  document_id: string;
  is_context_active: boolean;
}

export interface KnowledgeToggleResponse {
  bot_id: string;
  document_id: string;
  is_context_active: boolean;
  message: string;
}

export interface KnowledgeDeleteResponse {
  bot_id: string;
  document_id: string;
  deleted: boolean;
  vectors_removed: number;
  message: string;
}

export interface KnowledgeChunk {
  chunk_index: number;
  text: string;
  similarity_weight: number;
}

export interface KnowledgeChunksResponse {
  bot_id: string;
  document_id: string;
  file_name: string;
  chunks: KnowledgeChunk[];
  total: number;
}

export interface KnowledgeReindexRequest {
  crawl_depth?: number;
}

export interface KnowledgeReindexResponse {
  bot_id: string;
  document_id: string;
  file_name: string;
  character_count: number;
  chunks_stored: number;
  message: string;
}

export type KnowledgeFormatFilter = "all" | "pdf" | "docx_txt" | "web";

export type SimilarityScoreTier = "high" | "medium" | "low";

export interface SimilarityScoreDisplay {
  label: string;
  percent: number;
  tier: SimilarityScoreTier;
}

export const KNOWLEDGE_FORMAT_FILTERS: Array<{
  id: KnowledgeFormatFilter;
  label: string;
}> = [
  { id: "all", label: "Все" },
  { id: "pdf", label: "PDF" },
  { id: "docx_txt", label: "DOCX/TXT" },
  { id: "web", label: "Ссылки (Web)" },
];

export const KNOWLEDGE_PAGE_SIZE = 5;

export const UPLOAD_STAGE_LABELS: Record<
  Exclude<KnowledgeUploadStage, "idle">,
  string
> = {
  uploading: "Загрузка...",
  chunking: "Нарезка на чанки (Chunking)...",
  indexing: "Индексация в ChromaDB",
  complete: "Готово",
};

export const UPLOAD_STAGE_PROGRESS: Record<
  Exclude<KnowledgeUploadStage, "idle">,
  number
> = {
  uploading: 28,
  chunking: 58,
  indexing: 86,
  complete: 100,
};

export function formatKnowledgeFileSize(characterCount: number): string {
  if (characterCount >= 1_000_000) {
    return `${(characterCount / 1_000_000).toFixed(1)} MB`;
  }
  if (characterCount >= 1000) {
    return `${(characterCount / 1000).toFixed(1)} KB`;
  }
  return `${characterCount} B`;
}

export function formatKnowledgeDate(value: string): string {
  try {
    return new Intl.DateTimeFormat("ru-RU", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

export function getKnowledgeSyncStatus(asset: KnowledgeAsset): KnowledgeSyncStatus {
  if (!asset.is_context_active) {
    return "disabled";
  }
  const status = asset.status;
  if (status === "PENDING" || status === "PARSING") {
    return "indexing";
  }
  if (status === "FAILED") {
    return "disabled";
  }
  if (asset.chunk_count <= 0 && status !== "INDEXED") {
    return "indexing";
  }
  return "synced";
}

export function getKnowledgeSyncLabel(status: KnowledgeSyncStatus): string {
  if (status === "synced") {
    return "Синхронизировано";
  }
  if (status === "indexing") {
    return "Индексация…";
  }
  return "Отключено из поиска";
}

export function inferSourceTypeFromFileName(fileName: string): KnowledgeSourceType {
  const lower = fileName.toLowerCase();
  if (lower.startsWith("http://") || lower.startsWith("https://")) {
    return "web";
  }
  return "file";
}

export function getAssetFormatCategory(asset: KnowledgeAsset): Exclude<KnowledgeFormatFilter, "all"> {
  if (asset.source_type === "web") {
    return "web";
  }
  if (asset.file_name.toLowerCase().endsWith(".pdf")) {
    return "pdf";
  }
  return "docx_txt";
}

export function assetMatchesFormatFilter(
  asset: KnowledgeAsset,
  filter: KnowledgeFormatFilter,
): boolean {
  if (filter === "all") {
    return true;
  }
  return getAssetFormatCategory(asset) === filter;
}

export function formatSimilarityScore(weight: number): SimilarityScoreDisplay {
  const clamped = Math.min(Math.max(weight, 0), 1);
  const percent = Math.round(clamped * 100);
  const label = `${clamped.toFixed(2)} · ${percent}% match`;

  if (weight >= 0.85) {
    return { label, percent, tier: "high" };
  }
  if (weight >= 0.65) {
    return { label, percent, tier: "medium" };
  }
  return { label, percent, tier: "low" };
}

export function similarityBadgeClassName(tier: SimilarityScoreTier): string {
  if (tier === "high") {
    return "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30";
  }
  if (tier === "medium") {
    return "bg-violet-500/15 text-violet-200 ring-1 ring-violet-500/30";
  }
  return "bg-zinc-800/90 text-zinc-400 ring-1 ring-zinc-700";
}

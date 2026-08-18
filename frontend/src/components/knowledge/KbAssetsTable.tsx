"use client";

import { useMemo, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Eye,
  FileText,
  Globe,
  Loader2,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";

import { cn } from "@/lib/utils";
import {
  assetMatchesFormatFilter,
  formatKnowledgeDate,
  formatKnowledgeFileSize,
  getKnowledgeSyncLabel,
  getKnowledgeSyncStatus,
  KNOWLEDGE_FORMAT_FILTERS,
  KNOWLEDGE_PAGE_SIZE,
  type KnowledgeAsset,
  type KnowledgeFormatFilter,
} from "@/types/knowledge";

interface KbAssetsTableProps {
  assets: KnowledgeAsset[];
  loading: boolean;
  togglingId: string | null;
  deletingId: string | null;
  viewingChunksId: string | null;
  reindexingId: string | null;
  onToggleActive: (asset: KnowledgeAsset, nextValue: boolean) => void;
  onViewChunks: (asset: KnowledgeAsset) => void;
  onReindex: (asset: KnowledgeAsset) => void;
  onDelete: (asset: KnowledgeAsset) => void;
}

function AssetIcon({ asset }: { asset: KnowledgeAsset }) {
  if (asset.source_type === "web") {
    return <Globe className="h-4 w-4 text-cyan-300" />;
  }
  if (asset.file_name.toLowerCase().endsWith(".pdf")) {
    return <FileText className="h-4 w-4 text-red-300" />;
  }
  return <FileText className="h-4 w-4 text-violet-300" />;
}

function SyncBadge({ asset }: { asset: KnowledgeAsset }) {
  const status = getKnowledgeSyncStatus(asset);
  const label = getKnowledgeSyncLabel(status);

  return (
    <span className="inline-flex items-center gap-2 text-xs text-zinc-300">
      <span
        className={cn(
          "relative flex h-2.5 w-2.5 rounded-full",
          status === "synced" && "bg-emerald-400",
          status === "indexing" && "bg-amber-400",
          status === "disabled" && "bg-zinc-600",
        )}
      >
        {status === "synced" ? (
          <span className="absolute inset-0 animate-ping rounded-full bg-emerald-400/60" />
        ) : null}
      </span>
      {label}
    </span>
  );
}

export function KbAssetsTable({
  assets,
  loading,
  togglingId,
  deletingId,
  viewingChunksId,
  reindexingId,
  onToggleActive,
  onViewChunks,
  onReindex,
  onDelete,
}: KbAssetsTableProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [formatFilter, setFormatFilter] = useState<KnowledgeFormatFilter>("all");
  const [page, setPage] = useState(1);

  const filteredAssets = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return assets.filter((asset) => {
      if (!assetMatchesFormatFilter(asset, formatFilter)) {
        return false;
      }
      if (!query) {
        return true;
      }
      return asset.file_name.toLowerCase().includes(query);
    });
  }, [assets, formatFilter, searchQuery]);

  const totalPages = Math.max(1, Math.ceil(filteredAssets.length / KNOWLEDGE_PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageStart = filteredAssets.length === 0 ? 0 : (safePage - 1) * KNOWLEDGE_PAGE_SIZE + 1;
  const pageEnd = Math.min(safePage * KNOWLEDGE_PAGE_SIZE, filteredAssets.length);
  const paginatedAssets = filteredAssets.slice(
    (safePage - 1) * KNOWLEDGE_PAGE_SIZE,
    safePage * KNOWLEDGE_PAGE_SIZE,
  );

  const handleFilterChange = (next: KnowledgeFormatFilter): void => {
    setFormatFilter(next);
    setPage(1);
  };

  const handleSearchChange = (value: string): void => {
    setSearchQuery(value);
    setPage(1);
  };

  return (
    <section className="overflow-hidden rounded-2xl border border-zinc-800/90 bg-[#0d0d0f]/95 backdrop-blur-sm">
      <div className="border-b border-zinc-800 px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-zinc-100">Knowledge Assets</h3>
            <p className="mt-1 text-xs text-zinc-500">
              {assets.length > 0
                ? `${assets.length} источник(ов) в ChromaDB`
                : "Документы ещё не загружены"}
            </p>
          </div>
        </div>

        <div className="mt-4 space-y-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
            <input
              value={searchQuery}
              onChange={(event) => handleSearchChange(event.target.value)}
              placeholder="Поиск по названию документа..."
              className="h-10 w-full rounded-xl border border-zinc-800 bg-zinc-950/90 pl-10 pr-3 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500/40 focus:outline-none focus:ring-2 focus:ring-violet-500/15"
            />
          </div>

          <div className="flex flex-wrap gap-2">
            {KNOWLEDGE_FORMAT_FILTERS.map((filter) => {
              const active = formatFilter === filter.id;
              return (
                <button
                  key={filter.id}
                  type="button"
                  onClick={() => handleFilterChange(filter.id)}
                  className={cn(
                    "rounded-full border px-3 py-1.5 text-xs font-medium transition",
                    active
                      ? "border-violet-500/40 bg-violet-500/15 text-violet-200 shadow-[0_0_12px_rgba(139,92,246,0.15)]"
                      : "border-zinc-800 bg-zinc-950/70 text-zinc-500 hover:border-zinc-700 hover:text-zinc-300",
                  )}
                >
                  {filter.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="border-b border-zinc-800 bg-zinc-950/70 text-[11px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="px-5 py-3 font-medium">Файл</th>
              <th className="px-5 py-3 font-medium">Дата</th>
              <th className="px-5 py-3 font-medium">Размер / чанки</th>
              <th className="px-5 py-3 font-medium">Статус</th>
              <th className="px-5 py-3 font-medium">Активен в поиске</th>
              <th className="px-5 py-3 font-medium text-right">Действия</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} className="px-5 py-12 text-center text-zinc-500">
                  <Loader2 className="mx-auto h-5 w-5 animate-spin" />
                </td>
              </tr>
            ) : filteredAssets.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-5 py-12 text-center text-zinc-500">
                  {assets.length === 0
                    ? "Загрузите первый документ, чтобы включить RAG для этого агента."
                    : "Ничего не найдено по текущему фильтру или запросу."}
                </td>
              </tr>
            ) : (
              paginatedAssets.map((asset) => (
                <tr
                  key={asset.id}
                  className="border-b border-zinc-900/80 transition hover:bg-zinc-950/50"
                >
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-950/80">
                        <AssetIcon asset={asset} />
                      </div>
                      <div className="min-w-0">
                        <p className="truncate font-medium text-zinc-100">{asset.file_name}</p>
                        <p className="text-xs capitalize text-zinc-500">{asset.source_type}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-4 text-zinc-400">
                    {formatKnowledgeDate(asset.created_at)}
                  </td>
                  <td className="px-5 py-4 text-zinc-300">
                    {formatKnowledgeFileSize(asset.character_count)} · {asset.chunk_count} chunks
                  </td>
                  <td className="px-5 py-4">
                    <SyncBadge asset={asset} />
                  </td>
                  <td className="px-5 py-4">
                    <button
                      type="button"
                      role="switch"
                      aria-checked={asset.is_context_active}
                      disabled={togglingId === asset.id}
                      onClick={() => onToggleActive(asset, !asset.is_context_active)}
                      className={cn(
                        "relative h-7 w-12 rounded-full transition-colors disabled:opacity-50",
                        asset.is_context_active ? "bg-violet-600" : "bg-zinc-700",
                      )}
                    >
                      <span
                        className={cn(
                          "absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition-transform",
                          asset.is_context_active ? "translate-x-5" : "translate-x-0.5",
                        )}
                      />
                    </button>
                  </td>
                  <td className="px-5 py-4">
                    <div className="flex items-center justify-end gap-2">
                      {asset.source_type === "web" ? (
                        <button
                          type="button"
                          onClick={() => onReindex(asset)}
                          disabled={reindexingId === asset.id}
                          title="Переиндексировать"
                          className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-xs font-medium text-zinc-300 transition hover:border-cyan-500/30 hover:text-cyan-200 disabled:opacity-50"
                        >
                          <RefreshCw
                            className={cn(
                              "h-3.5 w-3.5",
                              reindexingId === asset.id && "animate-spin",
                            )}
                          />
                          Переиндексировать
                        </button>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => onViewChunks(asset)}
                        disabled={viewingChunksId === asset.id}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-xs font-medium text-zinc-300 transition hover:border-violet-500/30 hover:text-violet-200 disabled:opacity-50"
                      >
                        {viewingChunksId === asset.id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Eye className="h-3.5 w-3.5" />
                        )}
                        Посмотреть чанки
                      </button>
                      <button
                        type="button"
                        onClick={() => onDelete(asset)}
                        disabled={deletingId === asset.id}
                        className="inline-flex items-center justify-center rounded-lg border border-red-500/20 bg-red-500/10 p-2 text-red-400 transition hover:bg-red-500/20 disabled:opacity-50"
                        aria-label={`Удалить ${asset.file_name}`}
                      >
                        {deletingId === asset.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Trash2 className="h-4 w-4" />
                        )}
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {!loading && filteredAssets.length > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-800 px-5 py-3">
          <p className="text-xs text-zinc-500">
            Показывано {pageStart}–{pageEnd} из {filteredAssets.length} документов
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={safePage <= 1}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-800 text-zinc-400 transition hover:bg-zinc-900 disabled:opacity-40"
              aria-label="Предыдущая страница"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="min-w-[4.5rem] text-center text-xs tabular-nums text-zinc-400">
              {safePage} / {totalPages}
            </span>
            <button
              type="button"
              disabled={safePage >= totalPages}
              onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-800 text-zinc-400 transition hover:bg-zinc-900 disabled:opacity-40"
              aria-label="Следующая страница"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

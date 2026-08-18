"use client";

import { useRef, useState } from "react";
import { ChevronDown, Globe, Loader2, UploadCloud } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  UPLOAD_STAGE_LABELS,
  UPLOAD_STAGE_PROGRESS,
  type KnowledgeUploadStage,
} from "@/types/knowledge";

type UploadTab = "file" | "url" | "text";

interface KbDropzoneProps {
  uploading: boolean;
  uploadStage: KnowledgeUploadStage;
  uploadProgress: number;
  showTextTab?: boolean;
  onUploadFile: (file: File) => Promise<void>;
  onUploadUrl: (url: string, crawlDepth: number) => Promise<void>;
  onUploadText?: (text: string, fileName: string) => Promise<void>;
}

export function KbDropzone({
  uploading,
  uploadStage,
  uploadProgress,
  showTextTab = false,
  onUploadFile,
  onUploadUrl,
  onUploadText,
}: KbDropzoneProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [activeTab, setActiveTab] = useState<UploadTab>("file");
  const [isDragging, setIsDragging] = useState(false);
  const [urlValue, setUrlValue] = useState("");
  const [textValue, setTextValue] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [crawlDepth, setCrawlDepth] = useState(1);

  const stageLabel =
    uploadStage !== "idle" ? UPLOAD_STAGE_LABELS[uploadStage] : null;

  return (
    <section className="rounded-2xl border border-zinc-800/90 bg-[#0d0d0f]/95 p-5 backdrop-blur-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">Загрузка знаний</h3>
          <p className="mt-1 text-xs text-zinc-500">
            PDF, TXT, DOCX или crawl веб-страницы в ChromaDB
          </p>
        </div>
        <div className="flex gap-1.5 rounded-xl border border-zinc-800 bg-zinc-950/70 p-1">
          <button
            type="button"
            onClick={() => setActiveTab("file")}
            className={cn(
              "rounded-lg px-3 py-1.5 text-xs font-medium transition",
              activeTab === "file"
                ? "bg-violet-600/20 text-violet-200 ring-1 ring-violet-500/30"
                : "text-zinc-500 hover:text-zinc-300",
            )}
          >
            Файлы
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("url")}
            className={cn(
              "rounded-lg px-3 py-1.5 text-xs font-medium transition",
              activeTab === "url"
                ? "bg-violet-600/20 text-violet-200 ring-1 ring-violet-500/30"
                : "text-zinc-500 hover:text-zinc-300",
            )}
          >
            URL
          </button>
          {showTextTab ? (
            <button
              type="button"
              onClick={() => setActiveTab("text")}
              className={cn(
                "rounded-lg px-3 py-1.5 text-xs font-medium transition",
                activeTab === "text"
                  ? "bg-violet-600/20 text-violet-200 ring-1 ring-violet-500/30"
                  : "text-zinc-500 hover:text-zinc-300",
              )}
            >
              Вручную
            </button>
          ) : null}
        </div>
      </div>

      {activeTab === "file" ? (
        <div
          onDragOver={(event) => {
            event.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setIsDragging(false);
            const file = event.dataTransfer.files?.[0];
            if (file) {
              void onUploadFile(file);
            }
          }}
          onClick={() => fileInputRef.current?.click()}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              fileInputRef.current?.click();
            }
          }}
          role="button"
          tabIndex={0}
          className={cn(
            "flex min-h-[190px] cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed px-6 py-8 text-center transition",
            isDragging
              ? "border-violet-400 bg-violet-500/10"
              : "border-zinc-700 bg-zinc-950/70 hover:border-zinc-600 hover:bg-zinc-900/60",
          )}
        >
          <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-violet-500/10 ring-1 ring-violet-500/20">
            {uploading ? (
              <Loader2 className="h-5 w-5 animate-spin text-violet-300" />
            ) : (
              <UploadCloud className="h-5 w-5 text-violet-300" />
            )}
          </div>
          <p className="text-sm font-medium text-zinc-100">
            Перетащите файл или нажмите для выбора
          </p>
          <p className="mt-1 text-xs text-zinc-500">PDF · TXT · DOCX · MD · CSV · JSON</p>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.txt,.docx,.md,.markdown,.csv,.json,text/plain,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) {
                void onUploadFile(file);
              }
              event.target.value = "";
            }}
          />
        </div>
      ) : activeTab === "text" ? (
        <div className="space-y-3 rounded-2xl border border-dashed border-zinc-700 bg-zinc-950/70 p-5">
          <label className="text-xs font-medium text-zinc-400">Текст знаний</label>
          <textarea
            value={textValue}
            onChange={(event) => setTextValue(event.target.value)}
            rows={8}
            placeholder="Вставьте FAQ, прайс, скрипт продаж…"
            className="w-full resize-y rounded-xl border border-zinc-800 bg-zinc-950/80 px-3 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500/40 focus:outline-none focus:ring-2 focus:ring-violet-500/15"
          />
          <button
            type="button"
            disabled={uploading || !textValue.trim() || !onUploadText}
            onClick={() => void onUploadText?.(textValue.trim(), "manual-entry.txt")}
            className="inline-flex h-11 items-center justify-center rounded-xl bg-gradient-to-r from-violet-600 to-purple-600 px-4 text-sm font-semibold text-white disabled:opacity-40"
          >
            Сохранить в базу
          </button>
        </div>
      ) : (
        <div className="space-y-3 rounded-2xl border border-dashed border-zinc-700 bg-zinc-950/70 p-5">
          <label className="text-xs font-medium text-zinc-400">URL страницы для crawl</label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative min-w-0 flex-1">
              <Globe className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
              <input
                value={urlValue}
                onChange={(event) => setUrlValue(event.target.value)}
                placeholder="https://company.com/docs/pricing"
                className="h-11 w-full rounded-xl border border-zinc-800 bg-zinc-950/80 pl-10 pr-3 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500/40 focus:outline-none focus:ring-2 focus:ring-violet-500/15"
              />
            </div>
            <button
              type="button"
              disabled={uploading || !urlValue.trim()}
              onClick={() => void onUploadUrl(urlValue.trim(), crawlDepth)}
              className="inline-flex h-11 items-center justify-center rounded-xl bg-gradient-to-r from-violet-600 to-purple-600 px-4 text-sm font-semibold text-white shadow-glow-purple disabled:opacity-40"
            >
              Crawl URL
            </button>
          </div>

          <div className="rounded-xl border border-zinc-800/80 bg-zinc-950/60">
            <button
              type="button"
              onClick={() => setShowAdvanced((open) => !open)}
              className="flex w-full items-center justify-between px-4 py-3 text-left text-xs font-medium text-zinc-400 transition hover:text-zinc-200"
            >
              <span>Расширенные параметры crawler</span>
              <ChevronDown
                className={cn("h-4 w-4 transition", showAdvanced && "rotate-180")}
              />
            </button>
            {showAdvanced ? (
              <div className="border-t border-zinc-800/80 px-4 pb-4 pt-3">
                <label htmlFor="crawl-depth" className="text-xs font-medium text-zinc-400">
                  Глубина парсинга (Depth limit)
                </label>
                <div className="mt-2 flex items-center gap-3">
                  <input
                    id="crawl-depth"
                    type="number"
                    min={1}
                    max={5}
                    value={crawlDepth}
                    onChange={(event) => {
                      const next = Number.parseInt(event.target.value, 10);
                      if (Number.isNaN(next)) {
                        setCrawlDepth(1);
                        return;
                      }
                      setCrawlDepth(Math.min(5, Math.max(1, next)));
                    }}
                    className="h-10 w-24 rounded-xl border border-zinc-800 bg-zinc-950/80 px-3 text-sm tabular-nums text-zinc-100 focus:border-violet-500/40 focus:outline-none focus:ring-2 focus:ring-violet-500/15"
                  />
                  <p className="text-xs text-zinc-500">
                    По умолчанию 1 страница — ограничивает широкие crawl-запуски.
                  </p>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}

      {uploadStage !== "idle" ? (
        <div className="mt-4">
          <div className="mb-1.5 flex items-center justify-between text-xs">
            <span className="text-violet-200">{stageLabel}</span>
            <span className="text-zinc-500">{uploadProgress}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-zinc-900 ring-1 ring-zinc-800">
            <div
              className="h-full rounded-full bg-gradient-to-r from-violet-500 via-purple-500 to-violet-400 transition-all duration-500 ease-out"
              style={{ width: `${uploadProgress}%` }}
            />
          </div>
        </div>
      ) : null}
    </section>
  );
}

export function advanceUploadStage(
  current: KnowledgeUploadStage,
): KnowledgeUploadStage {
  if (current === "uploading") return "chunking";
  if (current === "chunking") return "indexing";
  if (current === "indexing") return "complete";
  return current;
}

export function getStageProgress(stage: KnowledgeUploadStage): number {
  if (stage === "idle") return 0;
  return UPLOAD_STAGE_PROGRESS[stage];
}

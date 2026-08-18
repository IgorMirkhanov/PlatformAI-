"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { KnowledgeBaseManager } from "@/components/knowledge/KnowledgeBaseManager";
import { PageSkeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/hooks/useToast";
import { useAgentWorkspace } from "@/hooks/useAgentWorkspace";
import {
  fetchAgentRagCollections,
  updateAgentRagCollection,
} from "@/lib/api";
import { getApiErrorMessage } from "@/store/useBotStore";
import { FUNCTION_NAME_PATTERN, type AgentRagCollection } from "@/types/agent";

export default function AgentRagEditorPage() {
  const params = useParams<{ id: string; ragId: string }>();
  const botId = params.id;
  const ragId = params.ragId;
  const router = useRouter();
  const { profile, loading } = useAgentWorkspace(botId);
  const { showToast } = useToast();
  const [item, setItem] = useState<AgentRagCollection | null>(null);
  const [functionName, setFunctionName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const response = await fetchAgentRagCollections(botId);
    const found = (response.items || []).find((row) => row.id === ragId) ?? null;
    if (!found) {
      router.replace(`/bots/${botId}/knowledge-base/agent-rag`);
      return;
    }
    setItem(found);
    setFunctionName(found.function_name);
    setDescription(found.description || "");
  }, [botId, ragId, router]);

  useEffect(() => {
    void load().catch((error) => {
      showToast(getApiErrorMessage(error, "Не удалось открыть коллекцию."), "error");
    });
  }, [load, showToast]);

  const persist = async (documentIds?: string[]): Promise<void> => {
    if (!FUNCTION_NAME_PATTERN.test(functionName.trim())) {
      showToast("Название: только латиница, цифры и _ , начинается с буквы.", "error");
      return;
    }
    setSaving(true);
    try {
      const updated = await updateAgentRagCollection(botId, ragId, {
        function_name: functionName.trim(),
        description,
        document_ids: documentIds ?? item?.document_ids ?? [],
      });
      setItem(updated);
      showToast("Коллекция сохранена.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось сохранить коллекцию."), "error");
    } finally {
      setSaving(false);
    }
  };

  if ((loading && !profile) || !item) return <PageSkeleton />;
  if (!profile) return null;

  return (
    <div className="space-y-5">
      <Link
        href={`/bots/${botId}/knowledge-base/agent-rag`}
        className="inline-flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-200"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        К списку коллекций
      </Link>

      <div className="rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-5 space-y-4">
        <div>
          <label className="text-xs font-medium text-zinc-400">Название функции</label>
          <input
            value={functionName}
            onChange={(event) => setFunctionName(event.target.value)}
            placeholder="alexandrite_db"
            className="mt-1.5 h-11 w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 font-mono text-sm text-zinc-100 focus:border-violet-500/40 focus:outline-none"
          />
          <p className="mt-1 text-[11px] text-zinc-600">Только латинские буквы, цифры и _</p>
        </div>
        <div>
          <label className="text-xs font-medium text-zinc-400">Условия вызова</label>
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            rows={4}
            placeholder="Запросы про натуральные камни, опалы, розницу, опт..."
            className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm text-zinc-100 focus:border-violet-500/40 focus:outline-none"
          />
        </div>
        <button
          type="button"
          disabled={saving}
          onClick={() => void persist()}
          className="rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
        >
          Сохранить описание
        </button>
      </div>

      <KnowledgeBaseManager
        botId={botId}
        profile={profile}
        mode="direct"
        documentIds={item.document_ids}
        onDocumentUploaded={(documentId) => {
          const next = Array.from(new Set([...(item.document_ids || []), documentId]));
          void persist(next);
        }}
      />
    </div>
  );
}

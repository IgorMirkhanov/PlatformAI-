"use client";

import { useCallback, useEffect, useState } from "react";
import { BookOpen, Loader2 } from "lucide-react";

import { NeuralModelSidebar } from "@/components/prompting/NeuralModelSidebar";
import { SystemPromptEditor } from "@/components/prompting/SystemPromptEditor";
import { SaveBar } from "@/components/bots/SaveBar";
import { Toggle } from "@/components/ui/Toggle";
import {
  enhanceBotPrompt,
  fetchKnowledgeBaseDocuments,
  updateKnowledgeDocumentContext,
} from "@/lib/api";
import { useToast } from "@/hooks/useToast";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import type { BotAgentProfile } from "@/types/agent";
import type { KnowledgeBaseDocument } from "@/types/knowledge-base";
import {
  revealPromptWithFade,
  type PromptingContextVisibility,
  type PromptingModelConfig,
} from "@/types/prompting";

interface AgentPromptingTabProps {
  botId: string;
  profile: BotAgentProfile;
}

export function AgentPromptingTab({ botId, profile }: AgentPromptingTabProps) {
  const saveAgentPrompting = useBotStore((state) => state.saveAgentPrompting);
  const profileSaving = useBotStore((state) => state.profileSaving[botId] ?? false);
  const { showToast } = useToast();

  const [instructions, setInstructions] = useState(profile.prompt_instructions);
  const [model, setModel] = useState<PromptingModelConfig>({
    llm_model_name: profile.llm_model_name,
    llm_temperature: profile.llm_temperature,
  });
  const [visibility, setVisibility] = useState<PromptingContextVisibility>({
    show_username_visibility: profile.show_username_visibility,
    show_messenger_visibility: profile.show_messenger_visibility,
    show_datetime_visibility: profile.show_datetime_visibility ?? false,
  });

  const [enhancing, setEnhancing] = useState(false);
  const [revealing, setRevealing] = useState(false);
  const [documents, setDocuments] = useState<KnowledgeBaseDocument[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(true);
  const [contextUpdatingId, setContextUpdatingId] = useState<string | null>(null);

  useEffect(() => {
    setInstructions(profile.prompt_instructions);
    setModel({
      llm_model_name: profile.llm_model_name,
      llm_temperature: profile.llm_temperature,
    });
    setVisibility({
      show_username_visibility: profile.show_username_visibility,
      show_messenger_visibility: profile.show_messenger_visibility,
      show_datetime_visibility: profile.show_datetime_visibility ?? false,
    });
  }, [profile]);

  const loadDocuments = useCallback(async (): Promise<void> => {
    setDocumentsLoading(true);
    try {
      const response = await fetchKnowledgeBaseDocuments(botId);
      setDocuments(response.documents);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить базу знаний."), "error");
    } finally {
      setDocumentsLoading(false);
    }
  }, [botId, showToast]);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  const handleEnhance = async (): Promise<void> => {
    const source = instructions.trim();
    if (!source) {
      showToast("Добавьте инструкцию перед улучшением.", "error");
      return;
    }

    setEnhancing(true);
    try {
      const response = await enhanceBotPrompt(botId, { prompt_instructions: source });
      setRevealing(true);
      await revealPromptWithFade(response.enhanced_prompt, setInstructions);
      showToast("Промпт улучшен через AI-оркестратор.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось улучшить промпт."), "error");
    } finally {
      setEnhancing(false);
      setRevealing(false);
    }
  };

  const handleContextToggle = async (
    document: KnowledgeBaseDocument,
    isContextActive: boolean,
  ): Promise<void> => {
    setContextUpdatingId(document.id);
    setDocuments((current) =>
      current.map((item) =>
        item.id === document.id ? { ...item, is_context_active: isContextActive } : item,
      ),
    );

    try {
      await updateKnowledgeDocumentContext(botId, document.id, {
        is_context_active: isContextActive,
      });
      showToast(
        isContextActive
          ? `${document.file_name} подключён к RAG-контексту.`
          : `${document.file_name} отключён от RAG-контекста.`,
        "success",
      );
    } catch (error) {
      setDocuments((current) =>
        current.map((item) =>
          item.id === document.id
            ? { ...item, is_context_active: document.is_context_active }
            : item,
        ),
      );
      showToast(getApiErrorMessage(error, "Не удалось обновить контекст документа."), "error");
    } finally {
      setContextUpdatingId(null);
    }
  };

  const handleSave = async (): Promise<void> => {
    try {
      await saveAgentPrompting(botId, {
        prompt_instructions: instructions.trim(),
        llm_model_name: model.llm_model_name,
        llm_temperature: model.llm_temperature,
        show_username_visibility: visibility.show_username_visibility,
        show_messenger_visibility: visibility.show_messenger_visibility,
        show_datetime_visibility: visibility.show_datetime_visibility,
      });
      showToast("Промпт и параметры модели сохранены.", "prompting");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось сохранить промптинг."), "error");
    }
  };

  return (
    <div className="space-y-6 pb-28">
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <SystemPromptEditor
          value={instructions}
          onChange={setInstructions}
          onEnhance={handleEnhance}
          enhancing={enhancing}
          revealing={revealing}
          disabled={profileSaving}
          agentName={profile.name}
        />

        <NeuralModelSidebar
          model={model}
          visibility={visibility}
          onModelChange={setModel}
          onVisibilityChange={setVisibility}
          disabled={profileSaving || enhancing || revealing}
        />
      </div>

      <section className="moonai-panel">
        <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-violet-300/70">
              RAG Context Pool
            </p>
            <h3 className="mt-1 text-lg font-semibold text-zinc-50">Контекст базы знаний</h3>
            <p className="mt-1 text-xs text-zinc-500">
              Активные документы участвуют в vector search во время диалога.
            </p>
          </div>
          <span className="rounded-full border border-zinc-800 bg-zinc-950/60 px-3 py-1 text-xs text-zinc-400">
            {documents.filter((doc) => doc.is_context_active).length} / {documents.length} активно
          </span>
        </div>

        {documentsLoading ? (
          <div className="flex min-h-[160px] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-violet-400" />
          </div>
        ) : documents.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-zinc-800 bg-black/20 px-6 py-10 text-center">
            <BookOpen className="mx-auto h-8 w-8 text-zinc-600" />
            <p className="mt-3 text-sm text-zinc-300">Документы не найдены</p>
            <p className="mt-1 text-xs text-zinc-500">
              Загрузите знания во вкладке «База знаний», затем подключите их здесь.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {documents.map((document) => (
              <div
                key={document.id}
                className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-zinc-800/80 bg-zinc-950/40 px-4 py-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate font-mono text-sm text-zinc-100">{document.file_name}</p>
                  <p className="mt-1 text-xs text-zinc-500">
                    {document.chunk_count} фрагм. ·{" "}
                    {document.character_count.toLocaleString("ru-RU")} симв. · {document.source_type}
                  </p>
                </div>
                <Toggle
                  checked={document.is_context_active}
                  disabled={contextUpdatingId === document.id}
                  onChange={(checked) => void handleContextToggle(document, checked)}
                  label={document.is_context_active ? "В контексте" : "Отключён"}
                />
              </div>
            ))}
          </div>
        )}
      </section>

      <SaveBar
        onSave={handleSave}
        saving={profileSaving}
        label="Сохранить промпт"
      />
    </div>
  );
}

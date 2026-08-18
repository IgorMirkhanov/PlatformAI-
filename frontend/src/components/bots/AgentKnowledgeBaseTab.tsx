"use client";

import { KnowledgeBaseManager } from "@/components/knowledge/KnowledgeBaseManager";
import type { BotAgentProfile } from "@/types/agent";

interface AgentKnowledgeBaseTabProps {
  botId: string;
  profile: BotAgentProfile;
  mode?: "direct" | "all";
  collectionId?: string;
  documentIds?: string[];
  onDocumentUploaded?: (documentId: string) => void;
}

export function AgentKnowledgeBaseTab({
  botId,
  profile,
  mode = "all",
  collectionId,
  documentIds,
  onDocumentUploaded,
}: AgentKnowledgeBaseTabProps) {
  return (
    <KnowledgeBaseManager
      botId={botId}
      profile={profile}
      mode={mode}
      collectionId={collectionId}
      documentIds={documentIds}
      onDocumentUploaded={onDocumentUploaded}
      showTextTab={mode === "direct"}
    />
  );
}

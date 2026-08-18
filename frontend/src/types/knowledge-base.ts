export interface KnowledgeBaseDocument {
  id: string;
  bot_id: string;
  file_name: string;
  source_type: "file" | "text" | "web" | "google_drive";
  format?: string | null;
  character_count: number;
  chunk_count: number;
  is_context_active: boolean;
  created_at: string;
}

export interface KnowledgeBaseDocumentListResponse {
  bot_id: string;
  knowledge_base_id: string;
  documents: KnowledgeBaseDocument[];
  total: number;
}

export interface KnowledgeBaseUploadResponse {
  knowledge_base_id: string;
  document_id: string;
  file_name: string;
  character_count: number;
  chunks_stored: number;
  message: string;
}

export interface KnowledgeBaseDeleteResponse {
  bot_id: string;
  document_id: string;
  deleted: boolean;
  vectors_removed: number;
  message: string;
}

export interface KnowledgeBaseTextUploadRequest {
  knowledge_base_id: string;
  text: string;
  file_name?: string;
}

export interface KnowledgeBaseDocumentContextUpdate {
  is_context_active: boolean;
}

export interface KnowledgeBaseDocumentContextResponse {
  bot_id: string;
  document_id: string;
  is_context_active: boolean;
  message: string;
}

export interface GoogleSyncRequest {
  google_url: string;
}

export interface GoogleSyncAcceptedResponse {
  bot_id: string;
  document_id: string;
  google_url: string;
  format: string;
  status: "accepted";
  message: string;
}

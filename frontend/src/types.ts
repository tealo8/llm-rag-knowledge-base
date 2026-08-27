export type Role = "admin" | "editor" | "viewer";
export type Visibility = "organization" | "restricted" | "private";
export type KnowledgeBasePermission = "view" | "upload" | "edit" | "admin";

export interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
}

export interface PageParams {
  page?: number;
  pageSize?: number;
  q?: string;
}

export interface User {
  id: string;
  org_id: string;
  organization: string;
  username: string;
  display_name: string;
  email: string;
  role: Role;
  groups: string[];
}

export interface Group {
  id: string;
  name: string;
  description: string;
  member_count: number;
}

export interface AdminUser {
  id: string;
  username: string;
  display_name: string;
  email: string;
  role: Role;
  active: boolean;
  groups: Group[];
}

export interface KnowledgeBase {
  id: string;
  name: string;
  slug: string;
  description: string;
  status: "active" | "archived";
  permission: KnowledgeBasePermission;
  document_count: number;
  created_at: string;
}

export interface KnowledgeBaseMember {
  user_id: string;
  username: string;
  display_name: string;
  email: string;
  role: Role;
  permission: KnowledgeBasePermission | null;
}

export interface DocumentItem {
  id: string;
  owner_id: string;
  knowledge_base_id: string;
  filename: string;
  title: string;
  content_type: string;
  size_bytes: number;
  visibility: Visibility;
  status: "processing" | "indexed" | "failed";
  processing_stage: "queued" | "parsing" | "embedding" | "indexed" | "failed";
  task_id: string | null;
  chunk_count: number;
  owner_name: string;
  groups: Group[];
  allowed_user_ids: string[];
  tags: string[];
  version_group_id: string;
  version_number: number;
  is_current: boolean;
  archived_at: string | null;
  chunk_strategy: "fixed" | "semantic";
  created_at: string;
  error: string | null;
}

export interface Citation {
  index: number;
  document_id: string;
  chunk_id: string;
  title: string;
  filename: string;
  page_number: number | null;
  paragraph_number: number | null;
  excerpt: string;
  score: number;
}

export interface ChatResult {
  answer: string;
  citations: Citation[];
  retrieval: Record<string, string | number>;
  conversation_id: string;
  message_id: string;
}

export interface Chunk {
  id: string;
  document_id: string;
  title: string;
  page_number: number | null;
  paragraph_number: number | null;
  text: string;
}

export interface ConversationSummary {
  id: string;
  knowledge_base_id: string;
  knowledge_base_name: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ConversationMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  metrics: Record<string, string | number>;
  feedback: "up" | "down" | null;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ConversationMessage[];
}

export interface RagSettings {
  chunk_strategy: "fixed" | "semantic";
  chunk_size: number;
  chunk_overlap: number;
  top_k: number;
  lexical_weight: number;
  vector_weight: number;
  bm25_enabled: boolean;
  reranker_enabled: boolean;
  similarity_threshold: number;
  temperature: number;
  strict_rag: boolean;
  max_context_chars: number;
  max_history_messages: number;
  prompt_injection_filter: boolean;
  sensitive_words: string[];
  system_prompt: string;
}

export interface AuditLog {
  id: string;
  user_name: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  query: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ModelState {
  model: string;
  ready: boolean;
  size_bytes?: number | null;
  parameter_size?: string | null;
  quantization?: string | null;
  dimensions?: number | null;
  capabilities?: string[];
}

export interface SystemStatus {
  models: {
    reachable: boolean;
    error?: string;
    generation: ModelState;
    embedding: ModelState;
  };
  index: {
    configured_model: string;
    current_chunks: number;
    stale_chunks: number;
    total_chunks: number;
    versions: Array<{
      embedding_model: string;
      embedding_dimensions: number;
      chunk_count: number;
    }>;
  };
  vector_store: {
    provider: string;
    ready: boolean;
    isolation?: string;
    error?: string;
  };
}

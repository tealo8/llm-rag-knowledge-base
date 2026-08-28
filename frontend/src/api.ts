import type {
  AdminUser, AuditLog, ChatResult, Chunk, ConversationDetail, ConversationSummary,
  DocumentItem, Group, KnowledgeBase, KnowledgeBaseMember, KnowledgeBasePermission, Citation,
  PageParams, PageResult, RagSettings, Role, SystemStatus, User, Visibility,
} from "./types";

const API_BASE = import.meta.env.VITE_API_URL ?? "/api";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, token?: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (typeof options.body === "string" && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "请求失败" }));
    throw new ApiError(payload.detail ?? "请求失败", response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function pagedRequest<T>(path: string, token: string): Promise<PageResult<T>> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "请求失败" }));
    throw new ApiError(payload.detail ?? "请求失败", response.status);
  }
  const items = await response.json() as T[];
  const pageSize = Number(response.headers.get("X-Page-Size")) || items.length || 20;
  const total = Number(response.headers.get("X-Total-Count")) || 0;
  return {
    items,
    total,
    page: Number(response.headers.get("X-Page")) || 1,
    pageSize,
    totalPages: Number(response.headers.get("X-Total-Pages")) || (total ? Math.ceil(total / pageSize) : 0),
  };
}

function pageQuery(params: PageParams = {}, extra: Record<string, string | number | boolean | undefined> = {}) {
  const query = new URLSearchParams();
  query.set("page", String(params.page ?? 1));
  query.set("page_size", String(params.pageSize ?? 20));
  if (params.q?.trim()) query.set("q", params.q.trim());
  Object.entries(extra).forEach(([key, value]) => {
    if (value !== undefined) query.set(key, String(value));
  });
  return query.toString();
}

async function collectPages<T>(fetchPage: (page: number) => Promise<PageResult<T>>) {
  const first = await fetchPage(1);
  const items = [...first.items];
  for (let page = 2; page <= first.totalPages; page += 1) {
    items.push(...(await fetchPage(page)).items);
  }
  return items;
}

interface UploadOptions {
  knowledgeBaseId: string;
  title: string;
  visibility: Visibility;
  groupIds: string[];
  userIds: string[];
  tags: string[];
  chunkStrategy: "fixed" | "semantic";
  versionOf?: string;
  onProgress?: (percentage: number) => void;
}

async function directUpload(token: string, file: File, options: UploadOptions) {
  const body = new FormData();
  body.append("file", file);
  body.append("title", options.title);
  body.append("knowledge_base_id", options.knowledgeBaseId);
  body.append("visibility", options.visibility);
  body.append("group_ids", JSON.stringify(options.groupIds));
  body.append("user_ids", JSON.stringify(options.userIds));
  body.append("tags", JSON.stringify(options.tags));
  body.append("chunk_strategy", options.chunkStrategy);
  if (options.versionOf) body.append("version_of", options.versionOf);
  const result = await request<DocumentItem>("/documents", token, { method: "POST", body });
  options.onProgress?.(100);
  return result;
}

async function chunkedUpload(token: string, file: File, options: UploadOptions) {
  const chunkSize = 5 * 1024 * 1024;
  const session = await request<{ id: string; chunk_size: number }>("/uploads", token, {
    method: "POST",
    body: JSON.stringify({
      knowledge_base_id: options.knowledgeBaseId,
      filename: file.name,
      content_type: file.type || "application/octet-stream",
      total_size: file.size,
      chunk_size: chunkSize,
      title: options.title,
      visibility: options.visibility,
      group_ids: options.groupIds,
      user_ids: options.userIds,
      tags: options.tags,
      chunk_strategy: options.chunkStrategy,
      version_of: options.versionOf ?? null,
    }),
  });
  try {
    let part = 0;
    for (let offset = 0; offset < file.size; offset += session.chunk_size) {
      const end = Math.min(offset + session.chunk_size, file.size);
      await request(`/uploads/${session.id}/parts/${part}`, token, {
        method: "PUT",
        headers: { "Content-Type": "application/octet-stream" },
        body: await file.slice(offset, end).arrayBuffer(),
      });
      part += 1;
      options.onProgress?.(Math.round((end / file.size) * 95));
    }
    const completed = await request<{ document_id: string; document: DocumentItem }>(`/uploads/${session.id}/complete`, token, { method: "POST" });
    options.onProgress?.(100);
    return completed.document;
  } catch (error) {
    await request(`/uploads/${session.id}`, token, { method: "DELETE" }).catch(() => undefined);
    throw error;
  }
}

export const api = {
  login: (username: string, password: string) => request<{ access_token: string; user: User }>("/auth/login", undefined, {
    method: "POST", body: JSON.stringify({ username, password }),
  }),
  me: (token: string) => request<User>("/auth/me", token),

  knowledgeBasePage: (token: string, params: PageParams = {}, includeArchived = false) =>
    pagedRequest<KnowledgeBase>(`/knowledge-bases?${pageQuery(params, { include_archived: includeArchived })}`, token),
  knowledgeBases: (token: string, includeArchived = false) =>
    collectPages((page) => pagedRequest<KnowledgeBase>(`/knowledge-bases?${pageQuery({ page, pageSize: 100 }, { include_archived: includeArchived })}`, token)),
  createKnowledgeBase: (token: string, values: { name: string; slug: string; description: string }) =>
    request<KnowledgeBase>("/knowledge-bases", token, { method: "POST", body: JSON.stringify(values) }),
  updateKnowledgeBase: (token: string, id: string, values: Partial<Pick<KnowledgeBase, "name" | "description" | "status" | "tags" | "avatar_url" | "allow_qa" | "allow_upload" | "quota_documents" | "quota_bytes">> & { rag_settings?: Record<string, unknown> }) =>
    request<KnowledgeBase>(`/knowledge-bases/${id}`, token, { method: "PATCH", body: JSON.stringify(values) }),
  deleteKnowledgeBase: (token: string, id: string) => request<void>(`/knowledge-bases/${id}`, token, { method: "DELETE" }),
  knowledgeBaseStats: (token: string, id: string) => request<{ knowledge_base_id: string; document_count: number; chunk_count: number; question_count: number; prompt_tokens: number; completion_tokens: number; cited_question_count: number; answer_success_rate: number }>(`/knowledge-bases/${id}/stats`, token),
  knowledgeBaseMemberPage: (token: string, id: string, params: PageParams = {}) =>
    pagedRequest<KnowledgeBaseMember>(`/knowledge-bases/${id}/access?${pageQuery(params)}`, token),
  knowledgeBaseMembers: (token: string, id: string) =>
    collectPages((page) => pagedRequest<KnowledgeBaseMember>(`/knowledge-bases/${id}/access?${pageQuery({ page, pageSize: 100 })}`, token)),
  setKnowledgeBaseAccess: (token: string, id: string, userId: string, permission: KnowledgeBasePermission | null) =>
    request<void>(`/knowledge-bases/${id}/access`, token, { method: "PUT", body: JSON.stringify({ user_id: userId, permission }) }),

  documentPage: (token: string, knowledgeBaseId: string, params: PageParams & { includeVersions?: boolean; visibility?: Visibility | "all"; tag?: string } = {}) =>
    pagedRequest<DocumentItem>(`/documents?${pageQuery(params, {
      knowledge_base_id: knowledgeBaseId,
      include_versions: params.includeVersions ?? false,
      visibility: params.visibility && params.visibility !== "all" ? params.visibility : undefined,
      tag: params.tag,
    })}`, token),
  documents: (token: string, knowledgeBaseId: string, includeVersions = false) =>
    collectPages((page) => pagedRequest<DocumentItem>(`/documents?${pageQuery({ page, pageSize: 100 }, { knowledge_base_id: knowledgeBaseId, include_versions: includeVersions })}`, token)),
  document: (token: string, documentId: string) => request<DocumentItem>(`/documents/${documentId}`, token),
  documentPreview: (token: string, documentId: string) => request<{ id: string; title: string; filename: string; content_type: string; text: string }>(`/documents/${documentId}/preview`, token),
  documentVersionPage: (token: string, documentId: string, params: PageParams = {}) =>
    pagedRequest<DocumentItem>(`/documents/${documentId}/versions?${pageQuery(params)}`, token),
  documentVersions: (token: string, documentId: string) =>
    collectPages((page) => pagedRequest<DocumentItem>(`/documents/${documentId}/versions?${pageQuery({ page, pageSize: 100 })}`, token)),
  activateDocumentVersion: (token: string, documentId: string) => request<DocumentItem>(`/documents/${documentId}/activate`, token, { method: "POST" }),
  reparseDocument: (token: string, documentId: string) => request<{ status: string; chunk_count: number }>(`/documents/${documentId}/reparse`, token, { method: "POST" }),
  documentStatus: (token: string, documentId: string) => request<DocumentItem>(`/documents/${documentId}/status`, token),
  upload: (token: string, file: File, options: UploadOptions) =>
    file.size > 8 * 1024 * 1024 ? chunkedUpload(token, file, options) : directUpload(token, file, options),
  updateDocumentPermissions: (token: string, documentId: string, visibility: Visibility, groupIds: string[], userIds: string[]) =>
    request<DocumentItem>(`/documents/${documentId}/permissions`, token, { method: "PATCH", body: JSON.stringify({ visibility, group_ids: groupIds, user_ids: userIds }) }),
  deleteDocument: (token: string, documentId: string) => request<void>(`/documents/${documentId}`, token, { method: "DELETE" }),
  batchDocuments: (token: string, documentIds: string[], action: "delete" | "reparse") => request<{ action: string; results: Array<{ document_id: string; status: string; error?: string; chunk_count?: number }> }>("/documents/batch", token, { method: "POST", body: JSON.stringify({ document_ids: documentIds, action }) }),
  chunk: (token: string, documentId: string, chunkId: string) => request<Chunk>(`/documents/${documentId}/chunks/${chunkId}`, token),
  async download(token: string, document: DocumentItem) {
    const response = await fetch(`${API_BASE}/documents/${document.id}/download`, { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) throw new ApiError("下载失败", response.status);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = document.filename;
    anchor.click();
    URL.revokeObjectURL(url);
  },

  chat: (token: string, query: string, knowledgeBaseId: string, conversationId?: string, options: { top_k?: number; rerank?: boolean; mode?: "fast" | "deep"; stream?: boolean; model?: string; temperature?: number; top_p?: number; signal?: AbortSignal } = {}) =>
    request<ChatResult>("/chat", token, { method: "POST", signal: options.signal, body: JSON.stringify({ query, knowledge_base_id: knowledgeBaseId, conversation_id: conversationId ?? null, ...options, signal: undefined }) }),
  conversationPage: (token: string, knowledgeBaseId: string, params: PageParams & { favorite?: boolean } = {}) =>
    pagedRequest<ConversationSummary>(`/conversations?${pageQuery(params, { knowledge_base_id: knowledgeBaseId, favorite: params.favorite })}`, token),
  conversations: (token: string, knowledgeBaseId: string) =>
    collectPages((page) => pagedRequest<ConversationSummary>(`/conversations?${pageQuery({ page, pageSize: 100 }, { knowledge_base_id: knowledgeBaseId })}`, token)),
  conversation: (token: string, id: string) => request<ConversationDetail>(`/conversations/${id}`, token),
  deleteConversation: (token: string, id: string) => request<void>(`/conversations/${id}`, token, { method: "DELETE" }),
  updateConversation: (token: string, id: string, values: { title?: string; favorite?: boolean }) => request<ConversationSummary>(`/conversations/${id}`, token, { method: "PATCH", body: JSON.stringify(values) }),
  branchConversation: (token: string, id: string, messageId?: string) => request<ConversationSummary>(`/conversations/${id}/branch`, token, { method: "POST", body: JSON.stringify({ message_id: messageId ?? null }) }),
  shareConversation: (token: string, id: string, values: { mode: "readonly" | "continue"; expires_in_hours?: number; password?: string }) => request<{ id: string; conversation_id: string; mode: "readonly" | "continue"; token: string; expires_at: string | null; created_at: string }>(`/conversations/${id}/share`, token, { method: "POST", body: JSON.stringify(values) }),
  sharedConversation: (shareToken: string, password?: string) => request<{ title: string; knowledge_base_name: string; mode: "readonly" | "continue"; expires_at: string | null; messages: Array<{ id: string; role: "user" | "assistant"; content: string; citations: Citation[]; metrics: Record<string, string | number>; created_at: string }> }>(`/conversations/share/${encodeURIComponent(shareToken)}/access`, undefined, { method: "POST", body: JSON.stringify({ password: password || null }) }),
  feedback: (token: string, conversationId: string, messageId: string, rating: "up" | "down", reason?: string, comment = "") =>
    request<void>(`/conversations/${conversationId}/messages/${messageId}/feedback`, token, { method: "PUT", body: JSON.stringify({ rating, reason: reason ?? null, comment }) }),
  async exportConversation(token: string, id: string, format: "markdown" | "pdf" = "markdown") {
    const response = await fetch(`${API_BASE}/conversations/${id}/export?format=${format}`, { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) throw new ApiError("会话导出失败", response.status);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = `conversation-${id}.${format === "pdf" ? "pdf" : "md"}`;
    anchor.click();
    URL.revokeObjectURL(url);
  },

  groupPage: (token: string, params: PageParams = {}) => pagedRequest<Group>(`/admin/groups?${pageQuery(params)}`, token),
  groups: (token: string) => collectPages((page) => pagedRequest<Group>(`/admin/groups?${pageQuery({ page, pageSize: 100 })}`, token)),
  userPage: (token: string, params: PageParams = {}) => pagedRequest<AdminUser>(`/admin/users?${pageQuery(params)}`, token),
  users: (token: string) => collectPages((page) => pagedRequest<AdminUser>(`/admin/users?${pageQuery({ page, pageSize: 100 })}`, token)),
  createUser: (token: string, values: { username: string; display_name: string; email: string; password: string; role: Role; group_ids: string[] }) =>
    request<AdminUser>("/admin/users", token, { method: "POST", body: JSON.stringify(values) }),
  setUserStatus: (token: string, userId: string, active: boolean) => request<void>(`/admin/users/${userId}/status`, token, { method: "PATCH", body: JSON.stringify({ active }) }),
  updateUserAccess: (token: string, userId: string, role: Role, groupIds: string[]) =>
    request<AdminUser>(`/admin/users/${userId}/access`, token, { method: "PATCH", body: JSON.stringify({ role, group_ids: groupIds }) }),
  createGroup: (token: string, name: string, description: string) => request<Group>("/admin/groups", token, { method: "POST", body: JSON.stringify({ name, description }) }),
  deleteGroup: (token: string, groupId: string) => request<void>(`/admin/groups/${groupId}`, token, { method: "DELETE" }),
  auditPage: (token: string, params: PageParams & { action?: string; result?: string } = {}) => pagedRequest<AuditLog>(`/admin/audit?${pageQuery(params, { action: params.action, result: params.result })}`, token),
  audit: (token: string) => collectPages((page) => pagedRequest<AuditLog>(`/admin/audit?${pageQuery({ page, pageSize: 100 })}`, token)),
  systemStatus: (token: string) => request<SystemStatus>("/admin/system/status", token),
  settings: (token: string) => request<RagSettings>("/admin/settings", token),
  updateSettings: (token: string, values: RagSettings) => request<RagSettings>("/admin/settings", token, { method: "PUT", body: JSON.stringify(values) }),
  reindex: (token: string) => request<{ model: string; vector_store: string; chunks_reindexed: number; dimensions: number; latency_ms: number; index: SystemStatus["index"] }>("/admin/reindex", token, { method: "POST" }),
};

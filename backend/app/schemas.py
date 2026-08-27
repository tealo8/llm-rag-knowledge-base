from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=6, max_length=128)


class UserResponse(BaseModel):
    id: str
    org_id: str
    organization: str
    username: str
    display_name: str
    email: str
    role: Literal["admin", "editor", "viewer"]
    groups: list[str]


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class GroupResponse(BaseModel):
    id: str
    name: str
    description: str
    member_count: int


class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=240)


class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    status: Literal["active", "archived"]
    permission: Literal["view", "upload", "edit", "admin"]
    document_count: int
    created_at: str


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    description: str = Field(default="", max_length=500)


class KnowledgeBaseUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    status: Literal["active", "archived"] | None = None


class KnowledgeBaseAccessUpdate(BaseModel):
    user_id: str
    permission: Literal["view", "upload", "edit", "admin"] | None


class KnowledgeBaseMemberAccess(BaseModel):
    user_id: str
    username: str
    display_name: str
    email: str
    role: Literal["admin", "editor", "viewer"]
    permission: Literal["view", "upload", "edit", "admin"] | None


class AdminUserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    email: str
    role: Literal["admin", "editor", "viewer"]
    active: bool = True
    groups: list[GroupResponse]


class AdminUserCreateRequest(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]{2,80}$")
    display_name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=200)
    password: str = Field(min_length=12, max_length=128)
    role: Literal["admin", "editor", "viewer"] = "viewer"
    group_ids: list[str] = Field(default_factory=list, max_length=50)


class AdminUserStatusUpdate(BaseModel):
    active: bool


class UserAccessUpdate(BaseModel):
    role: Literal["admin", "editor", "viewer"]
    group_ids: list[str] = Field(default_factory=list, max_length=50)


class DocumentResponse(BaseModel):
    id: str
    owner_id: str
    knowledge_base_id: str
    filename: str
    title: str
    content_type: str
    size_bytes: int
    visibility: Literal["organization", "restricted", "private"]
    status: Literal["processing", "indexed", "failed"]
    processing_stage: Literal["queued", "parsing", "embedding", "indexed", "failed"] = "queued"
    task_id: str | None = None
    chunk_count: int
    owner_name: str
    groups: list[GroupResponse]
    allowed_user_ids: list[str]
    tags: list[str]
    version_group_id: str
    version_number: int
    is_current: bool
    archived_at: str | None
    chunk_strategy: Literal["fixed", "semantic"]
    created_at: str
    error: str | None = None


class DocumentPermissionUpdate(BaseModel):
    visibility: Literal["organization", "restricted", "private"]
    group_ids: list[str] = Field(default_factory=list, max_length=50)
    user_ids: list[str] = Field(default_factory=list, max_length=100)


class RagSettingsUpdate(BaseModel):
    chunk_strategy: Literal["fixed", "semantic"] = "fixed"
    chunk_size: int = Field(default=720, ge=200, le=4000)
    chunk_overlap: int = Field(default=100, ge=0, le=1000)
    top_k: int = Field(default=6, ge=2, le=20)
    lexical_weight: float = Field(default=0.55, ge=0, le=1)
    vector_weight: float = Field(default=0.45, ge=0, le=1)
    bm25_enabled: bool = True
    reranker_enabled: bool = False
    similarity_threshold: float = Field(default=0.4, ge=-1, le=1)
    temperature: float = Field(default=0.1, ge=0, le=2)
    strict_rag: bool = True
    max_context_chars: int = Field(default=12000, ge=2000, le=100000)
    max_history_messages: int = Field(default=10, ge=0, le=50)
    prompt_injection_filter: bool = True
    sensitive_words: list[str] = Field(default_factory=list, max_length=200)
    system_prompt: str = Field(default="", max_length=4000)


class UploadSessionCreate(BaseModel):
    knowledge_base_id: str
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="application/octet-stream", max_length=200)
    total_size: int = Field(gt=0)
    chunk_size: int = Field(default=5 * 1024 * 1024, ge=256 * 1024, le=20 * 1024 * 1024)
    title: str = Field(default="", max_length=200)
    visibility: Literal["organization", "restricted", "private"] = "organization"
    group_ids: list[str] = Field(default_factory=list, max_length=50)
    user_ids: list[str] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=30)
    chunk_strategy: Literal["fixed", "semantic"] | None = None
    version_of: str | None = None


class UploadSessionResponse(BaseModel):
    id: str
    filename: str
    total_size: int
    received_size: int
    chunk_size: int
    next_part: int
    status: Literal["open", "completed", "aborted"]


class CitationResponse(BaseModel):
    index: int
    document_id: str
    chunk_id: str
    title: str
    filename: str
    page_number: int | None
    paragraph_number: int | None = None
    excerpt: str
    score: float


class ChatRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    knowledge_base_id: str | None = None
    conversation_id: str | None = None
    top_k: int | None = Field(default=None, ge=2, le=20)


class ChatResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]
    retrieval: dict[str, int | float | str]
    conversation_id: str
    message_id: str


class ChunkResponse(BaseModel):
    id: str
    document_id: str
    title: str
    page_number: int | None
    paragraph_number: int | None = None
    text: str


class AuditResponse(BaseModel):
    id: str
    user_name: str
    action: str
    resource_type: str
    resource_id: str | None
    query: str | None
    metadata: dict
    created_at: str


class ConversationSummary(BaseModel):
    id: str
    knowledge_base_id: str
    knowledge_base_name: str
    title: str
    message_count: int
    created_at: str
    updated_at: str


class ConversationMessageResponse(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    citations: list[CitationResponse]
    metrics: dict[str, Any]
    feedback: Literal["up", "down"] | None = None
    created_at: str


class ConversationDetail(ConversationSummary):
    messages: list[ConversationMessageResponse]


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    comment: str = Field(default="", max_length=1000)

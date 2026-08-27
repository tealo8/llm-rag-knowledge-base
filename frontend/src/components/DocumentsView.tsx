import { useEffect, useRef, useState } from "react";
import {
  Building2,
  Check,
  Download,
  File,
  FilePlus2,
  FileText,
  Filter,
  LoaderCircle,
  Lock,
  History,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Trash2,
  UploadCloud,
  Users,
  X,
} from "lucide-react";
import { api, ApiError } from "../api";
import type { DocumentItem, Group, KnowledgeBase, KnowledgeBaseMember, User, Visibility } from "../types";
import { Pagination } from "./Pagination";

interface DocumentsViewProps {
  token: string;
  user: User;
  knowledgeBase: KnowledgeBase | null;
  notify: (message: string, tone?: "error" | "success") => void;
}

const visibilityConfig = {
  organization: { label: "全组织", icon: Building2 },
  restricted: { label: "指定成员", icon: Users },
  private: { label: "仅自己", icon: Lock },
};

const DOCUMENT_PAGE_SIZE = 10;

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export function DocumentsView({ token, user, knowledgeBase, notify }: DocumentsViewProps) {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [members, setMembers] = useState<KnowledgeBaseMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [visibility, setVisibility] = useState<Visibility | "all">("all");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [permissionDocument, setPermissionDocument] = useState<DocumentItem | null>(null);
  const [versionTarget, setVersionTarget] = useState<DocumentItem | null>(null);
  const [newVersionOf, setNewVersionOf] = useState<DocumentItem | null>(null);

  async function loadDocuments(requestedPage = page) {
    setLoading(true);
    try {
      if (!knowledgeBase) { setDocuments([]); setTotal(0); return; }
      const result = await api.documentPage(token, knowledgeBase.id, {
        page: requestedPage,
        pageSize: DOCUMENT_PAGE_SIZE,
        q: search,
        visibility,
      });
      if (requestedPage > Math.max(result.totalPages, 1)) {
        setPage(Math.max(result.totalPages, 1));
        return;
      }
      setDocuments(result.items);
      setTotal(result.total);
    } catch (error) {
      notify(error instanceof Error ? error.message : "文档加载失败", "error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!knowledgeBase) { setGroups([]); setMembers([]); return; }
    Promise.all([
      api.groups(token),
      knowledgeBase.permission === "admin" ? api.knowledgeBaseMembers(token, knowledgeBase.id) : Promise.resolve([]),
    ]).then(([groupData, memberData]) => {
      setGroups(groupData);
      setMembers(memberData);
    }).catch((error) => notify(error instanceof Error ? error.message : "权限选项加载失败", "error"));
  }, [token, knowledgeBase?.id, knowledgeBase?.permission]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadDocuments(page); }, 250);
    return () => window.clearTimeout(timer);
  }, [token, knowledgeBase?.id, page, search, visibility]);

  useEffect(() => {
    if (!documents.some((item) => item.status === "processing")) return;
    const timer = window.setInterval(() => { void loadDocuments(page); }, 2500);
    return () => window.clearInterval(timer);
  }, [documents, page, token, knowledgeBase?.id, search, visibility]);

  async function remove(document: DocumentItem) {
    if (!window.confirm(`确认删除“${document.title}”？索引和原始文件都会被删除。`)) return;
    try {
      await api.deleteDocument(token, document.id);
      await loadDocuments();
      notify("文档已删除", "success");
    } catch (error) {
      notify(error instanceof Error ? error.message : "删除失败", "error");
    }
  }

  async function reparse(document: DocumentItem) {
    try {
      const result = await api.reparseDocument(token, document.id);
      setDocuments((current) => current.map((item) => item.id === document.id ? { ...item, status: "indexed", chunk_count: result.chunk_count, error: null } : item));
      notify(`重新解析完成，共 ${result.chunk_count} 个片段`, "success");
    } catch (error) { notify(error instanceof Error ? error.message : "重新解析失败", "error"); }
  }

  const canUpload = knowledgeBase && knowledgeBase.permission !== "view";
  const canEdit = knowledgeBase && ["edit", "admin"].includes(knowledgeBase.permission);

  if (!knowledgeBase) return <div className="empty-workspace"><FileText size={30} /><h2>没有可访问的知识库</h2><p>请让管理员授予知识库权限。</p></div>;

  return (
    <section className="page documents-page">
      <div className="page-heading">
        <div><p className="eyebrow">Library</p><h1>文档库</h1><p>管理经过解析、分块和权限标记的企业资料</p></div>
        {canUpload && (
          <button className="button primary" onClick={() => setUploadOpen(true)}><FilePlus2 size={18} />上传文档</button>
        )}
      </div>

      <div className="library-stats">
        <div><span>匹配文档</span><strong>{total}</strong></div>
        <div><span>本页索引片段</span><strong>{documents.reduce((sum, item) => sum + item.chunk_count, 0)}</strong></div>
        <div><span>本页受限资料</span><strong>{documents.filter((item) => item.visibility !== "organization").length}</strong></div>
      </div>

      <div className="table-toolbar">
        <label className="search-field"><Search size={17} /><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="搜索标题、文件或所有者" /></label>
        <label className="filter-select"><Filter size={16} /><select value={visibility} onChange={(event) => { setVisibility(event.target.value as Visibility | "all"); setPage(1); }}>
          <option value="all">全部范围</option><option value="organization">全组织</option><option value="restricted">指定用户组</option><option value="private">仅自己</option>
        </select></label>
      </div>

      <div className="data-table-wrap">
        {loading ? (
          <div className="document-skeleton" aria-label="正在加载文档"><span /><span /><span /><span /></div>
        ) : documents.length === 0 ? (
          <div className="table-state"><FileText size={28} /><span>没有匹配的文档</span></div>
        ) : (
          <table className="data-table document-table">
            <thead><tr><th>文档</th><th>可见范围</th><th>所有者</th><th>索引</th><th>更新时间</th><th><span className="sr-only">操作</span></th></tr></thead>
            <tbody>
              {documents.map((document) => {
                const config = visibilityConfig[document.visibility];
                const VisibilityIcon = config.icon;
                return (
                  <tr key={document.id}>
                    <td><div className="document-name"><span className="file-badge"><File size={19} /></span><span><strong>{document.title}</strong><small>{document.filename} · {formatBytes(document.size_bytes)}</small></span></div></td>
                    <td><span className={`visibility-badge ${document.visibility}`}><VisibilityIcon size={14} />{config.label}</span>{document.groups.length > 0 && <small className="cell-subtext">{document.groups.map((group) => group.name).join("、")}</small>}</td>
                    <td>{document.owner_name}</td>
                    <td><DocumentStatus document={document} /></td>
                    <td>{formatDate(document.created_at)}</td>
                    <td><div className="row-actions">
                      {canEdit && <button className="icon-button" title="设置文档权限" onClick={() => setPermissionDocument(document)}><Settings2 size={17} /></button>}
                      {canEdit && <button className="icon-button" title="文档版本" onClick={() => setVersionTarget(document)}><History size={17} /></button>}
                      {canEdit && <button className="icon-button" title="上传新版本" onClick={() => { setNewVersionOf(document); setUploadOpen(true); }}><UploadCloud size={17} /></button>}
                      {canEdit && document.status === "failed" && <button className="icon-button" title="重新解析" onClick={() => reparse(document)}><RefreshCw size={17} /></button>}
                      <button className="icon-button" title="下载原文" onClick={() => api.download(token, document).catch((error) => notify(error.message, "error"))}><Download size={17} /></button>
                      {canEdit && <button className="icon-button danger" title="删除文档" onClick={() => remove(document)}><Trash2 size={17} /></button>}
                    </div></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <Pagination page={page} pageSize={DOCUMENT_PAGE_SIZE} total={total} onPageChange={setPage} />
      </div>

      {uploadOpen && (
        <UploadDialog
          token={token}
          knowledgeBase={knowledgeBase}
          groups={groups}
          members={members}
          versionOf={newVersionOf}
          onClose={() => setUploadOpen(false)}
          onUploaded={(document) => {
            setPage(1);
            void loadDocuments(1);
            setUploadOpen(false);
            setNewVersionOf(null);
            notify(document.status === "indexed" ? "文档已解析并完成索引" : "文档已上传，后台正在处理", "success");
          }}
          notify={notify}
        />
      )}
      {permissionDocument && (
        <PermissionDialog
          token={token}
          document={permissionDocument}
          groups={groups}
          members={members}
          onClose={() => setPermissionDocument(null)}
          onUpdated={(updated) => {
            setDocuments((current) => current.map((item) => item.id === updated.id ? updated : item));
            setPermissionDocument(null);
            notify("文档权限已更新", "success");
          }}
          notify={notify}
        />
      )}
      {versionTarget && <VersionsDialog token={token} document={versionTarget} canEdit={Boolean(canEdit)} onClose={() => setVersionTarget(null)} onChanged={loadDocuments} notify={notify} />}
    </section>
  );
}

function DocumentStatus({ document }: { document: DocumentItem }) {
  const labels: Record<DocumentItem["processing_stage"], string> = {
    queued: "待解析", parsing: "解析中", embedding: "向量化中", indexed: `${document.chunk_count} 个片段`, failed: "解析失败",
  };
  return <div className="status-cell"><span className={`status-badge ${document.status} ${document.processing_stage}`}><i />{labels[document.processing_stage]}</span>{document.error && <small className="status-error">{document.error}</small>}</div>;
}

interface PermissionDialogProps {
  token: string;
  document: DocumentItem;
  groups: Group[];
  members: KnowledgeBaseMember[];
  onClose: () => void;
  onUpdated: (document: DocumentItem) => void;
  notify: (message: string, tone?: "error" | "success") => void;
}

function PermissionDialog({ token, document, groups, members, onClose, onUpdated, notify }: PermissionDialogProps) {
  const [visibility, setVisibility] = useState<Visibility>(document.visibility);
  const [selectedGroups, setSelectedGroups] = useState<string[]>(document.groups.map((group) => group.id));
  const [selectedUsers, setSelectedUsers] = useState<string[]>(document.allowed_user_ids);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (visibility === "restricted" && selectedGroups.length === 0 && selectedUsers.length === 0) {
      return notify("受限文档至少选择一个用户组或指定用户", "error");
    }
    setSubmitting(true);
    try {
      onUpdated(await api.updateDocumentPermissions(
        token,
        document.id,
        visibility,
        visibility === "restricted" ? selectedGroups : [],
        visibility === "restricted" ? selectedUsers : [],
      ));
    } catch (error) {
      notify(error instanceof Error ? error.message : "权限更新失败", "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <form className="modal permission-dialog" role="dialog" aria-modal="true" aria-labelledby="permission-title" onSubmit={submit}>
        <div className="modal-header">
          <div><p className="eyebrow">Document ACL</p><h2 id="permission-title">设置文档权限</h2></div>
          <button type="button" className="icon-button" title="关闭" onClick={onClose}><X size={19} /></button>
        </div>
        <div className="modal-body">
          <div className="permission-target"><span className="file-badge"><FileText size={19} /></span><span><strong>{document.title}</strong><small>所有者：{document.owner_name}</small></span></div>
          <fieldset className="field"><legend>可见范围</legend><div className="segmented visibility-segments">
            {(Object.entries(visibilityConfig) as [Visibility, (typeof visibilityConfig)[Visibility]][]).map(([value, config]) => {
              const Icon = config.icon;
              return <button type="button" key={value} className={visibility === value ? "active" : ""} onClick={() => setVisibility(value)}><Icon size={16} />{config.label}</button>;
            })}
          </div></fieldset>
          {visibility === "restricted" && <fieldset className="field"><legend>授权用户组</legend><div className="group-checks">
            {groups.map((group) => <label key={group.id}><input type="checkbox" checked={selectedGroups.includes(group.id)} onChange={() => setSelectedGroups((current) => current.includes(group.id) ? current.filter((id) => id !== group.id) : [...current, group.id])} /><span><strong>{group.name}</strong><small>{group.member_count} 名成员 · {group.description}</small></span></label>)}
          </div>{members.length > 0 && <><legend className="sublegend">指定用户</legend><div className="group-checks member-checks">{members.filter((member) => member.role !== "admin").map((member) => <label key={member.user_id}><input type="checkbox" checked={selectedUsers.includes(member.user_id)} onChange={() => setSelectedUsers((current) => current.includes(member.user_id) ? current.filter((id) => id !== member.user_id) : [...current, member.user_id])} /><span><strong>{member.display_name}</strong><small>{member.email}</small></span></label>)}</div></>}</fieldset>}
          <div className="security-note"><ShieldCheck size={18} /><span><strong>保存后立即生效</strong><small>列表、混合检索、引用片段和原文下载都会使用新权限。</small></span></div>
        </div>
        <div className="modal-footer"><button type="button" className="button secondary" onClick={onClose}>取消</button><button className="button primary" disabled={submitting}>{submitting ? <LoaderCircle className="spin" size={18} /> : <ShieldCheck size={18} />}保存权限</button></div>
      </form>
    </div>
  );
}

interface UploadDialogProps {
  token: string;
  knowledgeBase: KnowledgeBase;
  groups: Group[];
  members: KnowledgeBaseMember[];
  versionOf: DocumentItem | null;
  onClose: () => void;
  onUploaded: (document: DocumentItem) => void;
  notify: (message: string, tone?: "error" | "success") => void;
}

function UploadDialog({ token, knowledgeBase, groups, members, versionOf, onClose, onUploaded, notify }: UploadDialogProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [visibility, setVisibility] = useState<Visibility>(versionOf?.visibility ?? "organization");
  const [selectedGroups, setSelectedGroups] = useState<string[]>(versionOf?.groups.map((group) => group.id) ?? []);
  const [selectedUsers, setSelectedUsers] = useState<string[]>(versionOf?.allowed_user_ids ?? []);
  const [tags, setTags] = useState(versionOf?.tags.join(", ") ?? "");
  const [chunkStrategy, setChunkStrategy] = useState<"fixed" | "semantic">(versionOf?.chunk_strategy ?? "fixed");
  const [progress, setProgress] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [inlineError, setInlineError] = useState("");

  function selectFile(nextFile: File | undefined) {
    if (!nextFile) return;
    setFile(nextFile);
    if (!title) setTitle(versionOf?.title ?? nextFile.name.replace(/\.[^.]+$/, ""));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return notify("请选择一个文档", "error");
    if (visibility === "restricted" && selectedGroups.length === 0 && selectedUsers.length === 0) return notify("受限文档至少选择一个用户组或指定用户", "error");
    setSubmitting(true);
    setInlineError("");
    try {
      onUploaded(await api.upload(token, file, {
        knowledgeBaseId: knowledgeBase.id,
        title,
        visibility,
        groupIds: visibility === "restricted" ? selectedGroups : [],
        userIds: visibility === "restricted" ? selectedUsers : [],
        tags: tags.split(/[,，]/).map((item) => item.trim()).filter(Boolean),
        chunkStrategy,
        versionOf: versionOf?.id,
        onProgress: setProgress,
      }));
    } catch (error) {
      const message = error instanceof Error ? error.message : "上传失败";
      setInlineError(error instanceof ApiError && error.status === 409 ? `重复文档：${message}` : message);
      notify(message, "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <form className="modal upload-dialog" role="dialog" aria-modal="true" aria-labelledby="upload-title" onSubmit={submit}>
        <div className="modal-header"><div><p className="eyebrow">Ingestion</p><h2 id="upload-title">{versionOf ? `上传“${versionOf.title}”的新版本` : "上传并建立索引"}</h2></div><button type="button" className="icon-button" title="关闭" onClick={onClose}><X size={19} /></button></div>
        <div className="modal-body">
          <div className="ingestion-flow"><span className="done"><Check size={13} />安全校验</span><i /><span>文本解析</span><i /><span>分块向量化</span><i /><span>权限入库</span></div>
          <button
            type="button"
            className={file ? "dropzone has-file" : "dropzone"}
            onClick={() => inputRef.current?.click()}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => { event.preventDefault(); selectFile(event.dataTransfer.files[0]); }}
          >
            <input ref={inputRef} type="file" hidden accept=".pdf,.docx,.md,.txt,.xlsx" onChange={(event) => selectFile(event.target.files?.[0])} />
            {file ? <><FileText size={27} /><strong>{file.name}</strong><span>{formatBytes(file.size)}{submitting ? ` · ${progress}%` : ""}</span></> : <><UploadCloud size={30} /><strong>选择或拖入文档</strong><span>PDF、DOCX、XLSX、Markdown、TXT · 大文件自动分片</span></>}
          </button>
          {inlineError && <div className="inline-error" role="alert"><ShieldCheck size={16} />{inlineError}</div>}
          <label className="field"><span>文档标题</span><input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="输入易于检索的标题" /></label>
          <label className="field"><span>标签</span><input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="制度, 研发, 2026（逗号分隔）" /></label>
          <fieldset className="field"><legend>分块策略</legend><div className="segmented two-segments"><button type="button" className={chunkStrategy === "fixed" ? "active" : ""} onClick={() => setChunkStrategy("fixed")}>固定大小</button><button type="button" className={chunkStrategy === "semantic" ? "active" : ""} onClick={() => setChunkStrategy("semantic")}>语义段落</button></div></fieldset>
          <fieldset className="field"><legend>可见范围</legend><div className="segmented visibility-segments">
            {(Object.entries(visibilityConfig) as [Visibility, (typeof visibilityConfig)[Visibility]][]).map(([value, config]) => {
              const Icon = config.icon;
              return <button type="button" key={value} className={visibility === value ? "active" : ""} onClick={() => setVisibility(value)}><Icon size={16} />{config.label}</button>;
            })}
          </div></fieldset>
          {visibility === "restricted" && <fieldset className="field"><legend>授权用户组</legend><div className="group-checks">
            {groups.map((group) => <label key={group.id}><input type="checkbox" checked={selectedGroups.includes(group.id)} onChange={() => setSelectedGroups((current) => current.includes(group.id) ? current.filter((id) => id !== group.id) : [...current, group.id])} /><span><strong>{group.name}</strong><small>{group.member_count} 名成员 · {group.description}</small></span></label>)}
          </div>{members.length > 0 && <><legend className="sublegend">指定用户</legend><div className="group-checks member-checks">{members.filter((member) => member.role !== "admin").map((member) => <label key={member.user_id}><input type="checkbox" checked={selectedUsers.includes(member.user_id)} onChange={() => setSelectedUsers((current) => current.includes(member.user_id) ? current.filter((id) => id !== member.user_id) : [...current, member.user_id])} /><span><strong>{member.display_name}</strong><small>{member.email}</small></span></label>)}</div></>}</fieldset>}
          <div className="security-note"><ShieldCheck size={18} /><span><strong>权限在检索前执行</strong><small>未授权片段不会进入召回候选或模型上下文。</small></span></div>
        </div>
        <div className="modal-footer"><button type="button" className="button secondary" onClick={onClose}>取消</button><button className="button primary" disabled={submitting || !file}>{submitting ? <LoaderCircle className="spin" size={18} /> : <UploadCloud size={18} />}上传并索引</button></div>
      </form>
    </div>
  );
}

function VersionsDialog({ token, document, canEdit, onClose, onChanged, notify }: { token: string; document: DocumentItem; canEdit: boolean; onClose: () => void; onChanged: () => Promise<void>; notify: DocumentsViewProps["notify"] }) {
  const [versions, setVersions] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  useEffect(() => {
    setLoading(true);
    api.documentVersionPage(token, document.id, { page, pageSize: 5 })
      .then((result) => { setVersions(result.items); setTotal(result.total); })
      .catch((error) => notify(error.message, "error"))
      .finally(() => setLoading(false));
  }, [token, document.id, page]);
  async function activate(item: DocumentItem) {
    try {
      await api.activateDocumentVersion(token, item.id);
      setVersions((current) => current.map((version) => ({ ...version, is_current: version.id === item.id })));
      await onChanged();
      notify(`已切换到 v${item.version_number}`, "success");
    } catch (error) { notify(error instanceof Error ? error.message : "版本切换失败", "error"); }
  }
  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><div className="modal"><div className="modal-header"><div><p className="eyebrow">Document versions</p><h2>{document.title} · 版本</h2></div><button className="icon-button" title="关闭" onClick={onClose}><X size={19} /></button></div><div className="modal-body">{loading ? <div className="table-state"><LoaderCircle className="spin" size={22} />加载版本</div> : <><div className="version-list">{versions.map((item) => <div key={item.id}><span><strong>v{item.version_number}{item.is_current ? " · 当前" : ""}</strong><small>{item.filename} · {formatDate(item.created_at)} · {item.chunk_count} 个片段</small></span>{canEdit && !item.is_current && <button className="button compact secondary" onClick={() => activate(item)}>设为当前</button>}</div>)}</div><Pagination page={page} pageSize={5} total={total} onPageChange={setPage} /></>}</div><div className="modal-footer"><button className="button primary" onClick={onClose}>完成</button></div></div></div>;
}

import { useEffect, useState } from "react";
import { Archive, ArchiveRestore, Database, LoaderCircle, Plus, Save, Search, Trash2, Users, X } from "lucide-react";
import { api } from "../api";
import type { KnowledgeBase, KnowledgeBaseMember, KnowledgeBasePermission, User } from "../types";
import { Pagination } from "./Pagination";

interface Props {
  token: string;
  user: User;
  selectedId: string;
  onSelect: (id: string) => void;
  onChanged: () => Promise<void>;
  notify: (message: string, tone?: "error" | "success") => void;
}

const permissionLabels: Record<KnowledgeBasePermission, string> = {
  view: "可查看", upload: "仅上传", edit: "可编辑", admin: "知识库管理员",
};

export function KnowledgeBasesView({ token, user, selectedId, onSelect, onChanged, notify }: Props) {
  const [items, setItems] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [accessTarget, setAccessTarget] = useState<KnowledgeBase | null>(null);

  async function load(requestedPage = page) {
    setLoading(true);
    try {
      const result = await api.knowledgeBasePage(token, { page: requestedPage, pageSize: 10, q: search }, true);
      if (requestedPage > Math.max(result.totalPages, 1)) { setPage(Math.max(result.totalPages, 1)); return; }
      setItems(result.items);
      setTotal(result.total);
    }
    catch (error) { notify(error instanceof Error ? error.message : "知识库加载失败", "error"); }
    finally { setLoading(false); }
  }
  useEffect(() => {
    const timer = window.setTimeout(() => { void load(page); }, 250);
    return () => window.clearTimeout(timer);
  }, [token, page, search]);

  async function toggleArchive(item: KnowledgeBase) {
    try {
      await api.updateKnowledgeBase(token, item.id, { status: item.status === "active" ? "archived" : "active" });
      await Promise.all([load(), onChanged()]);
      notify(item.status === "active" ? "知识库已归档" : "知识库已恢复", "success");
    } catch (error) { notify(error instanceof Error ? error.message : "状态更新失败", "error"); }
  }

  async function remove(item: KnowledgeBase) {
    if (!window.confirm(`确认删除空知识库“${item.name}”？此操作不可恢复。`)) return;
    try {
      await api.deleteKnowledgeBase(token, item.id);
      await Promise.all([load(), onChanged()]);
      notify("知识库已删除", "success");
    } catch (error) { notify(error instanceof Error ? error.message : "知识库删除失败", "error"); }
  }

  return <section className="page knowledge-base-page">
    <div className="page-heading">
      <div><p className="eyebrow">Knowledge spaces</p><h1>知识库管理</h1><p>知识库是检索和授权的第一层边界，成员必须被显式授权</p></div>
      {user.role === "admin" && <button className="button primary" onClick={() => setCreateOpen(true)}><Plus size={18} />新建知识库</button>}
    </div>
    <div className="table-toolbar"><label className="search-field"><Search size={17} /><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="搜索知识库名称、标识或说明" /></label></div>
    <div className="data-table-wrap">
      {loading ? <div className="table-state"><LoaderCircle className="spin" size={23} />正在读取知识库</div> : !items.length ?
        <div className="table-state"><Database size={27} />暂无可管理的知识库</div> :
        <table className="data-table knowledge-base-table"><thead><tr><th>知识库</th><th>状态</th><th>我的权限</th><th>文档</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>
          {items.map((item) => <tr key={item.id} className={item.id === selectedId ? "selected-row" : ""}>
            <td><button className="knowledge-base-name" onClick={() => { if (item.status === "active") onSelect(item.id); }}><Database size={18} /><span><strong>{item.name}</strong><small>{item.slug} · {item.description || "无说明"}</small></span></button></td>
            <td><span className={`status-badge ${item.status === "active" ? "indexed" : ""}`}><i />{item.status === "active" ? "启用" : "已归档"}</span></td>
            <td><span className="role-badge editor">{permissionLabels[item.permission]}</span></td>
            <td>{item.document_count}</td>
            <td><div className="row-actions">
              {item.permission === "admin" && <button className="button compact secondary" onClick={() => setAccessTarget(item)}><Users size={15} />成员权限</button>}
              {item.permission === "admin" && <button className="icon-button" title={item.status === "active" ? "归档" : "恢复"} onClick={() => toggleArchive(item)}>{item.status === "active" ? <Archive size={16} /> : <ArchiveRestore size={16} />}</button>}
              {item.permission === "admin" && item.document_count === 0 && <button className="icon-button danger" title="删除空知识库" onClick={() => remove(item)}><Trash2 size={16} /></button>}
            </div></td>
          </tr>)}
        </tbody></table>}
      <Pagination page={page} pageSize={10} total={total} onPageChange={setPage} />
    </div>
    {createOpen && <CreateKnowledgeBaseDialog token={token} onClose={() => setCreateOpen(false)} onCreated={async (item) => { setCreateOpen(false); onSelect(item.id); setPage(1); await Promise.all([load(1), onChanged()]); notify("知识库已创建", "success"); }} notify={notify} />}
    {accessTarget && <KnowledgeBaseAccessDialog token={token} knowledgeBase={accessTarget} onClose={() => setAccessTarget(null)} notify={notify} />}
  </section>;
}

function CreateKnowledgeBaseDialog({ token, onClose, onCreated, notify }: { token: string; onClose: () => void; onCreated: (item: KnowledgeBase) => Promise<void>; notify: Props["notify"] }) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setSaving(true);
    try { await onCreated(await api.createKnowledgeBase(token, { name: name.trim(), slug: slug.trim().toLowerCase(), description: description.trim() })); }
    catch (error) { notify(error instanceof Error ? error.message : "创建失败", "error"); }
    finally { setSaving(false); }
  }
  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><form className="modal" onSubmit={submit}>
    <div className="modal-header"><div><p className="eyebrow">Knowledge base</p><h2>新建知识库</h2></div><button type="button" className="icon-button" title="关闭" onClick={onClose}><X size={19} /></button></div>
    <div className="modal-body"><label className="field"><span>名称</span><input value={name} onChange={(event) => setName(event.target.value)} minLength={2} maxLength={100} required /></label><label className="field"><span>唯一标识</span><input value={slug} onChange={(event) => setSlug(event.target.value)} pattern="[a-z0-9][a-z0-9-]{1,62}" placeholder="engineering-handbook" required /></label><label className="field"><span>说明</span><textarea value={description} onChange={(event) => setDescription(event.target.value)} maxLength={500} rows={3} /></label></div>
    <div className="modal-footer"><button type="button" className="button secondary" onClick={onClose}>取消</button><button className="button primary" disabled={saving}><Plus size={17} />创建</button></div>
  </form></div>;
}

function KnowledgeBaseAccessDialog({ token, knowledgeBase, onClose, notify }: { token: string; knowledgeBase: KnowledgeBase; onClose: () => void; notify: Props["notify"] }) {
  const [members, setMembers] = useState<KnowledgeBaseMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setLoading(true);
      api.knowledgeBaseMemberPage(token, knowledgeBase.id, { page, pageSize: 8, q: search })
        .then((result) => { setMembers(result.items); setTotal(result.total); })
        .catch((error) => notify(error.message, "error"))
        .finally(() => setLoading(false));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [token, knowledgeBase.id, page, search]);
  async function update(member: KnowledgeBaseMember, value: string) {
    const permission = value ? value as KnowledgeBasePermission : null;
    setSavingId(member.user_id);
    try {
      await api.setKnowledgeBaseAccess(token, knowledgeBase.id, member.user_id, permission);
      setMembers((current) => current.map((item) => item.user_id === member.user_id ? { ...item, permission } : item));
      notify("知识库权限已更新", "success");
    } catch (error) { notify(error instanceof Error ? error.message : "授权失败", "error"); }
    finally { setSavingId(""); }
  }
  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><div className="modal access-dialog" role="dialog" aria-modal="true">
    <div className="modal-header"><div><p className="eyebrow">Knowledge base ACL</p><h2>{knowledgeBase.name} · 成员权限</h2></div><button className="icon-button" title="关闭" onClick={onClose}><X size={19} /></button></div>
    <div className="modal-body"><label className="search-field"><Search size={16} /><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="搜索成员" /></label>{loading ? <div className="table-state"><LoaderCircle className="spin" size={22} />加载成员</div> : <><div className="access-member-list">{members.map((member) => <div key={member.user_id}><span className="member-avatar">{member.display_name.slice(0, 1)}</span><span><strong>{member.display_name}</strong><small>{member.email} · @{member.username}</small></span><select value={member.role === "admin" ? "admin" : member.permission ?? ""} disabled={member.role === "admin" || savingId === member.user_id} onChange={(event) => update(member, event.target.value)}><option value="">无权限</option><option value="view">可查看</option><option value="upload">仅上传</option><option value="edit">可编辑</option><option value="admin">知识库管理员</option></select>{savingId === member.user_id && <LoaderCircle className="spin" size={16} />}</div>)}</div><Pagination page={page} pageSize={8} total={total} onPageChange={setPage} /></>}</div>
    <div className="modal-footer"><span className="modal-footnote">组织管理员始终拥有管理权限</span><button className="button primary" onClick={onClose}><Save size={17} />完成</button></div>
  </div></div>;
}

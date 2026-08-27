import { useEffect, useState } from "react";
import {
  Building2,
  CheckCircle2,
  Crown,
  Eye,
  FileKey2,
  LoaderCircle,
  Lock,
  Pencil,
  Plus,
  Power,
  RefreshCw,
  Save,
  Settings2,
  ShieldCheck,
  Trash2,
  UserCog,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import { api } from "../api";
import type { AdminUser, AuditLog, Group, RagSettings, Role, SystemStatus, User } from "../types";
import { Pagination } from "./Pagination";

interface GovernanceViewProps {
  token: string;
  user: User;
  notify: (message: string, tone?: "error" | "success") => void;
}

const actionLabels: Record<string, string> = {
  "knowledge.query": "知识查询",
  "document.upload": "上传文档",
  "document.delete": "删除文档",
  "document.permissions.update": "修改文档权限",
  "user.access.update": "修改成员权限",
  "group.create": "新建用户组",
  "group.delete": "删除用户组",
  "index.rebuild": "重建向量索引",
  "knowledge_base.access.update": "修改知识库权限",
  "knowledge_base.create": "新建知识库",
  "knowledge_base.update": "更新知识库",
  "user.create": "新建成员",
  "user.status.update": "修改成员状态",
  "system.settings.update": "更新 RAG 参数",
  "answer.feedback": "问答反馈",
};

const roleConfig = {
  admin: { label: "管理员", description: "管理文档、成员、用户组和审计", icon: Crown },
  editor: { label: "编辑者", description: "上传文档并管理自己的文档", icon: Pencil },
  viewer: { label: "只读成员", description: "检索和查看被授权的资料", icon: Eye },
};

function time(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

export function GovernanceView({ token, user, notify }: GovernanceViewProps) {
  const [groups, setGroups] = useState<Group[]>([]);
  const [groupOptions, setGroupOptions] = useState<Group[]>([]);
  const [groupPage, setGroupPage] = useState(1);
  const [groupTotal, setGroupTotal] = useState(0);
  const [members, setMembers] = useState<AdminUser[]>([]);
  const [audit, setAudit] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [memberPage, setMemberPage] = useState(1);
  const [memberTotal, setMemberTotal] = useState(0);
  const [auditPage, setAuditPage] = useState(1);
  const [auditTotal, setAuditTotal] = useState(0);
  const [editingMember, setEditingMember] = useState<AdminUser | null>(null);
  const [createGroupOpen, setCreateGroupOpen] = useState(false);
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [reindexing, setReindexing] = useState(false);
  const [settings, setSettings] = useState<RagSettings | null>(null);
  const [savingSettings, setSavingSettings] = useState(false);
  const [createUserOpen, setCreateUserOpen] = useState(false);

  async function load() {
    setLoading(true);
    try {
      if (user.role === "admin") {
        const [groupData, groupOptionData, memberData, auditData, systemData, settingsData] = await Promise.all([
          api.groupPage(token, { page: groupPage, pageSize: 10 }), api.groups(token), api.userPage(token, { page: memberPage, pageSize: 10 }), api.auditPage(token, { page: auditPage, pageSize: 10 }), api.systemStatus(token), api.settings(token),
        ]);
        const validGroupPage = Math.max(groupData.totalPages, 1);
        const validMemberPage = Math.max(memberData.totalPages, 1);
        const validAuditPage = Math.max(auditData.totalPages, 1);
        if (groupPage > validGroupPage || memberPage > validMemberPage || auditPage > validAuditPage) {
          if (groupPage > validGroupPage) setGroupPage(validGroupPage);
          if (memberPage > validMemberPage) setMemberPage(validMemberPage);
          if (auditPage > validAuditPage) setAuditPage(validAuditPage);
          return;
        }
        setGroups(groupData.items);
        setGroupTotal(groupData.total);
        setGroupOptions(groupOptionData);
        setMembers(memberData.items);
        setMemberTotal(memberData.total);
        setAudit(auditData.items);
        setAuditTotal(auditData.total);
        setSystem(systemData);
        setSettings(settingsData);
      } else {
        const groupData = await api.groupPage(token, { page: groupPage, pageSize: 10 });
        setGroups(groupData.items);
        setGroupTotal(groupData.total);
        setGroupOptions(groupData.items);
      }
    } catch (error) {
      notify(error instanceof Error ? error.message : "治理信息加载失败", "error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [token, user.role, groupPage, memberPage, auditPage]);

  async function removeGroup(group: Group) {
    if (!window.confirm(`确认删除用户组“${group.name}”？`)) return;
    try {
      await api.deleteGroup(token, group.id);
      await load();
      notify("用户组已删除", "success");
    } catch (error) {
      notify(error instanceof Error ? error.message : "用户组删除失败", "error");
    }
  }

  async function rebuildIndex() {
    if (!window.confirm("确认使用当前 Embedding 模型重建本组织全部向量？")) return;
    setReindexing(true);
    try {
      const result = await api.reindex(token);
      setSystem((current) => current ? { ...current, index: result.index } : current);
      const auditData = await api.auditPage(token, { page: auditPage, pageSize: 10 });
      setAudit(auditData.items); setAuditTotal(auditData.total);
      notify(`已重建 ${result.chunks_reindexed} 个片段`, "success");
    } catch (error) {
      notify(error instanceof Error ? error.message : "向量索引重建失败", "error");
    } finally {
      setReindexing(false);
    }
  }

  async function saveSettings(event: React.FormEvent) {
    event.preventDefault();
    if (!settings) return;
    setSavingSettings(true);
    try {
      setSettings(await api.updateSettings(token, settings));
      const auditData = await api.auditPage(token, { page: auditPage, pageSize: 10 });
      setAudit(auditData.items); setAuditTotal(auditData.total);
      notify("RAG 与安全参数已保存", "success");
    } catch (error) { notify(error instanceof Error ? error.message : "参数保存失败", "error"); }
    finally { setSavingSettings(false); }
  }

  async function toggleMember(member: AdminUser) {
    const action = member.active ? "停用" : "启用";
    if (!window.confirm(`确认${action}成员“${member.display_name}”？`)) return;
    try {
      await api.setUserStatus(token, member.id, !member.active);
      setMembers((current) => current.map((item) => item.id === member.id ? { ...item, active: !item.active } : item));
      notify(`成员已${action}`, "success");
    } catch (error) { notify(error instanceof Error ? error.message : `${action}失败`, "error"); }
  }

  return (
    <section className="page governance-page">
      <div className="page-heading">
        <div><p className="eyebrow">Governance</p><h1>权限与审计</h1><p>配置当前知识空间的成员权限、用户组和访问边界</p></div>
        <span className="policy-active"><CheckCircle2 size={17} />策略生效中</span>
      </div>

      <section className="policy-section">
        <div className="section-heading"><div><h2>文档访问策略</h2><p>所有规则都在召回候选生成前执行</p></div></div>
        <div className="policy-grid">
          <div><span className="policy-icon organization"><Building2 size={20} /></span><strong>全组织</strong><p>同一租户中的有效成员可检索。</p></div>
          <div><span className="policy-icon restricted"><Users size={20} /></span><strong>指定用户组</strong><p>用户与文档至少共享一个授权组。</p></div>
          <div><span className="policy-icon private"><Lock size={20} /></span><strong>仅自己</strong><p>仅所有者和组织管理员可检索。</p></div>
        </div>
        <div className="acl-flow"><span><FileKey2 size={17} />查询请求</span><i /><span><Building2 size={17} />租户校验</span><i /><span><ShieldCheck size={17} />角色与组 ACL</span><i /><span><Eye size={17} />授权片段召回</span></div>
      </section>

      {user.role === "admin" && system && (
        <section className="system-section">
          <div className="section-heading">
            <div><h2>模型与向量索引</h2><p>运行状态来自本地模型服务和当前租户索引</p></div>
            <button className="button compact secondary" onClick={rebuildIndex} disabled={reindexing || !system.models.embedding.ready}>
              <RefreshCw className={reindexing ? "spin" : ""} size={15} />{reindexing ? "正在重建" : "重建索引"}
            </button>
          </div>
          <div className="system-status-grid">
            <div><span className={system.models.generation.ready ? "model-dot ready" : "model-dot"} /><span><strong>生成模型</strong><small>{system.models.generation.model} · {system.models.generation.ready ? "可用" : "不可用"}</small></span></div>
            <div><span className={system.models.embedding.ready ? "model-dot ready" : "model-dot"} /><span><strong>Embedding</strong><small>{system.models.embedding.model} · {system.models.embedding.dimensions ?? "-"} 维</small></span></div>
            <div><span className={system.index.stale_chunks === 0 ? "model-dot ready" : "model-dot warning"} /><span><strong>向量版本</strong><small>{system.index.current_chunks} 当前 · {system.index.stale_chunks} 待重建</small></span></div>
            <div><span className={system.vector_store.ready ? "model-dot ready" : "model-dot"} /><span><strong>向量库</strong><small>{system.vector_store.provider} · {system.vector_store.ready ? "可用" : system.vector_store.error ?? "不可用"}</small></span></div>
          </div>
        </section>
      )}

      {user.role === "admin" && settings && <section className="settings-section">
        <div className="section-heading"><div><h2>RAG 与安全参数</h2><p>新文档采用当前切块参数，检索和回答参数即时生效</p></div></div>
        <form className="settings-form" onSubmit={saveSettings}>
          <div className="settings-grid">
            <label className="field"><span>默认分块策略</span><select value={settings.chunk_strategy} onChange={(event) => setSettings({ ...settings, chunk_strategy: event.target.value as RagSettings["chunk_strategy"] })}><option value="fixed">固定大小</option><option value="semantic">语义段落</option></select></label>
            <label className="field"><span>切块大小</span><input type="number" min={200} max={4000} value={settings.chunk_size} onChange={(event) => setSettings({ ...settings, chunk_size: Number(event.target.value) })} /></label>
            <label className="field"><span>重叠字符</span><input type="number" min={0} max={1000} value={settings.chunk_overlap} onChange={(event) => setSettings({ ...settings, chunk_overlap: Number(event.target.value) })} /></label>
            <label className="field"><span>Top K</span><input type="number" min={2} max={20} value={settings.top_k} onChange={(event) => setSettings({ ...settings, top_k: Number(event.target.value) })} /></label>
            <label className="field"><span>关键词权重</span><input type="number" step="0.05" min={0} max={1} value={settings.lexical_weight} onChange={(event) => setSettings({ ...settings, lexical_weight: Number(event.target.value) })} /></label>
            <label className="field"><span>向量权重</span><input type="number" step="0.05" min={0} max={1} value={settings.vector_weight} onChange={(event) => setSettings({ ...settings, vector_weight: Number(event.target.value) })} /></label>
            <label className="field"><span>相似度阈值</span><input type="number" step="0.05" min={-1} max={1} value={settings.similarity_threshold} onChange={(event) => setSettings({ ...settings, similarity_threshold: Number(event.target.value) })} /></label>
            <label className="field"><span>Temperature</span><input type="number" step="0.05" min={0} max={2} value={settings.temperature} onChange={(event) => setSettings({ ...settings, temperature: Number(event.target.value) })} /></label>
            <label className="field"><span>上下文字符上限</span><input type="number" min={2000} max={100000} value={settings.max_context_chars} onChange={(event) => setSettings({ ...settings, max_context_chars: Number(event.target.value) })} /></label>
            <label className="field"><span>历史消息上限</span><input type="number" min={0} max={50} value={settings.max_history_messages} onChange={(event) => setSettings({ ...settings, max_history_messages: Number(event.target.value) })} /></label>
          </div>
          <div className="toggle-row"><label><input type="checkbox" checked={settings.bm25_enabled} onChange={(event) => setSettings({ ...settings, bm25_enabled: event.target.checked })} /><span><strong>BM25 关键词检索</strong><small>关闭后只使用向量召回</small></span></label><label><input type="checkbox" checked={settings.reranker_enabled} onChange={(event) => setSettings({ ...settings, reranker_enabled: event.target.checked })} /><span><strong>融合后重排序</strong><small>使用本地词项覆盖率做确定性重排</small></span></label></div>
          <div className="toggle-row"><label><input type="checkbox" checked={settings.strict_rag} onChange={(event) => setSettings({ ...settings, strict_rag: event.target.checked })} /><span><strong>严格知识库模式</strong><small>无相关资料时禁止模型使用常识补答</small></span></label><label><input type="checkbox" checked={settings.prompt_injection_filter} onChange={(event) => setSettings({ ...settings, prompt_injection_filter: event.target.checked })} /><span><strong>Prompt 注入过滤</strong><small>拦截覆盖系统指令和泄漏提示词的常见模式</small></span></label></div>
          <label className="field"><span>敏感词（逗号分隔）</span><input value={settings.sensitive_words.join(", ")} onChange={(event) => setSettings({ ...settings, sensitive_words: event.target.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean) })} /></label>
          <label className="field"><span>系统 Prompt</span><textarea rows={4} value={settings.system_prompt} onChange={(event) => setSettings({ ...settings, system_prompt: event.target.value })} /></label>
          <div className="settings-actions"><button className="button primary" disabled={savingSettings}>{savingSettings ? <LoaderCircle className="spin" size={17} /> : <Save size={17} />}保存参数</button></div>
        </form>
      </section>}

      {user.role === "admin" && (
        <section className="members-section">
          <div className="section-heading">
            <div><h2>成员权限</h2><p>角色控制操作能力，用户组控制受限文档的访问范围</p></div>
            <button className="button compact secondary" onClick={() => setCreateUserOpen(true)}><UserPlus size={15} />新建成员</button>
          </div>
          <div className="data-table-wrap">
            {loading ? <div className="table-state"><LoaderCircle className="spin" size={23} />正在读取成员权限</div> : (
              <table className="data-table members-table">
                <thead><tr><th>成员</th><th>角色</th><th>所属用户组</th><th>状态与操作</th></tr></thead>
                <tbody>{members.map((member) => (
                  <tr key={member.id}>
                    <td><div className="member-cell"><span className="member-avatar">{member.display_name.slice(0, 1)}</span><span><strong>{member.display_name}</strong><small>{member.email} · @{member.username}</small></span></div></td>
                    <td><span className={`role-badge ${member.role}`}>{roleConfig[member.role].label}</span></td>
                    <td><div className="group-tags">{member.groups.length ? member.groups.map((group) => <span key={group.id}>{group.name}</span>) : <em>无用户组</em>}</div></td>
                    <td><div className="row-actions member-actions"><span className={`status-badge ${member.active ? "indexed" : ""}`}><i />{member.active ? "启用" : "停用"}</span><button className="icon-button" title="设置组织角色和用户组" onClick={() => setEditingMember(member)}><Settings2 size={15} /></button><button className="icon-button danger" title={member.active ? "停用成员" : "启用成员"} disabled={member.id === user.id} onClick={() => toggleMember(member)}><Power size={15} /></button></div></td>
                  </tr>
                ))}</tbody>
              </table>
            )}
            <Pagination page={memberPage} pageSize={10} total={memberTotal} onPageChange={setMemberPage} />
          </div>
        </section>
      )}

      <section className="groups-section">
        <div className="section-heading">
          <div><h2>用户组</h2><p>{user.organization} · 你属于 {user.groups.length ? user.groups.join("、") : "无指定用户组"}</p></div>
          {user.role === "admin" && <button className="button compact secondary" onClick={() => setCreateGroupOpen(true)}><Plus size={15} />新建用户组</button>}
        </div>
          <div className="group-list">
          {groups.map((group) => (
            <div key={group.id}>
              <span className="group-avatar"><Users size={18} /></span>
              <span><strong>{group.name}</strong><small>{group.description}</small></span>
              <b>{group.member_count} 人</b>
              {user.role === "admin" && <button className="icon-button danger" title="删除用户组" onClick={() => removeGroup(group)}><Trash2 size={16} /></button>}
            </div>
          ))}
          </div>
        <Pagination page={groupPage} pageSize={10} total={groupTotal} onPageChange={setGroupPage} />
      </section>

      {user.role === "admin" && (
        <section className="audit-section">
          <div className="section-heading"><div><h2>最近审计事件</h2><p>查询、上传、删除和权限变更均记录在当前租户内</p></div></div>
          <div className="data-table-wrap">
            {loading ? <div className="table-state"><LoaderCircle className="spin" size={23} />正在读取审计日志</div> : (
              <table className="data-table audit-table"><thead><tr><th>时间</th><th>成员</th><th>动作</th><th>查询 / 资源</th><th>结果</th></tr></thead><tbody>
                {audit.map((item) => <tr key={item.id}><td>{time(item.created_at)}</td><td>{item.user_name}</td><td><span className="audit-action">{actionLabels[item.action] ?? item.action}</span></td><td className="audit-query">{item.query ?? item.resource_id ?? "-"}</td><td>{item.action === "knowledge.query" ? `${String(item.metadata.citations ?? 0)} 条引用` : "已完成"}</td></tr>)}
              </tbody></table>
            )}
            <Pagination page={auditPage} pageSize={10} total={auditTotal} onPageChange={setAuditPage} />
          </div>
        </section>
      )}

      {editingMember && (
        <MemberAccessDialog
          token={token}
          member={editingMember}
            groups={groupOptions}
          onClose={() => setEditingMember(null)}
          onUpdated={async (updated) => {
            setMembers((current) => current.map((item) => item.id === updated.id ? updated : item));
            setEditingMember(null);
            setGroupOptions(await api.groups(token));
            notify("成员权限已更新", "success");
          }}
          notify={notify}
        />
      )}
      {createGroupOpen && (
        <CreateGroupDialog
          token={token}
          onClose={() => setCreateGroupOpen(false)}
          onCreated={(group) => {
            setGroups((current) => [...current, group].sort((left, right) => left.name.localeCompare(right.name, "zh-CN")));
            setGroupOptions((current) => [...current, group].sort((left, right) => left.name.localeCompare(right.name, "zh-CN")));
            setCreateGroupOpen(false);
            notify("用户组已创建", "success");
          }}
          notify={notify}
        />
      )}
      {createUserOpen && <CreateUserDialog token={token} groups={groupOptions} onClose={() => setCreateUserOpen(false)} onCreated={async (member) => { setMembers((current) => [...current, member]); setCreateUserOpen(false); await load(); notify("成员已创建", "success"); }} notify={notify} />}
    </section>
  );
}

interface MemberAccessDialogProps {
  token: string;
  member: AdminUser;
  groups: Group[];
  onClose: () => void;
  onUpdated: (member: AdminUser) => void | Promise<void>;
  notify: (message: string, tone?: "error" | "success") => void;
}

function MemberAccessDialog({ token, member, groups, onClose, onUpdated, notify }: MemberAccessDialogProps) {
  const [role, setRole] = useState<Role>(member.role);
  const [selectedGroups, setSelectedGroups] = useState<string[]>(member.groups.map((group) => group.id));
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    try {
      await onUpdated(await api.updateUserAccess(token, member.id, role, selectedGroups));
    } catch (error) {
      notify(error instanceof Error ? error.message : "成员权限更新失败", "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <form className="modal member-access-dialog" role="dialog" aria-modal="true" aria-labelledby="member-access-title" onSubmit={submit}>
        <div className="modal-header"><div><p className="eyebrow">Member Access</p><h2 id="member-access-title">设置成员权限</h2></div><button type="button" className="icon-button" title="关闭" onClick={onClose}><X size={19} /></button></div>
        <div className="modal-body">
          <div className="permission-target"><span className="member-avatar large">{member.display_name.slice(0, 1)}</span><span><strong>{member.display_name}</strong><small>{member.email} · @{member.username}</small></span></div>
          <fieldset className="field"><legend>成员角色</legend><div className="role-options">
            {(Object.entries(roleConfig) as [Role, (typeof roleConfig)[Role]][]).map(([value, config]) => {
              const Icon = config.icon;
              return <button type="button" key={value} className={role === value ? "active" : ""} onClick={() => setRole(value)}><Icon size={18} /><span><strong>{config.label}</strong><small>{config.description}</small></span></button>;
            })}
          </div></fieldset>
          <fieldset className="field"><legend>所属用户组</legend><div className="group-checks">
            {groups.map((group) => <label key={group.id}><input type="checkbox" checked={selectedGroups.includes(group.id)} onChange={() => setSelectedGroups((current) => current.includes(group.id) ? current.filter((id) => id !== group.id) : [...current, group.id])} /><span><strong>{group.name}</strong><small>{group.description} · 当前 {group.member_count} 人</small></span></label>)}
          </div></fieldset>
          <div className="security-note"><ShieldCheck size={18} /><span><strong>权限变更立即生效</strong><small>组织至少需要保留一名管理员，跨租户用户组不会被接受。</small></span></div>
        </div>
        <div className="modal-footer"><button type="button" className="button secondary" onClick={onClose}>取消</button><button className="button primary" disabled={submitting}>{submitting ? <LoaderCircle className="spin" size={18} /> : <Save size={18} />}保存权限</button></div>
      </form>
    </div>
  );
}

interface CreateGroupDialogProps {
  token: string;
  onClose: () => void;
  onCreated: (group: Group) => void;
  notify: (message: string, tone?: "error" | "success") => void;
}

function CreateGroupDialog({ token, onClose, onCreated, notify }: CreateGroupDialogProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    try {
      onCreated(await api.createGroup(token, name.trim(), description.trim()));
    } catch (error) {
      notify(error instanceof Error ? error.message : "用户组创建失败", "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <form className="modal group-dialog" role="dialog" aria-modal="true" aria-labelledby="group-title" onSubmit={submit}>
        <div className="modal-header"><div><p className="eyebrow">Access Group</p><h2 id="group-title">新建用户组</h2></div><button type="button" className="icon-button" title="关闭" onClick={onClose}><X size={19} /></button></div>
        <div className="modal-body">
          <label className="field"><span>用户组名称</span><input value={name} onChange={(event) => setName(event.target.value)} minLength={2} maxLength={80} required placeholder="例如：法务与合规" /></label>
          <label className="field"><span>用途说明</span><input value={description} onChange={(event) => setDescription(event.target.value)} maxLength={240} placeholder="说明该组包含的成员或负责范围" /></label>
        </div>
        <div className="modal-footer"><button type="button" className="button secondary" onClick={onClose}>取消</button><button className="button primary" disabled={submitting || name.trim().length < 2}>{submitting ? <LoaderCircle className="spin" size={18} /> : <Plus size={18} />}创建用户组</button></div>
      </form>
    </div>
  );
}

function CreateUserDialog({ token, groups, onClose, onCreated, notify }: { token: string; groups: Group[]; onClose: () => void; onCreated: (member: AdminUser) => void; notify: GovernanceViewProps["notify"] }) {
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setSaving(true);
    try {
      onCreated(await api.createUser(token, { username, display_name: displayName, email, password, role, group_ids: groupIds }));
    } catch (error) { notify(error instanceof Error ? error.message : "成员创建失败", "error"); }
    finally { setSaving(false); }
  }
  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><form className="modal" onSubmit={submit}>
    <div className="modal-header"><div><p className="eyebrow">Organization member</p><h2>新建成员</h2></div><button type="button" className="icon-button" title="关闭" onClick={onClose}><X size={19} /></button></div>
    <div className="modal-body"><div className="settings-grid"><label className="field"><span>用户名</span><input value={username} onChange={(event) => setUsername(event.target.value)} minLength={2} required /></label><label className="field"><span>显示名称</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} minLength={2} required /></label><label className="field"><span>邮箱</span><input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label><label className="field"><span>初始密码（至少 12 位）</span><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={12} required /></label></div>
      <fieldset className="field"><legend>组织角色</legend><div className="segmented three-segments">{(["admin", "editor", "viewer"] as Role[]).map((value) => <button type="button" key={value} className={role === value ? "active" : ""} onClick={() => setRole(value)}>{roleConfig[value].label}</button>)}</div></fieldset>
      <fieldset className="field"><legend>用户组</legend><div className="group-checks member-checks">{groups.map((group) => <label key={group.id}><input type="checkbox" checked={groupIds.includes(group.id)} onChange={() => setGroupIds((current) => current.includes(group.id) ? current.filter((id) => id !== group.id) : [...current, group.id])} /><span><strong>{group.name}</strong><small>{group.description}</small></span></label>)}</div></fieldset>
      <div className="security-note"><ShieldCheck size={18} /><span><strong>创建后还需分配知识库权限</strong><small>组织角色与知识库权限是两层独立控制；请到“知识库管理”设置查看、上传、编辑或管理权限。</small></span></div>
    </div>
    <div className="modal-footer"><button type="button" className="button secondary" onClick={onClose}>取消</button><button className="button primary" disabled={saving}>{saving ? <LoaderCircle className="spin" size={17} /> : <UserPlus size={17} />}创建成员</button></div>
  </form></div>;
}

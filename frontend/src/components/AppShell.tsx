import { useState } from "react";
import {
  BookOpenText,
  ChevronDown,
  FileStack,
  Database,
  LogOut,
  Menu,
  MessageSquareText,
  ShieldCheck,
  X,
} from "lucide-react";
import type { KnowledgeBase, User } from "../types";

export type View = "chat" | "documents" | "knowledge-bases" | "governance";

interface AppShellProps {
  user: User;
  view: View;
  setView: (view: View) => void;
  onLogout: () => void;
  knowledgeBases: KnowledgeBase[];
  knowledgeBaseId: string;
  setKnowledgeBaseId: (id: string) => void;
  children: React.ReactNode;
}

const roleLabels = { admin: "管理员", editor: "编辑者", viewer: "只读成员" };

export function AppShell({ user, view, setView, onLogout, knowledgeBases, knowledgeBaseId, setKnowledgeBaseId, children }: AppShellProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const nav = [
    { id: "chat" as const, label: "知识问答", icon: MessageSquareText },
    { id: "documents" as const, label: "文档库", icon: FileStack },
    { id: "knowledge-bases" as const, label: "知识库管理", icon: Database },
    { id: "governance" as const, label: "权限与审计", icon: ShieldCheck },
  ];

  function navigate(target: View) {
    setView(target);
    setMobileOpen(false);
  }

  return (
    <div className="app-shell">
      {mobileOpen && <button className="mobile-scrim" aria-label="关闭导航" onClick={() => setMobileOpen(false)} />}
      <aside className={mobileOpen ? "sidebar mobile-open" : "sidebar"}>
        <div className="sidebar-brand">
          <span className="brand-mark small"><BookOpenText size={20} /></span>
          <span><strong>知域</strong><small>Knowledge Hub</small></span>
          <button className="icon-button sidebar-close" title="关闭导航" onClick={() => setMobileOpen(false)}>
            <X size={19} />
          </button>
        </div>
        <div className="workspace-label">
          <label htmlFor="workspace-select">当前知识库</label>
          <select id="workspace-select" value={knowledgeBaseId} onChange={(event) => setKnowledgeBaseId(event.target.value)} disabled={!knowledgeBases.length}>
            {knowledgeBases.length ? knowledgeBases.map((item) => <option key={item.id} value={item.id}>{item.name}</option>) : <option value="">暂无授权空间</option>}
          </select>
        </div>
        <nav className="sidebar-nav" aria-label="主导航">
          {nav.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={view === item.id ? "nav-item active" : "nav-item"}
                onClick={() => navigate(item.id)}
              >
                <Icon size={19} />
                {item.label}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-policy">
          <ShieldCheck size={17} />
          <span><strong>访问策略已启用</strong><small>租户 · 角色 · 用户组</small></span>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <button className="icon-button mobile-menu" title="打开导航" onClick={() => setMobileOpen(true)}>
            <Menu size={21} />
          </button>
          <div className="topbar-title">
            <span>{view === "chat" ? "知识问答" : view === "documents" ? "文档库" : view === "knowledge-bases" ? "知识库管理" : "权限与审计"}</span>
            <small>{user.organization}</small>
          </div>
          <div className="profile-menu">
            <button className="profile-trigger" onClick={() => setProfileOpen((current) => !current)}>
              <span className="avatar">{user.display_name.slice(0, 1)}</span>
              <span className="profile-copy"><strong>{user.display_name}</strong><small>{roleLabels[user.role]}</small></span>
              <ChevronDown size={16} />
            </button>
            {profileOpen && (
              <div className="profile-popover">
                <span>{user.email}</span>
                <button onClick={onLogout}><LogOut size={16} />退出登录</button>
              </div>
            )}
          </div>
        </header>
        <div className="workspace-content">{children}</div>
      </div>
    </div>
  );
}

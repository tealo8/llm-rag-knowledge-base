import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, LoaderCircle, XCircle, Lock, FileText } from "lucide-react";
import { api, ApiError } from "./api";
import { AppShell, type View } from "./components/AppShell";
import { ChatView } from "./components/ChatView";
import { DocumentsView } from "./components/DocumentsView";
import { GovernanceView } from "./components/GovernanceView";
import { KnowledgeBasesView } from "./components/KnowledgeBasesView";
import { LoginScreen } from "./components/LoginScreen";
import type { KnowledgeBase, User } from "./types";

const TOKEN_KEY = "zhiyu_access_token";
const KNOWLEDGE_BASE_KEY = "zhiyu_knowledge_base";

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) ?? "");
  const [user, setUser] = useState<User | null>(null);
  const [view, setView] = useState<View>("chat");
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [knowledgeBaseId, setKnowledgeBaseId] = useState(() => localStorage.getItem(KNOWLEDGE_BASE_KEY) ?? "");
  const [checking, setChecking] = useState(Boolean(token));
  const [loginError, setLoginError] = useState("");
  const [toast, setToast] = useState<{ message: string; tone: "error" | "success" } | null>(null);

  const sharedMatch = window.location.pathname.match(/^\/shared\/conversations\/([^/]+)/);
  if (sharedMatch) return <SharedConversationView token={decodeURIComponent(sharedMatch[1])} />;

  useEffect(() => {
    if (!token) { setChecking(false); return; }
    api.me(token).then(setUser).catch(() => logout()).finally(() => setChecking(false));
  }, [token]);

  const refreshKnowledgeBases = useCallback(async () => {
    if (!token || !user) return;
    try {
      const items = await api.knowledgeBases(token);
      setKnowledgeBases(items);
      setKnowledgeBaseId((current) => {
        const next = items.some((item) => item.id === current) ? current : (items[0]?.id ?? "");
        if (next) localStorage.setItem(KNOWLEDGE_BASE_KEY, next);
        else localStorage.removeItem(KNOWLEDGE_BASE_KEY);
        return next;
      });
    } catch (error) {
      notify(error instanceof Error ? error.message : "知识库加载失败", "error");
    }
  }, [token, user]);

  useEffect(() => { refreshKnowledgeBases(); }, [refreshKnowledgeBases]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 3600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  async function login(username: string, password: string) {
    setLoginError("");
    try {
      const result = await api.login(username, password);
      localStorage.setItem(TOKEN_KEY, result.access_token);
      setToken(result.access_token);
      setUser(result.user);
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : "登录失败");
      throw error;
    }
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    setToken("");
    setUser(null);
    setKnowledgeBases([]);
    setKnowledgeBaseId("");
    setView("chat");
  }

  function notify(message: string, tone: "error" | "success" = "success") {
    setToast({ message, tone });
  }

  function selectKnowledgeBase(id: string) {
    setKnowledgeBaseId(id);
    localStorage.setItem(KNOWLEDGE_BASE_KEY, id);
  }

  if (checking) return <div className="app-loading"><LoaderCircle className="spin" size={26} /><span>正在验证知识空间</span></div>;
  if (!token || !user) return <LoginScreen onLogin={login} error={loginError} />;

  return (
    <AppShell user={user} view={view} setView={setView} onLogout={logout} knowledgeBases={knowledgeBases} knowledgeBaseId={knowledgeBaseId} setKnowledgeBaseId={selectKnowledgeBase}>
      {view === "chat" && <ChatView key={knowledgeBaseId} token={token} user={user} knowledgeBase={knowledgeBases.find((item) => item.id === knowledgeBaseId) ?? null} notify={notify} />}
      {view === "documents" && <DocumentsView key={knowledgeBaseId} token={token} user={user} knowledgeBase={knowledgeBases.find((item) => item.id === knowledgeBaseId) ?? null} notify={notify} />}
      {view === "knowledge-bases" && <KnowledgeBasesView token={token} user={user} selectedId={knowledgeBaseId} onSelect={selectKnowledgeBase} onChanged={refreshKnowledgeBases} notify={notify} />}
      {view === "governance" && <GovernanceView token={token} user={user} notify={notify} />}
      {toast && <div className={`toast ${toast.tone}`} role="status">{toast.tone === "success" ? <CheckCircle2 size={18} /> : <XCircle size={18} />}{toast.message}</div>}
    </AppShell>
  );
}

function SharedConversationView({ token }: { token: string }) {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.sharedConversation>> | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  async function load(value?: string) { setLoading(true); setError(""); try { setData(await api.sharedConversation(token, value)); } catch (err) { if (err instanceof ApiError && err.status === 401 && !value) setError("此分享链接需要密码"); else setError(err instanceof Error ? err.message : "分享链接读取失败"); } finally { setLoading(false); } }
  useEffect(() => { void load(); }, [token]);
  if (loading) return <div className="app-loading"><LoaderCircle className="spin" size={26} /><span>正在读取分享会话</span></div>;
  if (!data) return <div className="shared-page"><div className="shared-card"><Lock size={26} /><h1>受保护的会话</h1><p>{error || "链接无效或已过期"}</p>{error.includes("密码") && <form onSubmit={(event) => { event.preventDefault(); void load(password); }}><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="输入访问密码" minLength={6} /><button className="button primary">查看会话</button></form>}</div></div>;
  return <div className="shared-page"><main className="shared-card conversation-shared"><div className="shared-heading"><div><p className="eyebrow">Shared conversation</p><h1>{data.title}</h1><p>{data.knowledge_base_name} · {data.mode === "readonly" ? "只读分享" : "继续模式预留（当前只读）"}</p></div><FileText size={24} /></div><div className="shared-messages">{data.messages.map((message) => <article key={message.id} className={`shared-message ${message.role}`}><span>{message.role === "user" ? "提问" : "知域助手"}</span><div>{message.content}</div>{message.citations.length > 0 && <small>引用：{message.citations.map((citation) => `${citation.title}${citation.page_number ? ` · 第${citation.page_number}页` : ""}`).join("；")}</small>}</article>)}</div></main></div>;
}

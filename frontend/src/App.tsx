import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, LoaderCircle, XCircle } from "lucide-react";
import { api } from "./api";
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

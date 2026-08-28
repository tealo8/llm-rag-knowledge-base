import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle, ArrowUp, BookOpen, CheckCircle2, Clock3, Download, FileDown, FileText,
  History, LoaderCircle, MessageSquarePlus, Search, Sparkles, ThumbsDown,
  ThumbsUp, Trash2, X, Pencil, Star, Share2, GitBranch, Copy, SlidersHorizontal,
} from "lucide-react";
import { api } from "../api";
import type { ChatResult, Chunk, Citation, ConversationSummary, KnowledgeBase, User } from "../types";
import { Pagination } from "./Pagination";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  result?: ChatResult;
  feedback?: "up" | "down" | null;
}

interface Props {
  token: string;
  user: User;
  knowledgeBase: KnowledgeBase | null;
  notify: (message: string, tone?: "error" | "success") => void;
}

const suggestions = [
  "研发项目发布前必须完成哪些检查？",
  "紧急修复完成后需要多久提交复盘？",
  "代码合并前的审查要求是什么？",
];

export function ChatView({ token, user, knowledgeBase, notify }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState("");
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationPage, setConversationPage] = useState(1);
  const [conversationTotal, setConversationTotal] = useState(0);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [activeResult, setActiveResult] = useState<ChatResult | null>(null);
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
  const [chunk, setChunk] = useState<Chunk | null>(null);
  const [feedbackTarget, setFeedbackTarget] = useState<ChatMessage | null>(null);
  const [feedbackReason, setFeedbackReason] = useState<"hallucination" | "incorrect" | "incomplete" | "irrelevant">("incorrect");
  const [feedbackComment, setFeedbackComment] = useState("");
  const [rerankEnabled, setRerankEnabled] = useState(Boolean(knowledgeBase?.rag_settings?.reranker_enabled));
  const [topK, setTopK] = useState(Number(knowledgeBase?.rag_settings?.top_k ?? 6));
  const [deepMode, setDeepMode] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [model, setModel] = useState("qwen2.5:7b");
  const [temperature, setTemperature] = useState(0.1);
  const [topP, setTopP] = useState(0.9);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  async function loadConversations(requestedPage = conversationPage) {
    if (!knowledgeBase || knowledgeBase.permission === "upload") return setConversations([]);
    try {
      const result = await api.conversationPage(token, knowledgeBase.id, { page: requestedPage, pageSize: 8 });
      if (requestedPage > Math.max(result.totalPages, 1)) { setConversationPage(Math.max(result.totalPages, 1)); return; }
      setConversations(result.items);
      setConversationTotal(result.total);
    }
    catch (error) { notify(error instanceof Error ? error.message : "会话历史加载失败", "error"); }
  }
  useEffect(() => { setConversationPage(1); }, [knowledgeBase?.id]);
  useEffect(() => { void loadConversations(conversationPage); }, [token, knowledgeBase?.id, conversationPage]);

  function newConversation() {
    setConversationId("");
    setMessages([]);
    setActiveResult(null);
    setActiveCitation(null);
    setChunk(null);
    setHistoryOpen(false);
  }

  async function openConversation(id: string) {
    try {
      const detail = await api.conversation(token, id);
      setConversationId(detail.id);
      setMessages(detail.messages.map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
        feedback: message.feedback,
        result: message.role === "assistant" ? {
          answer: message.content,
          citations: message.citations,
          retrieval: message.metrics,
          conversation_id: detail.id,
          message_id: message.id,
        } : undefined,
      })));
      const latest = [...detail.messages].reverse().find((message) => message.role === "assistant");
      if (latest) {
        const result = { answer: latest.content, citations: latest.citations, retrieval: latest.metrics, conversation_id: detail.id, message_id: latest.id };
        setActiveResult(result);
        setActiveCitation(latest.citations[0] ?? null);
      }
      setHistoryOpen(false);
    } catch (error) { notify(error instanceof Error ? error.message : "会话读取失败", "error"); }
  }

  async function ask(value = query) {
    const trimmed = value.trim();
    if (!trimmed || loading || !knowledgeBase) return;
    setMessages((current) => [...current, { id: crypto.randomUUID(), role: "user", content: trimmed }]);
    setQuery(""); setLoading(true);
    abortRef.current = new AbortController();
    try {
      const result = await api.chat(token, trimmed, knowledgeBase.id, conversationId || undefined, { top_k: topK, rerank: rerankEnabled, mode: deepMode ? "deep" : "fast", model, temperature, top_p: topP, signal: abortRef.current.signal });
      setConversationId(result.conversation_id);
      setMessages((current) => [...current, { id: result.message_id, role: "assistant", content: result.answer, result, feedback: null }]);
      setActiveResult(result);
      setActiveCitation(result.citations[0] ?? null);
      setChunk(null);
      await loadConversations(conversationPage);
    } catch (error) { if (!(error instanceof DOMException && error.name === "AbortError")) notify(error instanceof Error ? error.message : "问答请求失败", "error"); }
    finally { abortRef.current = null; setLoading(false); textareaRef.current?.focus(); }
  }

  async function setFeedback(message: ChatMessage, rating: "up" | "down", reason?: string, comment = "") {
    if (!message.result) return;
    try {
      await api.feedback(token, message.result.conversation_id, message.id, rating, reason, comment);
      setMessages((current) => current.map((item) => item.id === message.id ? { ...item, feedback: rating } : item));
      notify("反馈已记录", "success");
      setFeedbackTarget(null);
    } catch (error) { notify(error instanceof Error ? error.message : "反馈保存失败", "error"); }
  }

  async function renameConversation(item: ConversationSummary) {
    const title = window.prompt("请输入新的会话名称", item.title)?.trim();
    if (!title || title === item.title) return;
    try { await api.updateConversation(token, item.id, { title }); await loadConversations(conversationPage); notify("会话已重命名", "success"); }
    catch (error) { notify(error instanceof Error ? error.message : "重命名失败", "error"); }
  }

  async function toggleFavorite(item: ConversationSummary) {
    try { await api.updateConversation(token, item.id, { favorite: !item.favorite }); await loadConversations(conversationPage); }
    catch (error) { notify(error instanceof Error ? error.message : "收藏状态更新失败", "error"); }
  }

  async function shareConversation() {
    if (!conversationId) return;
    const password = window.prompt("可选：设置访问密码（至少 6 位，留空表示无密码）", "") || undefined;
    try {
      const share = await api.shareConversation(token, conversationId, { mode: "readonly", expires_in_hours: 72, password: password && password.length >= 6 ? password : undefined });
      await navigator.clipboard?.writeText(`${window.location.origin}/shared/conversations/${share.token}`);
      notify("只读分享链接已复制，72 小时后失效", "success");
    } catch (error) { notify(error instanceof Error ? error.message : "分享链接生成失败", "error"); }
  }

  async function branchConversation(message?: ChatMessage) {
    if (!conversationId) return;
    try { const branch = await api.branchConversation(token, conversationId, message?.id); await openConversation(branch.id); await loadConversations(conversationPage); notify("已创建会话分支", "success"); }
    catch (error) { notify(error instanceof Error ? error.message : "创建分支失败", "error"); }
  }

  async function copyText(value: string) {
    try { await navigator.clipboard.writeText(value); notify("内容已复制", "success"); } catch { notify("浏览器不允许访问剪贴板", "error"); }
  }

  async function removeConversation(item: ConversationSummary) {
    if (!window.confirm(`确认删除会话“${item.title}”？`)) return;
    try {
      await api.deleteConversation(token, item.id);
      if (conversationId === item.id) newConversation();
       await loadConversations(conversationPage);
      notify("会话已删除", "success");
    } catch (error) { notify(error instanceof Error ? error.message : "删除失败", "error"); }
  }

  async function openCitation(citation: Citation, result: ChatResult) {
    setActiveResult(result); setActiveCitation(citation); setChunk(null);
    try { setChunk(await api.chunk(token, citation.document_id, citation.chunk_id)); }
    catch (error) { notify(error instanceof Error ? error.message : "引用读取失败", "error"); }
  }

  function renderAnswer(message: ChatMessage) {
    const lines = message.content.split("\n");
    const blocks: ReactNode[] = [];
    let code: string[] = [];
    let inCode = false;
    lines.forEach((line, index) => {
      if (line.trim().startsWith("```")) {
        if (inCode) { const value = code.join("\n"); blocks.push(<div className="code-block" key={`code-${index}`}><button className="icon-button" title="复制代码" onClick={() => copyText(value)}><Copy size={14} /></button><pre>{value}</pre></div>); code = []; }
        inCode = !inCode; return;
      }
      if (inCode) { code.push(line); return; }
      if (!line.trim()) return;
      blocks.push(<p key={`p-${index}`}>{line.split(/(\[\d+])/g).map((part, partIndex) => { const match = part.match(/^\[(\d+)]$/); const citation = match && message.result?.citations.find((item) => item.index === Number(match[1])); return citation ? <button key={partIndex} className="inline-citation" onClick={() => openCitation(citation, message.result!)}>{part}</button> : <Fragment key={partIndex}>{part}</Fragment>; })}</p>);
    });
    return <>{blocks}</>;
  }

  if (!knowledgeBase) return <div className="empty-workspace"><BookOpen size={30} /><h2>没有可访问的知识库</h2><p>请让管理员在“知识库管理”中授予查看权限。</p></div>;
  if (knowledgeBase.permission === "upload") return <div className="empty-workspace"><BookOpen size={30} /><h2>当前知识库仅允许上传</h2><p>你可以在文档库提交资料，但不能查看文档或发起检索。</p></div>;
  if (!knowledgeBase.allow_qa && knowledgeBase.permission !== "admin") return <div className="empty-workspace"><BookOpen size={30} /><h2>当前知识库暂未开放问答</h2><p>请联系知识库管理员开启问答能力。</p></div>;

  return <div className="chat-layout">
    <section className="chat-main">
      <div className="chat-contextbar"><span><BookOpen size={15} />{knowledgeBase.name}</span><div><button className="button compact secondary" onClick={() => setHistoryOpen(true)}><History size={15} />会话历史</button><button className="icon-button" title="检索设置" onClick={() => setAdvancedOpen((value) => !value)}><SlidersHorizontal size={17} /></button><button className="icon-button" title="新会话" onClick={newConversation}><MessageSquarePlus size={17} /></button>{conversationId && <><button className="icon-button" title="分享会话" onClick={shareConversation}><Share2 size={17} /></button><button className="icon-button" title="导出 Markdown" onClick={() => api.exportConversation(token, conversationId, "markdown").catch((error) => notify(error.message, "error"))}><Download size={17} /></button><button className="icon-button" title="导出 PDF" onClick={() => api.exportConversation(token, conversationId, "pdf").catch((error) => notify(error.message, "error"))}><FileDown size={17} /></button></>}</div></div>
      {advancedOpen && <div className="chat-options"><label><input type="checkbox" checked={rerankEnabled} onChange={(event) => setRerankEnabled(event.target.checked)} />启用 Rerank</label><label>片段数 <input type="number" min={2} max={20} value={topK} onChange={(event) => setTopK(Number(event.target.value))} /></label><label>模型 <select value={model} onChange={(event) => setModel(event.target.value)}><option value="qwen2.5:7b">通用 · Qwen2.5 7B</option><option value="qwen2.5-coder:7b">代码 · Qwen2.5 Coder</option><option value="qwen2.5:14b">长文档 · Qwen2.5 14B</option></select></label><label>温度 <input type="number" min={0} max={2} step={0.1} value={temperature} onChange={(event) => setTemperature(Number(event.target.value))} /></label><label>Top-p <input type="number" min={0} max={1} step={0.05} value={topP} onChange={(event) => setTopP(Number(event.target.value))} /></label><label className="segmented"><button type="button" className={!deepMode ? "active" : ""} onClick={() => setDeepMode(false)}>快速</button><button type="button" className={deepMode ? "active" : ""} onClick={() => setDeepMode(true)}>深度</button></label><span className="option-note">当前 Prompt：{String(knowledgeBase.rag_settings?.system_prompt || "组织默认模板")}</span></div>}
      <div className="chat-scroll">
        {!messages.length ? <div className="chat-empty"><span className="assistant-emblem"><Sparkles size={25} /></span><h1>{user.display_name}，需要查找什么？</h1><p>仅检索“{knowledgeBase.name}”内你有权访问的资料，并附可核验引用。</p><div className="suggestion-list">{suggestions.map((suggestion) => <button key={suggestion} onClick={() => ask(suggestion)}><Search size={17} /><span>{suggestion}</span><ArrowUp size={16} /></button>)}</div></div> :
          <div className="message-list">{messages.map((message) => <article key={message.id} className={`message ${message.role}`}>
            <div className="message-author">{message.role === "assistant" ? <span><Sparkles size={15} />知域助手</span> : <span>{user.display_name}</span>}</div>
            <div className="message-body">{message.role === "assistant" ? renderAnswer(message) : message.content}</div>
            {message.result && <><div className="message-citations"><div className="citation-heading"><BookOpen size={14} />引用来源</div>{message.result.citations.length ? message.result.citations.map((citation) => <button key={citation.chunk_id} className="citation-card" onClick={() => openCitation(citation, message.result!)}><span className="citation-index">[{citation.index}]</span><span><strong>{citation.title}</strong><small>{citation.filename}{citation.page_number ? ` · 第 ${citation.page_number} 页` : citation.paragraph_number ? ` · 段落 ${citation.paragraph_number}` : ""}</small><em>{citation.excerpt}</em></span></button>) : <p className="citation-empty">未检索到可引用的授权资料，建议先上传相关文档。</p>}</div><div className="answer-meta"><span><BookOpen size={14} />{message.result.citations.length} 条引用</span><span><Clock3 size={14} />{message.result.retrieval.latency_ms ?? "-"} ms</span><span><CheckCircle2 size={14} />权限已过滤</span>{message.result.retrieval.generation_mode === "extractive_degraded" && <span className="degraded"><AlertTriangle size={14} />抽取式降级</span>}<span>{message.result.retrieval.retrieval_mode === "hybrid" ? "混合检索" : "全文检索降级"}</span></div><div className="message-tools"><button className="icon-button" title="复制全文" onClick={() => copyText(message.content)}><Copy size={15} /></button><button className="icon-button" title="从此处创建分支" onClick={() => branchConversation(message)}><GitBranch size={15} /></button><button className={message.feedback === "up" ? "active" : ""} title="回答有帮助" onClick={() => setFeedback(message, "up")}><ThumbsUp size={15} /></button><button className={message.feedback === "down" ? "active" : ""} title="回答无帮助" onClick={() => setFeedbackTarget(message)}><ThumbsDown size={15} /></button></div><div className="follow-up-actions"><button className="button compact secondary" onClick={() => ask("请用一句话总结刚才的回答")}>总结刚才的回答</button><button className="button compact secondary" onClick={() => ask("请列出刚才回答中最需要注意的风险")}>继续追问风险</button></div></>}
          </article>)}{loading && <article className="message assistant loading-message"><div className="message-author"><span><Sparkles size={15} />知域助手</span></div><div className="thinking"><LoaderCircle className="spin" size={18} />正在检索授权资料并核对引用</div></article>}</div>}
      </div>
      <div className="composer-wrap"><div className="composer"><textarea ref={textareaRef} value={query} rows={1} placeholder={`询问 ${knowledgeBase.name}...`} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); ask(); } }} />{loading ? <button className="send-button stop" title="停止生成" onClick={() => abortRef.current?.abort()}><X size={19} /></button> : <button className="send-button" title="发送问题" onClick={() => ask()} disabled={!query.trim()}><ArrowUp size={19} /></button>}</div><p>回答可能存在偏差，关键决策请核对引用原文。</p></div>
    </section>
    <aside className="source-panel"><div className="source-panel-header"><div><p className="eyebrow">Evidence</p><h2>引用依据</h2></div>{activeResult && <span>{activeResult.citations.length}</span>}</div>
      {!activeResult ? <div className="source-empty"><BookOpen size={28} /><p>检索后的引用资料会显示在这里</p></div> : !activeResult.citations.length ? <div className="source-empty"><Search size={28} /><p>当前权限范围内没有匹配资料</p></div> : <div className="source-content"><div className="source-tabs">{activeResult.citations.map((citation) => <button key={citation.chunk_id} className={activeCitation?.chunk_id === citation.chunk_id ? "active" : ""} onClick={() => openCitation(citation, activeResult)} title={citation.title}>[{citation.index}]</button>)}</div>{activeCitation && <div className="source-detail"><span className="source-file-icon"><FileText size={21} /></span><h3>{activeCitation.title}</h3><div className="source-detail-meta"><span>{activeCitation.filename}</span>{activeCitation.page_number ? <span>第 {activeCitation.page_number} 页</span> : activeCitation.paragraph_number ? <span>段落 {activeCitation.paragraph_number}</span> : null}<span>融合分 {Math.round(activeCitation.score * 100)}%</span></div><blockquote>{chunk?.text ?? activeCitation.excerpt}</blockquote><p className="source-permission"><CheckCircle2 size={15} />已通过当前用户权限校验</p></div>}</div>}
    </aside>
      {historyOpen && <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setHistoryOpen(false)}><div className="modal history-dialog"><div className="modal-header"><div><p className="eyebrow">Conversations</p><h2>{knowledgeBase.name} · 会话历史</h2></div><button className="icon-button" title="关闭" onClick={() => setHistoryOpen(false)}><X size={19} /></button></div><div className="modal-body conversation-list">{!conversations.length ? <div className="table-state"><History size={24} />暂无会话</div> : <>{conversations.map((item) => <div key={item.id} className={item.id === conversationId ? "active" : ""}><button onClick={() => openConversation(item.id)}><strong>{item.favorite ? "★ " : ""}{item.title}</strong><small>{item.message_count} 条消息 · {new Date(item.updated_at).toLocaleString("zh-CN")}</small></button><button className="icon-button" title="收藏/取消收藏" onClick={() => toggleFavorite(item)}><Star size={15} fill={item.favorite ? "currentColor" : "none"} /></button><button className="icon-button" title="重命名" onClick={() => renameConversation(item)}><Pencil size={15} /></button><button className="icon-button danger" title="删除会话" onClick={() => removeConversation(item)}><Trash2 size={15} /></button></div>)}<Pagination page={conversationPage} pageSize={8} total={conversationTotal} onPageChange={setConversationPage} /></>}</div><div className="modal-footer"><button className="button primary" onClick={newConversation}><MessageSquarePlus size={16} />新会话</button></div></div></div>}
      {feedbackTarget && <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setFeedbackTarget(null)}><form className="modal" onSubmit={(event) => { event.preventDefault(); void setFeedback(feedbackTarget, "down", feedbackReason, feedbackComment); }}><div className="modal-header"><div><p className="eyebrow">Answer feedback</p><h2>告诉我们哪里需要改进</h2></div><button type="button" className="icon-button" title="关闭" onClick={() => setFeedbackTarget(null)}><X size={19} /></button></div><div className="modal-body"><label className="field"><span>问题类型</span><select value={feedbackReason} onChange={(event) => setFeedbackReason(event.target.value as typeof feedbackReason)}><option value="hallucination">幻觉 / 编造</option><option value="incorrect">答案错误</option><option value="incomplete">资料不全</option><option value="irrelevant">答非所问</option></select></label><label className="field"><span>补充说明（可选）</span><textarea rows={4} value={feedbackComment} onChange={(event) => setFeedbackComment(event.target.value)} /></label></div><div className="modal-footer"><button type="button" className="button secondary" onClick={() => setFeedbackTarget(null)}>取消</button><button className="button primary">提交反馈</button></div></form></div>}
  </div>;
}

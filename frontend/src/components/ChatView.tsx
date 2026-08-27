import { Fragment, useEffect, useRef, useState } from "react";
import {
  AlertTriangle, ArrowUp, BookOpen, CheckCircle2, Clock3, Download, FileText,
  History, LoaderCircle, MessageSquarePlus, Search, Sparkles, ThumbsDown,
  ThumbsUp, Trash2, X,
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
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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
    try {
      const result = await api.chat(token, trimmed, knowledgeBase.id, conversationId || undefined);
      setConversationId(result.conversation_id);
      setMessages((current) => [...current, { id: result.message_id, role: "assistant", content: result.answer, result, feedback: null }]);
      setActiveResult(result);
      setActiveCitation(result.citations[0] ?? null);
      setChunk(null);
      await loadConversations(conversationPage);
    } catch (error) { notify(error instanceof Error ? error.message : "问答请求失败", "error"); }
    finally { setLoading(false); textareaRef.current?.focus(); }
  }

  async function setFeedback(message: ChatMessage, rating: "up" | "down") {
    if (!message.result) return;
    try {
      await api.feedback(token, message.result.conversation_id, message.id, rating);
      setMessages((current) => current.map((item) => item.id === message.id ? { ...item, feedback: rating } : item));
      notify("反馈已记录", "success");
    } catch (error) { notify(error instanceof Error ? error.message : "反馈保存失败", "error"); }
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
    return message.content.split("\n").filter(Boolean).map((paragraph, paragraphIndex) => <p key={paragraphIndex}>
      {paragraph.split(/(\[\d+])/g).map((part, index) => {
        const match = part.match(/^\[(\d+)]$/);
        const citation = match && message.result?.citations.find((item) => item.index === Number(match[1]));
        return citation ? <button key={index} className="inline-citation" onClick={() => openCitation(citation, message.result!)}>{part}</button> : <Fragment key={index}>{part}</Fragment>;
      })}
    </p>);
  }

  if (!knowledgeBase) return <div className="empty-workspace"><BookOpen size={30} /><h2>没有可访问的知识库</h2><p>请让管理员在“知识库管理”中授予查看权限。</p></div>;
  if (knowledgeBase.permission === "upload") return <div className="empty-workspace"><BookOpen size={30} /><h2>当前知识库仅允许上传</h2><p>你可以在文档库提交资料，但不能查看文档或发起检索。</p></div>;

  return <div className="chat-layout">
    <section className="chat-main">
      <div className="chat-contextbar"><span><BookOpen size={15} />{knowledgeBase.name}</span><div><button className="button compact secondary" onClick={() => setHistoryOpen(true)}><History size={15} />会话历史</button><button className="icon-button" title="新会话" onClick={newConversation}><MessageSquarePlus size={17} /></button>{conversationId && <button className="icon-button" title="导出当前会话" onClick={() => api.exportConversation(token, conversationId).catch((error) => notify(error.message, "error"))}><Download size={17} /></button>}</div></div>
      <div className="chat-scroll">
        {!messages.length ? <div className="chat-empty"><span className="assistant-emblem"><Sparkles size={25} /></span><h1>{user.display_name}，需要查找什么？</h1><p>仅检索“{knowledgeBase.name}”内你有权访问的资料，并附可核验引用。</p><div className="suggestion-list">{suggestions.map((suggestion) => <button key={suggestion} onClick={() => ask(suggestion)}><Search size={17} /><span>{suggestion}</span><ArrowUp size={16} /></button>)}</div></div> :
          <div className="message-list">{messages.map((message) => <article key={message.id} className={`message ${message.role}`}>
            <div className="message-author">{message.role === "assistant" ? <span><Sparkles size={15} />知域助手</span> : <span>{user.display_name}</span>}</div>
            <div className="message-body">{message.role === "assistant" ? renderAnswer(message) : message.content}</div>
            {message.result && <><div className="message-citations"><div className="citation-heading"><BookOpen size={14} />引用来源</div>{message.result.citations.length ? message.result.citations.map((citation) => <button key={citation.chunk_id} className="citation-card" onClick={() => openCitation(citation, message.result!)}><span className="citation-index">[{citation.index}]</span><span><strong>{citation.title}</strong><small>{citation.filename}{citation.page_number ? ` · 第 ${citation.page_number} 页` : citation.paragraph_number ? ` · 段落 ${citation.paragraph_number}` : ""}</small><em>{citation.excerpt}</em></span></button>) : <p className="citation-empty">未检索到可引用的授权资料</p>}</div><div className="answer-meta"><span><BookOpen size={14} />{message.result.citations.length} 条引用</span><span><Clock3 size={14} />{message.result.retrieval.latency_ms ?? "-"} ms</span><span><CheckCircle2 size={14} />权限已过滤</span>{message.result.retrieval.generation_mode === "extractive_degraded" && <span className="degraded"><AlertTriangle size={14} />抽取式降级</span>}<span>{message.result.retrieval.retrieval_mode === "hybrid" ? "混合检索" : "全文检索降级"}</span></div><div className="feedback-actions"><button className={message.feedback === "up" ? "active" : ""} title="回答有帮助" onClick={() => setFeedback(message, "up")}><ThumbsUp size={15} /></button><button className={message.feedback === "down" ? "active" : ""} title="回答无帮助" onClick={() => setFeedback(message, "down")}><ThumbsDown size={15} /></button></div></>}
          </article>)}{loading && <article className="message assistant loading-message"><div className="message-author"><span><Sparkles size={15} />知域助手</span></div><div className="thinking"><LoaderCircle className="spin" size={18} />正在检索授权资料并核对引用</div></article>}</div>}
      </div>
      <div className="composer-wrap"><div className="composer"><textarea ref={textareaRef} value={query} rows={1} placeholder={`询问 ${knowledgeBase.name}...`} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); ask(); } }} /><button className="send-button" title="发送问题" onClick={() => ask()} disabled={!query.trim() || loading}><ArrowUp size={19} /></button></div><p>回答可能存在偏差，关键决策请核对引用原文。</p></div>
    </section>
    <aside className="source-panel"><div className="source-panel-header"><div><p className="eyebrow">Evidence</p><h2>引用依据</h2></div>{activeResult && <span>{activeResult.citations.length}</span>}</div>
      {!activeResult ? <div className="source-empty"><BookOpen size={28} /><p>检索后的引用资料会显示在这里</p></div> : !activeResult.citations.length ? <div className="source-empty"><Search size={28} /><p>当前权限范围内没有匹配资料</p></div> : <div className="source-content"><div className="source-tabs">{activeResult.citations.map((citation) => <button key={citation.chunk_id} className={activeCitation?.chunk_id === citation.chunk_id ? "active" : ""} onClick={() => openCitation(citation, activeResult)} title={citation.title}>[{citation.index}]</button>)}</div>{activeCitation && <div className="source-detail"><span className="source-file-icon"><FileText size={21} /></span><h3>{activeCitation.title}</h3><div className="source-detail-meta"><span>{activeCitation.filename}</span>{activeCitation.page_number ? <span>第 {activeCitation.page_number} 页</span> : activeCitation.paragraph_number ? <span>段落 {activeCitation.paragraph_number}</span> : null}<span>融合分 {Math.round(activeCitation.score * 100)}%</span></div><blockquote>{chunk?.text ?? activeCitation.excerpt}</blockquote><p className="source-permission"><CheckCircle2 size={15} />已通过当前用户权限校验</p></div>}</div>}
    </aside>
    {historyOpen && <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setHistoryOpen(false)}><div className="modal history-dialog"><div className="modal-header"><div><p className="eyebrow">Conversations</p><h2>{knowledgeBase.name} · 会话历史</h2></div><button className="icon-button" title="关闭" onClick={() => setHistoryOpen(false)}><X size={19} /></button></div><div className="modal-body conversation-list">{!conversations.length ? <div className="table-state"><History size={24} />暂无会话</div> : <>{conversations.map((item) => <div key={item.id} className={item.id === conversationId ? "active" : ""}><button onClick={() => openConversation(item.id)}><strong>{item.title}</strong><small>{item.message_count} 条消息 · {new Date(item.updated_at).toLocaleString("zh-CN")}</small></button><button className="icon-button danger" title="删除会话" onClick={() => removeConversation(item)}><Trash2 size={15} /></button></div>)}<Pagination page={conversationPage} pageSize={8} total={conversationTotal} onPageChange={setConversationPage} /></>}</div><div className="modal-footer"><button className="button primary" onClick={newConversation}><MessageSquarePlus size={16} />新会话</button></div></div></div>}
  </div>;
}

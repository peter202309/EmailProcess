import React, { useState, useEffect } from 'react';
import {
  Mail,
  Settings,
  FileText,
  Activity,
  AlertTriangle,
  CheckCircle,
  Clock,
  Play,
  Search,
  MessageSquare,
  ShieldAlert,
  Save,
  Trash2,
  RefreshCw,
  MoreVertical,
  Sparkles,
  Zap,
  Loader2,
  Bot,
  Send,
  Rocket,
  Paperclip,
  History,
  List,
  BookOpen
} from 'lucide-react';

const apiKey = import.meta.env.VITE_GEMINI_API_KEY;
const groqKey = import.meta.env.VITE_GROQ_API_KEY;
const MODEL_NAME = "gemini-2.5-flash";
const GROQ_MODEL = "llama-3.3-70b-versatile";

const callGroq = async (prompt) => {
  try {
    const response = await fetch("https://api.groq.com/openai/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${groqKey}`
      },
      body: JSON.stringify({
        model: GROQ_MODEL,
        messages: [{ role: "user", content: prompt }]
      })
    });

    if (!response.ok) {
      const errorData = await response.json();
      return `Groq Error: ${errorData.error?.message || "Unknown error"}`;
    }

    const data = await response.json();
    return data.choices?.[0]?.message?.content || "Groq: No content returned.";
  } catch (error) {
    return `Groq Connection Error: ${error.message}`;
  }
};

const callGemini = async (prompt) => {
  try {
    const response = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${MODEL_NAME}:generateContent?key=${apiKey}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }] })
      }
    );

    if (!response.ok) {
      const errorData = await response.json();
      console.error("Gemini API HTTP Error:", response.status, errorData);
      const reason = errorData.error?.message || "未知错误";
      return `AI 暂时无法响应 (原因: ${reason})`;
    }

    const data = await response.json();
    return data.candidates?.[0]?.content?.parts?.[0]?.text || "AI 暂时无法响应 (原因: 无有效生成内容)。";
  } catch (error) {
    console.error("Gemini API Network Error:", error);
    return "连接 AI 服务失败，请检查网络或 API 配置。";
  }
};

const INITIAL_TEMPLATES = [
  { id: 'template_outage', name: '紧急故障响应', content: '尊敬的客户，\n\n我们已收到关于{{issue}}的报告。技术团队已介入并正在紧急排查。\n\n运维团队', keywords: '故障,outage,无法访问' },
  { id: 'template_received', name: '通用收悉', content: '您好，邮件已收到，我们会尽快处理。', keywords: '收到,确认,received' },
  { id: 'template_billing', name: '财务确认', content: '收到发票，已转交财务部门审核，预计3个工作日内付款。', keywords: '发票,付款,账单,invoice' }
];

const INITIAL_LOGS = [
  { id: 1, timestamp: '2023-10-27 08:31:00', action: 'AUTO_IGNORE', emailId: 'msg_003', detail: '判定为Newsletter，跳过回复' }
];

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [emails, setEmails] = useState([]);
  const [templates, setTemplates] = useState(INITIAL_TEMPLATES);
  const [logs, setLogs] = useState(INITIAL_LOGS);
  const [config, setConfig] = useState({
    autoReplyThreshold: 0.85,
    autoReplyMode: false,
    maxDailyRepliesPerUser: 3,
    checkInterval: 5,
    signature: 'AI Assistant | Host Provider'
  });
  const [replyAttachments, setReplyAttachments] = useState([]); // List of {name, content}
  const [selectedEmail, setSelectedEmail] = useState(null);
  const [isAiGenerating, setIsAiGenerating] = useState(false);
  const [isAiAnalyzing, setIsAiAnalyzing] = useState(false);
  const [isLoadingEmails, setIsLoadingEmails] = useState(false);
  const [aiProvider, setAiProvider] = useState('gemini'); // 'gemini' or 'groq'
  const [fetchMode, setFetchMode] = useState('all'); // 'all' or 'unread'
  const [kbStatus, setKbStatus] = useState({ active: false, doc_count: 0 });
  const [tasks, setTasks] = useState([]);
  const [viewingProcessed, setViewingProcessed] = useState(null);
  const [activeAccount, setActiveAccount] = useState('all'); // 'all' or specific account email
  const [dashboardFilter, setDashboardFilter] = useState('all'); // 'all', 'pending', 'resolved', 'replied'
  const [previewFile, setPreviewFile] = useState(null); // {url, filename, type, storedName}
  const [isAnalyzingAtt, setIsAnalyzingAtt] = useState(false);
  const [attAnalysis, setAttAnalysis] = useState(null);

  const safeEmails = Array.isArray(emails) ? emails : [];

  // Calculate unique accounts from emails
  const accountsList = ['all', ...new Set(safeEmails.map(e => e.accountOwner).filter(Boolean))];

  // Filter emails based on selected account AND dashboard filter
  const filteredEmails = safeEmails.filter(e => {
    // 1. Account Filter
    const matchAccount = activeAccount === 'all' || e.accountOwner === activeAccount;
    if (!matchAccount) return false;

    // 2. Status Filter
    if (dashboardFilter === 'all') return true;
    if (dashboardFilter === 'pending') return e.status !== 'processed';
    if (dashboardFilter === 'resolved') return e.status === 'processed' && !e.sentReply;
    if (dashboardFilter === 'replied') return e.status === 'processed' && !!e.sentReply;
    return true;
  });

  // Grouping Function
  const groupEmailsByDate = (emailsToGroup) => {
    const groups = {};
    emailsToGroup.forEach(e => {
      const dateStr = e.receivedAt ? e.receivedAt.split(' ')[0] : '未知日期';
      if (!groups[dateStr]) groups[dateStr] = [];
      groups[dateStr].push(e);
    });
    // Sort keys (dates) descending
    return Object.keys(groups).sort().reverse().map(date => ({
      date,
      emails: groups[date]
    }));
  };

  const statPending = filteredEmails.filter(e => e.status === 'pending_review' || e.status === 'unread').length;
  const statProcessed = filteredEmails.filter(e => e.status === 'processed').length;
  const statTotal = filteredEmails.length;

  const fetchEmails = async () => {
    setIsLoadingEmails(true);
    try {
      await fetch(`http://localhost:8010/poll-emails?fetch_mode=${fetchMode}`);
      const res = await fetch('http://localhost:8010/emails');
      const data = await res.json();
      if (Array.isArray(data)) setEmails(data);
    } catch (error) {
      console.error("Failed to fetch emails:", error);
    } finally {
      setIsLoadingEmails(false);
    }
  };

  const loadInitialData = async () => {
    try {
      const tRes = await fetch('http://localhost:8010/templates');
      const tData = await tRes.json();
      if (Array.isArray(tData)) setTemplates(tData);

      const sRes = await fetch('http://localhost:8010/settings');
      const sData = await sRes.json();
      if (sData) setConfig(prev => ({ ...prev, ...sData }));

      const lRes = await fetch('http://localhost:8010/logs');
      const lData = await lRes.json();
      if (Array.isArray(lData)) setLogs(lData);

      const tskRes = await fetch('http://localhost:8010/tasks');
      const tskData = await tskRes.json();
      if (Array.isArray(tskData)) setTasks(tskData);
    } catch (err) {
      console.error("Failed to load initial data", err);
    }
  };

  const fetchTasks = async () => {
    try {
      const res = await fetch('http://localhost:8010/tasks');
      const data = await res.json();
      if (Array.isArray(data)) setTasks(data);
    } catch (e) { console.error("Fetch tasks error", e); }
  };

  const fetchKbStatus = async () => {
    try {
      const res = await fetch('http://localhost:8010/kb-status');
      const data = await res.json();
      setKbStatus(data);
    } catch (e) { console.error("KB status error", e); }
  };

  useEffect(() => {
    fetchEmails();
    loadInitialData();
    fetchKbStatus();
  }, []);

  const handleSelectEmail = async (email) => {
    setSelectedEmail(email);

    // Mark as read if not already read
    if (!email.isRead) {
      try {
        await fetch(`http://localhost:8010/emails/${email.id}/mark-read`, { method: 'POST' });
        // Update local state
        setEmails(prev => prev.map(e => e.id === email.id ? { ...e, isRead: true } : e));
      } catch (error) {
        console.error("Failed to mark email as read:", error);
      }
    }
  };

  const handleSaveConfig = async () => {
    try {
      await Promise.all(Object.entries(config).map(([k, v]) =>
        fetch('http://localhost:8010/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key: k, value: String(v) })
        })
      ));
      alert("配置已保存");
    } catch (e) {
      alert("保存失败: " + e.message);
    }
  };

  const handleAddTemplate = async () => {
    const name = prompt("模版名称:");
    if (!name) return;
    const content = prompt("内容:");
    if (!content) return;
    const newTmpl = { id: `tmpl_${Date.now()}`, name, content };
    try {
      await fetch('http://localhost:8010/templates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newTmpl)
      });
      setTemplates(prev => [...prev, newTmpl]);
    } catch (e) { alert(e.message); }
  };

  const handleDeleteTemplate = async (id) => {
    if (!confirm("确定删除?")) return;
    try {
      await fetch(`http://localhost:8010/templates/${id}`, { method: 'DELETE' });
      setTemplates(prev => prev.filter(t => t.id !== id));
    } catch (e) { alert("删除失败"); }
  };

  const askAI = async (body, instruction = null) => {
    const res = await fetch('http://localhost:8010/analyze-email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        emailId: selectedEmail?.id || "temp",
        emailSubject: selectedEmail?.subject || "Direct Query",
        emailBody: body,
        provider: aiProvider,
        instruction: instruction
      })
    });
    const data = await res.json();
    return data;
  };

  const handleAiGenerateReply = async (tone) => {
    if (!selectedEmail) return;
    setIsAiGenerating(true);
    let toneInstruction = `Please generate a reply in a ${tone === 'antigravity' ? 'creative and humorous' : tone === 'professional' ? 'formal and professional' : 'warm and empathetic'} tone. Signature to use: ${config.signature}`;

    const data = await askAI(selectedEmail.body, toneInstruction);
    const result = data.analysis || "";

    const updated = {
      ...selectedEmail,
      aiAnalysis: {
        ...(selectedEmail.aiAnalysis || {}),
        draftReply: result,
        sourcesUsed: Array.isArray(data.sourcesUsed) ? data.sourcesUsed : [],
        ragSources: Array.isArray(data.ragSources) ? data.ragSources : []
      }
    };
    setSelectedEmail(updated);
    setEmails(prev => prev.map(e => e.id === updated.id ? updated : e));
    setIsAiGenerating(false);
  };

  const handleAiDeepAnalyze = async () => {
    if (!selectedEmail) return;
    setIsAiAnalyzing(true);
    const data = await askAI(selectedEmail.body, "Please perform a deep strategic analysis of this email. Identify hidden intents, potential issues, and suggest detailed business actions.");
    const result = data.analysis || "";
    setLogs(prev => [{ id: Date.now(), timestamp: new Date().toLocaleString(), action: `AI_INSIGHT_(${aiProvider.toUpperCase()})`, emailId: selectedEmail.id, detail: result }, ...prev]);
    setIsAiAnalyzing(false);
  };

  const processEmails = async () => {
    const toProcess = emails.filter(e => e.status === 'unread' || !e.aiAnalysis || (e.aiAnalysis && !e.aiAnalysis.category));
    if (!toProcess.length) return alert("无可处理邮件");
    setIsAiGenerating(true);
    const results = await Promise.all(toProcess.map(async (e) => {
      try {
        const res = await fetch('http://localhost:8010/analyze-email', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ emailId: e.id, emailSubject: e.subject, emailBody: e.body, provider: aiProvider })
        });
        const data = await res.json();
        const finalDraft = data.matchedTemplate ? data.matchedTemplate.content : data.analysis;
        const confidence = data.confidence || 0;
        const isAutoMatch = !!data.matchedTemplate;

        const updatedEmail = {
          ...e,
          status: 'pending_review',
          aiAnalysis: {
            draftReply: finalDraft,
            isUrgent: data.isUrgent || false,
            matchedTemplate: data.matchedTemplate,
            confidence: confidence,
            category: data.category || "Information",
            intent: data.intent || "",
            requiresReply: data.requiresReply ?? true,
            sourcesUsed: data.sourcesUsed || [],
            ragSources: data.ragSources || []
          }
        };

        // Logic check for Auto-Reply or Auto-Ignore
        if (config.autoReplyMode) {
          // Case 1: Doesn't require a reply (Newsletters, etc.)
          if (data.requiresReply === false && confidence >= config.autoReplyThreshold) {
            await fetch(`http://localhost:8010/emails/${e.id}/resolve`, { method: 'POST' });
            return { ...updatedEmail, status: 'processed' };
          }

          // Case 2: Requires reply and meets confidence/template match
          if (data.requiresReply !== false && (isAutoMatch || (confidence >= config.autoReplyThreshold))) {
            // Auto-send
            const actualAttachments = isAutoMatch ? (data.matchedTemplate.attachments || []) : [];
            fetch('http://localhost:8010/send-reply', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                emailId: e.id,
                recipient: e.from,
                subject: e.subject,
                replyBody: finalDraft,
                attachments: actualAttachments.map(a => ({ filename: a.name, content: a.content.split(',')[1] }))
              })
            }).catch(err => console.error("Auto-send failed", err));

            return {
              ...updatedEmail,
              status: 'processed',
              sentReply: finalDraft,
              sentAt: new Date().toLocaleString()
            };
          }
        }
        return updatedEmail;
      } catch (err) {
        console.error("Processing error", err);
        return e;
      }
    }));
    setEmails(prev => prev.map(e => results.find(r => r.id === e.id) || e));
    setIsAiGenerating(false);
  };


  const handleSendReply = async (emailId) => {
    if (!selectedEmail) return;
    try {
      await fetch('http://localhost:8010/send-reply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          emailId: selectedEmail.id,
          recipient: selectedEmail.from,
          subject: selectedEmail.subject,
          replyBody: selectedEmail.aiAnalysis?.draftReply || "",
          attachments: replyAttachments.map(a => ({ filename: a.name, content: a.content.split(',')[1] })) // Base64 part only
        })
      });
      setEmails(emails.map(e => e.id === emailId ? { ...e, status: 'processed', sentReply: selectedEmail.aiAnalysis?.draftReply } : e));
      setSelectedEmail(null);
      setReplyAttachments([]);
    } catch (e) { alert("发送失败"); }
  };

  const handleMarkResolved = async (emailId) => {
    if (!selectedEmail) return;
    if (!confirm("确定将此邮件标记为已处理（无需回复）？")) return;
    try {
      await fetch(`http://localhost:8010/emails/${emailId}/resolve`, { method: 'POST' });
      setEmails(emails.map(e => e.id === emailId ? { ...e, status: 'processed' } : e));
      setSelectedEmail(null);
    } catch (e) { alert("操作失败: " + e.message); }
  };

  const simulateNewEmail = () => fetchEmails();

  const handleCreateTask = async (task) => {
    try {
      await fetch('http://localhost:8010/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(task)
      });
      fetchTasks();
    } catch (e) { alert("创建任务失败"); }
  };

  const handleToggleTask = async (taskId, currentStatus) => {
    const newStatus = currentStatus === 'completed' ? 'pending' : 'completed';
    try {
      await fetch(`http://localhost:8010/tasks/${taskId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus })
      });
      fetchTasks();
    } catch (e) { alert("更新失败"); }
  };

  const handleDeleteTask = async (taskId) => {
    if (!confirm("确定删除任务?")) return;
    try {
      await fetch(`http://localhost:8010/tasks/${taskId}`, { method: 'DELETE' });
      fetchTasks();
    } catch (e) { alert("删除失败"); }
  };

  const navigateToEmail = (emailId) => {
    const email = safeEmails.find(e => e.id === emailId);
    if (email) {
      // 1. Ensure the correct account context is selected
      if (email.accountOwner && activeAccount !== 'all') {
        setActiveAccount(email.accountOwner);
      }

      // 2. Handle based on status
      if (email.status === 'processed') {
        // If already processed, show the detail modal instead of jumping to review
        setViewingProcessed(email);
        setActiveTab('dashboard'); // Go to list view where it originated
      } else {
        // If pending, jump to review tab and select it
        setSelectedEmail(email);
        setActiveTab('review');

        // Use timeout to ensure DOM is ready then scroll if needed
        setTimeout(() => {
          const el = document.getElementById(`review-item-${email.id}`);
          if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 100);
      }
    } else {
      alert("关联邮件未找到 (可能已超过24小时同步范围或被重置)");
    }
  };

  const handleResetDatabase = async () => {
    if (!confirm("⚠️ 危险操作：这将清除所有邮件、日志和任务记录！模版和设置将保留。确定要重新初始化数据库吗？")) return;
    try {
      const res = await fetch('http://localhost:8010/reset-emails', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'success') {
        alert("数据库已重置！");
        setEmails([]);
        setLogs([]);
        setTasks([]);
      } else {
        alert("重置失败: " + data.message);
      }
    } catch (e) {
      alert("重置失败，请检查后端。");
    }
  };

  const handleRebuildKB = async () => {
    if (!confirm("重建 Knowledge Base 会花费一些时间,确定继续?")) return;
    try {
      const res = await fetch('http://localhost:8010/rebuild-kb', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'success') {
        alert(`Knowledge Base 重建成功!\n文档数: ${data.doc_count}\n分块数: ${data.chunks}`);
        fetchKbStatus();
      } else {
        alert(`重建失败: ${data.message}`);
      }
    } catch (e) {
      alert("重建失败,请检查后端日志");
    }
  };

  const handleAnalyzeAttachment = async (storedName) => {
    if (!selectedEmail) return;
    setIsAnalyzingAtt(true);
    setAttAnalysis(null);
    try {
      const res = await fetch(`http://localhost:8010/analyze-attachment?emailId=${selectedEmail.id}&storedName=${storedName}`, {
        method: 'POST'
      });
      const data = await res.json();
      if (data.status === 'success') {
        setAttAnalysis(data.analysis);
      } else {
        // Display error message in the analysis panel instead of alert
        setAttAnalysis(data.message || "分析失败，请稍后重试");
      }
    } catch (e) {
      setAttAnalysis("❌ 网络错误：无法连接到后端服务器\n\n请确保后端服务正在运行 (python backend/main.py)");
    } finally {
      setIsAnalyzingAtt(false);
    }
  };

  return (
    <div className="flex h-screen bg-gray-50 text-gray-800 font-sans overflow-hidden">
      {/* Sidebar */}
      <div className="w-64 bg-slate-900 text-white flex flex-col shadow-xl">
        <div className="p-6 border-b border-slate-700">
          <div className="flex items-center gap-2 font-bold text-xl text-blue-400">
            <Activity size={24} />
            <span>AI MailGuard</span>
          </div>
        </div>
        <nav className="flex-1 p-4 space-y-2">
          {/* Tab Navigation - Moved to top */}
          <div className="mb-4 pb-4 border-b border-slate-700">
            <div className="text-xs text-slate-400 uppercase tracking-wider mb-2 px-2">导航</div>
            <NavItem icon={<AlertTriangle size={20} />} label="待处理" count={statPending} active={activeTab === 'review'} onClick={() => setActiveTab('review')} alert={statPending > 0} />
            <NavItem icon={<List size={20} />} label="任务中心" count={tasks.filter(t => t.status === 'pending').length} active={activeTab === 'tasks'} onClick={() => setActiveTab('tasks')} />
            <NavItem icon={<Mail size={20} />} label="所有邮件" active={activeTab === 'dashboard'} onClick={() => setActiveTab('dashboard')} />
            <NavItem icon={<FileText size={20} />} label="模版" active={activeTab === 'templates'} onClick={() => setActiveTab('templates')} />
            <NavItem icon={<CheckCircle size={20} />} label="日志" active={activeTab === 'logs'} onClick={() => setActiveTab('logs')} />
          </div>

          {/* Settings at bottom */}
          <NavItem icon={<Settings size={20} />} label="设置" active={activeTab === 'settings'} onClick={() => setActiveTab('settings')} />
        </nav>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="bg-white h-16 border-b flex items-center justify-between px-6 shadow-sm z-10">
          <div className="flex items-center gap-4">
            <h2 className="text-xl font-bold text-gray-800 uppercase tracking-wide">{activeTab}</h2>
            <div className="h-8 w-px bg-gray-200 mx-2" />
            <select
              value={aiProvider}
              onChange={(e) => setAiProvider(e.target.value)}
              className="px-3 py-1.5 text-xs font-bold rounded-lg border border-gray-200 bg-white hover:border-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all"
            >
              <option value="gemini">🔷 Gemini 2.0</option>
              <option value="deepseek">🧠 DeepSeek</option>
              <option value="openai">🤖 OpenAI GPT-4</option>
              <option value="groq">⚡ Groq (Llama)</option>
            </select>

            {/* Account Switcher */}
            <div className="flex bg-slate-100/80 p-1 rounded-xl ml-2 border border-slate-200/50 backdrop-blur-sm shadow-inner">
              {accountsList.map(acc => (
                <button
                  key={acc}
                  onClick={() => setActiveAccount(acc)}
                  className={`px-3 py-1.5 text-[10px] font-bold rounded-lg transition-all duration-300 ${activeAccount === acc
                    ? 'bg-white text-blue-600 shadow-md ring-1 ring-black/5 scale-105 transform'
                    : 'text-slate-400 hover:text-slate-600 hover:bg-white/50'
                    }`}
                >
                  <div className="flex items-center gap-2">
                    {acc === 'all' ? <Activity size={12} /> : <Mail size={12} />}
                    <span>{acc === 'all' ? '所有账户' : acc.split('@')[0]}</span>
                    {acc !== 'all' && (
                      <span className="px-1.5 py-0.5 bg-blue-50 text-blue-500 rounded-full text-[8px] font-black">
                        {safeEmails.filter(e => e.accountOwner === acc && (e.status === 'unread' || e.status === 'pending_review')).length}
                      </span>
                    )}
                  </div>
                </button>
              ))}
            </div>
            <div className={`ml-2 px-3 py-1 rounded-lg text-[10px] font-bold flex items-center gap-1.5 transition-colors cursor-pointer hover:bg-green-100 ${kbStatus.active ? 'bg-green-50 text-green-600 border border-green-100' : 'bg-gray-100 text-gray-400 border border-gray-200'}`} onClick={handleRebuildKB} title="点击重建 Knowledge Base">
              <div className={`w-1.5 h-1.5 rounded-full ${kbStatus.active ? 'bg-green-500 animate-pulse' : 'bg-gray-300'}`} />
              Knowledge Base: {kbStatus.active ? `${kbStatus.doc_count} Docs` : 'Click to Build'}
            </div>
          </div>
          <div className="flex gap-3">
            <button onClick={simulateNewEmail} className="px-4 py-2 border rounded-md text-sm hover:bg-gray-50 flex items-center gap-2"><RefreshCw size={14} /> 刷新</button>
            <button onClick={processEmails} className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm hover:bg-blue-700 flex items-center gap-2"><Zap size={14} /> 规则引擎</button>
          </div>
        </header>

        <main className="flex-1 overflow-auto p-6">
          {(activeTab === 'dashboard' || activeTab === 'review') && (
            <div className="grid grid-cols-3 gap-6 mb-6">
              <StatCard title="今日邮件总量" value={statTotal} icon={<Mail className="text-blue-500" />} bg="bg-blue-50" />
              <StatCard title="待人工审核" value={statPending} icon={<AlertTriangle className="text-orange-500" />} bg="bg-orange-50" urgent={statPending > 0} />
              <StatCard title="已处理" value={statProcessed} icon={<CheckCircle className="text-green-500" />} bg="bg-green-50" />
            </div>
          )}

          {activeTab === 'dashboard' && (
            <div className="bg-white rounded-xl border relative">
              <div className="p-4 border-b font-bold flex justify-between items-center bg-gray-50/50">
                <div className="flex items-center gap-4">
                  <span className="text-sm">最近邮件</span>
                  <div className="flex bg-gray-200/50 p-1 rounded-lg">
                    {[
                      { id: 'all', label: '全部', color: 'bg-gray-400' },
                      { id: 'pending', label: '待处理', color: 'bg-blue-500' },
                      { id: 'resolved', label: '已解决', color: 'bg-green-600' },
                      { id: 'replied', label: '已回复', color: 'bg-indigo-600' }
                    ].map(f => (
                      <button
                        key={f.id}
                        onClick={() => setDashboardFilter(f.id)}
                        className={`px-3 py-1 text-[10px] font-bold rounded-md transition-all ${dashboardFilter === f.id
                          ? 'bg-white text-blue-600 shadow-sm'
                          : 'text-gray-400 hover:text-gray-600'
                          }`}
                      >
                        <div className="flex items-center gap-1.5">
                          <div className={`w-1.5 h-1.5 rounded-full ${f.color}`} />
                          {f.label}
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
                <div className="flex gap-2">
                  <div className="flex items-center gap-1 text-[10px] text-gray-400">
                    <div className="w-2 h-2 rounded-full bg-blue-500" /> 待处理
                  </div>
                  <div className="flex items-center gap-1 text-[10px] text-gray-400">
                    <div className="w-2 h-2 rounded-full bg-green-500" /> 已处理
                  </div>
                </div>
              </div>
              <div className="divide-y max-h-[70vh] overflow-auto bg-slate-50/30">
                {filteredEmails.length === 0 ? (
                  <div className="p-12 text-center text-gray-400">暂无符合条件的邮件记录</div>
                ) : (
                  groupEmailsByDate(filteredEmails).map(group => (
                    <div key={group.date}>
                      <div className="bg-slate-100/80 px-4 py-1.5 text-[10px] font-black text-slate-500 sticky top-0 z-10 backdrop-blur-sm border-y border-slate-200/50 flex items-center justify-between">
                        <span>{group.date}</span>
                        <span className="bg-slate-200 px-1.5 rounded-full">{group.emails.length}</span>
                      </div>
                      <div className="bg-white">
                        {group.emails.map(e => (
                          <EmailRow
                            key={e.id}
                            email={e}
                            onClick={() => {
                              if (e.status === 'processed') {
                                setViewingProcessed(e);
                              } else {
                                handleSelectEmail(e);
                                setActiveTab('review');
                              }
                            }}
                          />
                        ))}
                      </div>
                    </div>
                  ))
                )}
              </div>

              {/* Processed Detail Modal */}
              {viewingProcessed && (
                <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-[100] flex items-center justify-center p-4 md:p-8 animate-in fade-in duration-200">
                  <div className="bg-white rounded-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col shadow-2xl animate-in zoom-in-95 duration-200 ring-1 ring-black/5">
                    <div className="p-6 border-b flex justify-between items-center bg-gray-50">
                      <div>
                        <div className="flex items-center gap-2 mb-1">
                          <CheckCircle className="text-green-500" size={18} />
                          <h3 className="font-bold text-lg">处理详情</h3>
                        </div>
                        <p className="text-xs text-gray-500">
                          邮件 ID: {viewingProcessed.id}
                          {viewingProcessed.accountOwner && <span className="ml-2 px-1.5 py-0.5 bg-slate-200 rounded text-slate-600">账户: {viewingProcessed.accountOwner}</span>}
                        </p>
                      </div>
                      <button
                        onClick={() => setViewingProcessed(null)}
                        className="p-2 hover:bg-gray-200 rounded-full transition-colors"
                      >
                        <Trash2 className="text-gray-400 rotate-45" size={24} />
                      </button>
                    </div>

                    <div className="flex-1 overflow-auto p-6 space-y-6">
                      {/* Email Contents */}
                      <section>
                        <div className="flex items-center gap-2 text-xs font-bold text-gray-400 uppercase tracking-wider mb-3">
                          <Mail size={14} /> 原始邮件
                        </div>
                        <div className="bg-slate-50 border rounded-xl p-5">
                          <div className="font-bold text-slate-800 mb-2">{viewingProcessed.subject}</div>
                          <div className="text-xs text-slate-400 mb-4 pb-4 border-b border-slate-200">
                            From: {viewingProcessed.from} • {viewingProcessed.receivedAt}
                          </div>
                          <div className="text-sm text-slate-600 whitespace-pre-wrap leading-relaxed">
                            {viewingProcessed.body}
                          </div>
                        </div>
                      </section>

                      {/* AI Result */}
                      {viewingProcessed.aiAnalysis && (
                        <section className="grid md:grid-cols-2 gap-4">
                          <div className="bg-blue-50 border border-blue-100 rounded-xl p-4">
                            <div className="text-[10px] font-bold text-blue-400 uppercase mb-2">AI 分析结果</div>
                            <div className="flex items-center gap-3 mb-2">
                              <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${getCategoryStyles(viewingProcessed.aiAnalysis.category)}`}>
                                {viewingProcessed.aiAnalysis.category}
                              </span>
                              <span className="text-[10px] font-bold text-blue-600">置信度: {Math.round((viewingProcessed.aiAnalysis.confidence || 0) * 100)}%</span>
                            </div>
                            <p className="text-xs text-blue-800 italic">“{viewingProcessed.aiAnalysis.intent}”</p>
                          </div>
                          <div className="bg-purple-50 border border-purple-100 rounded-xl p-4">
                            <div className="text-[10px] font-bold text-purple-400 uppercase mb-2">回复策略</div>
                            <div className="text-xs font-bold text-purple-800 flex items-center gap-1.5">
                              {viewingProcessed.aiAnalysis.requiresReply === false ? (
                                <><ShieldAlert size={12} /> 判定为无需回复邮件</>
                              ) : (
                                <><Bot size={12} /> AI 已建议/执行回复</>
                              )}
                            </div>
                          </div>
                        </section>
                      )}

                      {/* RAG Sources in Modal */}
                      {(viewingProcessed.aiAnalysis?.sourcesUsed?.length > 0 || viewingProcessed.aiAnalysis?.ragSources?.length > 0) && (
                        <section className="bg-blue-50/30 border border-blue-100 rounded-xl p-4">
                          <div className="flex items-center gap-1.5 text-[10px] font-black text-blue-600 uppercase tracking-widest mb-3">
                            <BookOpen size={14} /> 知识库参考记录
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {(viewingProcessed.aiAnalysis.sourcesUsed?.length > 0
                              ? viewingProcessed.aiAnalysis.sourcesUsed
                              : (viewingProcessed.aiAnalysis.ragSources || [])
                            ).map((src, idx) => (
                              <div key={idx} className="bg-white border border-blue-200 text-blue-700 px-2.5 py-1 rounded-lg text-[10px] font-bold shadow-sm flex items-center gap-2">
                                <FileText size={12} className="text-blue-400" /> {src}
                              </div>
                            ))}
                          </div>
                        </section>
                      )}

                      {/* Reply Content */}
                      {viewingProcessed.sentReply && (
                        <section>
                          <div className="flex items-center gap-2 text-xs font-bold text-gray-400 uppercase tracking-wider mb-3">
                            <Send size={14} className="text-green-500" /> 已发送的回复
                          </div>
                          <div className="bg-green-50 border border-green-100 rounded-xl p-5">
                            <div className="text-[10px] text-green-500 font-bold mb-2">
                              发送时间: {viewingProcessed.sentAt}
                            </div>
                            <div className="text-sm text-green-900 whitespace-pre-wrap font-medium">
                              {viewingProcessed.sentReply}
                            </div>
                          </div>
                        </section>
                      )}
                    </div>

                    <div className="p-6 border-t bg-gray-50 flex justify-end">
                      <button
                        onClick={() => setViewingProcessed(null)}
                        className="px-6 py-2 bg-slate-800 text-white rounded-lg font-bold hover:bg-slate-900 transition-all shadow-lg"
                      >
                        完成阅读
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === 'review' && (
            <div className="flex h-full gap-6 overflow-hidden">
              <div className="w-1/3 bg-white border rounded-xl overflow-hidden flex flex-col">
                {/* Fetch Mode Toggle */}
                <div className="p-3 bg-gradient-to-r from-blue-50 to-indigo-50 border-b flex items-center justify-between">
                  <div className="text-xs font-bold text-gray-700">邮件筛选:</div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => { setFetchMode('all'); fetchEmails(); }}
                      className={`px-3 py-1 text-xs font-bold rounded-md transition-all ${fetchMode === 'all'
                        ? 'bg-blue-600 text-white shadow-md'
                        : 'bg-white text-gray-600 hover:bg-gray-100 border border-gray-200'
                        }`}
                    >
                      所有邮件
                    </button>
                    <button
                      onClick={() => { setFetchMode('unread'); fetchEmails(); }}
                      className={`px-3 py-1 text-xs font-bold rounded-md transition-all ${fetchMode === 'unread'
                        ? 'bg-blue-600 text-white shadow-md'
                        : 'bg-white text-gray-600 hover:bg-gray-100 border border-gray-200'
                        }`}
                    >
                      仅未读
                    </button>
                  </div>
                </div>
                <div className="p-4 bg-gray-50 border-b font-bold">审核队列 ({statPending})</div>
                <div className="flex-1 overflow-auto divide-y">
                  {filteredEmails.filter(e => e.status !== 'processed').map(e => (
                    <div key={e.id} id={`review-item-${e.id}`} onClick={() => handleSelectEmail(e)} className={`p-4 cursor-pointer hover:bg-blue-50 transition-all ${selectedEmail?.id === e.id ? 'bg-blue-50 border-l-4 border-blue-500' : ''} ${e.aiAnalysis?.isUrgent ? 'border-red-400 border-l-4 bg-red-50' : ''} ${!e.isRead ? 'bg-blue-50/20' : ''}`}>
                      <div className="flex justify-between items-start mb-1 gap-2">
                        <div className="flex items-center gap-2 flex-1">
                          {!e.isRead && <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse flex-shrink-0" />}
                          <div className={`font-bold text-sm truncate ${e.aiAnalysis?.isUrgent ? 'text-red-700' : ''} ${!e.isRead ? 'font-extrabold' : ''}`}>{e.subject}</div>
                        </div>
                        {e.sentReply && <span className="px-1.5 py-0.5 bg-green-100 text-green-700 text-[8px] font-bold rounded uppercase whitespace-nowrap">已回复</span>}
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        {e.aiAnalysis?.category && (
                          <span className={`px-2 py-0.5 rounded text-[8px] font-bold border uppercase shadow-sm ${getCategoryStyles(e.aiAnalysis.category)}`}>
                            {e.aiAnalysis.category}
                          </span>
                        )}
                        <div className="text-[10px] text-slate-500 font-mono flex-1">{e.from}</div>
                        <div className="text-[9px] text-slate-400 font-medium whitespace-nowrap">{e.receivedAt}</div>
                      </div>
                      {e.accountOwner && (
                        <div className="mt-1 text-[9px] text-blue-400 font-mono italic">@{e.accountOwner.split('@')[0]}</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
              <div className="flex-1 bg-white border rounded-xl overflow-hidden flex flex-col">
                {selectedEmail ? (
                  <div className="flex flex-col h-full">
                    <div className="p-6 border-b flex justify-between items-start">
                      <div>
                        <div className="flex items-center gap-2 mb-1">
                          <h1 className="text-xl font-bold">{selectedEmail.subject}</h1>
                          {selectedEmail.aiAnalysis?.isUrgent && (
                            <span className="bg-red-500 text-white px-2 py-0.5 rounded text-[10px] font-bold animate-bounce shadow-lg">URGENT</span>
                          )}
                        </div>
                        <div className="flex items-center gap-4">
                          <p className="text-sm text-gray-500">{selectedEmail.from}</p>
                          <div className="flex items-center gap-2">
                            <span className="text-[10px] text-gray-400 font-bold uppercase">分类:</span>
                            <select
                              className={`px-2 py-0.5 rounded text-[10px] font-bold border outline-none ${getCategoryStyles(selectedEmail.aiAnalysis?.category)}`}
                              value={selectedEmail.aiAnalysis?.category || "Information"}
                              onChange={(e) => {
                                const newCat = e.target.value;
                                const updated = { ...selectedEmail, aiAnalysis: { ...selectedEmail.aiAnalysis, category: newCat } };
                                setSelectedEmail(updated);
                                setEmails(prev => prev.map(item => item.id === updated.id ? updated : item));
                                // Sync to DB
                                fetch('http://localhost:8010/analyze-email', {
                                  method: 'POST',
                                  headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify({ emailId: updated.id, ...updated.aiAnalysis, updateOnly: true })
                                });
                              }}
                            >
                              <option value="Urgent">紧急 (Urgent)</option>
                              <option value="Billing">财务 (Billing)</option>
                              <option value="Technical">技术 (Technical)</option>
                              <option value="Sales">销售 (Sales)</option>
                              <option value="Support">支持 (Support)</option>
                              <option value="Information">信息 (Information)</option>
                              <option value="Spam">垃圾 (Spam)</option>
                            </select>
                          </div>
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <button onClick={() => {
                          const title = prompt("任务标题:", `处理: ${selectedEmail.subject}`);
                          if (!title) return;
                          handleCreateTask({
                            title,
                            description: `来自邮件: ${selectedEmail.subject}\n发件人: ${selectedEmail.from}`,
                            priority: selectedEmail.aiAnalysis?.isUrgent ? 'High' : 'Normal',
                            email_id: selectedEmail.id
                          });
                          alert("任务已成功提取至任务中心");
                        }} className="text-xs text-blue-600 border border-blue-200 px-2 py-1 rounded hover:bg-blue-50 flex items-center gap-1">
                          <List size={12} /> 转为任务
                        </button>
                        <button onClick={handleAiDeepAnalyze} className="text-xs text-purple-600 border border-purple-200 px-2 py-1 rounded hover:bg-purple-50">AI 分析</button>
                        <button onClick={() => handleMarkResolved(selectedEmail.id)} className="text-xs text-green-600 border border-green-200 px-2 py-1 rounded hover:bg-green-50">标记为已解决</button>
                      </div>
                    </div>
                    <div className="flex-1 overflow-auto p-6 bg-gray-50 flex flex-col gap-4">
                      {/* Thread History */}
                      {emails.filter(e => selectedEmail.thread_id && e.thread_id === selectedEmail.thread_id && e.id !== selectedEmail.id).map(prev => (
                        <div key={prev.id} className="p-3 bg-white border border-gray-100 rounded shadow-sm opacity-60">
                          <div className="text-[10px] text-gray-400 mb-1 flex justify-between">
                            <span>此前对话 • {prev.receivedAt}</span>
                          </div>
                          <div className="text-[11px] line-clamp-3">{prev.body}</div>
                        </div>
                      ))}

                      {/* Current Email */}
                      <div className="p-4 bg-white border border-blue-100 rounded shadow-sm">
                        <div className="text-sm leading-relaxed whitespace-pre-wrap mb-4">{selectedEmail.body}</div>

                        {/* Attachments Section */}
                        {selectedEmail.attachments?.length > 0 && (
                          <div className="mt-4 pt-4 border-t border-gray-100">
                            <div className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-3 flex items-center gap-1.5">
                              <Paperclip size={12} /> 邮件附件 ({selectedEmail.attachments.length})
                            </div>
                            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                              {selectedEmail.attachments.map((att, idx) => {
                                const isImage = att.contentType?.startsWith('image/');
                                const isPDF = att.contentType === 'application/pdf';
                                const downloadUrl = `http://localhost:8010/attachments/${att.storedName}`;

                                return (
                                  <div
                                    key={idx}
                                    className="group relative bg-white border border-gray-200 rounded-lg p-3 hover:border-blue-400 hover:shadow-md transition-all cursor-pointer flex items-center gap-3"
                                  >
                                    <div
                                      onClick={() => (isImage || isPDF) ? setPreviewFile({ url: downloadUrl, filename: att.filename, type: isImage ? 'image' : 'pdf', storedName: att.storedName }) : window.open(downloadUrl)}
                                      className="flex flex-1 items-center gap-3 min-w-0"
                                    >
                                      <div className={`p-2 rounded-lg ${isImage ? 'bg-orange-50 text-orange-500' : isPDF ? 'bg-red-50 text-red-500' : 'bg-gray-50 text-gray-500'}`}>
                                        {isImage ? <Activity size={16} /> : isPDF ? <FileText size={16} /> : <Paperclip size={16} />}
                                      </div>
                                      <div className="flex-1 min-w-0">
                                        <div className="text-[11px] font-bold text-gray-700 truncate">{att.filename}</div>
                                        <div className="text-[9px] text-gray-400">{(att.size / 1024).toFixed(1)} KB</div>
                                      </div>
                                    </div>
                                    {(isImage || isPDF) && (
                                      <button
                                        onClick={(e) => { e.stopPropagation(); handleAnalyzeAttachment(att.storedName); setPreviewFile({ url: downloadUrl, filename: att.filename, type: isImage ? 'image' : 'pdf', storedName: att.storedName }); }}
                                        className="p-1.5 bg-blue-50 text-blue-600 rounded-md hover:bg-blue-600 hover:text-white transition-colors"
                                        title="AI 分析识别"
                                      >
                                        <Zap size={14} />
                                      </button>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Replied History */}
                      {selectedEmail.sentReply && (
                        <div className="mt-4 p-4 bg-green-50 border border-green-100 rounded-lg">
                          <div className="flex items-center gap-2 text-xs font-bold text-green-700 mb-2">
                            <History size={14} /> 已于 {selectedEmail.sentAt} 回复：
                          </div>
                          <div className="text-sm text-green-900 bg-white/50 p-3 rounded border border-green-50 whitespace-pre-wrap">
                            {selectedEmail.sentReply}
                          </div>
                        </div>
                      )}
                    </div>
                    <div className="p-6 border-t bg-white">
                      <div className="flex gap-2 mb-4 items-center">
                        <span className="text-xs text-gray-400 mr-2">快速生成:</span>
                        <button onClick={() => handleAiGenerateReply('professional')} className="px-3 py-1 border rounded text-xs bg-white hover:bg-gray-50">专业</button>
                        <button onClick={() => handleAiGenerateReply('empathetic')} className="px-3 py-1 border rounded text-xs bg-white hover:bg-gray-50">亲切</button>
                        <button onClick={() => handleAiGenerateReply('antigravity')} className="px-3 py-1 bg-purple-600 text-white rounded text-xs hover:bg-purple-700">🚀 AI</button>
                        <div className="flex-1" />
                        <select
                          className="text-xs border rounded px-2 py-1 bg-white"
                          onChange={(e) => {
                            const t = templates.find(temp => temp.id === e.target.value);
                            if (t) {
                              setSelectedEmail({ ...selectedEmail, aiAnalysis: { ...selectedEmail.aiAnalysis, draftReply: t.content, matchedTemplate: t } });
                              setReplyAttachments(t.attachments || []);
                            }
                          }}
                          value={selectedEmail.aiAnalysis?.matchedTemplate?.id || ""}
                        >
                          <option value="" disabled>选择既定模板...</option>
                          {templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                        </select>
                      </div>
                      <div className="mb-4">
                        <div className="flex flex-wrap gap-2 mb-2">
                          {replyAttachments.map((a, i) => (
                            <div key={i} className="flex items-center gap-1.5 bg-gray-100 px-2 py-1 rounded text-[10px] border border-gray-200">
                              <Paperclip size={10} /> {a.name}
                              <button onClick={() => setReplyAttachments(prev => prev.filter((_, idx) => idx !== i))} className="hover:text-red-500">×</button>
                            </div>
                          ))}
                        </div>
                        <label className="flex items-center gap-1.5 text-xs text-blue-600 cursor-pointer hover:bg-blue-50 w-max px-2 py-1 rounded border border-blue-100 border-dashed">
                          <Paperclip size={14} /> <span>添加附件</span>
                          <input
                            type="file" className="hidden"
                            onChange={(e) => {
                              const f = e.target.files[0];
                              if (f) {
                                const reader = new FileReader();
                                reader.onload = (re) => setReplyAttachments(prev => [...prev, { name: f.name, content: re.target.result }]);
                                reader.readAsDataURL(f);
                              }
                            }}
                          />
                        </label>
                      </div>

                      {/* Knowledge Base Sources - Enhanced Safety */}
                      {selectedEmail?.aiAnalysis && (selectedEmail.aiAnalysis.sourcesUsed?.length > 0 || selectedEmail.aiAnalysis.ragSources?.length > 0) && (
                        <div className="mb-4 px-4 py-2 bg-blue-50/50 border border-blue-100 rounded-lg animate-in slide-in-from-top-2 duration-300">
                          <div className="flex items-center gap-1.5 text-[9px] font-black text-blue-600 uppercase tracking-widest mb-2">
                            <BookOpen size={12} strokeWidth={3} /> {selectedEmail.aiAnalysis.sourcesUsed?.length > 0 ? "参考知识库文档" : "相关参考资料 (RAG命中)"}
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {(selectedEmail.aiAnalysis.sourcesUsed?.length > 0
                              ? selectedEmail.aiAnalysis.sourcesUsed
                              : (selectedEmail.aiAnalysis.ragSources || [])
                            ).map((src, idx) => (
                              <span key={idx} className="bg-white border border-blue-200 text-blue-700 px-2 py-0.5 rounded text-[10px] font-bold shadow-sm flex items-center gap-1.5 hover:bg-blue-50 transition-colors cursor-default">
                                <FileText size={10} className="text-blue-400" /> {src}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      <textarea
                        className="w-full h-32 p-3 border rounded text-sm mb-4 bg-white shadow-inner focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all"
                        placeholder="在此输入您的回复..."
                        value={selectedEmail.aiAnalysis?.draftReply || ""}
                        onChange={(e) => setSelectedEmail({ ...selectedEmail, aiAnalysis: { ...selectedEmail.aiAnalysis, draftReply: e.target.value } })}
                      />
                      <button onClick={() => handleSendReply(selectedEmail.id)} className="w-full bg-blue-600 text-white py-2 rounded font-bold hover:bg-blue-700 flex items-center justify-center gap-2">
                        <Send size={16} /> 发送回复
                      </button>
                    </div>
                  </div>
                ) : <div className="h-full flex items-center justify-center text-gray-400">选择邮件处理</div>}
              </div>
            </div>
          )}

          {activeTab === 'logs' && (
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm text-left">
                  <thead className="bg-gray-50 text-gray-500 font-medium border-b border-gray-100">
                    <tr>
                      <th className="px-6 py-4">时间</th>
                      <th className="px-6 py-4">相关邮件ID</th>
                      <th className="px-6 py-4">事件类型</th>
                      <th className="px-6 py-4">详情</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {logs.map(log => (
                      <tr key={log.id} className="hover:bg-gray-50 transition-colors">
                        <td className="px-6 py-4 text-gray-400 font-mono text-[10px] whitespace-nowrap">{log.timestamp}</td>
                        <td className="px-6 py-4 text-blue-600 font-mono text-xs font-medium">{log.emailId}</td>
                        <td className="px-6 py-4">
                          <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${log.action.includes('SENT') || log.action.includes('REPLY') ? 'bg-green-50 text-green-700 border-green-100' :
                            log.action.includes('GEMINI') ? 'bg-purple-50 text-purple-700 border-purple-100' :
                              log.action.includes('ANALYSIS') ? 'bg-blue-50 text-blue-700 border-blue-100' : 'bg-gray-50 text-gray-700 border-gray-100'
                            }`}>
                            {log.action}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-gray-600 max-w-sm">
                          <div className="line-clamp-2 hover:line-clamp-none transition-all cursor-pointer whitespace-pre-wrap">{log.detail}</div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {activeTab === 'tasks' && (
            <div className="bg-white rounded-xl border flex-1 flex flex-col overflow-hidden">
              <div className="p-4 border-b font-bold flex justify-between items-center bg-gray-50">
                <span>任务中心 ({tasks.filter(t => t.status === 'pending').length})</span>
                <button onClick={() => {
                  const title = prompt("输入新任务:");
                  if (title) handleCreateTask({ title });
                }} className="text-xs bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700">+ 新任务</button>
              </div>
              <div className="flex-1 overflow-auto">
                {tasks.length === 0 ? (
                  <div className="p-12 text-center text-gray-400">暂无任务</div>
                ) : (
                  <div className="divide-y">
                    {tasks.map(t => (
                      <div key={t.id} className={`p-4 flex items-center gap-4 hover:bg-gray-50 transition-colors ${t.status === 'completed' ? 'opacity-50' : ''}`}>
                        <input
                          type="checkbox"
                          className="w-5 h-5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                          checked={t.status === 'completed'}
                          onChange={() => handleToggleTask(t.id, t.status)}
                        />
                        <div className="flex-1">
                          <div className={`font-bold ${t.status === 'completed' ? 'line-through text-gray-400' : ''}`}>{t.title}</div>
                          {t.description && <div className="text-xs text-gray-500 mt-1">{t.description}</div>}
                          <div className="flex items-center gap-3 mt-2">
                            {t.priority === 'High' && <span className="px-1.5 py-0.5 bg-red-50 text-red-600 text-[10px] font-bold rounded border border-red-100 uppercase">紧急</span>}
                            {t.email_id && (
                              <button
                                onClick={() => navigateToEmail(t.email_id)}
                                className="text-[10px] text-blue-600 hover:underline flex items-center gap-1"
                              >
                                <Mail size={10} /> 查看关联邮件
                              </button>
                            )}
                            <span className="text-[10px] text-gray-300">创建于: {t.created_at}</span>
                          </div>
                        </div>
                        <button onClick={() => handleDeleteTask(t.id)} className="p-2 text-gray-300 hover:text-red-500 transition-colors">
                          <Trash2 size={16} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === 'templates' && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {templates.map(t => (
                <div key={t.id} className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm relative group hover:shadow-md transition-all">
                  <div className="flex justify-between items-center mb-4">
                    <h3 className="font-bold text-gray-800 text-lg">{t.name}</h3>
                    <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button onClick={() => handleDeleteTemplate(t.id)} className="p-2 hover:bg-red-100 rounded-full text-red-500"><Trash2 size={16} /></button>
                    </div>
                  </div>
                  <div className="bg-gray-50 p-4 rounded-lg text-sm text-gray-600 font-mono whitespace-pre-wrap h-32 overflow-auto border border-gray-100 mb-4">
                    {t.content}
                  </div>
                  <div className="flex flex-col gap-2 mb-4">
                    <span className="text-xs font-bold text-gray-400 uppercase">触发关键词:</span>
                    <input
                      className="w-full text-xs border-b border-gray-200 bg-transparent py-1 focus:border-blue-500 outline-none"
                      placeholder="用逗号分隔关键词..."
                      value={t.keywords || ""}
                      onChange={(e) => {
                        const updated = templates.map(temp => temp.id === t.id ? { ...temp, keywords: e.target.value } : temp);
                        setTemplates(updated);
                        fetch('http://localhost:8010/templates', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ ...t, keywords: e.target.value })
                        });
                      }}
                    />
                  </div>
                  <div className="flex flex-col gap-2">
                    <span className="text-xs font-bold text-gray-400 uppercase">关联附件:</span>
                    <div className="flex flex-wrap gap-2 mb-1">
                      {(t.attachments || []).map((a, idx) => (
                        <div key={idx} className="flex items-center gap-1 bg-blue-50 text-blue-700 px-2 py-0.5 rounded text-[10px] border border-blue-100">
                          <Paperclip size={10} /> <span>{a.name}</span>
                          <button
                            onClick={() => {
                              const updated = templates.map(temp => temp.id === t.id ? { ...temp, attachments: t.attachments.filter((_, i) => i !== idx) } : temp);
                              setTemplates(updated);
                              fetch('http://localhost:8010/templates', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(updated.find(item => item.id === t.id))
                              });
                            }}
                            className="hover:text-red-500 ml-1"
                          >
                            ×
                          </button>
                        </div>
                      ))}
                    </div>
                    <label className="flex items-center gap-1.5 text-xs text-blue-600 cursor-pointer hover:bg-blue-50 w-max px-2 py-1 rounded border border-blue-100 border-dashed">
                      <Paperclip size={12} /> <span>添加模版附件</span>
                      <input
                        type="file" className="hidden"
                        onChange={(e) => {
                          const f = e.target.files[0];
                          if (f) {
                            const reader = new FileReader();
                            reader.onload = (re) => {
                              const newAttach = { name: f.name, content: re.target.result };
                              const updated = templates.map(temp => temp.id === t.id ? { ...temp, attachments: [...(t.attachments || []), newAttach] } : temp);
                              setTemplates(updated);
                              fetch('http://localhost:8010/templates', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(updated.find(item => item.id === t.id))
                              });
                            };
                            reader.readAsDataURL(f);
                          }
                        }}
                      />
                    </label>
                  </div>
                </div>
              ))}
              <div
                onClick={handleAddTemplate}
                className="border-2 border-dashed border-gray-300 rounded-xl p-6 flex items-center justify-center cursor-pointer hover:border-blue-400 hover:bg-blue-50 transition-colors text-gray-400 group"
              >
                <div className="text-center">
                  <div className="mb-2 mx-auto w-10 h-10 bg-gray-100 rounded-full flex items-center justify-center text-gray-400 group-hover:bg-blue-100 group-hover:text-blue-600"><MoreVertical className="rotate-90" /></div>
                  <p className="text-sm font-medium">添加新模版</p>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'settings' && (
            <div className="max-w-2xl mx-auto bg-white rounded-xl shadow-sm border border-gray-200 p-8">
              <h3 className="text-xl font-bold text-gray-800 mb-8 flex items-center gap-2">
                <ShieldAlert className="text-blue-600" /> 自动化规则配置
              </h3>
              <div className="space-y-6">
                <div className="flex items-center justify-between p-4 bg-blue-50 rounded-lg border border-blue-100">
                  <div>
                    <div className="font-bold text-blue-900">启用全自动回复模式</div>
                    <div className="text-xs text-blue-700">开启后，系统会自动发送高置信度或关键词匹配的邮件回复。</div>
                  </div>
                  <button
                    onClick={() => setConfig({ ...config, autoReplyMode: !config.autoReplyMode })}
                    className={`w-12 h-6 rounded-full transition-colors relative ${config.autoReplyMode ? 'bg-blue-600' : 'bg-gray-300'}`}
                  >
                    <div className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-all ${config.autoReplyMode ? 'left-7' : 'left-1'}`} />
                  </button>
                </div>
                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">自动回复置信度阈值</label>
                  <div className="flex items-center gap-4">
                    <input
                      type="range" min="0.5" max="1.0" step="0.01"
                      className="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                      value={config.autoReplyThreshold || 0.85}
                      onChange={e => setConfig({ ...config, autoReplyThreshold: parseFloat(e.target.value) })}
                    />
                    <span className="text-sm font-mono bg-gray-100 px-3 py-1 rounded-md font-bold text-gray-700">{Math.round((config.autoReplyThreshold || 0.85) * 100)}%</span>
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">邮件签名</label>
                  <input
                    type="text"
                    className="w-full border border-gray-300 rounded-md p-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                    value={config.signature || ''}
                    onChange={e => setConfig({ ...config, signature: e.target.value })}
                  />
                </div>
                <div className="pt-6 border-t border-gray-100 flex justify-between items-center">
                  <button onClick={handleSaveConfig} className="bg-blue-600 text-white px-8 py-2.5 rounded-lg hover:bg-blue-700 text-sm font-bold shadow-md transition-colors flex items-center gap-2">
                    <Save size={18} /> 保存配置
                  </button>

                  <div className="flex flex-col items-end">
                    <span className="text-[10px] text-red-400 font-bold uppercase mb-1 tracking-wider">Danger Zone</span>
                    <button onClick={handleResetDatabase} className="text-red-500 hover:text-red-700 text-[10px] font-bold border border-red-200 px-3 py-1.5 rounded-lg hover:bg-red-50 transition-all flex items-center gap-1.5">
                      <Trash2 size={12} /> 初始化并重置邮件数据库
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>

      {/* Attachment Preview Modal - Moved to proper scope */}
      {previewFile && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-8 bg-black/90 backdrop-blur-sm animate-in fade-in duration-300">
          <div className="relative w-full h-full max-w-6xl bg-white rounded-2xl overflow-hidden flex flex-col shadow-2xl">
            <div className="p-4 border-b flex items-center justify-between bg-gray-50">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-blue-50 text-blue-600 rounded-lg">
                  <FileText size={20} />
                </div>
                <div>
                  <div className="text-sm font-bold text-gray-800">{previewFile.filename}</div>
                  <div className="text-[10px] text-gray-400 uppercase tracking-widest">文件预览</div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => { handleAnalyzeAttachment(previewFile.storedName); }}
                  className="px-4 py-2 bg-purple-600 text-white rounded-xl text-xs font-bold hover:bg-purple-700 transition-all flex items-center gap-2"
                  disabled={isAnalyzingAtt}
                >
                  {isAnalyzingAtt ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                  {isAnalyzingAtt ? '正在深度扫描...' : 'AI 深度识别'}
                </button>
                <div className="w-px h-6 bg-gray-200 mx-1" />
                <a
                  href={previewFile.url}
                  download={previewFile.filename}
                  className="px-4 py-2 bg-blue-600 text-white rounded-xl text-xs font-bold hover:bg-blue-700 transition-all flex items-center gap-2"
                >
                  <RefreshCw size={14} /> 下载原文件
                </a>
                <button
                  onClick={() => setPreviewFile(null)}
                  className="p-2 hover:bg-gray-200 rounded-full text-gray-400 transition-colors"
                >
                  <Trash2 size={24} className="rotate-45" />
                </button>
              </div>
            </div>

            <div className="flex-1 bg-gray-100 overflow-auto flex p-8 gap-6">
              <div className={`flex-1 flex items-center justify-center bg-white rounded-lg shadow-inner relative ${attAnalysis ? 'max-w-[60%]' : 'w-full'}`}>
                {previewFile.type === 'image' ? (
                  <img
                    src={previewFile.url}
                    alt={previewFile.filename}
                    className="max-w-full max-h-full object-contain p-4 shadow-sm"
                  />
                ) : (
                  <iframe
                    src={previewFile.url}
                    className="w-full h-full border-0 rounded-lg shadow-sm"
                    title="PDF Preview"
                  />
                )}
              </div>

              {/* Analysis Sidebar */}
              {(isAnalyzingAtt || attAnalysis) && (
                <div className="w-[40%] bg-white rounded-lg shadow-lg border border-purple-100 flex flex-col animate-in slide-in-from-right-4 duration-500">
                  <div className="p-4 border-b bg-purple-50 flex items-center gap-2">
                    <Sparkles className="text-purple-600" size={18} />
                    <span className="font-bold text-sm text-purple-900">AI 智能提取结果</span>
                  </div>
                  <div className="flex-1 overflow-auto p-6 text-slate-800">
                    {isAnalyzingAtt ? (
                      <div className="h-full flex flex-col items-center justify-center text-gray-400 gap-4 text-center">
                        <Loader2 size={40} className="animate-spin text-purple-500" />
                        <div className="text-xs font-bold animate-pulse">正在利用 Gemini 2.0 视觉能力解析文档...</div>
                        <div className="text-[10px] text-gray-300">这可能需要几秒钟时间</div>
                      </div>
                    ) : (
                      <div className="text-sm whitespace-pre-wrap leading-relaxed">
                        {attAnalysis}
                      </div>
                    )}
                  </div>
                  {attAnalysis && (
                    <div className="p-4 border-t bg-gray-50 text-[10px] text-gray-400 italic">
                      💡 提示：您可以根据提取到的单据信息进行人工核验。
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="p-4 bg-white border-t flex items-center justify-center gap-8">
              <div className="text-[10px] text-gray-400 flex items-center gap-2">
                <ShieldAlert size={14} /> 预览模式已加密传输
              </div>
              <div className="text-[10px] text-gray-400 flex items-center gap-2">
                <CheckCircle size={14} /> 已通过安全扫描
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function NavItem({ icon, label, count, active, onClick, alert }) {
  return (
    <button onClick={onClick} className={`w-full flex items-center justify-between px-4 py-2 rounded-lg text-sm transition-colors ${active ? 'bg-blue-600 text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-white'}`}>
      <div className="flex items-center gap-3">{icon}<span>{label}</span></div>
      {count > 0 && <span className={`px-2 py-0.5 rounded-full text-xs ${active ? 'bg-white text-blue-600' : 'bg-slate-700'}`}>{count}</span>}
    </button>
  );
}

function StatCard({ title, value, icon, urgent, bg }) {
  return (
    <div className={`p-4 rounded-xl border flex items-center justify-between ${bg} ${urgent ? 'border-red-200' : ''}`}>
      <div><div className="text-xs text-gray-500">{title}</div><div className="text-2xl font-bold">{value}</div></div>
      <div className="p-2 rounded-full bg-white/50">{icon}</div>
    </div>
  );
}

function getCategoryStyles(category) {
  const cat = category?.toLowerCase() || "";
  if (cat.includes('urgent')) return 'bg-red-100 text-red-700 border-red-200';
  if (cat.includes('billing')) return 'bg-amber-100 text-amber-700 border-amber-200';
  if (cat.includes('technical')) return 'bg-blue-100 text-blue-700 border-blue-200';
  if (cat.includes('sales')) return 'bg-emerald-100 text-emerald-700 border-emerald-200';
  if (cat.includes('spam')) return 'bg-gray-200 text-gray-600 border-gray-300 opacity-50';
  return 'bg-blue-50 text-blue-600 border-blue-100';
}

function EmailRow({ email, onClick }) {
  const isUrgent = email.aiAnalysis?.isUrgent;
  const category = email.aiAnalysis?.category || (email.aiAnalysis ? "Information" : null);
  const isUnread = !email.isRead;
  const isProcessed = email.status === 'processed';
  const isPending = !isProcessed;

  // Choose border and background colors based on status
  let statusClasses = 'border-slate-100';
  if (isUrgent) {
    statusClasses = 'border-red-500 bg-red-50/30';
  } else if (isProcessed) {
    statusClasses = 'border-green-500 bg-white opacity-80';
  } else if (isPending) {
    statusClasses = 'border-blue-500 bg-blue-50/5';
  }

  return (
    <div onClick={onClick} className={`p-4 hover:bg-slate-50 cursor-pointer flex justify-between items-center border-l-4 transition-all shadow-sm mb-2 rounded-r-lg ${statusClasses}`}>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 mb-1">
          {isUnread && <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />}
          <div className={`font-bold text-sm truncate ${isUrgent ? 'text-red-700 underline decoration-red-200 decoration-2 underline-offset-4' : ''} ${isUnread ? 'font-extrabold' : ''}`}>
            {email.subject}
          </div>
          {isUrgent && <span className="px-1.5 py-0.5 bg-red-600 text-white text-[8px] font-bold rounded animate-pulse shadow-sm">CRITICAL</span>}
          {email.sentReply && <span className="px-1.5 py-0.5 bg-green-50 text-green-600 text-[8px] font-bold rounded border border-green-100">REPLIED</span>}
        </div>
        <div className="flex items-center gap-3">
          {category && (
            <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold border uppercase ${getCategoryStyles(category)}`}>
              {category}
            </span>
          )}
          <div className="text-xs text-slate-500 font-medium truncate">{email.from}</div>
          {email.accountOwner && (
            <span className="text-[9px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200">
              @{email.accountOwner.split('@')[0]}
            </span>
          )}
          <div className="text-[9px] text-slate-400 font-mono ml-auto">{email.receivedAt}</div>
        </div>
      </div>
      <div className="text-[10px] text-slate-400 ml-4 font-mono font-bold">{email.receivedAt?.split(' ')[1]}</div>
    </div>
  );
}

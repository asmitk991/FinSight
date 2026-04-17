import { useEffect, useState } from "react";
import { supabase } from "./lib/supabase";
import {
  BarChart, Bar, Cell, LineChart, Line,
  PieChart, Pie, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  askAgent, clearTransactions, confirmPdf, deleteTransaction,
  fetchReport, fetchTransactions, generateExecutiveReport,
  pollImageJob, uploadImages, uploadPdf,
} from "./lib/api";

const PALETTE = ["#6366f1","#22c55e","#f59e0b","#f43f5e","#0ea5e9","#a855f7","#14b8a6","#fb923c"];

/* ─── Helpers ──────────────────────────────────────────────── */
function fmt(amount, currency = "INR") {
  const sym = { INR: "₹", USD: "$", AED: "AED ", EUR: "€", GBP: "£" };
  return `${sym[currency] ?? currency}${Number(amount).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function initials(email = "") { return email[0]?.toUpperCase() ?? "U"; }

function ttStyle() {
  return {
    background: "#2a2f3a",
    border: "1px solid rgba(255,255,255,0.2)",
    borderRadius: 10,
    color: "#ffffff",
    fontSize: 12,
    fontWeight: 600,
    padding: "8px 12px",
    boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
  };
}


/* ─── Auth Screen ──────────────────────────────────────────── */
function Auth() {
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);

  const go = async (isSignUp) => {
    setLoading(true); setError(null);
    const { error: err } = isSignUp
      ? await supabase.auth.signUp({ email, password })
      : await supabase.auth.signInWithPassword({ email, password });
    if (err) setError(err.message);
    setLoading(false);
  };

  return (
    <div className="auth-page">
      <div className="auth-card fadein">
        <div className="auth-logo">
          <div className="auth-logo-mark">F</div>
          <span className="auth-logo-text">FinSight</span>
        </div>
        <h1 className="auth-heading">Welcome back</h1>
        <p className="auth-sub">Sign in to your financial dashboard or create a new account.</p>
        {error && <div className="auth-err">{error}</div>}
        <div className="auth-field">
          <label>Email</label>
          <input type="email" placeholder="you@example.com" value={email} onChange={e => setEmail(e.target.value)} />
        </div>
        <div className="auth-field">
          <label>Password</label>
          <input type="password" placeholder="••••••••" value={password} onChange={e => setPassword(e.target.value)}
            onKeyDown={e => e.key === "Enter" && go(false)} />
        </div>
        <div className="auth-buttons">
          <button className="btn btn-primary" onClick={() => go(false)} disabled={loading}>
            {loading ? "Signing in…" : "Sign in"}
          </button>
          <button className="btn btn-ghost" onClick={() => go(true)} disabled={loading}>
            Create account
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─── Sidebar Nav ──────────────────────────────────────────── */
const NAV = [
  { id: "dashboard", icon: "⬡", label: "Dashboard" },
  { id: "upload",    icon: "↑", label: "Upload" },
  { id: "chat",      icon: "✦", label: "Ask AI" },
  { id: "report",    icon: "▤", label: "Report" },
];

function Sidebar({ activeTab, setActiveTab, session, theme, toggleTheme }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="logo-mark">F</div>
        <span className="logo-name">FinSight</span>
      </div>
      <nav className="sidebar-nav">
        {NAV.map(n => (
          <button key={n.id} className={`nav-item ${activeTab === n.id ? "active" : ""}`}
            onClick={() => setActiveTab(n.id)}>
            <span className="nav-icon">{n.icon}</span>
            <span className="nav-label">{n.label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">
        <button className="nav-item" onClick={toggleTheme}>
          <span className="nav-icon">{theme === "dark" ? "☀" : "☽"}</span>
          <span className="nav-label">{theme === "dark" ? "Light mode" : "Dark mode"}</span>
        </button>
        <button className="nav-item" onClick={() => supabase.auth.signOut()}>
          <span className="nav-icon">→</span>
          <span className="nav-label">Sign out</span>
        </button>
        <div className="user-chip">
          <div className="user-avatar">{initials(session?.user?.email)}</div>
          <span className="user-email">{session?.user?.email}</span>
        </div>
      </div>
    </aside>
  );
}

/* ─── Small reusable pieces ────────────────────────────────── */
function StatusMsg({ msg, type = "info" }) {
  if (!msg) return null;
  return <div className={`status-bar ${type} fadein`}><span>●</span> {msg}</div>;
}

function ChartEmpty({ label }) {
  return (
    <div className="empty-chart-state">
      <span className="empty-icon">◌</span>
      <span>{label}</span>
    </div>
  );
}

function TxBadge({ value, type }) {
  return <span className={`tx-badge ${type}`}>{value}</span>;
}

/* ─── Transaction Table ────────────────────────────────────── */
function TxTable({ rows, onDelete, busyId, compact }) {
  if (!rows?.length) return (
    <div style={{ padding: "24px 20px", color: "var(--text-muted)", fontSize: 13, textAlign: "center" }}>
      No transactions to display.
    </div>
  );
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Date</th><th>Merchant</th><th>Amount</th>
            <th>Category</th><th>Type</th>{!compact && <th>Source</th>}
            {onDelete && <th />}
          </tr>
        </thead>
        <tbody>
          {rows.map(tx => (
            <tr key={tx.id}>
              <td style={{ color: "var(--text-secondary)", whiteSpace: "nowrap" }}>{tx.date?.slice(0, 10)}</td>
              <td style={{ fontWeight: 500 }}>{tx.merchant}</td>
              <td>
                <span className={`tx-amount ${tx.type}`}>{fmt(tx.amount, tx.currency)}</span>
              </td>
              <td><TxBadge value={tx.category} type="cat" /></td>
              <td><TxBadge value={tx.type} type={tx.type} /></td>
              {!compact && <td style={{ color: "var(--text-muted)" }}>{tx.source}</td>}
              {onDelete && (
                <td>
                  <button className="btn btn-ghost btn-sm"
                    onClick={() => onDelete(tx.id)} disabled={busyId === tx.id}>
                    {busyId === tx.id ? "…" : "Delete"}
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ─── Chart Modal ──────────────────────────────────────────── */
function ChartModal({ title, children, onClose }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal fadein" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-title">{title}</span>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>Close</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

/* ─── Main App ─────────────────────────────────────────────── */
export default function App() {
  const [session, setSession]         = useState(null);
  const [theme, setTheme]             = useState("dark");
  const [activeTab, setActiveTab]     = useState("dashboard");

  // Data
  const [transactions, setTx]         = useState([]);
  const [report, setReport]           = useState(null);
  const [execReport, setExecReport]   = useState(null);
  const [preview, setPreview]         = useState(null);
  const [agentReply, setAgentReply]   = useState(null);
  const [imageJob, setImageJob]       = useState(null);

  // UI state
  const [question, setQuestion]       = useState("");
  const [selectedPdf, setSelectedPdf] = useState(null);
  const [uploadMsg, setUploadMsg]     = useState("");
  const [uploadErr, setUploadErr]     = useState("");
  const [agentErr, setAgentErr]       = useState("");
  const [reportErr, setReportErr]     = useState("");
  const [showAll, setShowAll]         = useState(false);
  const [activeChart, setActiveChart] = useState(null);

  // Loading flags
  const [busy, setBusy] = useState({
    pdf: false, saving: false, images: false,
    agent: false, report: false, clear: false, deleting: null,
  });
  const b = (k, v) => setBusy(p => ({ ...p, [k]: v }));

  /* ── Auth ── */
  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => setSession(session));
    supabase.auth.onAuthStateChange((_e, s) => {
      setSession(s);
      if (!s) {
        setTx([]); setReport(null); setExecReport(null);
        setPreview(null); setAgentReply(null); setImageJob(null);
        setQuestion(""); setUploadMsg(""); setUploadErr("");
        setAgentErr(""); setReportErr(""); setSelectedPdf(null);
      }
    });
  }, []);

  /* ── Theme ── */
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  /* ── Load data on login ── */
  useEffect(() => { if (session) refresh(); }, [session]);

  const toggleTheme = () => setTheme(t => t === "dark" ? "light" : "dark");

  async function refresh() {
    const data = await fetchTransactions().catch(() => []);
    setTx(data);
    if (!data.length) { setReport(null); return; }
    const dates = data.map(tx => new Date(tx.date));
    const start = new Date(Math.min(...dates)).toISOString().slice(0, 10);
    const end   = new Date(Math.max(...dates)).toISOString().slice(0, 10);
    fetchReport(start, end).then(setReport).catch(() => setReport(null));
  }

  /* ── PDF ── */
  async function handlePdfUpload() {
    if (!selectedPdf) { setUploadErr("Select a PDF first."); return; }
    try {
      b("pdf", true); setUploadErr(""); setUploadMsg(`Parsing ${selectedPdf.name}…`);
      const data = await uploadPdf(selectedPdf);
      setPreview(data);
      setUploadMsg(`Found ${data.transactions.length} transactions. Review and confirm below.`);
      setActiveTab("dashboard");
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setUploadErr(typeof detail === "string" ? detail : "Extraction failed. Check your PDF and try again.");
      setPreview(null);
    } finally { b("pdf", false); }
  }

  async function handleImageUpload(e) {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    try {
      setUploadErr(""); b("images", true);
      setUploadMsg(`Queued ${files.length} image(s) for OCR…`);
      const job = await uploadImages(files);
      setImageJob(job);
      const iv = setInterval(async () => {
        const u = await pollImageJob(job.job_id);
        setImageJob(u);
        if (u.status === "completed" || u.status === "failed") {
          clearInterval(iv); b("images", false); refresh();
          setUploadMsg(u.status === "completed"
            ? `Receipt processing complete.`
            : `Processing failed: ${u.error ?? "unknown error"}`);
        }
      }, 2000);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setUploadErr(typeof detail === "string" ? detail : "Image processing failed.");
      b("images", false);
    }
  }

  async function savePreview() {
    try {
      b("saving", true);
      await confirmPdf(preview.preview_id, preview.transactions.map(tx => tx.id));
      setPreview(null); setUploadMsg("Transactions saved successfully.");
      refresh();
    } finally { b("saving", false); }
  }

  function removePreviewRow(id) {
    setPreview(p => p ? { ...p, transactions: p.transactions.filter(tx => tx.id !== id) } : p);
  }

  /* ── Agent ── */
  async function handleAsk() {
    if (!question.trim()) return;
    try {
      b("agent", true); setAgentErr("");
      const data = await askAgent(question);
      setAgentReply(data);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setAgentErr(typeof detail === "string" ? detail : "Query failed. Please try again.");
    } finally { b("agent", false); }
  }

  /* ── Delete / Clear ── */
  async function handleDelete(id) {
    try {
      b("deleting", id);
      await deleteTransaction(id);
      refresh();
    } finally { b("deleting", null); }
  }

  async function handleClear() {
    try {
      b("clear", true);
      await clearTransactions();
      setTx([]); setReport(null); setExecReport(null);
      setPreview(null); setAgentReply(null);
      setUploadMsg("All transactions cleared.");
    } finally { b("clear", false); }
  }

  /* ── Exec Report ── */
  async function handleReport() {
    try {
      b("report", true); setReportErr(""); setExecReport(null);
      const data = await generateExecutiveReport();
      setExecReport(data);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setReportErr(typeof detail === "string" ? detail : "Report generation failed.");
    } finally { b("report", false); }
  }

  /* ── Chart data ── */
  const debits = transactions.filter(tx => tx.type === "debit");
  const credits = transactions.filter(tx => tx.type === "credit");
  // Currency helper
  const conv = (amt, cur) => {
    const rates = { INR: 1, USD: 83.15, AED: 22.64, EUR: 90.41, GBP: 105.72 };
    return Number(amt) * (rates[cur?.toUpperCase()] || 1);
  };

  const totalSpend = debits.reduce((s, tx) => s + conv(tx.amount, tx.currency), 0);
  const totalIn    = credits.reduce((s, tx) => s + conv(tx.amount, tx.currency), 0);

  const catData = (() => {
    if (report?.category_breakdown?.length) return report.category_breakdown;
    const m = {};
    debits.forEach(tx => { m[tx.category] = (m[tx.category] || 0) + conv(tx.amount, tx.currency); });
    return Object.entries(m).map(([category, total]) => ({ category, total })).sort((a, b) => b.total - a.total);
  })();

  const merchantData = (() => {
    if (report?.top_merchants?.length) return report.top_merchants;
    const m = {};
    debits.forEach(tx => { m[tx.merchant] = (m[tx.merchant] || 0) + conv(tx.amount, tx.currency); });
    return Object.entries(m).map(([merchant, total]) => ({ merchant, total }))
      .sort((a, b) => b.total - a.total).slice(0, 8);
  })();

  const dayData = (() => {
    const m = {};
    debits.forEach(tx => { const k = tx.date?.slice(0, 10); m[k] = (m[k] || 0) + conv(tx.amount, tx.currency); });
    return Object.entries(m).map(([date, total]) => ({ date, total })).sort((a, b) => a.date.localeCompare(b.date));
  })();

  const runData = debits
    .sort((a, b) => new Date(a.date) - new Date(b.date))
    .reduce((acc, tx) => {
      const last = acc[acc.length - 1]?.total || 0;
      acc.push({ date: tx.date?.slice(0, 10), total: last + conv(tx.amount, tx.currency) });
      return acc;
    }, []);

  /* ── Page map ── */
  const pageTitles = {
    dashboard: "Dashboard", upload: "Upload", chat: "Ask AI", report: "Financial Report",
  };

  if (!session) return <Auth />;

  return (
    <div className="app-shell">
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab}
        session={session} theme={theme} toggleTheme={toggleTheme} />

      <div className="main-content">
        {/* Top bar */}
        <div className="topbar">
          <span className="topbar-title">{pageTitles[activeTab]}</span>
          <div className="topbar-actions">
            {activeTab === "dashboard" && transactions.length > 0 && (
              <button className="btn btn-danger btn-sm" onClick={handleClear}
                disabled={busy.clear}>
                {busy.clear ? "Clearing…" : "Clear all"}
              </button>
            )}
            {activeTab === "report" && (
              <button className="btn btn-primary btn-sm" onClick={handleReport}
                disabled={busy.report || transactions.length === 0}>
                {busy.report ? "Generating…" : "Generate report"}
              </button>
            )}
          </div>
        </div>

        <div className="page-content">

          {/* ═══ DASHBOARD ═══════════════════════════════════════ */}
          {activeTab === "dashboard" && (
            <>
              {/* KPI strip */}
              <div className="stats-row fadein">
                <div className="stat-card">
                  <span className="stat-label">Total transactions</span>
                  <span className="stat-value">{transactions.length}</span>
                  <span className="stat-sub">{debits.length} debits · {credits.length} credits</span>
                </div>
                <div className="stat-card">
                  <span className="stat-label">Total spend</span>
                  <span className="stat-value negative">{fmt(totalSpend)}</span>
                  <span className="stat-sub">across {debits.length} debit transactions</span>
                </div>
                <div className="stat-card">
                  <span className="stat-label">Total received</span>
                  <span className="stat-value positive">{fmt(totalIn)}</span>
                  <span className="stat-sub">across {credits.length} credit transactions</span>
                </div>
                <div className="stat-card">
                  <span className="stat-label">Top category</span>
                  <span className="stat-value" style={{ fontSize: 17 }}>
                    {catData[0]?.category ?? "—"}
                  </span>
                  <span className="stat-sub">{catData[0] ? fmt(catData[0].total) : "No data yet"}</span>
                </div>
              </div>

              {/* Preview confirm bar */}
              {preview && (
                <div className="card fadein">
                  <div className="preview-bar">
                    <span className="preview-bar-text">
                      ✦ {preview.transactions.length} transactions extracted — review below then confirm.
                    </span>
                    <div style={{ display: "flex", gap: 8 }}>
                      <button className="btn btn-ghost btn-sm" onClick={() => setPreview(null)}>Discard</button>
                      <button className="btn btn-primary btn-sm" onClick={savePreview} disabled={busy.saving}>
                        {busy.saving ? "Saving…" : `Confirm ${preview.transactions.length} transactions`}
                      </button>
                    </div>
                  </div>
                  <div className="card-body no-pad">
                    <TxTable rows={preview.transactions} onDelete={removePreviewRow} busyId={busy.deleting} />
                  </div>
                </div>
              )}

              {/* Charts */}
              <div className="chart-grid fadein">
                {/* Category */}
                <div className="chart-card">
                  <div className="chart-card-header">
                    <span className="chart-card-title">Spend by category</span>
                    <button className="btn btn-ghost btn-sm" onClick={() => setActiveChart("category")}>Expand</button>
                  </div>
                  <div className="chart-card-body">
                    {catData.length ? (
                      <ResponsiveContainer width="100%" height={240}>
                        <PieChart>
                          <Pie data={catData} dataKey="total" nameKey="category" innerRadius={60} outerRadius={90}>
                            {catData.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                          </Pie>
                <Tooltip contentStyle={ttStyle()} />
                        </PieChart>
                      </ResponsiveContainer>
                    ) : <ChartEmpty label="Upload and confirm a statement to see category trends." />}
                  </div>
                </div>

                {/* Merchant */}
                <div className="chart-card">
                  <div className="chart-card-header">
                    <span className="chart-card-title">Top merchants</span>
                    <button className="btn btn-ghost btn-sm" onClick={() => setActiveChart("merchant")}>Expand</button>
                  </div>
                  <div className="chart-card-body">
                    {merchantData.length ? (
                      <ResponsiveContainer width="100%" height={240}>
                        <BarChart data={merchantData} layout="vertical">
                          <XAxis type="number" hide />
                          <YAxis dataKey="merchant" type="category" width={110}
                            tick={{ fill: "var(--text-secondary)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={ttStyle()} />
                          <Bar dataKey="total" fill={PALETTE[0]} radius={[0, 6, 6, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    ) : <ChartEmpty label="Merchant data appears after you confirm transactions." />}
                  </div>
                </div>

                {/* Daily spend */}
                <div className="chart-card">
                  <div className="chart-card-header">
                    <span className="chart-card-title">Daily spend</span>
                    <button className="btn btn-ghost btn-sm" onClick={() => setActiveChart("day")}>Expand</button>
                  </div>
                  <div className="chart-card-body">
                    {dayData.length ? (
                      <ResponsiveContainer width="100%" height={240}>
                        <BarChart data={dayData}>
                          <XAxis dataKey="date" hide />
                          <YAxis tick={{ fill: "var(--text-secondary)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={ttStyle()} />
                          <Bar dataKey="total" fill={PALETTE[2]} radius={[4, 4, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    ) : <ChartEmpty label="Daily breakdown appears once debits are saved." />}
                  </div>
                </div>

                {/* Running total */}
                <div className="chart-card">
                  <div className="chart-card-header">
                    <span className="chart-card-title">Cumulative spend</span>
                    <button className="btn btn-ghost btn-sm" onClick={() => setActiveChart("running")}>Expand</button>
                  </div>
                  <div className="chart-card-body">
                    {runData.length ? (
                      <ResponsiveContainer width="100%" height={240}>
                        <LineChart data={runData}>
                          <XAxis dataKey="date" hide />
                          <YAxis tick={{ fill: "var(--text-secondary)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={ttStyle()} />
                          <Line dataKey="total" stroke={PALETTE[0]} strokeWidth={2.5} dot={false} />
                        </LineChart>
                      </ResponsiveContainer>
                    ) : <ChartEmpty label="Cumulative spend requires saved debit transactions." />}
                  </div>
                </div>
              </div>

              {/* Transactions table */}
              <div className="card fadein">
                <div className="card-header">
                  <div>
                    <div className="card-title">Recent transactions</div>
                    <div className="card-sub">{transactions.length} total · showing {showAll ? transactions.length : Math.min(5, transactions.length)}</div>
                  </div>
                  {transactions.length > 5 && (
                    <button className="btn btn-ghost btn-sm" onClick={() => setShowAll(s => !s)}>
                      {showAll ? "Show less" : `Show all ${transactions.length}`}
                    </button>
                  )}
                </div>
                <div className="card-body no-pad">
                  <TxTable
                    rows={showAll ? transactions : transactions.slice(0, 5)}
                    onDelete={showAll ? handleDelete : null}
                    busyId={busy.deleting}
                  />
                </div>
              </div>
            </>
          )}

          {/* ═══ UPLOAD ═══════════════════════════════════════════ */}
          {activeTab === "upload" && (
            <div className="fadein" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div className="card">
                <div className="card-header">
                  <div>
                    <div className="card-title">Upload statement</div>
                    <div className="card-sub">We'll extract and categorise your transactions automatically.</div>
                  </div>
                </div>
                <div className="card-body">
                  <div className="upload-zone">
                    {/* PDF */}
                    <label className="upload-tile">
                      <span className="upload-tile-icon">📄</span>
                      <span className="upload-tile-title">
                        {selectedPdf ? selectedPdf.name : "Choose PDF"}
                      </span>
                      <span className="upload-tile-sub">UPI / bank statement PDF</span>
                      <input type="file" accept="application/pdf" onChange={e => {
                        setSelectedPdf(e.target.files?.[0] || null);
                        setUploadErr("");
                      }} />
                    </label>

                    {/* Images */}
                    <label className="upload-tile">
                      <span className="upload-tile-icon">🖼</span>
                      <span className="upload-tile-title">Upload receipts</span>
                      <span className="upload-tile-sub">JPG / PNG receipt images</span>
                      <input type="file" accept="image/*" multiple onChange={handleImageUpload} />
                    </label>
                  </div>

                  {selectedPdf && (
                    <div style={{ marginTop: 16, display: "flex", gap: 10 }}>
                      <button className={`btn btn-primary ${busy.pdf ? "busy" : ""}`}
                        onClick={handlePdfUpload} disabled={busy.pdf}>
                        {busy.pdf ? "Extracting…" : "Extract transactions"}
                      </button>
                      <button className="btn btn-ghost" onClick={() => setSelectedPdf(null)}>Cancel</button>
                    </div>
                  )}

                  {imageJob && (
                    <div style={{ marginTop: 14 }}>
                      <StatusMsg
                        msg={`Image job ${imageJob.status}${imageJob.status === "failed" ? ": " + imageJob.error : ""}`}
                        type={imageJob.status === "completed" ? "success" : imageJob.status === "failed" ? "error" : "info"}
                      />
                    </div>
                  )}
                </div>
              </div>

              {uploadMsg && <StatusMsg msg={uploadMsg} type="success" />}
              {uploadErr && <StatusMsg msg={uploadErr} type="error" />}
            </div>
          )}

          {/* ═══ ASK AI ═══════════════════════════════════════════ */}
          {activeTab === "chat" && (
            <div className="fadein" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div className="card">
                <div className="card-header">
                  <div>
                    <div className="card-title">Ask the finance agent</div>
                    <div className="card-sub">
                      Natural language queries over your entire transaction history.
                    </div>
                  </div>
                </div>
                <div className="card-body">
                  <div className="chat-input-row">
                    <input className="chat-input" value={question}
                      onChange={e => setQuestion(e.target.value)}
                      onKeyDown={e => e.key === "Enter" && handleAsk()}
                      placeholder="e.g. How much did I spend on food in March?" />
                    <button className={`btn btn-primary ${busy.agent ? "busy" : ""}`}
                      onClick={handleAsk} disabled={busy.agent}>
                      {busy.agent ? "Thinking…" : "Ask"}
                    </button>
                  </div>

                  {agentReply && (
                    <div className="agent-bubble fadein">
                      <p style={{ marginBottom: agentReply.supporting_transactions?.length ? 14 : 0 }}>
                        {agentReply.answer}
                      </p>
                      {agentReply.supporting_transactions?.length > 0 && (
                        <TxTable rows={agentReply.supporting_transactions} compact />
                      )}
                    </div>
                  )}
                  {agentErr && <StatusMsg msg={agentErr} type="error" />}
                </div>
              </div>

              {/* Prompt ideas */}
              <div className="card">
                <div className="card-header">
                  <div className="card-title">Example questions</div>
                </div>
                <div className="card-body">
                  {[
                    "How much did I spend total?",
                    "What's my biggest single transaction?",
                    "Show all food transactions in January",
                    "Compare spend in March vs April",
                  ].map(q => (
                    <button key={q} className="btn btn-ghost btn-sm"
                      style={{ marginRight: 8, marginBottom: 8 }}
                      onClick={() => { setQuestion(q); }}>
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ═══ REPORT ═══════════════════════════════════════════ */}
          {activeTab === "report" && (
            <div className="fadein" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {reportErr && <StatusMsg msg={reportErr} type="error" />}

              {!execReport && !busy.report && (
                <div className="card">
                  <div className="card-body" style={{ textAlign: "center", padding: "48px 24px" }}>
                    <div style={{ fontSize: 40, marginBottom: 16 }}>▤</div>
                    <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 8 }}>Executive Report</div>
                    <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 24, maxWidth: 380, margin: "0 auto 24px" }}>
                      AI-synthesised analysis of your spending patterns, behavioural insights, and personalised recommendations.
                    </div>
                    <button className="btn btn-primary"
                      onClick={handleReport} disabled={transactions.length === 0}>
                      {transactions.length === 0 ? "Upload transactions first" : "Generate report"}
                    </button>
                  </div>
                </div>
              )}

              {busy.report && (
                <div className="card">
                  <div className="card-body" style={{ textAlign: "center", padding: "48px 24px" }}>
                    <div style={{ fontSize: 30, marginBottom: 16 }} className="spinning">⚙</div>
                    <div style={{ fontSize: 14, color: "var(--text-secondary)" }}>
                      Analysing your financial data…
                    </div>
                  </div>
                </div>
              )}

              {execReport && (
                <>
                  {/* Health + headline */}
                  <div className="card">
                    <div className="card-body">
                      <div className="health-ring-wrap">
                        <div className="health-ring" style={{ "--score": execReport.health_score }}>
                          <div className="health-ring-inner">
                            <span className="health-ring-num">{execReport.health_score}</span>
                            <span className="health-ring-lbl">{execReport.health_label}</span>
                          </div>
                        </div>
                        <div>
                          <div className="exec-headline">{execReport.headline}</div>
                          <div className="exec-overview">{execReport.overview}</div>
                          <div style={{ marginTop: 8, fontSize: 11.5, color: "var(--text-muted)" }}>
                            Period: {execReport.period_label}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* KPIs */}
                  <div className="exec-kpi-grid">
                    <div className="exec-kpi-card">
                      <div className="exec-kpi-label">Total spend</div>
                      <div className="exec-kpi-value">₹{execReport.total_spend?.toLocaleString("en-IN", { maximumFractionDigits: 0 })}</div>
                    </div>
                    <div className="exec-kpi-card">
                      <div className="exec-kpi-label">Top category</div>
                      <div className="exec-kpi-value" style={{ fontSize: 15 }}>{execReport.top_category}</div>
                    </div>
                    <div className="exec-kpi-card">
                      <div className="exec-kpi-label">Top merchant</div>
                      <div className="exec-kpi-value" style={{ fontSize: 15 }}>{execReport.top_merchant}</div>
                    </div>
                  </div>

                  {/* Insights grid */}
                  <div className="exec-insights-grid">
                    {execReport.behavioral_insights?.length > 0 && (
                      <div className="insight-col">
                        <div className="insight-col-title">Behavioral insights</div>
                        <ul className="insight-list">
                          {execReport.behavioral_insights.map((s, i) => <li key={i}>{s}</li>)}
                        </ul>
                      </div>
                    )}
                    {execReport.recommendations?.length > 0 && (
                      <div className="insight-col reco">
                        <div className="insight-col-title">Recommendations</div>
                        <ul className="insight-list">
                          {execReport.recommendations.map((s, i) => <li key={i}>{s}</li>)}
                        </ul>
                      </div>
                    )}
                  </div>

                  <div style={{ display: "flex", justifyContent: "flex-end" }}>
                    <button className="btn btn-primary" onClick={handleReport} disabled={busy.report}>
                      Regenerate
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ═══ Chart Modal ════════════════════════════════════════ */}
      {activeChart && (
        <ChartModal
          title={{ category: "Spend by category", merchant: "Top merchants", day: "Daily spend", running: "Cumulative spend"}[activeChart]}
          onClose={() => setActiveChart(null)}
        >
          <ResponsiveContainer width="100%" height={480}>
            {activeChart === "category" ? (
              <PieChart>
                <Pie data={catData} dataKey="total" nameKey="category" innerRadius={100} outerRadius={180}>
                  {catData.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                </Pie>
                <Tooltip contentStyle={ttStyle()} />
              </PieChart>
            ) : activeChart === "merchant" ? (
              <BarChart data={merchantData} layout="vertical">
                <XAxis type="number" tick={{ fill: "var(--text-secondary)", fontSize: 12 }} axisLine={false} tickLine={false} />
                <YAxis dataKey="merchant" type="category" width={160}
                  tick={{ fill: "var(--text-secondary)", fontSize: 12 }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={ttStyle()} />
                <Bar dataKey="total" fill={PALETTE[0]} radius={[0, 6, 6, 0]} />
              </BarChart>
            ) : activeChart === "day" ? (
              <BarChart data={dayData}>
                <XAxis dataKey="date" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "var(--text-secondary)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={ttStyle()} />
                <Bar dataKey="total" fill={PALETTE[2]} radius={[4, 4, 0, 0]} />
              </BarChart>
            ) : (
              <LineChart data={runData}>
                <XAxis dataKey="date" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "var(--text-secondary)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={ttStyle()} />
                <Line dataKey="total" stroke={PALETTE[0]} strokeWidth={2.5} dot={false} />
              </LineChart>
            )}
          </ResponsiveContainer>
        </ChartModal>
      )}
    </div>
  );
}

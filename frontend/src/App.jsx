import { useEffect, useState } from "react";
import { supabase } from "./lib/supabase";
import {
  BarChart,
  Bar,
  Cell,
  LineChart,
  Line,
  PieChart,
  Pie,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  askAgent,
  clearTransactions,
  confirmPdf,
  deleteTransaction,
  fetchReport,
  fetchTransactions,
  generateExecutiveReport,
  pollImageJob,
  uploadImages,
  uploadPdf,
} from "./lib/api";

const COLORS = ["#10b981", "#f59e0b", "#3b82f6", "#f3f4f6", "#0ea5e9", "#ef4444"];

function Auth() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleAuth = async (isSignUp) => {
    setLoading(true);
    setError(null);
    const { error } = isSignUp 
      ? await supabase.auth.signUp({ email, password })
      : await supabase.auth.signInWithPassword({ email, password });
    
    if (error) setError(error.message);
    setLoading(false);
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h1>FinSight</h1>
        <p>Your AI-powered personal finance assistant.</p>
        {error && <div className="error-text">{error}</div>}
        <input 
          type="email" 
          placeholder="Email" 
          value={email} 
          onChange={(e) => setEmail(e.target.value)} 
        />
        <input 
          type="password" 
          placeholder="Password" 
          value={password} 
          onChange={(e) => setPassword(e.target.value)} 
        />
        <div className="auth-buttons">
          <button onClick={() => handleAuth(false)} disabled={loading}>
            {loading ? "..." : "Sign In"}
          </button>
          <button className="ghost-button" onClick={() => handleAuth(true)} disabled={loading}>
            Sign Up
          </button>
        </div>
      </div>
    </div>
  );
}

function App() {
  const [session, setSession] = useState(null);
  const [theme, setTheme] = useState("dark");
  const [preview, setPreview] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [question, setQuestion] = useState("");
  const [agentReply, setAgentReply] = useState(null);
  const [report, setReport] = useState(null);
  const [imageJob, setImageJob] = useState(null);
  const [selectedPdf, setSelectedPdf] = useState(null);
  const [uploadMessage, setUploadMessage] = useState("");
  const [uploadError, setUploadError] = useState("");
  const [isUploadingPdf, setIsUploadingPdf] = useState(false);
  const [isSavingPreview, setIsSavingPreview] = useState(false);
  const [isAskingAgent, setIsAskingAgent] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [isUploadingImages, setIsUploadingImages] = useState(false);
  const [activeChart, setActiveChart] = useState(null);
  const [agentError, setAgentError] = useState("");
  const [isClearingAll, setIsClearingAll] = useState(false);
  const [showAllStoredTransactions, setShowAllStoredTransactions] = useState(false);
  const [execReport, setExecReport] = useState(null);
  const [isGeneratingReport, setIsGeneratingReport] = useState(false);
  const [reportError, setReportError] = useState("");

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
    });

    supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
    });
  }, []);

  useEffect(() => {
    if (session) {
      refreshDashboard();
    }
    document.documentElement.setAttribute("data-theme", theme);
  }, [session, theme]);

  if (!session) return <Auth />;

  function toggleTheme() {
    const newTheme = theme === "dark" ? "light" : "dark";
    setTheme(newTheme);
    document.documentElement.setAttribute("data-theme", newTheme);
  }

  async function loadTransactions() {
    const data = await fetchTransactions();
    setTransactions(data);
    return data;
  }

  async function refreshDashboard() {
    const data = await loadTransactions();
    if (!data.length) {
      setReport(null);
      return;
    }
    const dates = data.map((tx) => new Date(tx.date));
    const minDate = new Date(Math.min(...dates));
    const maxDate = new Date(Math.max(...dates));
    const start = minDate.toISOString().slice(0, 10);
    const end = maxDate.toISOString().slice(0, 10);
    fetchReport(start, end).then(setReport).catch(() => setReport(null));
  }

  function handlePdfSelect(event) {
    const file = event.target.files?.[0];
    setSelectedPdf(file || null);
    setUploadError("");
    setUploadMessage(file ? `Selected PDF: ${file.name}` : "");
  }

  async function handlePdfUpload() {
    if (!selectedPdf) {
      setUploadError("Choose a PDF first.");
      return;
    }
    try {
      setIsUploadingPdf(true);
      setUploadError("");
      setUploadMessage(`Uploading ${selectedPdf.name} and extracting transactions...`);
      const data = await uploadPdf(selectedPdf);
      setPreview(data);
      setUploadMessage(`Parsed ${data.transactions.length} transactions from ${selectedPdf.name}.`);
    } catch (error) {
      const detail = error?.response?.data?.detail;
      setUploadError(typeof detail === "string" ? detail : "Extraction failed. Ensure your PDF contains valid transaction history and try again.");
      setPreview(null);
    } finally {
      setIsUploadingPdf(false);
    }
  }

  async function handleImageUpload(event) {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    try {
      setUploadError("");
      setIsUploadingImages(true);
      setUploadMessage(`Queued ${files.length} receipt image(s) for processing.`);
      const job = await uploadImages(files);
      setImageJob(job);
      const interval = setInterval(async () => {
        const updated = await pollImageJob(job.job_id);
        setImageJob(updated);
        if (updated.status === "completed" || updated.status === "failed") {
          clearInterval(interval);
          refreshDashboard();
          setIsUploadingImages(false);
        }
      }, 2000);
    } catch (error) {
      const detail = error?.response?.data?.detail;
      setUploadError(typeof detail === "string" ? detail : "Image processing failed. Please try again later.");
      setIsUploadingImages(false);
    }
  }

  async function savePreview() {
    try {
      setIsSavingPreview(true);
      await confirmPdf(preview.preview_id, preview.transactions.map((tx) => tx.id));
      setPreview(null);
      await refreshDashboard();
    } finally {
      setIsSavingPreview(false);
    }
  }

  async function handleAskAgent() {
    if (!question.trim()) return;
    try {
      setIsAskingAgent(true);
      setAgentError("");
      const data = await askAgent(question);
      setAgentReply(data);
    } catch (error) {
      const detail = error?.response?.data?.detail;
      setAgentError(typeof detail === "string" ? detail : "Agent query failed. Please try again.");
    } finally {
      setIsAskingAgent(false);
    }
  }

  async function handleDelete(id) {
    try {
      setDeletingId(id);
      await deleteTransaction(id);
      await refreshDashboard();
    } finally {
      setDeletingId(null);
    }
  }

  async function handleClearAll() {
    try {
      setIsClearingAll(true);
      setUploadError("");
      setAgentError("");
      await clearTransactions();
      setPreview(null);
      setAgentReply(null);
      setReport(null);
      setShowAllStoredTransactions(false);
      setUploadMessage("Cleared all saved transactions and chart data.");
      await refreshDashboard();
    } finally {
      setIsClearingAll(false);
    }
  }

  async function handleGenerateReport() {
    try {
      setIsGeneratingReport(true);
      setReportError("");
      setExecReport(null);
      const data = await generateExecutiveReport();
      setExecReport(data);
    } catch (error) {
      const detail = error?.response?.data?.detail;
      setReportError(typeof detail === "string" ? detail : "Report generation failed. Please try again.");
    } finally {
      setIsGeneratingReport(false);
    }
  }

  function removePreviewRow(id) {
    setPreview((current) => {
      if (!current) return current;
      return {
        ...current,
        transactions: current.transactions.filter((tx) => tx.id !== id),
      };
    });
  }

  const fallbackCategoryTotals = transactions
    .filter((tx) => tx.type === "debit")
    .reduce((acc, tx) => {
      acc[tx.category] = (acc[tx.category] || 0) + tx.amount;
      return acc;
    }, {});
  const fallbackCategoryData = Object.entries(fallbackCategoryTotals)
    .map(([category, total]) => ({ category, total }))
    .sort((a, b) => b.total - a.total);
  const chartCategoryData = report?.category_breakdown?.length ? report.category_breakdown : fallbackCategoryData;

  const fallbackMerchantTotals = transactions
    .filter((tx) => tx.type === "debit")
    .reduce((acc, tx) => {
      acc[tx.merchant] = (acc[tx.merchant] || 0) + tx.amount;
      return acc;
    }, {});
  const fallbackMerchantData = Object.entries(fallbackMerchantTotals)
    .map(([merchant, total]) => ({ merchant, total }))
    .sort((a, b) => b.total - a.total)
    .slice(0, 8);
  const chartMerchantData = report?.top_merchants?.length ? report.top_merchants : fallbackMerchantData;
  const reportDayTotals = transactions
    .filter((tx) => tx.type === "debit")
    .reduce((acc, tx) => {
      const key = tx.date.slice(0, 10);
      acc[key] = (acc[key] || 0) + tx.amount;
      return acc;
    }, {});
  const dayTotals = Object.entries(reportDayTotals).map(([date, total]) => ({ date, total }));
  const runningTotal = transactions
    .filter((tx) => tx.type === "debit")
    .sort((a, b) => new Date(a.date) - new Date(b.date))
    .reduce((acc, tx) => {
      const last = acc[acc.length - 1]?.total || 0;
      acc.push({ date: tx.date.slice(0, 10), total: last + tx.amount });
      return acc;
    }, []);
  const visibleTransactions = showAllStoredTransactions ? transactions : transactions.slice(0, 5);
  const chartAxisColor = getChartAxisColor(theme);
  const chartGridColor = getChartGridColor(theme);
  const chartTooltipStyle = getChartTooltipStyle(theme);
  const chartTooltipLabelStyle = getChartTooltipLabelStyle(theme);
  const chartTooltipItemStyle = getChartTooltipItemStyle(theme);

  return (
    <div className="app-shell">
      <div className="theme-toggle-row">
         <button className="ghost-button" onClick={toggleTheme}>
            {theme === "dark" ? "☀️ Switch to Light Mode" : "🌙 Switch to Dark Mode"}
         </button>
         <button className="ghost-button" onClick={() => supabase.auth.signOut()}>
            🚪 Sign Out
         </button>
      </div>
      <header className="hero">
        <div>
          <p className="eyebrow">FinSight</p>
          <h1>Intelligent personal finance analysis from statements and receipts.</h1>
          <p className="subtitle">
            Upload UPI Statement PDFs or receipt images, review extracted data, then ask natural-language questions over your spending.
          </p>
        </div>
      </header>

      <section className="panel upload-panel">
        <div>
          <h2>Upload sources</h2>
          <p>PDF statements return a reviewable preview. Receipt images are processed asynchronously through the OCR pipeline.</p>
        </div>
        <div className="upload-actions">
          <label className="upload-card">
            <span>Choose PDF Statement</span>
            <input type="file" accept="application/pdf" onChange={handlePdfSelect} />
          </label>
          <button className={`action-button ${isUploadingPdf ? "is-busy" : ""}`} onClick={handlePdfUpload} disabled={isUploadingPdf}>
            {isUploadingPdf ? "Uploading PDF..." : "Upload PDF"}
          </button>
          <label className="upload-card">
            <span>Upload Receipt Images</span>
            <input type="file" accept="image/*" multiple onChange={handleImageUpload} />
          </label>
          <div className={`upload-chip ${isUploadingImages ? "is-busy" : ""}`}>{isUploadingImages ? "Processing images..." : "Images idle"}</div>
        </div>
        {uploadMessage && <p className="job-status">{uploadMessage}</p>}
        {uploadError && <p className="error-text">{uploadError}</p>}
        {imageJob && <p className="job-status">Image job {imageJob.id || imageJob.job_id}: {imageJob.status}</p>}
      </section>

      {preview && (
        <section className="panel">
          <div className="section-row">
            <div>
              <h2>PDF extraction preview</h2>
              <p>Review the parsed transactions before saving them to storage and the vector index.</p>
            </div>
            <button className={`action-button ${isSavingPreview ? "is-busy" : ""}`} onClick={savePreview} disabled={isSavingPreview}>
              {isSavingPreview ? "Saving..." : `Confirm ${preview.transactions.length} transactions`}
            </button>
          </div>
          <TransactionTable transactions={preview.transactions} onDelete={removePreviewRow} busyId={deletingId} />
        </section>
      )}

      <section className="chart-grid">
        <ChartCard title="Spend by category" onExpand={() => setActiveChart("category")}>
          {chartCategoryData.length ? (
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie data={chartCategoryData} dataKey="total" nameKey="category" innerRadius={58} outerRadius={88}>
                  {chartCategoryData.map((_, index) => (
                    <Cell key={index} fill={theme === "light" ? COLORS[0] : COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip contentStyle={chartTooltipStyle} labelStyle={chartTooltipLabelStyle} itemStyle={chartTooltipItemStyle} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <EmptyChartState label="Upload and confirm transactions to see category trends." />
          )}
        </ChartCard>

        <ChartCard title="Top merchants" onExpand={() => setActiveChart("merchant")}>
          {chartMerchantData.length ? (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={chartMerchantData} layout="vertical">
                <XAxis type="number" hide tick={{ fill: chartAxisColor }} axisLine={{ stroke: chartGridColor }} />
                <YAxis dataKey="merchant" type="category" width={130} tick={{ fill: chartAxisColor, fontSize: 12 }} axisLine={{ stroke: chartGridColor }} tickLine={{ stroke: chartGridColor }} />
                <Tooltip contentStyle={chartTooltipStyle} labelStyle={chartTooltipLabelStyle} itemStyle={chartTooltipItemStyle} />
                <Bar dataKey="total" fill="var(--emerald-text)" radius={[0, 10, 10, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyChartState label="Merchant rollups will appear after you save transactions." />
          )}
        </ChartCard>

        <ChartCard title="Day-wise spend" onExpand={() => setActiveChart("day")}>
          {dayTotals.length ? (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={dayTotals}>
                <XAxis dataKey="date" hide tick={{ fill: chartAxisColor }} axisLine={{ stroke: chartGridColor }} />
                <YAxis tick={{ fill: chartAxisColor, fontSize: 12 }} axisLine={{ stroke: chartGridColor }} tickLine={{ stroke: chartGridColor }} />
                <Tooltip contentStyle={chartTooltipStyle} labelStyle={chartTooltipLabelStyle} itemStyle={chartTooltipItemStyle} />
                <Bar dataKey="total" fill="var(--emerald-text)" radius={[10, 10, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyChartState label="Daily spend will show up once debit transactions exist." />
          )}
        </ChartCard>

        <ChartCard title="Running total" onExpand={() => setActiveChart("running")}>
          {runningTotal.length ? (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={runningTotal}>
                <XAxis dataKey="date" hide tick={{ fill: chartAxisColor }} axisLine={{ stroke: chartGridColor }} />
                <YAxis tick={{ fill: chartAxisColor, fontSize: 12 }} axisLine={{ stroke: chartGridColor }} tickLine={{ stroke: chartGridColor }} />
                <Tooltip contentStyle={chartTooltipStyle} labelStyle={chartTooltipLabelStyle} itemStyle={chartTooltipItemStyle} />
                <Line dataKey="total" stroke="var(--emerald-text)" strokeWidth={3} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <EmptyChartState label="Running total needs saved debit transactions." />
          )}
        </ChartCard>
      </section>

      <section className="panel">
        <div className="section-row">
          <div>
            <h2>Stored transactions</h2>
            <p>These records back both the structured reports and the semantic retrieval flow, including peer-to-peer counterparties.</p>
          </div>
          <div className="button-row">
            {transactions.length > 5 && (
              <button className="ghost-button" onClick={() => setShowAllStoredTransactions((current) => !current)}>
                {showAllStoredTransactions ? "Show less" : `Show all (${transactions.length})`}
              </button>
            )}
            <button className={`ghost-button ${isClearingAll ? "is-busy" : ""}`} onClick={handleClearAll} disabled={isClearingAll}>
              {isClearingAll ? "Clearing..." : "Clear all"}
            </button>
          </div>
        </div>
        <p className="table-note">
          By default this shows the latest five saved rows. Delete is only for correcting a bad confirmed extraction, so it appears in the expanded view.
        </p>
        <TransactionTable
          transactions={visibleTransactions}
          onDelete={showAllStoredTransactions ? handleDelete : null}
          busyId={deletingId}
        />
      </section>

      {/* ── Executive Report Panel ── */}
      <section className="panel exec-report-panel">
        <div className="section-row">
          <div>
            <h2>Executive Financial Report</h2>
            <p>AI-synthesized analysis of your spending patterns and recommendations.</p>
          </div>
          <button
            className={`action-button ${isGeneratingReport ? "is-busy" : ""}`}
            onClick={handleGenerateReport}
            disabled={isGeneratingReport || transactions.length === 0}
          >
            {isGeneratingReport ? "Generating..." : "Generate Report"}
          </button>
        </div>

        {reportError && <p className="error-text">{reportError}</p>}

        {!execReport && !isGeneratingReport && (
          <div className="exec-report-empty">
            <span className="exec-report-icon">📊</span>
            <p>Click <strong>Generate Report</strong> to get an AI-powered executive summary of all your transactions.</p>
          </div>
        )}

        {isGeneratingReport && (
          <div className="exec-report-empty">
            <span className="exec-report-icon spinning">⚙️</span>
            <p>The Editor Agent is analysing your transactions…</p>
          </div>
        )}

        {execReport && (
          <div className="exec-report-body">
            {/* Header row: health score + headline */}
            <div className="exec-report-header">
              <div className="health-score-ring" style={{ "--score": execReport.health_score }}>
                <div className="health-score-inner">
                  <span className="health-score-num">{execReport.health_score}</span>
                  <span className="health-score-label">{execReport.health_label}</span>
                </div>
              </div>
              <div className="exec-report-headline-block">
                <p className="exec-report-period">{execReport.period_label}</p>
                <h3 className="exec-report-headline">{execReport.headline}</h3>
                <p className="exec-report-overview">{execReport.overview}</p>
              </div>
            </div>

            {/* KPI pills */}
            <div className="exec-kpi-row">
              <div className="exec-kpi">
                <span className="exec-kpi-label">Total Spend</span>
                <span className="exec-kpi-value">₹{execReport.total_spend?.toLocaleString("en-IN", { maximumFractionDigits: 0 })}</span>
              </div>
              <div className="exec-kpi">
                <span className="exec-kpi-label">Top Category</span>
                <span className="exec-kpi-value">{execReport.top_category}</span>
              </div>
              <div className="exec-kpi">
                <span className="exec-kpi-label">Top Merchant</span>
                <span className="exec-kpi-value">{execReport.top_merchant}</span>
              </div>
            </div>

            {/* Two columns: behavioral insights | recommendations */}
            <div className="exec-report-grid">
              {execReport.behavioral_insights?.length > 0 && (
                <div className="exec-report-col exec-report-col--wide">
                  <h4 className="exec-col-title">🧠 Spending Behaviour</h4>
                  <ul className="exec-list">
                    {execReport.behavioral_insights.map((insight, i) => (
                      <li key={i}>{insight}</li>
                    ))}
                  </ul>
                </div>
              )}

              {execReport.recommendations?.length > 0 && (
                <div className="exec-report-col">
                  <h4 className="exec-col-title">💡 Recommendations</h4>
                  <ul className="exec-list reco-list">
                    {execReport.recommendations.map((rec, i) => (
                      <li key={i}>{rec}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      <section className="panel chat-panel">
        <h2>Ask the finance agent</h2>
        <div className="chat-row">
          <input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Try: How much did I spend on food in January?"
          />
          <button className={`action-button ${isAskingAgent ? "is-busy" : ""}`} onClick={handleAskAgent} disabled={isAskingAgent}>
            {isAskingAgent ? "Thinking..." : "Ask"}
          </button>
        </div>
        {/* <p className="table-note">You can now scope merchant queries by month, for example: `How much did I spend on Chai Adda in March?`</p> */}
        {agentReply && (
          <div className="agent-response">
            <p>{agentReply.answer}</p>
            <TransactionTable transactions={agentReply.supporting_transactions} onDelete={null} compact />
          </div>
        )}
        {agentError && <p className="error-text">{agentError}</p>}
      </section>

      {activeChart && (
        <div className="chart-modal-backdrop" onClick={() => setActiveChart(null)}>
          <div className="chart-modal" onClick={(event) => event.stopPropagation()}>
            <div className="section-row">
              <h2>{chartTitle(activeChart)}</h2>
              <button className="ghost-button" onClick={() => setActiveChart(null)}>Close</button>
            </div>
            <div className="chart-modal-body">{renderExpandedChart(activeChart, chartCategoryData, chartMerchantData, dayTotals, runningTotal, theme, chartAxisColor, chartGridColor, chartTooltipStyle, chartTooltipLabelStyle, chartTooltipItemStyle)}</div>
          </div>
        </div>
      )}
    </div>
  );
}

function ChartCard({ title, children, onExpand }) {
  return (
    <section className="panel chart-card">
      <div className="chart-card-header">
        <h3>{title}</h3>
        <button className="ghost-button" onClick={onExpand}>Open</button>
      </div>
      {children}
    </section>
  );
}

function EmptyChartState({ label }) {
  return <div className="empty-chart-state">{label}</div>;
}

function TransactionTable({ transactions, onDelete, compact = false, busyId = null }) {
  return (
    <div className={`table-shell ${compact ? "compact" : ""}`}>
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Merchant</th>
            <th>Amount</th>
            <th>Category</th>
            <th>Source</th>
            <th>Type</th>
            {onDelete && <th />}
          </tr>
        </thead>
        <tbody>
          {transactions.map((tx) => (
            <tr key={tx.id}>
              <td>{tx.date.slice(0, 10)}</td>
              <td>{tx.merchant}</td>
              <td>{formatAmount(tx.amount, tx.currency)}</td>
              <td>{tx.category}</td>
              <td>{tx.source}</td>
              <td>{tx.type}</td>
              {onDelete && (
                <td>
                  <button
                    className={`ghost-button ${busyId === tx.id ? "is-busy" : ""}`}
                    onClick={() => onDelete(tx.id)}
                    disabled={busyId === tx.id}
                  >
                    {busyId === tx.id ? "Deleting..." : "Delete"}
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

function chartTitle(activeChart) {
  const titles = {
    category: "Spend by category",
    merchant: "Top merchants",
    day: "Day-wise spend",
    running: "Running total",
  };
  return titles[activeChart];
}

function renderExpandedChart(activeChart, chartCategoryData, chartMerchantData, dayTotals, runningTotal, theme, chartAxisColor, chartGridColor, chartTooltipStyle, chartTooltipLabelStyle, chartTooltipItemStyle) {
  if (activeChart === "category") {
    return (
      <ResponsiveContainer width="100%" height={520}>
        <PieChart>
          <Pie data={chartCategoryData} dataKey="total" nameKey="category" innerRadius={100} outerRadius={160}>
            {chartCategoryData.map((_, index) => (
              <Cell key={index} fill={COLORS[index % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip contentStyle={chartTooltipStyle} labelStyle={chartTooltipLabelStyle} itemStyle={chartTooltipItemStyle} />
        </PieChart>
      </ResponsiveContainer>
    );
  }
  if (activeChart === "merchant") {
    return (
      <ResponsiveContainer width="100%" height={520}>
        <BarChart data={chartMerchantData} layout="vertical">
          <XAxis type="number" tick={{ fill: chartAxisColor, fontSize: 12 }} axisLine={{ stroke: chartGridColor }} tickLine={{ stroke: chartGridColor }} />
          <YAxis dataKey="merchant" type="category" width={180} tick={{ fill: chartAxisColor, fontSize: 13 }} axisLine={{ stroke: chartGridColor }} tickLine={{ stroke: chartGridColor }} />
          <Tooltip contentStyle={chartTooltipStyle} labelStyle={chartTooltipLabelStyle} itemStyle={chartTooltipItemStyle} />
          <Bar dataKey="total" fill="var(--emerald-text)" radius={[0, 10, 10, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }
  if (activeChart === "day") {
    return (
      <ResponsiveContainer width="100%" height={520}>
        <BarChart data={dayTotals}>
          <XAxis dataKey="date" tick={{ fill: chartAxisColor, fontSize: 12 }} axisLine={{ stroke: chartGridColor }} tickLine={{ stroke: chartGridColor }} />
          <YAxis tick={{ fill: chartAxisColor, fontSize: 12 }} axisLine={{ stroke: chartGridColor }} tickLine={{ stroke: chartGridColor }} />
          <Tooltip contentStyle={chartTooltipStyle} labelStyle={chartTooltipLabelStyle} itemStyle={chartTooltipItemStyle} />
          <Bar dataKey="total" fill="var(--emerald-text)" radius={[10, 10, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={520}>
      <LineChart data={runningTotal}>
        <XAxis dataKey="date" tick={{ fill: chartAxisColor, fontSize: 12 }} axisLine={{ stroke: chartGridColor }} tickLine={{ stroke: chartGridColor }} />
        <YAxis tick={{ fill: chartAxisColor, fontSize: 12 }} axisLine={{ stroke: chartGridColor }} tickLine={{ stroke: chartGridColor }} />
        <Tooltip contentStyle={chartTooltipStyle} labelStyle={chartTooltipLabelStyle} itemStyle={chartTooltipItemStyle} />
        <Line dataKey="total" stroke="var(--emerald-text)" strokeWidth={3} dot />
      </LineChart>
    </ResponsiveContainer>
  );
}

export default App;

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import client from "../api/client.js";

function CountUp({ value, decimals = 0 }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    const numeric = typeof value === "number" ? value : parseFloat(value);
    if (isNaN(numeric)) { setDisplay(value); return; }
    let frame;
    const start = performance.now();
    const duration = 700;
    function tick(now) {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(numeric * eased);
      if (progress < 1) frame = requestAnimationFrame(tick);
      else setDisplay(numeric);
    }
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  if (typeof display !== "number") return display;
  return display.toLocaleString(undefined, { maximumFractionDigits: decimals });
}

const gridFade = {
  hidden: {},
  show: { transition: { staggerChildren: 0.05 } },
};
const cell = {
  hidden: { opacity: 0, scale: 0.9 },
  show: { opacity: 1, scale: 1 },
};

export function ProfileCard({ profile }) {
  const rows = [
    ["Rows", profile.rows], ["Columns", profile.columns], ["Numeric", profile.numeric_columns],
    ["Categorical", profile.categorical_columns], ["Date", profile.date_columns], ["Boolean", profile.boolean_columns],
    ["Memory Usage", `${profile.memory_usage_mb} MB`], ["Missing Values", `${profile.missing_values_pct}%`],
    ["Duplicates", `${profile.duplicates_pct}%`], ["Outliers Found", profile.outliers_found],
    ["Recommended Target", profile.recommended_target_column || "N/A"], ["Confidence", `${profile.target_confidence_pct}%`],
  ];
  return (
    <div className="glass-panel p-6">
      <h3 className="font-medium mb-4 text-slate-800">Dataset Summary</h3>
      <motion.div variants={gridFade} initial="hidden" animate="show" className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {rows.map(([label, value]) => (
          <motion.div key={label} variants={cell} whileHover={{ y: -2 }} className="glass rounded-xl p-3">
            <p className="text-xs text-slate-400">{label}</p>
            <p className="text-lg text-slate-800 font-medium">{value}</p>
          </motion.div>
        ))}
      </motion.div>
    </div>
  );
}

export function CleaningReport({ report }) {
  const rows = [
    ["Duplicates Removed", report.duplicates_removed], ["Missing Values Filled", report.missing_values_filled],
    ["Dates Corrected", report.dates_corrected], ["Categories Standardized", report.categories_standardized],
    ["Text Columns Normalized", report.text_columns_normalized], ["Rows After Cleaning", report.rows_after_cleaning],
    ["Columns After Cleaning", report.columns_after_cleaning],
  ];
  return (
    <div className="glass-panel p-6">
      <h3 className="font-medium mb-4 text-emerald-600">Cleaning Report</h3>
      <motion.div variants={gridFade} initial="hidden" animate="show" className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {rows.map(([label, value]) => (
          <motion.div key={label} variants={cell} whileHover={{ y: -2 }} className="glass rounded-xl p-3">
            <p className="text-xs text-slate-400">{label}</p>
            <p className="text-lg text-slate-800 font-medium"><CountUp value={value} /></p>
          </motion.div>
        ))}
      </motion.div>
    </div>
  );
}

export function DashboardCharts({ data }) {
  return (
    <div className="glass-panel p-6 space-y-6">
      <h3 className="font-medium text-sky-600">Auto-Generated Dashboard</h3>
      <motion.div variants={gridFade} initial="hidden" animate="show" className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {data.kpis.map((k) => (
          <motion.div key={k.label} variants={cell} whileHover={{ y: -2 }} className="glass rounded-xl p-4">
            <p className="text-xs text-slate-400">{k.label}</p>
            <p className="text-xl font-semibold text-slate-800"><CountUp value={k.value} decimals={2} /></p>
          </motion.div>
        ))}
      </motion.div>

      {data.time_series.length > 0 && (
        <div>
          <p className="text-sm text-slate-500 mb-2">{data.target_column} over time</p>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={data.time_series}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.08)" />
              <XAxis dataKey="period" tick={{ fill: "#64748b", fontSize: 12 }} />
              <YAxis tick={{ fill: "#64748b", fontSize: 12 }} />
              <Tooltip contentStyle={{ background: "#ffffff", border: "1px solid rgba(0,0,0,0.08)", borderRadius: 12 }} />
              <Line type="monotone" dataKey="value" stroke="#818cf8" strokeWidth={2.5} dot={false} animationDuration={800} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="grid sm:grid-cols-2 gap-6">
        {data.category_breakdown.length > 0 && (
          <div>
            <p className="text-sm text-slate-500 mb-2">Top {data.category_column} values</p>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={data.category_breakdown}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.08)" />
                <XAxis dataKey="category" tick={{ fill: "#64748b", fontSize: 10 }} />
                <YAxis tick={{ fill: "#64748b", fontSize: 12 }} />
                <Tooltip contentStyle={{ background: "#ffffff", border: "1px solid rgba(0,0,0,0.08)", borderRadius: 12 }} />
                <Bar dataKey="count" fill="#22d3ee" radius={[6, 6, 0, 0]} animationDuration={800} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
        {data.histogram.length > 0 && (
          <div>
            <p className="text-sm text-slate-500 mb-2">{data.target_column} distribution</p>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={data.histogram}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.08)" />
                <XAxis dataKey="bin" tick={{ fill: "#64748b", fontSize: 9 }} />
                <YAxis tick={{ fill: "#64748b", fontSize: 12 }} />
                <Tooltip contentStyle={{ background: "#ffffff", border: "1px solid rgba(0,0,0,0.08)", borderRadius: 12 }} />
                <Bar dataKey="count" fill="#a78bfa" radius={[6, 6, 0, 0]} animationDuration={800} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}

export function MLReport({ report }) {
  return (
    <div className="glass-panel p-6">
      <h3 className="font-medium text-amber-600 mb-1">
        Machine Learning Engine: {report.task_type} on "{report.target_column}"
      </h3>
      <p className="text-xs text-slate-400 mb-4">Trained on {report.rows_used} rows · {report.features_used.length} features</p>
      <motion.div variants={gridFade} initial="hidden" animate="show" className="space-y-2">
        {report.results.map((r) => (
          <motion.div
            key={r.model}
            variants={cell}
            whileHover={{ x: 2 }}
            className={`flex justify-between items-center rounded-xl px-4 py-3 ${r.model === report.best_model ? "glass border-amber-400/60" : "glass"}`}
          >
            <div>
              <p className="font-medium text-slate-800">
                {r.model} {r.model === report.best_model && <span className="text-amber-500 text-xs">★ Best</span>}
              </p>
              <p className="text-xs text-slate-400">Trained in {r.training_time_sec}s</p>
            </div>
            <div className="flex gap-4 text-sm">
              {Object.entries(r.metrics).map(([k, v]) => (
                <div key={k} className="text-right">
                  <p className="text-xs text-slate-400 uppercase">{k}</p>
                  <p className="text-slate-800 font-medium">{v}</p>
                </div>
              ))}
            </div>
          </motion.div>
        ))}
      </motion.div>
    </div>
  );
}

export function ExplainReport({ report }) {
  const max = Math.max(...report.feature_importance.map((f) => f.importance_pct), 1);
  return (
    <div className="glass-panel p-6">
      <h3 className="font-medium text-fuchsia-600 mb-4">Explainable AI: why "{report.target_column}" happens</h3>
      <div className="space-y-3">
        {report.feature_importance.map((f, i) => (
          <div key={f.feature}>
            <div className="flex justify-between text-sm mb-1">
              <span className="text-slate-700">{f.feature}</span>
              <span className="text-slate-400">{f.importance_pct}%</span>
            </div>
            <div className="w-full bg-slate-200/70 rounded-full h-2 overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${(f.importance_pct / max) * 100}%` }}
                transition={{ duration: 0.8, delay: i * 0.05, ease: "easeOut" }}
                className="bg-gradient-to-r from-fuchsia-500 to-violet-500 h-2 rounded-full"
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function AgentReport({ steps }) {
  return (
    <div className="glass-panel p-6">
      <h3 className="font-medium text-violet-600 mb-4">Guided Analysis: full pipeline</h3>
      <motion.div variants={gridFade} initial="hidden" animate="show" className="space-y-2">
        {steps.map((s, i) => (
          <motion.div key={i} variants={cell} className="glass rounded-xl px-4 py-3">
            <div className="flex justify-between items-center">
              <p className="font-medium text-slate-800">{i + 1}. {s.step}</p>
              <span className={`text-xs px-2 py-0.5 rounded-full ${s.status === "done" ? "bg-emerald-100 text-emerald-600" : "bg-slate-100 text-slate-400"}`}>
                {s.status}
              </span>
            </div>
            {s.step === "Notify user" && (
              <div className="mt-2 text-sm text-slate-600 space-y-1">
                <p>Target column: {s.result.target_column || "N/A"}</p>
                <p>Best model: {s.result.best_model || "N/A"}</p>
                <p>Top driving feature: {s.result.top_feature || "N/A"}</p>
                <p>Rows after cleaning: {s.result.rows_cleaned}</p>
              </div>
            )}
          </motion.div>
        ))}
      </motion.div>
    </div>
  );
}

export function ChatPanel({ datasetId }) {
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");

  async function handleAsk(e) {
    e.preventDefault();
    if (!question.trim()) return;
    const q = question;
    setMessages((m) => [...m, { role: "user", text: q }]);
    setQuestion("");
    setAsking(true);
    setError("");
    try {
      const res = await client.post(`/datasets/${datasetId}/chat`, { question: q });
      setMessages((m) => [...m, { role: "ai", text: res.data.answer }]);
    } catch (err) {
      setError(err?.response?.data?.detail || "Chat failed");
    } finally {
      setAsking(false);
    }
  }

  const suggestions = ["Summarize this dataset", "What stands out in this data?", "Which columns matter most?", "Any data quality issues?"];

  return (
    <div className="glass-panel p-6">
      <h3 className="font-medium text-teal-600 mb-4">AI Copilot</h3>
      <div className="space-y-3 mb-4 max-h-80 overflow-y-auto">
        {messages.length === 0 && (
          <div className="flex flex-wrap gap-2">
            {suggestions.map((s) => (
              <button key={s} onClick={() => setQuestion(s)} className="glass glass-hover text-xs text-slate-600 rounded-full px-3 py-1.5">
                {s}
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className={`rounded-xl px-4 py-2.5 text-sm max-w-[85%] ${m.role === "user" ? "bg-teal-100 ml-auto text-slate-800" : "glass text-slate-700"}`}
          >
            {m.text}
          </motion.div>
        ))}
        {asking && (
          <div className="glass rounded-xl px-4 py-2.5 text-sm w-16 flex gap-1">
            {[0, 1, 2].map((i) => (
              <motion.span key={i} className="w-1.5 h-1.5 rounded-full bg-teal-400" animate={{ y: [0, -4, 0] }} transition={{ repeat: Infinity, duration: 0.6, delay: i * 0.15 }} />
            ))}
          </div>
        )}
      </div>
      {error && <p className="text-red-500 text-sm mb-2">{error}</p>}
      <form onSubmit={handleAsk} className="flex gap-2">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="What would you like to know?"
          className="flex-1 rounded-xl bg-white/70 border border-white/80 px-4 py-2.5 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-400/50"
        />
        <motion.button whileTap={{ scale: 0.96 }} type="submit" disabled={asking} className="rounded-xl bg-teal-500 hover:bg-teal-400 transition px-5 py-2.5 text-sm font-medium text-white shadow-lg shadow-teal-500/30">
          Ask
        </motion.button>
      </form>
    </div>
  );
}

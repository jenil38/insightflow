/**
 * The scroll-storytelling centrepiece.
 *
 * A tall outer section holds a `sticky` viewport-height panel. As the user
 * scrolls the section's length, `useScrollSteps` converts scroll progress into a
 * discrete active stage, and the right-hand panel swaps its visual to match.
 * The effect: the page appears to hold still while the product walks itself
 * through its own pipeline.
 *
 * Each stage's visual is a small hand-built mock rather than a screenshot, so it
 * stays crisp at any size, themes correctly, and cannot go stale.
 */
import { AnimatePresence, motion, useReducedMotion, useTransform } from "framer-motion";
import { BarChart3, Brain, Lightbulb, Sparkles, Table2, Wand2 } from "lucide-react";

import { useScrollSteps } from "../../components/scroll/index.jsx";

const STAGES = [
  {
    icon: Table2,
    title: "Upload and explore",
    body: "Drop in a CSV, Excel workbook, or JSON file. Browse it a page at a time with sorting, search, and per-column statistics. The whole file never has to reach your browser.",
    visual: UploadVisual,
  },
  {
    icon: Sparkles,
    title: "Profile every column",
    body: "Types are inferred, not assumed. You get distributions, missing-value counts, outliers by the 1.5×IQR rule, correlations, and ranked target suggestions that each state their reasoning.",
    visual: ProfileVisual,
  },
  {
    icon: Wand2,
    title: "Clean, reversibly",
    body: "Choose exactly what happens: duplicates, whitespace, dates, imputation strategy, outlier treatment. Preview the effect before applying, and revert to the original file at any time.",
    visual: CleanVisual,
  },
  {
    icon: BarChart3,
    title: "Build the dashboard",
    body: "Pick a measure, aggregation, dimension, and time grain. Combinations that would mislead (a pie chart over forty categories, a sum over a text column) are refused with a reason.",
    visual: AnalyticsVisual,
  },
  {
    icon: Brain,
    title: "Train and compare",
    body: "Twelve candidate models run with cross-validation and light hyperparameter tuning. One failing estimator is skipped, not fatal. Every run is versioned and downloadable.",
    visual: ModelsVisual,
  },
  {
    icon: Lightbulb,
    title: "Understand the result",
    body: "SHAP where the model supports it, and a clearly labelled fallback where it does not. The method used is always stated, and correlation is never dressed up as causation.",
    visual: ExplainVisual,
  },
];

export default function PipelineSection() {
  const [ref, active, progress] = useScrollSteps(STAGES.length);
  const reduced = useReducedMotion();
  const lineScale = useTransform(progress, [0.05, 0.95], [0, 1]);

  return (
    <section id="pipeline" ref={ref} className="relative h-[500vh]">
      <div className="sticky top-0 flex h-screen items-center overflow-hidden">
        <div className="mx-auto w-full max-w-7xl px-6 py-16">
          <div className="grid items-center gap-10 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
            {/* ---------------------------------------------- stage list */}
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.2em] text-accent">
                The workflow
              </p>
              <h2 className="mt-3 text-display-sm font-semibold text-ink sm:text-display-md">
                Six steps, one place
              </h2>
              <p className="mt-3 max-w-md text-lg text-muted">
                Raw file to defensible answer, without leaving the browser or stitching tools
                together.
              </p>

              <ol className="relative mt-8">
                {/* Track + scroll-linked fill. */}
                <span
                  aria-hidden="true"
                  className="absolute left-[15px] top-2 h-[calc(100%-1rem)] w-0.5 bg-line"
                />
                <motion.span
                  aria-hidden="true"
                  className="absolute left-[15px] top-2 w-0.5 origin-top bg-accent"
                  style={{
                    height: "calc(100% - 1rem)",
                    scaleY: reduced ? 1 : lineScale,
                  }}
                />

                {STAGES.map((stage, index) => {
                  const isActive = index === active;
                  const isDone = index < active;
                  return (
                    <li key={stage.title} className="relative flex gap-4 pb-4 last:pb-0">
                      <span
                        className={`relative z-10 mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full border-2 transition-colors duration-500 ${
                          isActive
                            ? "border-accent bg-accent text-accent-contrast"
                            : isDone
                              ? "border-accent bg-accent/10 text-accent"
                              : "border-line/50 glass-chip text-subtle"
                        }`}
                      >
                        <stage.icon size={15} aria-hidden="true" />
                      </span>

                      <div className="min-w-0 pt-1">
                        <h3
                          className={`text-lg font-medium transition-colors duration-500 ${
                            isActive ? "text-ink" : "text-subtle"
                          }`}
                        >
                          {stage.title}
                        </h3>
                        {/* Only the active stage's copy is shown, so the column
                            stays readable instead of becoming a wall of text. */}
                        <AnimatePresence initial={false}>
                          {isActive && (
                            <motion.p
                              key="body"
                              initial={reduced ? false : { opacity: 0, height: 0 }}
                              animate={{ opacity: 1, height: "auto" }}
                              exit={reduced ? undefined : { opacity: 0, height: 0 }}
                              transition={{ duration: 0.35, ease: "easeOut" }}
                              className="overflow-hidden text-base leading-relaxed text-muted"
                            >
                              <span className="block pt-1.5">{stage.body}</span>
                            </motion.p>
                          )}
                        </AnimatePresence>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </div>

            {/* ------------------------------------------------- visual */}
            <div className="relative">
              <div className="glass glass-strong glass-glow relative aspect-[4/3] w-full overflow-hidden rounded-2xl">
                {/* Fake window chrome grounds the mock as "the product". */}
                <div className="flex items-center gap-1.5 border-b border-line/40 px-4 py-3">
                  {["bg-danger/50", "bg-warning/50", "bg-success/50"].map((dot) => (
                    <span key={dot} className={`h-2.5 w-2.5 rounded-full ${dot}`} />
                  ))}
                  <span className="ml-3 truncate text-xs text-subtle">
                    insightflow · {STAGES[active].title.toLowerCase()}
                  </span>
                </div>

                <div className="relative h-[calc(100%-2.75rem)] p-5">
                  <AnimatePresence mode="wait">
                    <motion.div
                      key={active}
                      initial={reduced ? false : { opacity: 0, y: 14 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={reduced ? undefined : { opacity: 0, y: -14 }}
                      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
                      className="h-full"
                    >
                      {(() => {
                        const Visual = STAGES[active].visual;
                        return <Visual />;
                      })()}
                    </motion.div>
                  </AnimatePresence>
                </div>
              </div>

              {/* Step counter, so position in the story is always clear. */}
              <div className="mt-4 flex items-center justify-center gap-2" aria-hidden="true">
                {STAGES.map((stage, index) => (
                  <span
                    key={stage.title}
                    className={`h-1 rounded-full transition-all duration-500 ${
                      index === active ? "w-8 bg-accent" : "w-4 bg-line"
                    }`}
                  />
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ visuals */

const SAMPLE_ROWS = [
  ["acme", "north", "412.50", "2024-01-05"],
  ["globex", "south", "1,208.00", "2024-02-11"],
  ["initech", "north", "310.25", "2024-03-01"],
  ["umbrella", "east", "90.00", "2024-04-14"],
  ["stark", "west", "2,505.75", "2024-05-09"],
];

function VisualFrame({ label, children }) {
  return (
    <div className="flex h-full flex-col">
      <p className="mb-3 shrink-0 text-xs font-medium uppercase tracking-wider text-subtle">
        {label}
      </p>
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  );
}

function UploadVisual() {
  return (
    <VisualFrame label="Data explorer · 5 of 1,284 rows">
      <div className="overflow-hidden rounded-lg border border-line/50">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-line/50 text-left">
              {["customer", "region", "revenue", "signup"].map((head) => (
                <th key={head} className="px-3 py-2 font-medium text-muted">
                  {head}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {SAMPLE_ROWS.map((row, rowIndex) => (
              <motion.tr
                key={row[0]}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: rowIndex * 0.07, duration: 0.3 }}
                className="border-b border-line/60 last:border-0"
              >
                {row.map((cell, cellIndex) => (
                  <td
                    key={cellIndex}
                    className={`px-3 py-2 ${
                      cellIndex === 2 ? "text-right font-mono tabular-nums text-ink" : "text-muted"
                    }`}
                  >
                    {cell}
                  </td>
                ))}
              </motion.tr>
            ))}
          </tbody>
        </table>
      </div>
    </VisualFrame>
  );
}

function ProfileVisual() {
  const columns = [
    { name: "revenue", type: "numeric", fill: 100, tone: "bg-chart-1" },
    { name: "region", type: "categorical", fill: 100, tone: "bg-chart-2" },
    { name: "signup", type: "datetime", fill: 94, tone: "bg-chart-5" },
    { name: "notes", type: "text", fill: 41, tone: "bg-chart-3" },
  ];
  return (
    <VisualFrame label="Column profile · types inferred">
      <div className="space-y-3">
        {columns.map((column, index) => (
          <motion.div
            key={column.name}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.08, duration: 0.35 }}
          >
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <span className="truncate font-mono text-xs text-ink">{column.name}</span>
              <span className="glass-chip shrink-0 rounded px-1.5 py-0.5 text-2xs uppercase tracking-wide text-subtle">
                {column.type}
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-line">
              <motion.div
                className={`h-full origin-left rounded-full ${column.tone}`}
                initial={{ scaleX: 0 }}
                animate={{ scaleX: column.fill / 100 }}
                transition={{ delay: 0.15 + index * 0.08, duration: 0.6, ease: "easeOut" }}
              />
            </div>
            <p className="mt-1 text-2xs text-subtle">{column.fill}% populated</p>
          </motion.div>
        ))}
      </div>
    </VisualFrame>
  );
}

function CleanVisual() {
  const changes = [
    { label: "Duplicate rows removed", value: "18" },
    { label: "Whitespace trimmed", value: "244" },
    { label: "Dates parsed to ISO", value: "1,190" },
    { label: "Missing values imputed", value: "63" },
  ];
  return (
    <VisualFrame label="Cleaning preview · nothing written yet">
      <div className="space-y-2">
        {changes.map((change, index) => (
          <motion.div
            key={change.label}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: index * 0.08, duration: 0.3 }}
            className="glass-chip flex items-center justify-between gap-3 rounded-lg px-3 py-2.5"
          >
            <span className="truncate text-xs text-muted">{change.label}</span>
            <span className="shrink-0 font-mono text-xs font-medium text-success">
              +{change.value}
            </span>
          </motion.div>
        ))}
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.45 }}
          className="pt-1 text-2xs leading-relaxed text-subtle"
        >
          Applying writes a separate cleaned file. The original upload is never modified, so
          reverting is always available.
        </motion.p>
      </div>
    </VisualFrame>
  );
}

function AnalyticsVisual() {
  const bars = [62, 88, 45, 96, 71, 54, 80];
  return (
    <VisualFrame label="Revenue by month · sum">
      <div className="flex h-full flex-col">
        <div className="flex min-h-0 flex-1 items-end gap-2">
          {bars.map((height, index) => (
            <motion.div
              key={index}
              className="flex-1 rounded-t bg-gradient-to-t from-accent/60 to-accent"
              initial={{ height: 0 }}
              animate={{ height: `${height}%` }}
              transition={{ delay: index * 0.06, duration: 0.5, ease: "easeOut" }}
            />
          ))}
        </div>
        <div className="mt-2 flex shrink-0 justify-between text-2xs text-subtle">
          {["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"].map((month) => (
            <span key={month}>{month}</span>
          ))}
        </div>
      </div>
    </VisualFrame>
  );
}

function ModelsVisual() {
  const models = [
    { name: "Gradient Boosting", score: 0.94, best: true },
    { name: "XGBoost", score: 0.93, best: false },
    { name: "Random Forest", score: 0.91, best: false },
    { name: "Extra Trees", score: 0.88, best: false },
    { name: "Linear Regression", score: 0.79, best: false },
  ];
  return (
    <VisualFrame label="Leaderboard · R² on held-out split">
      <div className="space-y-2">
        {models.map((model, index) => (
          <motion.div
            key={model.name}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: index * 0.07, duration: 0.3 }}
            className={`rounded-lg border px-3 py-2 ${
              model.best ? "border-accent/50 bg-accent/10" : "border-line/50 glass-subtle"
            }`}
          >
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1.5">
                <span className="truncate text-xs text-ink">{model.name}</span>
                {model.best && (
                  <span className="shrink-0 rounded bg-accent px-1.5 py-0.5 text-2xs font-medium text-accent-contrast">
                    best
                  </span>
                )}
              </span>
              <span className="shrink-0 font-mono text-xs tabular-nums text-muted">
                {model.score.toFixed(2)}
              </span>
            </div>
            <div className="h-1 overflow-hidden rounded-full bg-line">
              <motion.div
                className={`h-full origin-left rounded-full ${model.best ? "bg-accent" : "bg-line-strong"}`}
                initial={{ scaleX: 0 }}
                animate={{ scaleX: model.score }}
                transition={{ delay: 0.1 + index * 0.07, duration: 0.6, ease: "easeOut" }}
              />
            </div>
          </motion.div>
        ))}
      </div>
    </VisualFrame>
  );
}

function ExplainVisual() {
  const features = [
    { name: "spend", pct: 63 },
    { name: "visits", pct: 24 },
    { name: "region", pct: 9 },
    { name: "tenure", pct: 4 },
  ];
  return (
    <VisualFrame label="Feature importance">
      <div className="flex h-full flex-col">
        <motion.span
          initial={{ opacity: 0, scale: 0.94 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.3 }}
          className="mb-3 inline-flex w-fit items-center gap-1.5 rounded-full border border-success/40 bg-success-soft px-2.5 py-1 text-2xs font-medium text-success"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-success" />
          Method: SHAP (exact, tree model)
        </motion.span>

        <div className="min-h-0 flex-1 space-y-2.5">
          {features.map((feature, index) => (
            <motion.div
              key={feature.name}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: index * 0.07 }}
            >
              <div className="mb-1 flex justify-between text-xs">
                <span className="font-mono text-ink">{feature.name}</span>
                <span className="tabular-nums text-muted">{feature.pct}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-line">
                <motion.div
                  className="h-full origin-left rounded-full bg-gradient-to-r from-accent to-chart-4"
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: feature.pct / 100 }}
                  transition={{ delay: 0.1 + index * 0.07, duration: 0.7, ease: "easeOut" }}
                />
              </div>
            </motion.div>
          ))}
        </div>

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5 }}
          className="shrink-0 pt-2 text-2xs leading-relaxed text-subtle"
        >
          Importance shows association, not causation.
        </motion.p>
      </div>
    </VisualFrame>
  );
}

/**
 * Explainability section.
 *
 * The interactive bit is the point: switching the model changes the stated
 * method, because SHAP genuinely cannot explain every estimator. The product
 * reports which method produced the numbers instead of claiming SHAP for
 * everything, and this section demonstrates that rather than asserting it.
 */
import { useState } from "react";
import { motion } from "framer-motion";
import { Info, ShieldCheck, TriangleAlert } from "lucide-react";

import { CountUp, GrowBar, Reveal } from "../../components/scroll/index.jsx";

const MODELS = [
  {
    id: "gbm",
    label: "Gradient Boosting",
    method: "shap",
    methodLabel: "SHAP (Shapley additive explanations)",
    fallback: false,
    reason: null,
    features: [
      { feature: "spend", pct: 59.2 },
      { feature: "visits", pct: 39.3 },
      { feature: "region", pct: 0.9 },
      { feature: "noise", pct: 0.6 },
    ],
  },
  {
    id: "linear",
    label: "Linear Regression",
    method: "coefficients",
    methodLabel: "Linear coefficients (standardised by feature spread)",
    fallback: true,
    reason: "SHAP does not support this model type (InvalidModelError)",
    features: [
      { feature: "spend", pct: 63.3 },
      { feature: "visits", pct: 36.2 },
      { feature: "noise", pct: 0.5 },
    ],
  },
  {
    id: "knn",
    label: "K-Nearest Neighbours",
    method: "permutation_importance",
    methodLabel: "Permutation importance (model-agnostic)",
    fallback: true,
    reason: "SHAP does not support this model type (InvalidModelError)",
    features: [
      { feature: "spend", pct: 69.8 },
      { feature: "visits", pct: 27.8 },
      { feature: "noise", pct: 1.3 },
      { feature: "region", pct: 1.1 },
    ],
  },
];

export default function ExplainSection() {
  const [activeId, setActiveId] = useState(MODELS[0].id);
  const active = MODELS.find((m) => m.id === activeId) ?? MODELS[0];

  return (
    <section
      id="explainability"
      className="relative border-t border-line/60 py-24 sm:py-32"
    >
      <div className="mx-auto max-w-6xl px-6">
        <Reveal className="mx-auto max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">
            Explainability
          </p>
          <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
            It tells you which method it used.
          </h2>
          <p className="mt-4 text-base leading-relaxed text-muted">
            SHAP cannot explain every model. Most tools quietly fall back to something else and
            keep the SHAP label. Switch models below and watch the method change.
          </p>
        </Reveal>

        <Reveal delay={0.1}>
          <div
            role="tablist"
            aria-label="Model to explain"
            className="mt-10 flex flex-wrap justify-center gap-2"
          >
            {MODELS.map((model) => {
              const selected = model.id === activeId;
              return (
                <button
                  key={model.id}
                  role="tab"
                  type="button"
                  aria-selected={selected}
                  onClick={() => setActiveId(model.id)}
                  className={`relative rounded-full px-4 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-canvas ${
                    selected ? "text-accent-contrast" : "text-muted hover:text-ink"
                  }`}
                >
                  {selected && (
                    <motion.span
                      layoutId="explain-model-pill"
                      className="absolute inset-0 rounded-full bg-accent"
                      transition={{ type: "spring", stiffness: 380, damping: 30 }}
                    />
                  )}
                  <span className="relative z-10">{model.label}</span>
                </button>
              );
            })}
          </div>
        </Reveal>

        <Reveal delay={0.15}>
          <div className="glass glass-glow mx-auto mt-8 max-w-3xl overflow-hidden rounded-2xl">
            {/* ----------------------------------------- method disclosure */}
            <div className="border-b border-line/40 px-5 py-4">
              {/* No AnimatePresence here on purpose. Exit choreography would tie
                  the disclosure to an animation completing, and in a section
                  about reporting the method honestly the badge must never lag
                  the selected model. Changing `key` remounts immediately and the
                  new panel just fades in. */}
              <div>
                <motion.div
                  key={active.id}
                  initial={{ opacity: 0, y: -6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.22 }}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-semibold ${
                        active.fallback
                          ? "border-warning/25 bg-warning/10 text-warning"
                          : "border-success/25 bg-success/10 text-success"
                      }`}
                    >
                      {active.fallback ? (
                        <TriangleAlert size={12} aria-hidden="true" />
                      ) : (
                        <ShieldCheck size={12} aria-hidden="true" />
                      )}
                      {active.fallback ? "Fallback used" : "SHAP available"}
                    </span>
                    <code className="font-mono text-xs text-muted">
                      method: &ldquo;{active.method}&rdquo;
                    </code>
                  </div>
                  <p className="mt-2 text-sm text-ink">{active.methodLabel}</p>
                  {active.reason && (
                    <p className="mt-1 flex items-start gap-1.5 text-xs text-muted">
                      <Info size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
                      {active.reason}
                    </p>
                  )}
                </motion.div>
              </div>
            </div>

            {/* --------------------------------------------- importances */}
            <div className="px-5 py-5">
              <p className="mb-4 text-xs font-medium uppercase tracking-wide text-subtle">
                Feature importance · predicting revenue
              </p>
              <motion.ul
                key={active.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.2 }}
                className="space-y-3.5"
              >
                {active.features.map((row, index) => (
                  <li key={row.feature}>
                    <div className="flex items-baseline justify-between">
                      <span className="font-mono text-sm text-ink">{row.feature}</span>
                      <span className="text-sm font-semibold tabular-nums text-ink">
                        <CountUp value={row.pct} decimals={1} suffix="%" duration={800} />
                      </span>
                    </div>
                    <GrowBar pct={row.pct} delay={index * 0.06} className="mt-1.5" />
                  </li>
                ))}
              </motion.ul>
            </div>

            <div className="border-t border-line/40 px-5 py-3">
              <p className="text-xs leading-relaxed text-muted">
                Importance is statistical association, not causation. Correlated features share
                credit, so a real driver can rank low when a near-duplicate column absorbs its
                contribution — the API returns these caveats with every explanation.
              </p>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

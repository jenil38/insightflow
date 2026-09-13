/**
 * AutoML leaderboard section.
 *
 * Rows animate in ranked order and their score bars grow on scroll, so the
 * leaderboard visibly "settles" into its ranking. The metrics shown are the
 * real ones the API returns for a regression run (R², RMSE, MAE), including
 * the cross-validated column, which is the figure that actually matters.
 */
import { motion } from "framer-motion";
import { Crown, Download, GitBranch, Settings2 } from "lucide-react";

import { CountUp, GrowBar, Parallax, Reveal } from "../../components/scroll/index.jsx";

const LEADERBOARD = [
  { model: "Gradient Boosting", score: 0.9812, cv: 0.9744, time: 1.42, tuned: true },
  { model: "Random Forest", score: 0.9789, cv: 0.9721, time: 0.98, tuned: true },
  { model: "Extra Trees", score: 0.9764, cv: 0.9698, time: 0.71, tuned: false },
  { model: "LightGBM", score: 0.9702, cv: 0.9655, time: 0.44, tuned: false },
  { model: "XGBoost", score: 0.9688, cv: 0.9641, time: 0.52, tuned: false },
  { model: "Linear Regression", score: 0.9412, cv: 0.9388, time: 0.02, tuned: false },
  { model: "KNN", score: 0.8934, cv: 0.8801, time: 0.09, tuned: false },
  { model: "Decision Tree", score: 0.8712, cv: 0.8489, time: 0.06, tuned: false },
];

const CONTROLS = [
  { icon: Settings2, label: "Target column", value: "revenue" },
  { icon: GitBranch, label: "Excluded", value: "row_id" },
  { icon: Crown, label: "Task type", value: "regression" },
];

export default function ModelsSection() {
  const best = LEADERBOARD[0];

  return (
    <section id="models" className="relative border-t border-line py-24 sm:py-32">
      <div className="mx-auto max-w-6xl px-6">
        <div className="grid gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)] lg:items-start">
          {/* ------------------------------------------------------- copy */}
          <div className="lg:sticky lg:top-28">
            <Reveal>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">
                Modelling
              </p>
              <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
                Twelve models, one leaderboard.
              </h2>
              <p className="mt-4 text-base leading-relaxed text-muted">
                Pick the target or let it be recommended, exclude the columns that would leak,
                then compare every candidate on a held-out split <em>and</em> cross-validation.
                One model failing never takes the run down.
              </p>
            </Reveal>

            <Reveal delay={0.1}>
              <dl className="mt-8 space-y-3">
                {CONTROLS.map((control) => (
                  <div
                    key={control.label}
                    className="glass glass-hover flex items-center gap-3 rounded-xl px-3.5 py-2.5"
                  >
                    <control.icon size={15} className="shrink-0 text-muted" aria-hidden="true" />
                    <dt className="text-sm text-muted">{control.label}</dt>
                    <dd className="ml-auto font-mono text-sm font-medium text-ink">
                      {control.value}
                    </dd>
                  </div>
                ))}
              </dl>
            </Reveal>

            <Reveal delay={0.2}>
              <div className="mt-6 flex items-center gap-2 text-sm text-muted">
                <Download size={15} aria-hidden="true" />
                Every run is versioned and the winner is downloadable as a{" "}
                <code className="font-mono text-xs text-ink">.joblib</code> pipeline.
              </div>
            </Reveal>
          </div>

          {/* ------------------------------------------------ leaderboard */}
          <Parallax speed={0.06}>
            <Reveal>
              <div className="glass glass-strong sheen glass-glow overflow-hidden rounded-2xl">
                <div className="flex items-center justify-between border-b border-line px-4 py-3">
                  <span className="text-sm font-medium text-ink">Model comparison</span>
                  <span className="glass-chip rounded-full px-2 py-0.5 font-mono text-xs text-muted">
                    R² · higher is better
                  </span>
                </div>

                <div className="divide-y divide-line/40">
                  {LEADERBOARD.map((row, index) => {
                    const isBest = index === 0;
                    return (
                      <Reveal key={row.model} delay={index * 0.05} distance={12}>
                        <div
                          className={`grid grid-cols-[1.6fr_1fr_1fr_auto] items-center gap-3 px-4 py-3 ${
                            isBest ? "bg-accent-soft/40" : ""
                          }`}
                        >
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5">
                              <span className="truncate text-sm font-medium text-ink">
                                {row.model}
                              </span>
                              {isBest && (
                                <motion.span
                                  initial={{ scale: 0, rotate: -20 }}
                                  whileInView={{ scale: 1, rotate: 0 }}
                                  viewport={{ once: true }}
                                  transition={{ delay: 0.4, type: "spring", stiffness: 400, damping: 18 }}
                                  className="inline-flex shrink-0 items-center gap-1 rounded-full bg-accent px-1.5 py-0.5 text-[10px] font-semibold text-accent-contrast"
                                >
                                  <Crown size={9} aria-hidden="true" />
                                  Best
                                </motion.span>
                              )}
                              {row.tuned && (
                                <span className="shrink-0 rounded border border-line px-1 py-0.5 text-[10px] text-subtle">
                                  tuned
                                </span>
                              )}
                            </div>
                            <GrowBar
                              pct={row.score * 100}
                              delay={index * 0.05 + 0.15}
                              height="h-1"
                              className="mt-1.5"
                            />
                          </div>

                          <div className="text-right">
                            <p className="text-[10px] uppercase tracking-wide text-subtle">Test</p>
                            <p className="text-sm font-semibold tabular-nums text-ink">
                              <CountUp value={row.score} decimals={4} duration={900} />
                            </p>
                          </div>

                          <div className="text-right">
                            <p className="text-[10px] uppercase tracking-wide text-subtle">CV</p>
                            <p className="text-sm tabular-nums text-muted">
                              <CountUp value={row.cv} decimals={4} duration={900} />
                            </p>
                          </div>

                          <div className="w-14 text-right">
                            <p className="text-[10px] uppercase tracking-wide text-subtle">Time</p>
                            <p className="text-sm tabular-nums text-muted">{row.time}s</p>
                          </div>
                        </div>
                      </Reveal>
                    );
                  })}
                </div>

                <div className="border-t border-line/40 px-4 py-3">
                  <p className="text-xs text-muted">
                    <span className="font-medium text-ink">{best.model}</span> wins on
                    cross-validated R² of{" "}
                    <span className="font-mono font-medium text-ink">{best.cv}</span>. Saved as
                    version 1 with its full configuration, so the run is reproducible.
                  </p>
                </div>
              </div>
            </Reveal>
          </Parallax>
        </div>
      </div>
    </section>
  );
}

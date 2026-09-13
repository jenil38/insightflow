/**
 * Data-quality section.
 *
 * The dial fills as the section scrolls through the viewport, and each score
 * component grows in turn. The numbers shown are the same weighted formula the
 * backend actually uses (35% completeness, 30% duplicate-freedom, 20% type
 * consistency, 15% uniqueness) rather than decorative figures - the point of
 * the section is that the score is explainable.
 */
import { useRef } from "react";
import { motion, useReducedMotion, useScroll, useTransform } from "framer-motion";
import { AlertTriangle, CheckCircle2, Info } from "lucide-react";

import { CountUp, GrowBar, Reveal } from "../../components/scroll/index.jsx";

const COMPONENTS = [
  { label: "Completeness", weight: 35, score: 96.4, formula: "non-null cells / total cells" },
  { label: "Duplicate-freedom", weight: 30, score: 90.9, formula: "1 - duplicate rows / total rows" },
  { label: "Type consistency", weight: 20, score: 98.2, formula: "share matching each column's dominant type" },
  { label: "Uniqueness", weight: 15, score: 68.2, formula: "distinct / non-null, excluding identifier columns" },
];

const OVERALL = 90.9;

const FINDINGS = [
  { severity: "danger", icon: AlertTriangle, text: "1 column is over 40% empty" },
  { severity: "warning", icon: AlertTriangle, text: "1 duplicate row found" },
  { severity: "info", icon: Info, text: "1 likely identifier column: exclude from training" },
  { severity: "info", icon: Info, text: "1 outlier by the 1.5×IQR rule" },
];

const SEVERITY_STYLES = {
  danger: "text-danger bg-danger/10 border-danger/20",
  warning: "text-warning bg-warning/10 border-warning/20",
  info: "text-muted glass-chip border-transparent",
};

export default function QualitySection() {
  const ref = useRef(null);
  const reduce = useReducedMotion();
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start 0.85", "center 0.55"],
  });

  // The dial is a stroked circle; animating strokeDashoffset from full to the
  // target fraction reads as "filling up" without needing a canvas.
  const CIRCUMFERENCE = 2 * Math.PI * 88;
  const targetOffset = CIRCUMFERENCE * (1 - OVERALL / 100);
  const dashOffset = useTransform(scrollYProgress, [0, 1], [CIRCUMFERENCE, targetOffset]);

  return (
    <section
      ref={ref}
      id="quality"
      className="relative border-t border-line/60 py-24 sm:py-32"
    >
      <div className="mx-auto max-w-6xl px-6">
        <Reveal>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">
            Data quality
          </p>
          <h2 className="mt-3 max-w-2xl text-balance text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
            A score you can actually argue with.
          </h2>
          <p className="mt-4 max-w-2xl text-base leading-relaxed text-muted">
            Every component is a documented formula over observable counts. No opaque
            &ldquo;AI score&rdquo;: the API returns the arithmetic alongside the number, so you can
            check the work.
          </p>
        </Reveal>

        <div className="mt-14 grid items-center gap-12 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
          {/* ---------------------------------------------------------- dial */}
          <Reveal className="flex justify-center lg:justify-start">
            <div className="relative h-[240px] w-[240px]">
              <svg viewBox="0 0 200 200" className="h-full w-full -rotate-90">
                <circle
                  cx="100"
                  cy="100"
                  r="88"
                  fill="none"
                  strokeWidth="12"
                  className="stroke-line"
                />
                <motion.circle
                  cx="100"
                  cy="100"
                  r="88"
                  fill="none"
                  strokeWidth="12"
                  strokeLinecap="round"
                  className="stroke-accent"
                  strokeDasharray={CIRCUMFERENCE}
                  style={{ strokeDashoffset: reduce ? targetOffset : dashOffset }}
                />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <div className="flex items-baseline gap-1">
                  <span className="text-5xl font-semibold tabular-nums tracking-tight text-ink">
                    <CountUp value={OVERALL} decimals={1} />
                  </span>
                  <span className="text-lg font-medium text-muted">/100</span>
                </div>
                <span className="mt-1 inline-flex items-center gap-1.5 rounded-full border border-success/20 bg-success/10 px-2.5 py-0.5 text-xs font-medium text-success">
                  <CheckCircle2 size={12} aria-hidden="true" />
                  Excellent
                </span>
              </div>
            </div>
          </Reveal>

          {/* ------------------------------------------------------ breakdown */}
          <div className="space-y-5">
            {COMPONENTS.map((component, index) => (
              <Reveal key={component.label} delay={index * 0.08}>
                <div>
                  <div className="flex items-baseline justify-between gap-4">
                    <div className="flex items-baseline gap-2">
                      <span className="text-sm font-medium text-ink">{component.label}</span>
                      <span className="text-xs text-subtle">{component.weight}% weight</span>
                    </div>
                    <span className="text-sm font-semibold tabular-nums text-ink">
                      <CountUp value={component.score} decimals={1} />
                    </span>
                  </div>
                  <GrowBar pct={component.score} delay={index * 0.08} className="mt-2" />
                  <p className="mt-1.5 font-mono text-xs text-subtle">{component.formula}</p>
                </div>
              </Reveal>
            ))}

            <Reveal delay={0.3}>
              <div className="glass glass-strong rounded-xl p-4">
                <p className="text-xs font-medium uppercase tracking-wide text-subtle">
                  Findings on this dataset
                </p>
                <ul className="mt-3 space-y-2">
                  {FINDINGS.map((finding) => (
                    <li key={finding.text} className="flex items-start gap-2.5 text-sm">
                      <span
                        className={`mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded border ${SEVERITY_STYLES[finding.severity]}`}
                      >
                        <finding.icon size={11} aria-hidden="true" />
                      </span>
                      <span className="text-muted">{finding.text}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </Reveal>
          </div>
        </div>
      </div>
    </section>
  );
}

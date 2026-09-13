/**
 * Closing CTA and footer.
 *
 * The stat row uses the project's real measured figures (test count, model
 * count, supported formats) rather than invented traction numbers. There are
 * no users to count, and claiming otherwise would be fiction.
 */
import { Link } from "react-router-dom";
import { ArrowRight, Github } from "lucide-react";

import { Aurora, CountUp, Reveal } from "../../components/scroll/index.jsx";

const STATS = [
  { value: 106, suffix: "", label: "Backend tests" },
  { value: 12, suffix: "", label: "Candidate models" },
  { value: 4, suffix: "", label: "File formats" },
  { value: 100, suffix: "%", label: "Ownership-checked routes" },
];

const NAV = [
  { label: "Pipeline", href: "#pipeline" },
  { label: "Data quality", href: "#quality" },
  { label: "Modelling", href: "#models" },
  { label: "Explainability", href: "#explainability" },
  { label: "Copilot", href: "#copilot" },
];

export default function CtaSection() {
  return (
    <>
      <section className="relative overflow-hidden border-t border-line py-24 sm:py-32">
        <Aurora className="opacity-60" />

        <div className="relative mx-auto max-w-4xl px-6 text-center">
          <Reveal>
            <h2 className="text-balance text-3xl font-semibold tracking-tight text-ink sm:text-4xl md:text-5xl">
              Upload a CSV. See the whole picture.
            </h2>
            <p className="mx-auto mt-5 max-w-xl text-base leading-relaxed text-muted sm:text-lg">
              Profiling, cleaning, dashboards, model comparison, explanations and a PDF report,
              from one file, in one place.
            </p>
          </Reveal>

          <Reveal delay={0.1}>
            <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Link
                to="/register"
                className="btn-3d btn-raised sheen group inline-flex h-12 items-center gap-2 rounded-xl px-7 text-sm font-semibold text-accent-contrast focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-canvas"
              >
                Create an account
                <ArrowRight
                  size={15}
                  className="transition-transform group-hover:translate-x-0.5"
                  aria-hidden="true"
                />
              </Link>
              <Link
                to="/login"
                className="glass glass-hover inline-flex h-12 items-center rounded-xl px-7 text-sm font-semibold text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-canvas"
              >
                Sign in
              </Link>
            </div>
          </Reveal>

          <Reveal delay={0.2}>
            <dl className="mx-auto mt-16 grid max-w-2xl grid-cols-2 gap-x-6 gap-y-8 sm:grid-cols-4">
              {STATS.map((stat) => (
                <div key={stat.label}>
                  <dd className="text-luxe text-3xl font-semibold tabular-nums tracking-tight">
                    <CountUp value={stat.value} suffix={stat.suffix} />
                  </dd>
                  <dt className="mt-1 text-xs leading-snug text-muted">{stat.label}</dt>
                </div>
              ))}
            </dl>
          </Reveal>
        </div>
      </section>

      <footer className="glass glass-subtle relative border-x-0 border-b-0">
        <div className="mx-auto max-w-6xl px-6 py-10">
          <div className="flex flex-col gap-8 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-accent-lift text-xs font-bold text-accent-contrast shadow-rim">
                  IF
                </span>
                <span className="text-sm font-semibold text-ink">InsightFlow</span>
              </div>
              <p className="mt-3 max-w-xs text-xs leading-relaxed text-muted">
                Self-service analytics: profiling, cleaning, dashboards, AutoML, explainability
                and reporting over your own data.
              </p>
            </div>

            <nav aria-label="Sections">
              <ul className="grid grid-cols-2 gap-x-8 gap-y-2 sm:grid-cols-1">
                {NAV.map((item) => (
                  <li key={item.href}>
                    <a
                      href={item.href}
                      className="text-xs text-muted transition-colors hover:text-ink"
                    >
                      {item.label}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>

            <div className="flex flex-col gap-2 text-xs text-muted">
              <a
                href="https://github.com/jenil38/insightflow"
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1.5 transition-colors hover:text-ink"
              >
                <Github size={13} aria-hidden="true" />
                Source
              </a>
              <Link to="/login" className="transition-colors hover:text-ink">
                Sign in
              </Link>
              <Link to="/register" className="transition-colors hover:text-ink">
                Create account
              </Link>
            </div>
          </div>

          <p className="mt-10 border-t border-line pt-6 text-xs text-subtle">
            A portfolio project. Figures shown on this page describe the implementation, not
            production usage.
          </p>
        </div>
      </footer>
    </>
  );
}

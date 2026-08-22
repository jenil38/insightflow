/**
 * Hero. Parallax-drifts and fades as the user scrolls past, so the pinned
 * pipeline section below feels like it takes over rather than merely following.
 */
import { Link } from "react-router-dom";
import { motion, useReducedMotion } from "framer-motion";
import { ArrowRight, Check } from "lucide-react";

import { Aurora, Reveal, ScrollCue, ScrollFadeOut, WordReveal } from "../../components/scroll/index.jsx";

/* Claims here map to features that actually exist in the product. */
const PROOF_POINTS = [
  "12 models compared per run",
  "SHAP with honest fallbacks",
  "Explainable quality scores",
];

export default function HeroSection() {
  const reduced = useReducedMotion();

  return (
    <section className="relative isolate min-h-screen overflow-hidden">
      <Aurora className="opacity-70" />

      {/* Faint grid, masked to fade toward the edges. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-[0.35]"
        style={{
          backgroundImage:
            "linear-gradient(to right, rgb(var(--color-border)) 1px, transparent 1px), linear-gradient(to bottom, rgb(var(--color-border)) 1px, transparent 1px)",
          backgroundSize: "64px 64px",
          maskImage: "radial-gradient(ellipse 70% 55% at 50% 40%, black 40%, transparent 100%)",
          WebkitMaskImage:
            "radial-gradient(ellipse 70% 55% at 50% 40%, black 40%, transparent 100%)",
        }}
      />

      <ScrollFadeOut className="relative mx-auto flex min-h-screen max-w-5xl flex-col items-center justify-center px-6 pt-24 text-center">
        <Reveal direction="none" delay={0.1}>
          <span className="glass-chip inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-medium uppercase tracking-[0.16em] text-muted">
            <span className="relative grid h-1.5 w-1.5 place-items-center">
              <span className="absolute inline-flex h-full w-full rounded-full bg-success opacity-75" />
              {!reduced && (
                <motion.span
                  className="absolute inline-flex h-full w-full rounded-full bg-success"
                  animate={{ scale: [1, 2.4, 1], opacity: [0.7, 0, 0.7] }}
                  transition={{ duration: 2.4, repeat: Infinity, ease: "easeOut" }}
                />
              )}
            </span>
            Self-service analytics platform
          </span>
        </Reveal>

        {/* The payoff line carries the champagne foil - one phrase per page, so
            it stays an accent rather than decoration. */}
        <h1 className="mt-6 max-w-4xl text-display-md font-semibold text-ink sm:text-display-lg lg:text-display-xl">
          <WordReveal text="Upload a spreadsheet." delay={0.2} />
          <span className="text-luxe mt-1 block">
            <WordReveal text="Leave with answers." delay={0.5} />
          </span>
        </h1>

        <Reveal delay={0.9} className="mt-6 max-w-2xl">
          <p className="text-lg leading-relaxed text-muted sm:text-xl">
            InsightFlow profiles your data, scores its quality against formulas you can read,
            trains and ranks a dozen models, and explains what actually drives the outcome —
            without you writing a line of code.
          </p>
        </Reveal>

        <Reveal delay={1.05} className="mt-8 w-full">
          <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              to="/register"
              className="btn-3d btn-raised sheen group inline-flex w-full items-center justify-center
                         gap-2 rounded-xl px-7 py-3.5 text-lg font-medium text-accent-contrast sm:w-auto"
            >
              Start analysing free
              <ArrowRight
                size={17}
                aria-hidden="true"
                className="transition-transform group-hover:translate-x-0.5"
              />
            </Link>
            <a
              href="#pipeline"
              className="glass glass-hover inline-flex w-full items-center justify-center gap-2 rounded-xl px-7 py-3.5 text-lg font-medium text-ink sm:w-auto"
            >
              See how it works
            </a>
          </div>
        </Reveal>

        <Reveal delay={1.2} className="mt-8">
          <ul className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2">
            {PROOF_POINTS.map((point) => (
              <li key={point} className="flex items-center gap-2 text-base text-muted">
                <Check size={15} aria-hidden="true" className="shrink-0 text-success" />
                {point}
              </li>
            ))}
          </ul>
        </Reveal>

        <Reveal delay={1.4} className="mt-16">
          <ScrollCue />
        </Reveal>
      </ScrollFadeOut>
    </section>
  );
}

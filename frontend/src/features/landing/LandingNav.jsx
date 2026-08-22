/**
 * Landing-page header.
 *
 * Transparent over the hero, then gains a blurred background and a hairline
 * border once the user scrolls past it - so it never competes with the hero but
 * stays legible over content.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { motion, useMotionValueEvent, useScroll } from "framer-motion";
import { BarChart3, Menu, Moon, Sun, X } from "lucide-react";

import { useTheme } from "../../app/providers.jsx";

const SECTIONS = [
  { id: "pipeline", label: "How it works" },
  { id: "quality", label: "Data quality" },
  { id: "models", label: "Models" },
  { id: "explainability", label: "Explainability" },
  { id: "copilot", label: "Copilot" },
];

export default function LandingNav() {
  const { scrollY } = useScroll();
  const [stuck, setStuck] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const { theme, toggleTheme } = useTheme();

  useMotionValueEvent(scrollY, "change", (value) => {
    const next = value > 80;
    setStuck((current) => (current === next ? current : next));
  });

  return (
    <motion.header
      className={`fixed inset-x-0 top-0 z-40 transition-colors duration-300 ${
        stuck ? "glass border-x-0 border-t-0" : "border-b border-transparent"
      }`}
      initial={{ y: -80, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-6">
        <Link to="/" className="flex items-center gap-2 rounded-md" aria-label="InsightFlow home">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent-lift text-accent-contrast shadow-rim glow-accent">
            <BarChart3 size={17} aria-hidden="true" />
          </span>
          <span className="text-lg font-semibold tracking-tight text-ink">InsightFlow</span>
        </Link>

        <nav aria-label="Page sections" className="hidden items-center gap-1 lg:flex">
          {SECTIONS.map((section) => (
            <a
              key={section.id}
              href={`#${section.id}`}
              className="rounded-md px-3 py-2 text-base text-muted transition-colors hover:bg-surface hover:text-ink"
            >
              {section.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={toggleTheme}
            className="glass-chip grid h-9 w-9 place-items-center rounded-lg text-muted transition-colors hover:text-ink"
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          >
            {theme === "dark" ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}
          </button>

          <Link
            to="/login"
            className="hidden rounded-md px-3 py-2 text-base font-medium text-muted transition-colors hover:text-ink sm:block"
          >
            Sign in
          </Link>
          <Link
            to="/register"
            className="btn-3d btn-raised rounded-lg px-4 py-2 text-base font-medium text-accent-contrast"
          >
            Get started
          </Link>

          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            className="glass-chip grid h-9 w-9 place-items-center rounded-lg text-muted lg:hidden"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
          >
            {menuOpen ? <X size={16} aria-hidden="true" /> : <Menu size={16} aria-hidden="true" />}
          </button>
        </div>
      </div>

      {menuOpen && (
        <motion.nav
          aria-label="Page sections"
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          className="glass glass-strong overflow-hidden border-x-0 border-b-0 lg:hidden"
        >
          <div className="flex flex-col p-3">
            {SECTIONS.map((section) => (
              <a
                key={section.id}
                href={`#${section.id}`}
                onClick={() => setMenuOpen(false)}
                className="rounded-md px-3 py-2.5 text-base text-muted hover:bg-surface hover:text-ink"
              >
                {section.label}
              </a>
            ))}
          </div>
        </motion.nav>
      )}
    </motion.header>
  );
}

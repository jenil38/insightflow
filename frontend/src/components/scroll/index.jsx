/**
 * Scroll-driven animation primitives.
 *
 * Everything here is built on Framer Motion's scroll hooks and animates only
 * `transform` and `opacity`, so the compositor does the work and long pages stay
 * at 60fps. No layout-triggering properties (height/top/width) are animated.
 *
 * Accessibility contract: every primitive checks `useReducedMotion()` and, when
 * set, renders the *final* state immediately rather than a faster animation.
 * A user who asks for no motion gets no motion, not brisk motion.
 */
import { useEffect, useRef, useState } from "react";
import {
  motion,
  useInView,
  useMotionValueEvent,
  useReducedMotion,
  useScroll,
  useSpring,
  useTransform,
} from "framer-motion";

/* ------------------------------------------------------------------ Reveal */

/**
 * Fades and slides content in the first time it enters the viewport.
 * `direction` picks the axis; `delay` staggers siblings.
 */
export function Reveal({
  children,
  delay = 0,
  direction = "up",
  distance = 24,
  className = "",
  once = true,
  as: Tag = "div",
}) {
  const reduced = useReducedMotion();
  const offsets = {
    up: { y: distance, x: 0 },
    down: { y: -distance, x: 0 },
    left: { x: distance, y: 0 },
    right: { x: -distance, y: 0 },
    none: { x: 0, y: 0 },
  };
  const from = offsets[direction] ?? offsets.up;
  const MotionTag = motion[Tag] ?? motion.div;

  if (reduced) return <Tag className={className}>{children}</Tag>;

  return (
    <MotionTag
      className={className}
      initial={{ opacity: 0, ...from }}
      whileInView={{ opacity: 1, x: 0, y: 0 }}
      viewport={{ once, margin: "-12% 0px -12% 0px" }}
      transition={{ duration: 0.7, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </MotionTag>
  );
}

/**
 * Reveals a headline word by word. Splitting on words rather than characters
 * keeps the text selectable and readable to screen readers as whole words.
 */
export function WordReveal({ text, className = "", delay = 0, stagger = 0.06 }) {
  const reduced = useReducedMotion();
  const words = String(text).split(" ");

  if (reduced) return <span className={className}>{text}</span>;

  return (
    <span className={className}>
      {words.map((word, index) => (
        <span key={`${word}-${index}`} className="inline-block overflow-hidden align-bottom">
          <motion.span
            className="inline-block"
            initial={{ y: "110%" }}
            animate={{ y: 0 }}
            transition={{
              duration: 0.8,
              delay: delay + index * stagger,
              ease: [0.22, 1, 0.36, 1],
            }}
          >
            {word}
            {index < words.length - 1 ? " " : ""}
          </motion.span>
        </span>
      ))}
    </span>
  );
}

/* ---------------------------------------------------------------- Parallax */

/**
 * Moves content at a different rate than the page scroll.
 * `speed` > 0 drifts up (foreground), < 0 drifts down (background).
 */
export function Parallax({ children, speed = 0.2, className = "" }) {
  const ref = useRef(null);
  const reduced = useReducedMotion();
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start end", "end start"],
  });
  const y = useTransform(scrollYProgress, [0, 1], [`${speed * 100}%`, `${-speed * 100}%`]);

  return (
    <div ref={ref} className={className}>
      {reduced ? children : <motion.div style={{ y }}>{children}</motion.div>}
    </div>
  );
}

/** Fades and lifts a hero out of the way as the user scrolls past it. */
export function ScrollFadeOut({ children, className = "" }) {
  const ref = useRef(null);
  const reduced = useReducedMotion();
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start start", "end start"],
  });
  const opacity = useTransform(scrollYProgress, [0, 0.7], [1, 0]);
  const y = useTransform(scrollYProgress, [0, 1], [0, -80]);
  const scale = useTransform(scrollYProgress, [0, 1], [1, 0.96]);

  return (
    <div ref={ref} className={className}>
      {reduced ? children : <motion.div style={{ opacity, y, scale }}>{children}</motion.div>}
    </div>
  );
}

/* ------------------------------------------------------------ Progress bar */

/** Thin reading-progress indicator pinned to the top of the viewport. */
export function ScrollProgressBar() {
  const { scrollYProgress } = useScroll();
  // Spring smoothing stops the bar from twitching on trackpad scroll.
  const scaleX = useSpring(scrollYProgress, { stiffness: 120, damping: 30, restDelta: 0.001 });

  return (
    <motion.div
      aria-hidden="true"
      style={{ scaleX }}
      className="fixed inset-x-0 top-0 z-50 h-0.5 origin-left bg-accent"
    />
  );
}

/* --------------------------------------------------------------- Step logic */

/**
 * Maps a pinned section's scroll progress onto a discrete active step.
 *
 * Returns `[ref, activeStep, progress]`. Attach `ref` to the tall outer
 * section; put a `sticky` child inside it. Progress is the raw 0-1 value for
 * continuous effects, `activeStep` the derived index for discrete UI.
 */
export function useScrollSteps(count) {
  const ref = useRef(null);
  const [active, setActive] = useState(0);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start start", "end end"],
  });

  useMotionValueEvent(scrollYProgress, "change", (value) => {
    // Leading/trailing padding so the first and last steps hold on screen
    // instead of flicking past at the very edges of the pin.
    const eased = Math.min(Math.max((value - 0.05) / 0.9, 0), 0.999);
    const next = Math.floor(eased * count);
    setActive((current) => (current === next ? current : next));
  });

  return [ref, active, scrollYProgress];
}

/* ----------------------------------------------------------------- CountUp */

/**
 * Animates a number upward once it scrolls into view.
 * Uses requestAnimationFrame rather than a motion value so the formatted
 * output (decimals, thousands separators) stays under our control.
 */
export function CountUp({ value, decimals = 0, suffix = "", prefix = "", duration = 1200 }) {
  const ref = useRef(null);
  const reduced = useReducedMotion();
  const inView = useInView(ref, { once: true, margin: "-15% 0px" });
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    if (!inView) return undefined;
    const target = Number(value) || 0;
    if (reduced) {
      setDisplay(target);
      return undefined;
    }

    let frame;
    const start = performance.now();
    const tick = (now) => {
      const progress = Math.min((now - start) / duration, 1);
      // easeOutCubic: fast start, gentle settle.
      setDisplay(target * (1 - Math.pow(1 - progress, 3)));
      if (progress < 1) frame = requestAnimationFrame(tick);
      else setDisplay(target);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [inView, value, duration, reduced]);

  return (
    <span ref={ref} className="tabular-nums">
      {prefix}
      {display.toLocaleString(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })}
      {suffix}
    </span>
  );
}

/* ------------------------------------------------------------------ Aurora */

/**
 * Soft animated background wash for marketing sections only.
 *
 * The product UI stays deliberately flat and calm; expressive background
 * treatment is confined to the public landing page, where it sets tone without
 * competing with data. Sits behind content at low opacity and is inert to
 * pointer events.
 */
export function Aurora({ className = "" }) {
  const reduced = useReducedMotion();
  const blobs = [
    { className: "left-[-10%] top-[-15%] h-[38rem] w-[38rem] bg-accent/25", duration: 18 },
    { className: "right-[-15%] top-[10%] h-[32rem] w-[32rem] bg-chart-2/20", duration: 24 },
    { className: "bottom-[-20%] left-[25%] h-[34rem] w-[34rem] bg-chart-5/20", duration: 21 },
  ];

  return (
    <div aria-hidden="true" className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}>
      {blobs.map((blob, index) => (
        <motion.div
          key={index}
          className={`absolute rounded-full blur-[110px] ${blob.className}`}
          animate={
            reduced
              ? undefined
              : { x: [0, 40, -25, 0], y: [0, -30, 25, 0], scale: [1, 1.08, 0.95, 1] }
          }
          transition={
            reduced
              ? undefined
              : { duration: blob.duration, repeat: Infinity, ease: "easeInOut" }
          }
        />
      ))}
    </div>
  );
}

/* -------------------------------------------------------------- Scroll cue */

/** Animated affordance telling the user there is more below the fold. */
export function ScrollCue({ label = "Scroll to explore" }) {
  const reduced = useReducedMotion();
  return (
    <div className="flex flex-col items-center gap-2 text-subtle">
      <span className="text-xs uppercase tracking-[0.2em]">{label}</span>
      <motion.div
        className="h-10 w-6 rounded-full border border-line-strong p-1"
        animate={reduced ? undefined : { opacity: [0.5, 1, 0.5] }}
        transition={reduced ? undefined : { duration: 2, repeat: Infinity }}
      >
        <motion.div
          className="h-2 w-full rounded-full bg-accent"
          animate={reduced ? undefined : { y: [0, 16, 0] }}
          transition={reduced ? undefined : { duration: 2, repeat: Infinity, ease: "easeInOut" }}
        />
      </motion.div>
    </div>
  );
}

/* -------------------------------------------------------------- Grow bar */

/**
 * Horizontal bar that grows to `pct` when scrolled into view.
 * Animates scaleX (compositor-friendly) rather than width (layout-triggering).
 */
export function GrowBar({ pct, className = "", delay = 0, height = "h-2" }) {
  const reduced = useReducedMotion();
  const clamped = Math.max(0, Math.min(Number(pct) || 0, 100));

  return (
    <div className={`w-full overflow-hidden rounded-full bg-line ${height}`}>
      <motion.div
        className={`h-full origin-left rounded-full ${className}`}
        initial={reduced ? false : { scaleX: 0 }}
        whileInView={{ scaleX: clamped / 100 }}
        viewport={{ once: true, margin: "-10% 0px" }}
        transition={reduced ? { duration: 0 } : { duration: 0.9, delay, ease: [0.22, 1, 0.36, 1] }}
        style={{ width: "100%", scaleX: reduced ? clamped / 100 : undefined }}
      />
    </div>
  );
}

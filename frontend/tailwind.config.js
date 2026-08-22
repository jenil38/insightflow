/**
 * Tailwind is driven by the CSS variables declared in src/index.css.
 * Components never hard-code a colour - they reference these semantic tokens,
 * which is what lets a single `data-theme` switch flip the whole app between
 * light and dark without per-component dark: variants everywhere.
 */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        canvas: "rgb(var(--color-canvas) / <alpha-value>)",
        surface: "rgb(var(--color-surface) / <alpha-value>)",
        elevated: "rgb(var(--color-elevated) / <alpha-value>)",
        line: "rgb(var(--color-border) / <alpha-value>)",
        "line-strong": "rgb(var(--color-border-strong) / <alpha-value>)",
        ink: "rgb(var(--color-text) / <alpha-value>)",
        muted: "rgb(var(--color-text-muted) / <alpha-value>)",
        subtle: "rgb(var(--color-text-subtle) / <alpha-value>)",
        accent: {
          DEFAULT: "rgb(var(--color-accent) / <alpha-value>)",
          hover: "rgb(var(--color-accent-hover) / <alpha-value>)",
          soft: "rgb(var(--color-accent-soft) / <alpha-value>)",
          contrast: "rgb(var(--color-accent-contrast) / <alpha-value>)",
        },
        /* Champagne gold. `DEFAULT` is the AA-safe weight for text and icons;
           `bright` is decorative only - rims, gradients, glints. */
        luxe: {
          DEFAULT: "rgb(var(--color-luxe) / <alpha-value>)",
          bright: "rgb(var(--color-luxe-bright) / <alpha-value>)",
          sheen: "rgb(var(--color-luxe-sheen) / <alpha-value>)",
          soft: "rgb(var(--color-luxe-soft) / <alpha-value>)",
        },
        /* Top stop of the surface fill gradient - the lit face of a raised
           element. Exposed so one-off panels can match the card treatment. */
        lift: "rgb(var(--color-surface-lift) / <alpha-value>)",
        success: {
          DEFAULT: "rgb(var(--color-success) / <alpha-value>)",
          soft: "rgb(var(--color-success-soft) / <alpha-value>)",
        },
        warning: {
          DEFAULT: "rgb(var(--color-warning) / <alpha-value>)",
          soft: "rgb(var(--color-warning-soft) / <alpha-value>)",
        },
        danger: {
          DEFAULT: "rgb(var(--color-danger) / <alpha-value>)",
          soft: "rgb(var(--color-danger-soft) / <alpha-value>)",
        },
        /* Chart series exposed as utilities so marketing sections and custom
           visuals can use the same palette the charts do, instead of inventing
           one-off colours that drift from the data views. */
        chart: {
          1: "rgb(var(--chart-1) / <alpha-value>)",
          2: "rgb(var(--chart-2) / <alpha-value>)",
          3: "rgb(var(--chart-3) / <alpha-value>)",
          4: "rgb(var(--chart-4) / <alpha-value>)",
          5: "rgb(var(--chart-5) / <alpha-value>)",
          6: "rgb(var(--chart-6) / <alpha-value>)",
        },
      },
      /* Softened one step across the board. Tighter radii read as "utility
         dashboard"; these read as moulded objects, which is what the raised
         surfaces are trying to be. */
      borderRadius: {
        DEFAULT: "0.625rem",
        md: "0.625rem",
        lg: "0.875rem",
        xl: "1.125rem",
        "2xl": "1.5rem",
      },
      // 8px base scale; half-steps exist for control padding, where 8px
      // increments are too coarse.
      spacing: {
        1: "0.25rem",
        2: "0.5rem",
        3: "0.75rem",
        4: "1rem",
        5: "1.25rem",
        6: "1.5rem",
        8: "2rem",
        10: "2.5rem",
        12: "3rem",
        16: "4rem",
      },
      fontFamily: {
        sans: [
          "Inter", "ui-sans-serif", "system-ui", "-apple-system",
          "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
        xs: ["0.75rem", { lineHeight: "1.125rem" }],
        sm: ["0.8125rem", { lineHeight: "1.25rem" }],
        base: ["0.875rem", { lineHeight: "1.375rem" }],
        lg: ["1rem", { lineHeight: "1.5rem" }],
        xl: ["1.125rem", { lineHeight: "1.625rem" }],
        "2xl": ["1.375rem", { lineHeight: "1.875rem" }],
        "3xl": ["1.75rem", { lineHeight: "2.125rem" }],
        /* Display sizes for the marketing landing page only. The product UI
           tops out at 3xl deliberately - dashboards need density, not drama.
           Tighter leading and negative tracking keep large headlines from
           looking loose. */
        "display-sm": ["2.25rem", { lineHeight: "2.5rem", letterSpacing: "-0.02em" }],
        "display-md": ["3rem", { lineHeight: "3.25rem", letterSpacing: "-0.025em" }],
        "display-lg": ["3.75rem", { lineHeight: "3.9rem", letterSpacing: "-0.03em" }],
        "display-xl": ["4.75rem", { lineHeight: "4.9rem", letterSpacing: "-0.035em" }],
      },
      /* The named sizes map onto the same depth ladder defined in index.css,
         so `shadow-md` and `shadow-depth-2` are the same physical distance.
         Light mode leans on the cast shadow; dark mode substitutes a rim,
         which is why these resolve through CSS variables rather than literals. */
      boxShadow: {
        xs: "var(--depth-1)",
        sm: "var(--depth-1)",
        md: "var(--depth-2)",
        lg: "var(--depth-3)",
        xl: "var(--depth-4)",
        focus: "0 0 0 3px rgb(var(--color-accent) / 0.25)",
        /* Inset pair that turns a flat fill into a lit face. */
        rim: "inset 0 1px 0 0 rgb(var(--rim) / var(--rim-alpha)), inset 0 -1px 0 0 rgb(var(--rim-shade) / var(--rim-shade-alpha))",
        well: "inset 0 2px 4px -1px rgb(var(--shadow-rgb) / 0.09), inset 0 1px 2px 0 rgb(var(--shadow-rgb) / 0.06)",
      },
      backgroundImage: {
        /* The lit face used by every raised surface. */
        lift: "linear-gradient(180deg, rgb(var(--color-surface-lift)) 0%, rgb(var(--color-surface)) 62%)",
        "accent-lift": "linear-gradient(180deg, rgb(var(--color-accent-hover)) 0%, rgb(var(--color-accent)) 100%)",
        "luxe-lift": "linear-gradient(140deg, rgb(var(--color-luxe-bright)) 0%, rgb(var(--color-luxe)) 100%)",
      },
      keyframes: {
        "fade-in": { from: { opacity: 0 }, to: { opacity: 1 } },
        "slide-up": {
          from: { opacity: 0, transform: "translateY(4px)" },
          to: { opacity: 1, transform: "translateY(0)" },
        },
        /* Entrance for stacked panels: rises and rotates flat, so a grid of
           cards reads as settling into place rather than fading in. */
        "rise-3d": {
          from: { opacity: 0, transform: "perspective(1200px) translateY(14px) rotateX(7deg)" },
          to: { opacity: 1, transform: "perspective(1200px) translateY(0) rotateX(0deg)" },
        },
        shimmer: {
          "100%": { transform: "translateX(120%)" },
        },
      },
      animation: {
        "fade-in": "fade-in 150ms ease-out",
        "slide-up": "slide-up 180ms ease-out",
        "rise-3d": "rise-3d 420ms cubic-bezier(0.22, 1, 0.36, 1) both",
      },
    },
  },
  plugins: [],
};

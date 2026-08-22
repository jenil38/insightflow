/**
 * Design-system primitives.
 *
 * Everything the app renders is built from these, so spacing, radius, focus
 * rings, disabled states and status colours stay consistent by construction
 * rather than by discipline. Colours come from the semantic Tailwind tokens
 * (see index.css) - no component hard-codes a hex value.
 */
import { forwardRef, useEffect, useId, useRef, useState } from "react";
import clsx from "clsx";
import {
  AlertCircle, AlertTriangle, Check, ChevronDown, Info, Loader2, X,
} from "lucide-react";

/* ------------------------------------------------------------------ Button */

/* Raised variants carry their extrusion in CSS (see .btn-raised / .btn-surface
   in index.css) so the lit face, the under-lip shade and the press state stay
   in one place instead of being reassembled from utilities per variant. */
const BUTTON_VARIANTS = {
  primary:
    "btn-3d btn-raised text-accent-contrast disabled:opacity-45 disabled:shadow-none",
  secondary:
    "btn-3d btn-surface text-ink disabled:text-subtle disabled:opacity-60",
  ghost: "btn-3d text-muted hover:bg-surface hover:text-ink disabled:text-subtle",
  danger: "btn-3d btn-danger-raised text-white disabled:opacity-45",
  "danger-ghost": "btn-3d text-danger hover:bg-danger-soft disabled:text-subtle",
  /* Champagne. Reserved for the single highest-intent action on a screen. */
  luxe:
    "btn-3d bg-luxe-lift text-[rgb(28_23_8)] shadow-rim glow-luxe disabled:opacity-45",
};

const BUTTON_SIZES = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-9 px-4 text-base gap-2",
  lg: "h-11 px-6 text-base gap-2",
};

export const Button = forwardRef(function Button(
  {
    variant = "primary", size = "md", loading = false, disabled = false,
    icon: Icon, iconRight: IconRight, className, children, type = "button", ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={clsx(
        "inline-flex items-center justify-center rounded-lg font-medium tracking-[-0.01em]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:ring-offset-2",
        "disabled:cursor-not-allowed",
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <Loader2 size={15} className="animate-spin" aria-hidden="true" />
      ) : (
        Icon && <Icon size={15} aria-hidden="true" />
      )}
      {children}
      {IconRight && !loading && <IconRight size={15} aria-hidden="true" />}
    </button>
  );
});

/** Icon-only button. `label` is required - it becomes the accessible name. */
export const IconButton = forwardRef(function IconButton(
  { icon: Icon, label, variant = "ghost", size = "md", className, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      title={label}
      aria-label={label}
      className={clsx(
        "inline-flex items-center justify-center rounded-lg",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:ring-offset-2",
        "disabled:cursor-not-allowed disabled:text-subtle",
        BUTTON_VARIANTS[variant],
        size === "sm" ? "h-7 w-7" : "h-9 w-9",
        className,
      )}
      {...rest}
    >
      <Icon size={size === "sm" ? 14 : 16} aria-hidden="true" />
    </button>
  );
});

/* -------------------------------------------------------------------- Card */

/**
 * Raised panel.
 *
 * `interactive` adds the hover lift. `tilt` additionally rotates the card
 * toward the pointer - reserved for sparse, card-led screens (overviews,
 * marketing), because a dense grid of tilting panels is motion sickness, not
 * polish. Both are opt-in so data tables stay perfectly flat and readable.
 */
export function Card({ className, children, interactive, tilt, ...rest }) {
  const ref = useRef(null);

  function handlePointerMove(event) {
    if (!tilt || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    // Normalise the pointer to -0.5..0.5 across the card, then map to a small
    // rotation. 6deg is about the limit before text edges start to shimmer.
    const px = (event.clientX - rect.left) / rect.width - 0.5;
    const py = (event.clientY - rect.top) / rect.height - 0.5;
    ref.current.style.setProperty("--ry", `${px * 6}deg`);
    ref.current.style.setProperty("--rx", `${-py * 6}deg`);
  }

  function resetTilt() {
    if (!tilt || !ref.current) return;
    ref.current.style.setProperty("--ry", "0deg");
    ref.current.style.setProperty("--rx", "0deg");
  }

  return (
    <div
      ref={ref}
      onPointerMove={handlePointerMove}
      onPointerLeave={resetTilt}
      className={clsx(
        "card",
        interactive && "card-interactive",
        tilt && "tilt-3d",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardHeader({ title, description, actions, className }) {
  return (
    <div
      className={clsx(
        // The header sits on the lit top third of the card gradient, so it gets
        // a hairline rather than a filled bar - a second fill would flatten the
        // extrusion the card is built on.
        "flex items-start justify-between gap-4 border-b border-line/70 px-5 py-4",
        className,
      )}
    >
      <div className="min-w-0">
        <h3 className="truncate text-base font-semibold tracking-[-0.01em] text-ink">{title}</h3>
        {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export function CardBody({ className, children }) {
  return <div className={clsx("p-5", className)}>{children}</div>;
}

/* ---------------------------------------------------------------- StatCard */

/**
 * Headline metric tile.
 *
 * `tone="luxe"` swaps the panel for a gold-rimmed variant. It marks the single
 * standout figure on a screen - the winning model, the headline score - so it
 * has to stay rare to keep meaning anything.
 */
export function StatCard({ label, value, hint, icon: Icon, tone = "default", loading }) {
  const tones = {
    default: "text-ink",
    success: "text-success",
    warning: "text-warning",
    danger: "text-danger",
    accent: "text-accent",
    luxe: "text-luxe",
  };
  const luxe = tone === "luxe";

  return (
    <div
      className={clsx(
        "card-interactive relative overflow-hidden rounded-xl p-4",
        luxe ? "luxe-rim" : "surface-3d",
      )}
    >
      {/* Specular sweep across the top face. Purely a lighting cue, so it is
          inert to pointers and hidden from assistive tech. */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/60 to-transparent dark:via-white/15"
      />
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wider text-subtle">{label}</p>
        {Icon && (
          <span
            className={clsx(
              "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg shadow-rim",
              luxe ? "bg-luxe-soft text-luxe" : "bg-canvas text-subtle",
            )}
          >
            <Icon size={14} aria-hidden="true" />
          </span>
        )}
      </div>
      {loading ? (
        <Skeleton className="mt-2 h-8 w-24" />
      ) : (
        <p className={clsx("mt-1.5 text-3xl font-semibold tabular-nums tracking-[-0.02em]", tones[tone])}>
          {value}
        </p>
      )}
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

/* ------------------------------------------------------------------- Badge */

const BADGE_TONES = {
  neutral: "bg-canvas text-muted border-line",
  accent: "bg-accent-soft text-accent border-accent/25",
  success: "bg-success-soft text-success border-success/25",
  warning: "bg-warning-soft text-warning border-warning/25",
  danger: "bg-danger-soft text-danger border-danger/25",
  luxe: "bg-luxe-soft text-luxe border-luxe-bright/35",
};

export function Badge({ tone = "neutral", icon: Icon, className, children }) {
  return (
    <span
      className={clsx(
        // Pill + rim highlight so badges read as small pressed tokens rather
        // than flat colour swatches.
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium shadow-rim",
        BADGE_TONES[tone],
        className,
      )}
    >
      {Icon && <Icon size={11} aria-hidden="true" />}
      {children}
    </span>
  );
}

/* ------------------------------------------------------------ Input/Select */

/** Label + control + error, wired together so screen readers announce both. */
export function Field({ label, htmlFor, error, hint, required, children, className }) {
  return (
    <div className={clsx("space-y-1.5", className)}>
      {label && (
        <label htmlFor={htmlFor} className="block text-sm font-medium text-ink">
          {label}
          {required && <span className="ml-0.5 text-danger" aria-hidden="true">*</span>}
        </label>
      )}
      {children}
      {error ? (
        // role=alert so validation failures are announced, not just recoloured.
        <p role="alert" className="flex items-start gap-1 text-xs text-danger">
          <AlertCircle size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
          {error}
        </p>
      ) : (
        hint && <p className="text-xs text-muted">{hint}</p>
      )}
    </div>
  );
}

export const Input = forwardRef(function Input({ className, invalid, ...rest }, ref) {
  return (
    <input
      ref={ref}
      aria-invalid={invalid || undefined}
      className={clsx("input-base", invalid && "border-danger focus:border-danger focus:ring-danger/25", className)}
      {...rest}
    />
  );
});

export const Select = forwardRef(function Select(
  { className, invalid, options = [], placeholder, children, ...rest },
  ref,
) {
  return (
    <div className="relative">
      <select
        ref={ref}
        aria-invalid={invalid || undefined}
        className={clsx(
          "input-base appearance-none pr-9",
          invalid && "border-danger focus:border-danger",
          className,
        )}
        {...rest}
      >
        {placeholder && <option value="">{placeholder}</option>}
        {options.map((option) => {
          const value = typeof option === "string" ? option : option.value;
          const label = typeof option === "string" ? option : option.label;
          return (
            <option key={value} value={value}>
              {label}
            </option>
          );
        })}
        {children}
      </select>
      <ChevronDown
        size={15}
        aria-hidden="true"
        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-subtle"
      />
    </div>
  );
});

export const Checkbox = forwardRef(function Checkbox({ label, description, id, className, ...rest }, ref) {
  const generated = useId();
  const inputId = id || generated;
  return (
    <div className={clsx("flex items-start gap-2.5", className)}>
      <input
        ref={ref}
        id={inputId}
        type="checkbox"
        className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer rounded border-line-strong text-accent
                   focus-visible:ring-2 focus-visible:ring-accent/50"
        {...rest}
      />
      <div className="min-w-0">
        <label htmlFor={inputId} className="cursor-pointer text-base text-ink">
          {label}
        </label>
        {description && <p className="text-xs text-muted">{description}</p>}
      </div>
    </div>
  );
});

/* ------------------------------------------------------------------ Toggle */

/**
 * On/off switch.
 *
 * Built on a real `role="switch"` button rather than a restyled checkbox: the
 * switch role is what makes a screen reader announce "on"/"off" instead of
 * "checked", which is the correct semantic for a setting that takes effect
 * immediately rather than on submit.
 */
export function Toggle({
  checked = false, onChange, label, description, disabled, id, className,
}) {
  const generated = useId();
  const inputId = id || generated;
  const descriptionId = description ? `${inputId}-description` : undefined;

  return (
    <div className={clsx("flex items-start justify-between gap-4", className)}>
      <div className="min-w-0">
        <label htmlFor={inputId} className={clsx("text-base text-ink", !disabled && "cursor-pointer")}>
          {label}
        </label>
        {description && (
          <p id={descriptionId} className="mt-0.5 text-xs text-muted">{description}</p>
        )}
      </div>

      <button
        id={inputId}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-describedby={descriptionId}
        disabled={disabled}
        onClick={() => onChange?.(!checked)}
        className={clsx(
          "relative mt-0.5 h-[22px] w-[38px] shrink-0 rounded-full transition-colors duration-200",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:ring-offset-2",
          "disabled:cursor-not-allowed disabled:opacity-50",
          checked ? "bg-accent" : "bg-line-strong",
        )}
      >
        {/* The knob carries its own small shadow so it reads as sitting on top
            of the track rather than punched into it. */}
        <span
          aria-hidden="true"
          className={clsx(
            "absolute top-[3px] h-4 w-4 rounded-full bg-white shadow-depth-1",
            "transition-transform duration-200 ease-[cubic-bezier(0.22,1,0.36,1)]",
            checked ? "translate-x-[19px]" : "translate-x-[3px]",
          )}
        />
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ Slider */

/**
 * Range input with a filled track.
 *
 * The fill is a background gradient on the native input rather than an overlay
 * element, so the thumb stays draggable across the whole track and keyboard
 * support (arrows, Home/End, Page Up/Down) comes for free from the platform.
 */
export function Slider({
  value, onChange, min = 0, max = 100, step = 1,
  label, hint, formatValue, disabled, id, className,
}) {
  const generated = useId();
  const inputId = id || generated;
  const percent = max === min ? 0 : ((value - min) / (max - min)) * 100;

  return (
    <div className={clsx("min-w-0", className)}>
      {(label || formatValue) && (
        <div className="mb-2 flex items-baseline justify-between gap-3">
          {label && (
            <label htmlFor={inputId} className="text-base text-ink">{label}</label>
          )}
          {formatValue && (
            <span className="shrink-0 font-mono text-xs tabular-nums text-muted">
              {formatValue(value)}
            </span>
          )}
        </div>
      )}
      <input
        id={inputId}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange?.(Number(event.target.value))}
        style={{
          background:
            `linear-gradient(90deg, rgb(var(--color-accent)) ${percent}%, ` +
            `rgb(var(--color-border-strong)) ${percent}%)`,
        }}
        className={clsx(
          "h-1.5 w-full cursor-pointer appearance-none rounded-full",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:ring-offset-2",
          "disabled:cursor-not-allowed disabled:opacity-50",
          "[&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4",
          "[&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full",
          "[&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-accent",
          "[&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:shadow-depth-1",
          "[&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4",
          "[&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2",
          "[&::-moz-range-thumb]:border-accent [&::-moz-range-thumb]:bg-white",
        )}
      />
      {hint && <p className="mt-1.5 text-xs text-muted">{hint}</p>}
    </div>
  );
}

/* ------------------------------------------------------- SegmentedControl */

/**
 * Two to four mutually exclusive options shown side by side.
 *
 * Uses the radiogroup pattern: arrow keys move the selection (which is what
 * radios do natively), and only the selected option sits in the tab order.
 */
export function SegmentedControl({
  value, onChange, options = [], label, size = "md", disabled, className,
}) {
  const refs = useRef([]);
  const index = options.findIndex((option) => option.value === value);

  function onKeyDown(event) {
    const last = options.length - 1;
    let next = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = index >= last ? 0 : index + 1;
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = index <= 0 ? last : index - 1;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = last;
    if (next === null) return;
    event.preventDefault();
    onChange?.(options[next].value);
    refs.current[next]?.focus();
  }

  return (
    <div
      role="radiogroup"
      aria-label={label}
      onKeyDown={onKeyDown}
      className={clsx("surface-inset inline-flex rounded-lg p-1", className)}
    >
      {options.map((option, i) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            ref={(node) => { refs.current[i] = node; }}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            disabled={disabled}
            onClick={() => onChange?.(option.value)}
            className={clsx(
              "inline-flex flex-1 items-center justify-center gap-1.5 rounded-md font-medium",
              "transition-colors duration-150 focus-visible:outline-none",
              "focus-visible:ring-2 focus-visible:ring-accent/50",
              "disabled:cursor-not-allowed disabled:opacity-50",
              size === "sm" ? "h-7 px-2.5 text-xs" : "h-8 px-3 text-base",
              selected
                ? "btn-surface text-ink"
                : "text-muted hover:text-ink",
            )}
          >
            {option.icon && <option.icon size={14} aria-hidden="true" />}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

/* -------------------------------------------------------------------- Tabs */

/**
 * Tablist with full keyboard support: arrow keys move between tabs, Home/End
 * jump to the ends, and only the active tab is in the tab order (roving
 * tabindex), which is what the WAI-ARIA tabs pattern specifies.
 */
export function Tabs({ tabs, value, onChange, className }) {
  const refs = useRef([]);

  function handleKeyDown(event) {
    const index = tabs.findIndex((t) => t.key === value);
    let next = null;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    if (next === null) return;
    event.preventDefault();
    onChange(tabs[next].key);
    refs.current[next]?.focus();
  }

  return (
    <div
      role="tablist"
      aria-label="Workspace sections"
      onKeyDown={handleKeyDown}
      /* Segmented rail rather than an underline: the whole strip is a recessed
         well and the selected tab is a raised pill inside it, which carries the
         same lit-from-above logic as every other surface. */
      className={clsx("surface-inset flex gap-1 overflow-x-auto rounded-xl p-1", className)}
    >
      {tabs.map((tab, index) => {
        const active = tab.key === value;
        return (
          <button
            key={tab.key}
            ref={(node) => (refs.current[index] = node)}
            role="tab"
            id={`tab-${tab.key}`}
            aria-selected={active}
            aria-controls={`panel-${tab.key}`}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(tab.key)}
            className={clsx(
              "flex shrink-0 items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-base font-medium",
              "transition-[background-color,color,box-shadow,transform] duration-200",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:ring-inset",
              active
                ? "bg-lift text-accent shadow-rim shadow-depth-2"
                : "text-muted hover:bg-surface/60 hover:text-ink",
            )}
          >
            {tab.icon && <tab.icon size={15} aria-hidden="true" />}
            {tab.label}
            {tab.badge != null && (
              <span
                className={clsx(
                  "rounded-full px-1.5 text-2xs tabular-nums shadow-rim",
                  active ? "bg-accent-soft text-accent" : "bg-canvas text-muted",
                )}
              >
                {tab.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ tabKey, active, children, className }) {
  if (!active) return null;
  return (
    <div
      role="tabpanel"
      id={`panel-${tabKey}`}
      aria-labelledby={`tab-${tabKey}`}
      tabIndex={0}
      className={clsx("animate-rise-3d focus-visible:outline-none", className)}
    >
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------- Modal */

/**
 * Accessible dialog: focus moves in on open and returns on close, Escape
 * dismisses, Tab is trapped inside, and background scroll is locked.
 */
export function Modal({ open, onClose, title, description, footer, size = "md", children }) {
  const panelRef = useRef(null);
  const restoreFocusRef = useRef(null);
  const titleId = useId();

  useEffect(() => {
    if (!open) return undefined;
    restoreFocusRef.current = document.activeElement;
    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";

    // Focus the first control, or the panel itself if there isn't one.
    const focusable = panelRef.current?.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    (focusable?.[0] || panelRef.current)?.focus();

    function onKeyDown(event) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose?.();
        return;
      }
      if (event.key !== "Tab") return;
      const nodes = panelRef.current?.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (!nodes?.length) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.body.style.overflow = overflow;
      restoreFocusRef.current?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  const widths = { sm: "max-w-md", md: "max-w-lg", lg: "max-w-2xl", xl: "max-w-4xl" };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-4">
      {/* Heavier blur than before: pushing the page far out of focus is what
          makes the dialog read as floating well above it. */}
      <div
        className="absolute inset-0 bg-ink/50 backdrop-blur-md"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={clsx(
          "relative z-10 max-h-[92vh] w-full overflow-y-auto rounded-t-2xl bg-elevated sm:rounded-2xl",
          "border border-line shadow-rim shadow-depth-4",
          "animate-rise-3d focus-visible:outline-none",
          widths[size],
        )}
      >
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/70 to-transparent dark:via-white/20"
        />
        <div className="flex items-start justify-between gap-4 border-b border-line/70 px-5 py-4">
          <div className="min-w-0">
            <h2 id={titleId} className="text-lg font-semibold tracking-[-0.01em] text-ink">{title}</h2>
            {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
          </div>
          <IconButton icon={X} label="Close dialog" onClick={onClose} size="sm" />
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer && (
          <div className="flex justify-end gap-2 border-t border-line/70 bg-canvas/50 px-5 py-3">{footer}</div>
        )}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open, onClose, onConfirm, title, message, confirmLabel = "Confirm",
  cancelLabel = "Cancel", tone = "danger", loading,
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button variant={tone} onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p className="text-base text-muted">{message}</p>
    </Modal>
  );
}

/* ----------------------------------------------------------------- Tooltip */

/** Tooltip on hover and on keyboard focus - hover-only would hide it from
 *  keyboard users entirely. */
export function Tooltip({ content, children, className }) {
  const [visible, setVisible] = useState(false);
  const id = useId();
  if (!content) return children;
  return (
    <span
      className={clsx("relative inline-flex", className)}
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onFocus={() => setVisible(true)}
      onBlur={() => setVisible(false)}
    >
      <span aria-describedby={visible ? id : undefined}>{children}</span>
      {visible && (
        <span
          role="tooltip"
          id={id}
          className="pointer-events-none absolute bottom-full left-1/2 z-40 mb-2 w-max max-w-xs
                     -translate-x-1/2 animate-slide-up rounded-lg bg-ink px-3 py-2 text-xs font-normal
                     leading-relaxed text-canvas shadow-depth-3"
        >
          {content}
        </span>
      )}
    </span>
  );
}

/* ---------------------------------------------------------------- Progress */

export function Progress({ value, label, tone = "accent", showValue = true, className }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  // Each fill is a gradient with a lit top edge, so the bar reads as a rounded
  // rod sitting in the recessed track rather than a flat block of colour.
  const tones = {
    accent: "bg-gradient-to-b from-accent-hover to-accent",
    success: "bg-gradient-to-b from-success to-success/80",
    warning: "bg-gradient-to-b from-warning to-warning/80",
    danger: "bg-gradient-to-b from-danger to-danger/80",
    luxe: "bg-luxe-lift",
  };
  return (
    <div className={className}>
      {(label || showValue) && (
        <div className="mb-1 flex items-baseline justify-between gap-2">
          {label && <span className="text-sm text-muted">{label}</span>}
          {showValue && <span className="text-sm font-medium tabular-nums text-ink">{pct.toFixed(0)}%</span>}
        </div>
      )}
      <div
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label || "Progress"}
        className="surface-inset h-2 w-full overflow-hidden rounded-full"
      >
        <div
          className={clsx(
            "h-full rounded-full shadow-[inset_0_1px_0_0_rgb(255_255_255/0.3)] transition-[width] duration-500",
            tones[tone],
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- Skeleton */

export function Skeleton({ className }) {
  return (
    <div
      className={clsx("animate-pulse rounded-lg bg-line/70 shadow-well", className)}
      aria-hidden="true"
    />
  );
}

export function SkeletonText({ lines = 3, className }) {
  return (
    <div className={clsx("space-y-2", className)} aria-hidden="true">
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton key={index} className={clsx("h-3", index === lines - 1 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}

/** Screen readers get a live announcement; sighted users get the skeleton. */
export function LoadingState({ message = "Loading", rows = 3 }) {
  return (
    <div>
      <span role="status" aria-live="polite" className="sr-only">{message}</span>
      <SkeletonText lines={rows} />
    </div>
  );
}

export function LoadingOverlay({ message = "Working" }) {
  return (
    <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 rounded-xl bg-surface/70 backdrop-blur-md">
      <span className="surface-3d flex h-12 w-12 items-center justify-center rounded-2xl">
        <Loader2 size={20} className="animate-spin text-accent" aria-hidden="true" />
      </span>
      <p role="status" aria-live="polite" className="text-sm font-medium text-muted">{message}</p>
    </div>
  );
}

/* ------------------------------------------------------- Empty/Error state */

export function EmptyState({ icon: Icon, title, description, action, className }) {
  return (
    <div className={clsx("flex flex-col items-center justify-center px-6 py-12 text-center", className)}>
      {Icon && (
        // Raised plinth for the icon, so an empty panel still has one object
        // with weight in it rather than reading as a blank rectangle.
        <div className="surface-3d mb-4 flex h-14 w-14 items-center justify-center rounded-2xl">
          <Icon size={22} className="text-accent" aria-hidden="true" />
        </div>
      )}
      <h3 className="text-lg font-semibold tracking-[-0.01em] text-ink">{title}</h3>
      {description && <p className="mt-1.5 max-w-sm text-sm text-muted">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorState({ title = "Something went wrong", message, onRetry, className }) {
  return (
    <div
      role="alert"
      className={clsx("flex flex-col items-center justify-center px-6 py-10 text-center", className)}
    >
      <div className="surface-3d mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-danger-soft">
        <AlertTriangle size={22} className="text-danger" aria-hidden="true" />
      </div>
      <h3 className="text-lg font-semibold tracking-[-0.01em] text-ink">{title}</h3>
      {message && <p className="mt-1.5 max-w-md text-sm text-muted">{message}</p>}
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-5" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ Alert */

const ALERT_TONES = {
  info: { cls: "bg-accent-soft border-accent/25 text-ink", Icon: Info, iconCls: "text-accent" },
  success: { cls: "bg-success-soft border-success/25 text-ink", Icon: Check, iconCls: "text-success" },
  warning: { cls: "bg-warning-soft border-warning/25 text-ink", Icon: AlertTriangle, iconCls: "text-warning" },
  danger: { cls: "bg-danger-soft border-danger/25 text-ink", Icon: AlertCircle, iconCls: "text-danger" },
};

export function Alert({ tone = "info", title, children, className, action }) {
  const { cls, Icon, iconCls } = ALERT_TONES[tone] ?? ALERT_TONES.info;
  return (
    <div className={clsx("flex items-start gap-2.5 rounded-xl border px-4 py-3 shadow-rim", cls, className)}>
      <Icon size={15} className={clsx("mt-0.5 shrink-0", iconCls)} aria-hidden="true" />
      <div className="min-w-0 flex-1 text-sm">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={clsx(title && "mt-0.5", "text-muted")}>{children}</div>}
      </div>
      {action}
    </div>
  );
}

/* ------------------------------------------------------------- PageHeader */

export function PageHeader({ title, description, actions, meta, className }) {
  return (
    <div className={clsx("mb-6", className)}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-3xl font-semibold tracking-[-0.025em] text-ink">{title}</h1>
          {description && <p className="mt-1.5 max-w-2xl text-base text-muted">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {meta && <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-muted">{meta}</div>}
    </div>
  );
}

export function SectionHeader({ title, description, actions, className }) {
  return (
    <div className={clsx("mb-3 flex flex-wrap items-end justify-between gap-2", className)}>
      <div className="min-w-0">
        <h2 className="text-lg font-semibold text-ink">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

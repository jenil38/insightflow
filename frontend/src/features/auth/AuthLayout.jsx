/**
 * Shared chrome for the unauthenticated screens, plus the Zod schemas and the
 * password strength helper the auth forms share.
 */
import { Link } from "react-router-dom";
import { Activity } from "lucide-react";
import { z } from "zod";

import ServerWakeNotice from "../../components/feedback/ServerWakeNotice.jsx";

export default function AuthLayout({ title, description, children, footer }) {
  return (
    // The mesh wash gives the raised card something to sit against; on a flat
    // canvas its shadow has nothing to fall on and the panel looks pasted down.
    <div className="mesh-bg grain relative flex min-h-screen items-center justify-center overflow-hidden bg-canvas px-4 py-10">
      <div className="relative z-10 w-full max-w-sm animate-rise-3d">
        <div className="mb-7 flex flex-col items-center text-center">
          <span
            className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-lift
                       text-accent-contrast shadow-rim glow-accent"
            aria-hidden="true"
          >
            <Activity size={22} />
          </span>
          <h1 className="text-2xl font-semibold tracking-[-0.02em] text-ink">{title}</h1>
          {description && <p className="mt-1.5 text-base text-muted">{description}</p>}
        </div>

        <ServerWakeNotice className="mb-4" />

        <div className="card shadow-depth-3 p-6 sm:p-7">{children}</div>

        {footer && <div className="mt-5 text-center text-base text-muted">{footer}</div>}

        <div className="rule-luxe mx-auto mt-7 w-32" />
        <p className="mt-4 text-center text-xs text-subtle">
          Insight<span className="text-luxe">Flow</span> &middot; self-service analytics
        </p>
      </div>
    </div>
  );
}

export function AuthLink({ to, children }) {
  return (
    <Link
      to={to}
      className="font-medium text-accent underline-offset-2 transition-colors hover:underline
                 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
    >
      {children}
    </Link>
  );
}

/* ------------------------------------------------------------------ schemas */

/**
 * Mirrors the backend's `validate_password_complexity` exactly (8+ chars, upper,
 * lower, digit, symbol). Keeping them in sync means the user is told about a
 * weak password while typing, instead of after a round trip.
 */
export const passwordSchema = z
  .string()
  .min(8, "Use at least 8 characters")
  .regex(/[A-Z]/, "Include an uppercase letter")
  .regex(/[a-z]/, "Include a lowercase letter")
  .regex(/\d/, "Include a number")
  .regex(/[^\w\s]/, "Include a symbol");

export const emailSchema = z.string().min(1, "Email is required").email("Enter a valid email address");

export const loginSchema = z.object({
  email: emailSchema,
  password: z.string().min(1, "Password is required"),
});

export const registerSchema = z.object({
  full_name: z.string().trim().max(120, "That name is too long").optional().or(z.literal("")),
  email: emailSchema,
  password: passwordSchema,
});

export const resetSchema = z
  .object({
    password: passwordSchema,
    confirm: z.string().min(1, "Confirm your password"),
  })
  .refine((values) => values.password === values.confirm, {
    message: "Passwords do not match",
    path: ["confirm"],
  });

/** The five backend rules, each with whether the current value satisfies it. */
export function passwordChecks(value = "") {
  return [
    { label: "8+ characters", met: value.length >= 8 },
    { label: "Uppercase letter", met: /[A-Z]/.test(value) },
    { label: "Lowercase letter", met: /[a-z]/.test(value) },
    { label: "Number", met: /\d/.test(value) },
    { label: "Symbol", met: /[^\w\s]/.test(value) },
  ];
}

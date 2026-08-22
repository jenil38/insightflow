/**
 * Password field with a visibility toggle and live rule checklist.
 *
 * The checklist mirrors the backend's complexity rules, so the user finds out
 * their password is too weak while typing rather than after a failed request.
 */
import { forwardRef, useState } from "react";
import clsx from "clsx";
import { Check, Eye, EyeOff, X } from "lucide-react";

import { Input } from "../../components/ui/index.jsx";
import { passwordChecks } from "./AuthLayout.jsx";

const PasswordInput = forwardRef(function PasswordInput(
  { showChecklist = false, value = "", invalid, ...rest },
  ref,
) {
  const [visible, setVisible] = useState(false);
  const checks = passwordChecks(value);

  return (
    <div>
      <div className="relative">
        <Input
          ref={ref}
          type={visible ? "text" : "password"}
          invalid={invalid}
          value={value}
          className="pr-10"
          {...rest}
        />
        {/* 40px square rather than sized to the icon: this is the one control
            on the auth screens a thumb has to hit, and a 28px box fails the
            minimum touch target on a phone. The icon stays visually small. */}
        <button
          type="button"
          onClick={() => setVisible((current) => !current)}
          aria-label={visible ? "Hide password" : "Show password"}
          aria-pressed={visible}
          className="absolute right-0.5 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center
                     rounded-lg text-subtle transition-colors hover:text-ink
                     focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
        >
          {visible ? <EyeOff size={15} aria-hidden="true" /> : <Eye size={15} aria-hidden="true" />}
        </button>
      </div>

      {showChecklist && value.length > 0 && (
        <ul className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1" aria-label="Password requirements">
          {checks.map((check) => (
            <li
              key={check.label}
              className={clsx(
                "flex items-center gap-1.5 text-xs",
                check.met ? "text-success" : "text-subtle",
              )}
            >
              {check.met ? (
                <Check size={12} aria-hidden="true" />
              ) : (
                <X size={12} aria-hidden="true" />
              )}
              <span>{check.label}</span>
              <span className="sr-only">{check.met ? "satisfied" : "not yet satisfied"}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
});

export default PasswordInput;

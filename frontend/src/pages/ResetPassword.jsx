import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";

import { normalizeError } from "../api/client.js";
import { auth as authApi } from "../api/endpoints.js";
import AuthLayout, { AuthLink, resetSchema } from "../features/auth/AuthLayout.jsx";
import PasswordInput from "../features/auth/PasswordInput.jsx";
import { Alert, Button, Field } from "../components/ui/index.jsx";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token");
  const navigate = useNavigate();
  const [formError, setFormError] = useState(null);

  const {
    register, handleSubmit, watch, formState: { errors, isSubmitting },
  } = useForm({ resolver: zodResolver(resetSchema), defaultValues: { password: "", confirm: "" } });

  const passwordValue = watch("password") || "";
  const confirmValue = watch("confirm") || "";

  async function onSubmit(values) {
    setFormError(null);
    try {
      await authApi.resetPassword(token, values.password);
      toast.success("Password updated. Please sign in.");
      navigate("/login", { replace: true });
    } catch (error) {
      const { message, code } = normalizeError(error, "Could not reset your password.");
      setFormError(
        code === "invalid_reset_token"
          ? "That reset link is invalid or has expired. Request a new one."
          : message,
      );
    }
  }

  // A missing token means the user opened this page directly rather than from a
  // reset email; there is nothing to submit.
  if (!token) {
    return (
      <AuthLayout title="Reset link required">
        <Alert tone="warning" title="No reset token">
          Open this page from the link in your password-reset email.
        </Alert>
        <div className="mt-4 flex flex-col gap-2">
          <Link to="/forgot-password">
            <Button variant="secondary" className="w-full">Request a new link</Button>
          </Link>
          <AuthLink to="/login">Back to sign in</AuthLink>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Choose a new password"
      description="Signing in again will be required everywhere after this."
      footer={<AuthLink to="/login">Back to sign in</AuthLink>}
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        {formError && <Alert tone="danger">{formError}</Alert>}

        <Field label="New password" htmlFor="password" error={errors.password?.message} required>
          <PasswordInput
            id="password"
            autoComplete="new-password"
            autoFocus
            showChecklist
            invalid={Boolean(errors.password)}
            {...register("password")}
            value={passwordValue}
          />
        </Field>

        <Field label="Confirm new password" htmlFor="confirm" error={errors.confirm?.message} required>
          <PasswordInput
            id="confirm"
            autoComplete="new-password"
            invalid={Boolean(errors.confirm)}
            {...register("confirm")}
            value={confirmValue}
          />
        </Field>

        <Button type="submit" className="w-full" loading={isSubmitting}>
          Update password
        </Button>
      </form>
    </AuthLayout>
  );
}

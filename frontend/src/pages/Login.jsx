import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";

import { normalizeError } from "../api/client.js";
import { useAuth } from "../app/providers.jsx";
import AuthLayout, { AuthLink, loginSchema } from "../features/auth/AuthLayout.jsx";
import PasswordInput from "../features/auth/PasswordInput.jsx";
import { Alert, Button, Field, Input } from "../components/ui/index.jsx";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [formError, setFormError] = useState(null);

  const {
    register, handleSubmit, watch, formState: { errors, isSubmitting },
  } = useForm({ resolver: zodResolver(loginSchema), defaultValues: { email: "", password: "" } });

  const passwordValue = watch("password") || "";

  async function onSubmit(values) {
    setFormError(null);
    try {
      await login(values.email, values.password);
      toast.success("Signed in");
      // Return the user to wherever they were headed before being redirected.
      navigate(location.state?.from || "/", { replace: true });
    } catch (error) {
      const { message, code } = normalizeError(error, "Could not sign in.");
      setFormError(
        code === "rate_limited" || code === "http_429"
          ? "Too many sign-in attempts. Wait a minute and try again."
          : message,
      );
    }
  }

  return (
    <AuthLayout
      title="Sign in to InsightFlow"
      description="Upload a dataset and get profiling, dashboards, and models."
      footer={<>No account yet? <AuthLink to="/register">Create one</AuthLink></>}
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        {formError && <Alert tone="danger">{formError}</Alert>}

        <Field label="Email" htmlFor="email" error={errors.email?.message} required>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            autoFocus
            placeholder="you@company.com"
            invalid={Boolean(errors.email)}
            {...register("email")}
          />
        </Field>

        <Field label="Password" htmlFor="password" error={errors.password?.message} required>
          <PasswordInput
            id="password"
            autoComplete="current-password"
            placeholder="Your password"
            invalid={Boolean(errors.password)}
            {...register("password")}
            value={passwordValue}
          />
        </Field>

        <div className="flex justify-end">
          <AuthLink to="/forgot-password">Forgot your password?</AuthLink>
        </div>

        <Button type="submit" className="w-full" loading={isSubmitting}>
          Sign in
        </Button>
      </form>
    </AuthLayout>
  );
}

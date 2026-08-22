import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";

import { normalizeError } from "../api/client.js";
import { auth as authApi } from "../api/endpoints.js";
import { useAuth } from "../app/providers.jsx";
import AuthLayout, { AuthLink, registerSchema } from "../features/auth/AuthLayout.jsx";
import PasswordInput from "../features/auth/PasswordInput.jsx";
import { Alert, Button, Field, Input } from "../components/ui/index.jsx";

export default function Register() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [formError, setFormError] = useState(null);

  const {
    register, handleSubmit, watch, formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(registerSchema),
    defaultValues: { full_name: "", email: "", password: "" },
  });

  const passwordValue = watch("password") || "";

  async function onSubmit(values) {
    setFormError(null);
    try {
      await authApi.register({
        email: values.email,
        password: values.password,
        full_name: values.full_name?.trim() || null,
      });
      // Sign straight in: making someone re-enter credentials they just typed
      // is friction with no security benefit.
      await login(values.email, values.password);
      toast.success("Account created");
      navigate("/", { replace: true });
    } catch (error) {
      const { message, code } = normalizeError(error, "Could not create your account.");
      setFormError(
        code === "email_taken"
          ? "An account with that email already exists. Try signing in instead."
          : message,
      );
    }
  }

  return (
    <AuthLayout
      title="Create your account"
      description="Free to set up. No credit card, no configuration."
      footer={<>Already registered? <AuthLink to="/login">Sign in</AuthLink></>}
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        {formError && <Alert tone="danger">{formError}</Alert>}

        <Field
          label="Full name"
          htmlFor="full_name"
          error={errors.full_name?.message}
          hint="Optional"
        >
          <Input
            id="full_name"
            autoComplete="name"
            placeholder="Alex Morgan"
            invalid={Boolean(errors.full_name)}
            {...register("full_name")}
          />
        </Field>

        <Field label="Email" htmlFor="email" error={errors.email?.message} required>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            placeholder="you@company.com"
            invalid={Boolean(errors.email)}
            {...register("email")}
          />
        </Field>

        <Field label="Password" htmlFor="password" error={errors.password?.message} required>
          <PasswordInput
            id="password"
            autoComplete="new-password"
            placeholder="Choose a strong password"
            showChecklist
            invalid={Boolean(errors.password)}
            {...register("password")}
            value={passwordValue}
          />
        </Field>

        <Button type="submit" className="w-full" loading={isSubmitting}>
          Create account
        </Button>
      </form>
    </AuthLayout>
  );
}

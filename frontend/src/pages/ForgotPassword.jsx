import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { MailCheck } from "lucide-react";

import { normalizeError } from "../api/client.js";
import { auth as authApi } from "../api/endpoints.js";
import AuthLayout, { AuthLink, emailSchema } from "../features/auth/AuthLayout.jsx";
import { Alert, Button, Field, Input } from "../components/ui/index.jsx";

const schema = z.object({ email: emailSchema });

export default function ForgotPassword() {
  const [sent, setSent] = useState(false);
  const [formError, setFormError] = useState(null);

  const {
    register, handleSubmit, getValues, formState: { errors, isSubmitting },
  } = useForm({ resolver: zodResolver(schema), defaultValues: { email: "" } });

  async function onSubmit(values) {
    setFormError(null);
    try {
      await authApi.requestPasswordReset(values.email);
      setSent(true);
    } catch (error) {
      setFormError(normalizeError(error, "Could not send the reset link.").message);
    }
  }

  if (sent) {
    return (
      <AuthLayout title="Check your email" footer={<AuthLink to="/login">Back to sign in</AuthLink>}>
        <div className="flex flex-col items-center py-2 text-center">
          <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-success-soft" aria-hidden="true">
            <MailCheck size={20} className="text-success" />
          </span>
          <p className="text-base text-ink">
            If <span className="font-medium">{getValues("email")}</span> is registered, a reset link is
            on its way.
          </p>
          {/* The backend answers identically either way, so we must not imply the
              address definitely exists. */}
          <p className="mt-2 text-sm text-muted">
            We do not confirm whether an address has an account, so this message appears either way.
          </p>
          <Alert tone="info" className="mt-4 text-left">
            In local development no email is actually sent - the reset link is written to the backend
            server log instead.
          </Alert>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Reset your password"
      description="We'll email you a link to choose a new one."
      footer={<AuthLink to="/login">Back to sign in</AuthLink>}
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
        <Button type="submit" className="w-full" loading={isSubmitting}>
          Send reset link
        </Button>
      </form>
    </AuthLayout>
  );
}

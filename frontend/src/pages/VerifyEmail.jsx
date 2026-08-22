import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { BadgeCheck, XCircle } from "lucide-react";

import { normalizeError } from "../api/client.js";
import { auth as authApi } from "../api/endpoints.js";
import AuthLayout, { AuthLink } from "../features/auth/AuthLayout.jsx";
import { Alert, Button, LoadingState } from "../components/ui/index.jsx";

export default function VerifyEmail() {
  const [params] = useSearchParams();
  const token = params.get("token");
  const [state, setState] = useState(token ? "verifying" : "missing");
  const [error, setError] = useState(null);
  const attempted = useRef(false);

  useEffect(() => {
    if (!token || attempted.current) return;
    // Guard against StrictMode's double-invoke consuming a single-use token twice.
    attempted.current = true;

    authApi
      .verifyEmail(token)
      .then(() => setState("verified"))
      .catch((err) => {
        setError(normalizeError(err, "Could not verify this email address.").message);
        setState("failed");
      });
  }, [token]);

  if (state === "verifying") {
    return (
      <AuthLayout title="Verifying your email">
        <LoadingState message="Verifying your email address" rows={2} />
      </AuthLayout>
    );
  }

  if (state === "verified") {
    return (
      <AuthLayout title="Email verified" footer={<AuthLink to="/login">Continue to sign in</AuthLink>}>
        <div className="flex flex-col items-center py-2 text-center">
          <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-success-soft" aria-hidden="true">
            <BadgeCheck size={20} className="text-success" />
          </span>
          <p className="text-base text-ink">Your email address is confirmed.</p>
          <Link to="/login" className="mt-4 w-full">
            <Button className="w-full">Sign in</Button>
          </Link>
        </div>
      </AuthLayout>
    );
  }

  if (state === "missing") {
    return (
      <AuthLayout title="Verification link required" footer={<AuthLink to="/login">Back to sign in</AuthLink>}>
        <Alert tone="warning" title="No verification token">
          Open this page using the link from your verification email.
        </Alert>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Verification failed" footer={<AuthLink to="/login">Back to sign in</AuthLink>}>
      <div className="flex flex-col items-center py-2 text-center">
        <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-danger-soft" aria-hidden="true">
          <XCircle size={20} className="text-danger" />
        </span>
        <p className="text-base text-ink">{error}</p>
        <p className="mt-2 text-sm text-muted">
          Verification links can only be used once. Your account still works either way - email
          verification is not required to sign in.
        </p>
      </div>
    </AuthLayout>
  );
}

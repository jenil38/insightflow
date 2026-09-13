/**
 * Routing and top-level composition.
 *
 * Feature pages are lazy-loaded so the initial bundle stays small - the
 * original build shipped one 744 kB chunk containing every chart library and ML
 * result view whether or not the user ever opened them.
 */
import { Suspense, lazy, useState } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";

import AppShell from "./components/layout/AppShell.jsx";
import ErrorBoundary from "./components/feedback/ErrorBoundary.jsx";
import ServerWakeNotice from "./components/feedback/ServerWakeNotice.jsx";
import UploadDialog from "./features/datasets/UploadDialog.jsx";
import { AuthProvider, ThemeProvider, createQueryClient, useAuth, useTheme } from "./app/providers.jsx";
import { LoadingState } from "./components/ui/index.jsx";

const Landing = lazy(() => import("./pages/Landing.jsx"));
const Login = lazy(() => import("./pages/Login.jsx"));
const Register = lazy(() => import("./pages/Register.jsx"));
const ForgotPassword = lazy(() => import("./pages/ForgotPassword.jsx"));
const ResetPassword = lazy(() => import("./pages/ResetPassword.jsx"));
const VerifyEmail = lazy(() => import("./pages/VerifyEmail.jsx"));
const Home = lazy(() => import("./pages/Home.jsx"));
const DatasetsPage = lazy(() => import("./pages/DatasetsPage.jsx"));
const Workspace = lazy(() => import("./pages/Workspace.jsx"));
const Settings = lazy(() => import("./pages/Settings.jsx"));

const queryClient = createQueryClient();

export default function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <ToastHost />
            <ErrorBoundary>
              <Suspense fallback={<RouteFallback />}>
                <Routes>
                  {/* Public */}
                  <Route path="/login" element={<PublicOnly><Login /></PublicOnly>} />
                  <Route path="/register" element={<PublicOnly><Register /></PublicOnly>} />
                  <Route path="/forgot-password" element={<PublicOnly><ForgotPassword /></PublicOnly>} />
                  <Route path="/reset-password" element={<ResetPassword />} />
                  <Route path="/verify-email" element={<VerifyEmail />} />

                  {/* Root: the marketing page for visitors, the dashboard once
                      signed in. Same URL either way, so no internal link or
                      bookmark has to change. */}
                  <Route element={<ProtectedLayout unauthenticated={<Landing />} />}>
                    <Route path="/" element={<Home />} />
                  </Route>

                  {/* Authenticated */}
                  <Route element={<ProtectedLayout />}>
                    <Route path="/datasets" element={<DatasetsPage />} />
                    <Route path="/workspace/:id" element={<Workspace />} />
                    <Route path="/settings" element={<Settings />} />
                  </Route>

                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </Suspense>
            </ErrorBoundary>
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

/** Toasts need to know the active theme to avoid a white card on a dark page. */
function ToastHost() {
  const { theme } = useTheme();
  return (
    <Toaster
      theme={theme}
      position="bottom-right"
      closeButton
      richColors
      toastOptions={{ duration: 5000 }}
    />
  );
}

function RouteFallback() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-16">
      {/* A returning signed-in user waits here while their session is checked,
          which on a cold server is the entire wake-up. */}
      <ServerWakeNotice className="mb-6" />
      <LoadingState message="Loading page" rows={4} />
    </div>
  );
}

/**
 * Gate for authenticated routes.
 *
 * While the stored token is being validated the status is "loading", and we
 * render a placeholder rather than redirecting - otherwise every hard refresh
 * bounces the user to /login before the session check completes.
 *
 * `unauthenticated` lets a route show public content instead of redirecting,
 * which is how `/` serves the landing page to visitors and the dashboard to
 * signed-in users under one path.
 */
function ProtectedLayout({ unauthenticated = null }) {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();
  const [uploadOpen, setUploadOpen] = useState(false);

  if (isLoading) return <RouteFallback />;
  if (!isAuthenticated) {
    return unauthenticated ?? (
      <Navigate to="/login" replace state={{ from: location.pathname }} />
    );
  }

  const openUpload = () => setUploadOpen(true);

  return (
    <AppShell onUploadClick={openUpload}>
      {/* Pages reach the upload dialog through outlet context rather than each
          rendering their own copy of it. */}
      <Outlet context={{ onUploadClick: openUpload }} />
      <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} />
    </AppShell>
  );
}

/** Redirect away from login/register when already signed in. */
function PublicOnly({ children }) {
  const { isAuthenticated, isLoading } = useAuth();
  if (isLoading) return <RouteFallback />;
  if (isAuthenticated) return <Navigate to="/" replace />;
  return children;
}

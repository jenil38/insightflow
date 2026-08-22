/**
 * Application-wide providers: theme, server-state cache, auth session, and an
 * error boundary.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { toast } from "sonner";

import client, { errorMessage, onSessionExpired, tokenStore } from "../api/client.js";
import { auth as authApi } from "../api/endpoints.js";

/* ------------------------------------------------------------------- theme */

const ThemeContext = createContext(null);
const THEME_KEY = "if_theme";
const APPEARANCE_KEY = "if_appearance";

const DARK_QUERY = "(prefers-color-scheme: dark)";

/**
 * Appearance preferences, applied as data attributes on <html> and read by the
 * rules at the bottom of index.css. Defaults are the full-fidelity treatment;
 * every other value trades visual effect for rendering cost.
 */
export const APPEARANCE_DEFAULTS = {
  depth: "full",        // full | balanced | flat
  motion: "full",       // full | subtle | off
  density: "default",   // default | compact | spacious
};

function readAppearance() {
  try {
    const stored = JSON.parse(localStorage.getItem(APPEARANCE_KEY) || "{}");
    // Spread over the defaults rather than trusting the stored object, so a
    // key added in a later release doesn't come back undefined for users who
    // already have preferences saved.
    return { ...APPEARANCE_DEFAULTS, ...stored };
  } catch {
    return { ...APPEARANCE_DEFAULTS };
  }
}

export function ThemeProvider({ children }) {
  // `preference` is what the user chose ("system" included); `theme` is what
  // that resolves to right now. Keeping them separate is what lets Settings
  // show "System" as selected while the UI renders dark.
  const [preference, setPreference] = useState(() => {
    const stored = localStorage.getItem(THEME_KEY);
    return stored === "light" || stored === "dark" || stored === "system" ? stored : "system";
  });

  const [systemTheme, setSystemTheme] = useState(() =>
    window.matchMedia?.(DARK_QUERY).matches ? "dark" : "light",
  );

  const [appearance, setAppearance] = useState(readAppearance);

  // Track the OS setting continuously, not just at mount - on "system" the app
  // should follow the OS flipping at sunset without needing a reload.
  useEffect(() => {
    const media = window.matchMedia?.(DARK_QUERY);
    if (!media) return undefined;
    const onChange = (event) => setSystemTheme(event.matches ? "dark" : "light");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  const theme = preference === "system" ? systemTheme : preference;

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", theme);
    // Tells the browser which scrollbars, form controls and canvas to paint.
    root.style.colorScheme = theme;
    localStorage.setItem(THEME_KEY, preference);
  }, [theme, preference]);

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-depth", appearance.depth);
    root.setAttribute("data-motion", appearance.motion);
    root.setAttribute("data-density", appearance.density);
    localStorage.setItem(APPEARANCE_KEY, JSON.stringify(appearance));
  }, [appearance]);

  const value = useMemo(
    () => ({
      theme,
      preference,
      systemTheme,
      setTheme: setPreference,
      // Toggling from "system" resolves to the opposite of what is on screen,
      // which is what the user means by clicking the toggle.
      toggleTheme: () => setPreference(theme === "dark" ? "light" : "dark"),
      appearance,
      setAppearance: (patch) => setAppearance((current) => ({ ...current, ...patch })),
      resetAppearance: () => setAppearance({ ...APPEARANCE_DEFAULTS }),
    }),
    [theme, preference, systemTheme, appearance],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside ThemeProvider");
  return context;
}

/* ------------------------------------------------------------ query client */

export function createQueryClient() {
  return new QueryClient({
    // Surface background refetch failures once, centrally, instead of leaving
    // them silent or duplicating toast logic in every component.
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (query.state.data !== undefined) {
          toast.error(errorMessage(error, "Could not refresh data."));
        }
      },
    }),
    defaultOptions: {
      queries: {
        // Analysis results are expensive to compute and don't change unless the
        // user acts, so they stay fresh for a while. This is what makes results
        // survive tab switches without re-running anything.
        staleTime: 5 * 60 * 1000,
        gcTime: 30 * 60 * 1000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          const status = error?.response?.status;
          // Never retry a client error - the answer will not change.
          if (status && status >= 400 && status < 500) return false;
          return failureCount < 2;
        },
      },
      mutations: { retry: false },
    },
  });
}

/* -------------------------------------------------------------------- auth */

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  // "loading" until we know whether the stored token is actually valid - this
  // is what stops protected routes flashing their contents before redirecting.
  const [status, setStatus] = useState(tokenStore.hasSession() ? "loading" : "anonymous");

  const loadUser = useCallback(async () => {
    if (!tokenStore.hasSession()) {
      setUser(null);
      setStatus("anonymous");
      return null;
    }
    try {
      const profile = await authApi.me();
      setUser(profile);
      setStatus("authenticated");
      return profile;
    } catch {
      // The interceptor already tried to refresh; reaching here means the
      // session is genuinely dead.
      tokenStore.clear();
      setUser(null);
      setStatus("anonymous");
      return null;
    }
  }, []);

  useEffect(() => {
    loadUser();
  }, [loadUser]);

  // Forced logout from the axios layer (refresh failed).
  useEffect(
    () =>
      onSessionExpired(() => {
        setUser(null);
        setStatus("anonymous");
        toast.error("Your session expired. Please sign in again.");
      }),
    [],
  );

  const login = useCallback(
    async (email, password) => {
      const tokens = await authApi.login({ email, password });
      tokenStore.set(tokens);
      const profile = await loadUser();
      return profile;
    },
    [loadUser],
  );

  const logout = useCallback(async () => {
    const refreshToken = tokenStore.getRefresh();
    // Revoke server-side so the refresh token cannot be reused. The original
    // implementation only cleared localStorage, leaving it valid until expiry.
    if (refreshToken) {
      try {
        await authApi.logout(refreshToken);
      } catch {
        // Even if revocation fails, local state must still be cleared.
      }
    }
    tokenStore.clear();
    setUser(null);
    setStatus("anonymous");
  }, []);

  const value = useMemo(
    () => ({
      user,
      status,
      isAuthenticated: status === "authenticated",
      isLoading: status === "loading",
      login,
      logout,
      reload: loadUser,
    }),
    [user, status, login, logout, loadUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

/** Exposed for tests and debugging. */
export { client };

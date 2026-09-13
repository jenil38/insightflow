/**
 * Axios instance with a real refresh-token flow.
 *
 * The previous version stored only the access token and never refreshed it, so
 * the app died silently 30 minutes after login and `logout()` left the refresh
 * token valid on the server forever.
 *
 * Behaviour here:
 * - Access token attached to every request.
 * - On a 401, refresh is attempted exactly once per request, and concurrent
 *   401s share a single in-flight refresh (so ten parallel requests produce one
 *   refresh call, not ten - which would rotate the token out from under itself).
 * - If refresh fails, all auth state is cleared and listeners are notified so
 *   the router can redirect to /login.
 *
 * Security note: tokens live in localStorage, which is readable by any script
 * on the page and therefore vulnerable to XSS. An HttpOnly + Secure + SameSite
 * refresh cookie is the stronger design, but it requires the backend to set and
 * read cookies and a CSRF strategy to go with it. That trade-off is documented
 * in the README under Security notes.
 */
import axios from "axios";

export const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const ACCESS_TOKEN_KEY = "if_token";
const REFRESH_TOKEN_KEY = "if_refresh_token";

/* ------------------------------------------------------------ token store */

export const tokenStore = {
  getAccess: () => localStorage.getItem(ACCESS_TOKEN_KEY),
  getRefresh: () => localStorage.getItem(REFRESH_TOKEN_KEY),
  set({ access_token, refresh_token }) {
    if (access_token) localStorage.setItem(ACCESS_TOKEN_KEY, access_token);
    if (refresh_token) localStorage.setItem(REFRESH_TOKEN_KEY, refresh_token);
  },
  clear() {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
  },
  hasSession: () => Boolean(localStorage.getItem(ACCESS_TOKEN_KEY)),
};

/* --------------------------------------------------- session-expiry events */

const sessionListeners = new Set();

/** Subscribe to forced logout (refresh failed / no refresh token). */
export function onSessionExpired(listener) {
  sessionListeners.add(listener);
  return () => sessionListeners.delete(listener);
}

function notifySessionExpired() {
  sessionListeners.forEach((listener) => listener());
}

/* ------------------------------------------------------------------ client */

const client = axios.create({ baseURL: API_BASE });

// A bare instance for refresh calls: using `client` would recurse through this
// same interceptor if the refresh endpoint itself returned 401.
const refreshClient = axios.create({ baseURL: API_BASE });

client.interceptors.request.use((config) => {
  const token = tokenStore.getAccess();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let refreshPromise = null;

function refreshAccessToken() {
  // Collapse concurrent refreshes into one request.
  if (refreshPromise) return refreshPromise;

  const refreshToken = tokenStore.getRefresh();
  if (!refreshToken) return Promise.reject(new Error("no_refresh_token"));

  refreshPromise = refreshClient
    .post("/auth/refresh", { refresh_token: refreshToken })
    .then((response) => {
      tokenStore.set(response.data);
      return response.data.access_token;
    })
    .finally(() => {
      refreshPromise = null;
    });

  return refreshPromise;
}

client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { response, config } = error;

    // Only 401s are recoverable by refreshing, and only once per request.
    if (response?.status !== 401 || config?._retriedAfterRefresh) {
      return Promise.reject(error);
    }

    // A 401 from an auth endpoint means bad credentials, not a stale token.
    if (config?.url?.includes("/auth/login") || config?.url?.includes("/auth/refresh")) {
      return Promise.reject(error);
    }

    try {
      const token = await refreshAccessToken();
      config._retriedAfterRefresh = true;
      config.headers = { ...config.headers, Authorization: `Bearer ${token}` };
      return client(config);
    } catch {
      tokenStore.clear();
      notifySessionExpired();
      return Promise.reject(error);
    }
  },
);

/* ------------------------------------------------------- error normalisation */

/**
 * Turn any axios failure into a predictable shape.
 *
 * The backend returns `{detail, error_code, request_id}`, but `detail` is an
 * array for FastAPI validation errors, and network failures have no response at
 * all. Callers should never have to handle those three cases separately.
 */
export function normalizeError(error, fallback = "Something went wrong.") {
  if (!error) return { message: fallback, code: "unknown", status: null };

  if (error.code === "ERR_CANCELED" || error.name === "CanceledError") {
    return { message: "Request cancelled.", code: "cancelled", status: null };
  }

  if (!error.response) {
    // No response object means the request never completed: the backend is
    // down, VITE_API_BASE is wrong, or - most often in local development - the
    // CORS preflight was rejected because this origin isn't in CORS_ORIGINS.
    // A browser deliberately hides the distinction from JavaScript, so the
    // message has to name all three.
    return {
      message:
        "Could not reach the API. Check that the backend is running, that " +
        `VITE_API_BASE points at it, and that CORS_ORIGINS on the backend includes ${window.location.origin}.`,
      code: "network_error",
      status: null,
    };
  }

  const { status, data } = error.response;
  const code = data?.error_code || `http_${status}`;
  let message = data?.detail;

  if (Array.isArray(message)) {
    // FastAPI validation errors: surface the field name, which is what makes
    // the message actionable.
    message = message
      .map((item) => {
        const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : null;
        return field ? `${field}: ${item.msg}` : item.msg;
      })
      .join("; ");
  }

  if (typeof message !== "string" || !message) {
    message =
      {
        401: "Your session has expired. Please sign in again.",
        403: "You do not have permission to do that.",
        404: "That item could not be found.",
        413: "That file is too large.",
        429: "Too many requests. Wait a moment and try again.",
        500: "The server hit an unexpected error.",
        502: "An upstream service is unavailable.",
        503: "That feature is not available on this server.",
        504: "The server took too long to respond.",
      }[status] || fallback;
  }

  return { message, code, status, requestId: data?.request_id };
}

/** Convenience for toast handlers. */
export function errorMessage(error, fallback) {
  return normalizeError(error, fallback).message;
}

export default client;

/**
 * Backend wake-up.
 *
 * The API is hosted on an instance that is suspended after a quiet period, and
 * the first request after that waits for a full cold start - measured at over a
 * minute. This module sends one cheap request as soon as the bundle loads, so
 * that wait begins while the visitor is still reading the landing page or
 * typing their password, rather than after they press "Sign in".
 *
 * It is a plain `fetch` with no custom headers on purpose: that keeps it a CORS
 * "simple request", which the browser sends without a preflight round trip.
 * Going through the axios client would attach an Authorization header and cost
 * an extra OPTIONS request to a server that is, by assumption, asleep.
 */
import { API_BASE } from "./client.js";

// Longer than the slowest cold start observed, so a slow wake-up is reported
// as slow rather than as a failure.
const TIMEOUT_MS = 120_000;

let state = { status: "idle", startedAt: null, finishedAt: null };
const listeners = new Set();
let started = false;

function update(patch) {
  state = { ...state, ...patch };
  listeners.forEach((listener) => listener());
}

/** Idempotent: only the first call sends a request. */
export function wakeServer() {
  if (started) return;
  started = true;
  update({ status: "waking", startedAt: Date.now() });

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  // `no-cors`: the goal is to make the server start, not to read its reply. An
  // opaque response still only arrives once the server has actually answered,
  // and this way the ping also works from origins the API's CORS list doesn't
  // include (local dev on another port, Vercel preview deployments) instead of
  // reporting a healthy server as unreachable.
  fetch(`${API_BASE}/health`, { mode: "no-cors", cache: "no-store", signal: controller.signal })
    .then(() => update({ status: "ready", finishedAt: Date.now() }))
    .catch(() => update({ status: "unreachable", finishedAt: Date.now() }))
    .finally(() => clearTimeout(timer));
}

/* Shaped for React's useSyncExternalStore: the snapshot is a stable reference
   until something actually changes. */
export function getServerWakeState() {
  return state;
}

export function subscribeServerWake(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

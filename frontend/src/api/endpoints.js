/**
 * Every backend call the app makes, in one place.
 *
 * Components never build URLs; they call these functions. That keeps the API
 * surface auditable and means a route change is a one-line edit here.
 * Paths use the versioned /api/v1 prefix.
 */
import client from "./client.js";

const V1 = "/api/v1";

/* -------------------------------------------------------------------- auth */

export const auth = {
  register: (payload) => client.post(`${V1}/auth/register`, payload).then((r) => r.data),
  login: (payload) => client.post(`${V1}/auth/login`, payload).then((r) => r.data),
  logout: (refreshToken) =>
    client.post(`${V1}/auth/logout`, { refresh_token: refreshToken }).then((r) => r.data),
  me: () => client.get(`${V1}/auth/me`).then((r) => r.data),
  verifyEmail: (token) => client.post(`${V1}/auth/verify-email`, { token }).then((r) => r.data),
  requestPasswordReset: (email) =>
    client.post(`${V1}/auth/request-password-reset`, { email }).then((r) => r.data),
  resetPassword: (token, newPassword) =>
    client.post(`${V1}/auth/reset-password`, { token, new_password: newPassword }).then((r) => r.data),
};

/* --------------------------------------------------------------------- ops */

export const ops = {
  health: () => client.get("/health").then((r) => r.data),
};

export const users = {
  summary: () => client.get(`${V1}/users/me/summary`).then((r) => r.data),
};

/* ---------------------------------------------------------------- datasets */

export const datasets = {
  list: () => client.get(`${V1}/datasets`).then((r) => r.data),
  listWithStatus: () => client.get(`${V1}/datasets/with-status`).then((r) => r.data),
  get: (id) => client.get(`${V1}/datasets/${id}`).then((r) => r.data),
  remove: (id) => client.delete(`${V1}/datasets/${id}`).then((r) => r.data),

  upload: (file, { onProgress, signal } = {}) => {
    const form = new FormData();
    form.append("file", file);
    return client
      .post(`${V1}/datasets/upload`, form, {
        headers: { "Content-Type": "multipart/form-data" },
        signal,
        onUploadProgress: (event) => {
          if (!onProgress) return;
          // event.total is absent on some proxies; report indeterminate rather
          // than dividing by undefined.
          const pct = event.total ? Math.round((event.loaded / event.total) * 100) : null;
          onProgress(pct);
        },
      })
      .then((r) => r.data);
  },

  preview: (id, params) => client.get(`${V1}/datasets/${id}/preview`, { params }).then((r) => r.data),
  columns: (id, useCleaned = true) =>
    client.get(`${V1}/datasets/${id}/columns`, { params: { use_cleaned: useCleaned } }).then((r) => r.data),
  columnProfile: (id, column, useCleaned = true) =>
    client
      .get(`${V1}/datasets/${id}/columns/${encodeURIComponent(column)}`, {
        params: { use_cleaned: useCleaned },
      })
      .then((r) => r.data),
  exportCsv: (id, useCleaned = true) =>
    client.get(`${V1}/datasets/${id}/export`, {
      params: { use_cleaned: useCleaned },
      responseType: "blob",
    }),
};

/* ------------------------------------------------------- profiling/quality */

export const quality = {
  profile: (id) => client.get(`${V1}/datasets/${id}/profile`).then((r) => r.data),
  report: (id) => client.get(`${V1}/datasets/${id}/quality`).then((r) => r.data),
  targetCandidates: (id) => client.get(`${V1}/datasets/${id}/target-candidates`).then((r) => r.data),
};

/* ---------------------------------------------------------------- cleaning */

export const cleaning = {
  plan: (id) => client.get(`${V1}/datasets/${id}/clean/plan`).then((r) => r.data),
  preview: (id, config) =>
    client.post(`${V1}/datasets/${id}/clean/preview`, { config }).then((r) => r.data),
  apply: (id, config) =>
    client.post(`${V1}/datasets/${id}/clean/apply`, { config }).then((r) => r.data),
  revert: (id) => client.post(`${V1}/datasets/${id}/clean/revert`).then((r) => r.data),
};

/* --------------------------------------------------------------- analytics */

export const analytics = {
  dashboard: (id) => client.get(`${V1}/datasets/${id}/dashboard`).then((r) => r.data),
  query: (id, body) => client.post(`${V1}/datasets/${id}/analytics/query`, body).then((r) => r.data),
  listLayouts: (id) => client.get(`${V1}/datasets/${id}/dashboard-layouts`).then((r) => r.data),
  createLayout: (id, body) =>
    client.post(`${V1}/datasets/${id}/dashboard-layouts`, body).then((r) => r.data),
  updateLayout: (id, layoutId, body) =>
    client.put(`${V1}/datasets/${id}/dashboard-layouts/${layoutId}`, body).then((r) => r.data),
  deleteLayout: (id, layoutId) =>
    client.delete(`${V1}/datasets/${id}/dashboard-layouts/${layoutId}`).then((r) => r.data),
};

/* ---------------------------------------------------------------------- ml */

export const ml = {
  options: (id) => client.get(`${V1}/datasets/${id}/train/options`).then((r) => r.data),
  train: (id, body) => client.post(`${V1}/datasets/${id}/train`, body).then((r) => r.data),
  history: (id) => client.get(`${V1}/datasets/${id}/model/history`).then((r) => r.data),
  downloadUrl: (id) => `${V1}/datasets/${id}/model/download`,
  download: (id) => client.get(`${V1}/datasets/${id}/model/download`, { responseType: "blob" }),
};

export const explain = {
  get: (id) => client.get(`${V1}/datasets/${id}/explain`).then((r) => r.data),
};

/* ----------------------------------------------------------------- copilot */

export const copilot = {
  ask: (id, question) => client.post(`${V1}/datasets/${id}/chat`, { question }).then((r) => r.data),
  history: (id) => client.get(`${V1}/datasets/${id}/chat/history`).then((r) => r.data),
  clear: (id) => client.delete(`${V1}/datasets/${id}/chat/history`).then((r) => r.data),
  suggestions: (id) => client.get(`${V1}/datasets/${id}/chat/suggestions`).then((r) => r.data),
};

/* -------------------------------------------------------------------- jobs */

export const jobs = {
  list: () => client.get(`${V1}/jobs`).then((r) => r.data),
  get: (id) => client.get(`${V1}/jobs/${id}`).then((r) => r.data),
  cancel: (id) => client.post(`${V1}/jobs/${id}/cancel`).then((r) => r.data),
};

/* ------------------------------------------------------------------- agent */

export const agent = {
  run: (id, { applyCleaning = true, train = true } = {}) =>
    client
      .post(`${V1}/datasets/${id}/agent/run`, null, {
        params: { apply_cleaning: applyCleaning, train },
      })
      .then((r) => r.data),
};

/* ------------------------------------------------------------------ report */

export const reports = {
  download: (id) => client.get(`${V1}/datasets/${id}/report`, { responseType: "blob" }),
  history: (id) => client.get(`${V1}/datasets/${id}/report/history`).then((r) => r.data),
};

/* ------------------------------------------------------------------ helpers */

/** Trigger a browser download from a blob response, honouring the server's
 *  Content-Disposition filename when present. */
export function saveBlobResponse(response, fallbackName) {
  const disposition = response.headers?.["content-disposition"] || "";
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  const filename = match ? decodeURIComponent(match[1]) : fallbackName;

  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoking immediately can cancel the download in some browsers.
  setTimeout(() => window.URL.revokeObjectURL(url), 1000);
}

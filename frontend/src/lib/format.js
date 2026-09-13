/**
 * Formatting helpers.
 *
 * Every one of these treats null/undefined/NaN as "no value" and renders a dash,
 * because the API legitimately returns null for statistics that don't apply
 * (the mean of a text column, a correlation on a constant column) and printing
 * "NaN" or "null" in a table is worse than printing nothing.
 */

const DASH = "-";

export function formatNumber(value, { decimals, compact = false } = {}) {
  if (value === null || value === undefined || value === "") return DASH;
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return DASH;

  if (compact && Math.abs(numeric) >= 10_000) {
    return numeric.toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 1 });
  }
  if (decimals !== undefined) {
    return numeric.toLocaleString(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }
  // Integers print without decimals; floats get up to 4 significant decimals.
  return Number.isInteger(numeric)
    ? numeric.toLocaleString()
    : numeric.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

export function formatPercent(value, decimals = 1) {
  if (value === null || value === undefined) return DASH;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return DASH;
  return `${numeric.toFixed(decimals)}%`;
}

export function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return DASH;
  const numeric = Number(bytes);
  if (!Number.isFinite(numeric) || numeric < 0) return DASH;
  if (numeric === 0) return "0 B";

  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(numeric) / Math.log(1024)), units.length - 1);
  const value = numeric / 1024 ** exponent;
  return `${value.toFixed(exponent === 0 ? 0 : 1)} ${units[exponent]}`;
}

export function formatDate(value, { withTime = false } = {}) {
  if (!value) return DASH;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return DASH;
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

/** "3 hours ago" / "in 2 days", falling back to an absolute date past a week. */
export function formatRelative(value) {
  if (!value) return DASH;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return DASH;

  const seconds = (date.getTime() - Date.now()) / 1000;
  const absolute = Math.abs(seconds);
  if (absolute > 7 * 86400) return formatDate(value);

  const units = [
    ["second", 60],
    ["minute", 60],
    ["hour", 24],
    ["day", 7],
  ];
  let amount = seconds;
  for (const [unit, size] of units) {
    if (Math.abs(amount) < size) {
      return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(
        Math.round(amount),
        unit,
      );
    }
    amount /= size;
  }
  return formatDate(value);
}

/** Render any cell value for a table, including nulls and objects. */
export function formatCell(value) {
  if (value === null || value === undefined) return null; // caller renders the null badge
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function titleCase(value) {
  if (!value) return "";
  return String(value)
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

/** Metric keys -> the labels used across results screens and the PDF. */
export const METRIC_LABELS = {
  r2: "R²",
  mae: "MAE",
  rmse: "RMSE",
  mape: "MAPE",
  f1: "F1",
  accuracy: "Accuracy",
  precision: "Precision",
  recall: "Recall",
  roc_auc: "ROC-AUC",
  score: "Score",
  cv_score: "CV score",
};

export const METRIC_HELP = {
  r2: "Share of variance in the target explained by the model. 1.0 is perfect, 0 is no better than predicting the mean.",
  mae: "Mean absolute error, in the target's own units. Lower is better.",
  rmse: "Root mean squared error, in the target's units. Penalises large misses more than MAE.",
  mape: "Mean absolute percentage error. Only shown when no actual value is zero.",
  f1: "Harmonic mean of precision and recall, weighted across classes. Better than accuracy on imbalanced data.",
  accuracy: "Share of predictions that were correct. Misleading when classes are imbalanced.",
  precision: "Of the rows predicted positive, how many were. Weighted across classes.",
  recall: "Of the actually-positive rows, how many were found. Weighted across classes.",
  roc_auc: "Probability the model ranks a random positive above a random negative. 0.5 is chance.",
  cv_score: "Mean score across cross-validation folds - a more reliable signal than a single split.",
};

export function metricLabel(key) {
  return METRIC_LABELS[key] || titleCase(key);
}

/** Chart series colours, read from the CSS variables so charts follow the theme. */
export function chartColor(index) {
  return `rgb(var(--chart-${(index % 6) + 1}))`;
}

export const CHART_AXIS_COLOR = "rgb(var(--chart-axis))";
export const CHART_GRID_COLOR = "rgb(var(--chart-grid))";

/**
 * Explainability.
 *
 * The method actually used is displayed prominently. The original UI claimed
 * "powered by SHAP" unconditionally while the backend silently fell back to
 * model feature importances, so the label could be simply false.
 */
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Brain, Info, Lightbulb, ShieldQuestion } from "lucide-react";

import { errorMessage, normalizeError } from "../../api/client.js";
import { explain as explainApi } from "../../api/endpoints.js";
import {
  Alert, Badge, Card, CardBody, CardHeader, EmptyState, ErrorState, Skeleton, Tooltip,
} from "../../components/ui/index.jsx";
import { formatDate, formatPercent } from "../../lib/format.js";

const METHOD_TONE = {
  shap: "success",
  model_feature_importance: "accent",
  coefficients: "accent",
  permutation_importance: "warning",
};

const METHOD_NOTE = {
  shap:
    "Shapley values attribute each prediction to its features exactly, then average across rows. " +
    "This is the most faithful attribution available.",
  model_feature_importance:
    "The model's own importance scores. For tree ensembles this reflects how often and how " +
    "effectively each feature was used for splitting.",
  coefficients:
    "Linear model coefficients, each scaled by its feature's standard deviation so magnitudes are " +
    "comparable across columns measured on different scales.",
  permutation_importance:
    "Each column is shuffled in turn and the drop in score measured. Model-agnostic, and it " +
    "reflects what the model actually relies on at prediction time.",
};

export default function ExplainPanel({ datasetId, onGoToModels }) {
  const query = useQuery({
    queryKey: ["explain", datasetId],
    queryFn: () => explainApi.get(datasetId),
    retry: false,
  });

  if (query.isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  if (query.isError) {
    const { code, message } = normalizeError(query.error);
    // Not-yet-trained is a normal state, not an error to apologise for.
    if (code === "no_trained_model") {
      return (
        <EmptyState
          icon={Brain}
          title="Train a model first"
          description="Explanations describe a specific trained model, so there's nothing to explain until you train one."
          action={
            onGoToModels && (
              <button
                type="button"
                onClick={onGoToModels}
                className="text-base font-medium text-accent hover:underline"
              >
                Go to Models
              </button>
            )
          }
        />
      );
    }
    return (
      <ErrorState
        title="Could not explain this model"
        message={message}
        onRetry={query.refetch}
      />
    );
  }

  const report = query.data;
  const maxImportance = Math.max(...report.feature_importance.map((f) => f.importance_pct || 0), 1);

  return (
    <div className="space-y-5">
      {/* Method + model context */}
      <Card>
        <CardBody className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted">Method</span>
            <Badge tone={METHOD_TONE[report.method] || "neutral"}>{report.method_label}</Badge>
            {report.fallback_used ? (
              <Badge tone="warning">Fallback</Badge>
            ) : (
              <Badge tone="success">Preferred method</Badge>
            )}
            <span className="ml-auto text-sm text-muted">
              {report.model_name} v{report.model_version} &middot;{" "}
              {formatDate(report.trained_at, { withTime: true })}
            </span>
          </div>

          <div className="flex items-start gap-2 rounded-md bg-canvas px-3 py-2.5">
            <Info size={14} className="mt-0.5 shrink-0 text-subtle" aria-hidden="true" />
            <div className="text-sm text-muted">
              <p>{METHOD_NOTE[report.method]}</p>
              {report.fallback_used && report.fallback_reason && (
                <p className="mt-1">
                  <span className="font-medium text-ink">Why not SHAP:</span> {report.fallback_reason}.
                </p>
              )}
            </div>
          </div>

          <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted">
            <span>Predicting <span className="font-medium text-ink">{report.target_column}</span></span>
            <span>Task: {report.task_type}</span>
            <span>{report.rows_explained} rows analysed</span>
            <span>{report.data_source} data</span>
          </div>
        </CardBody>
      </Card>

      {/* Interpretation */}
      <Alert tone="info" title="What this means">{report.interpretation}</Alert>

      {/* Importance ranking */}
      <Card>
        <CardHeader
          title="Feature importance"
          description="Share of total measured importance, largest first"
        />
        <CardBody className="space-y-3">
          {report.feature_importance.map((feature) => (
            <div key={feature.feature}>
              <div className="mb-1 flex items-baseline justify-between gap-3">
                <span className="min-w-0 truncate text-base text-ink">{feature.feature}</span>
                <span className="shrink-0 text-sm font-medium tabular-nums text-muted">
                  {formatPercent(feature.importance_pct, 2)}
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-canvas">
                <div
                  className="h-full rounded-full bg-accent transition-[width] duration-500"
                  style={{ width: `${((feature.importance_pct || 0) / maxImportance) * 100}%` }}
                />
              </div>
              {feature.direction && (
                <p className="mt-0.5 text-2xs text-subtle">
                  Typically {feature.direction} the prediction
                </p>
              )}
            </div>
          ))}
        </CardBody>
      </Card>

      {/* Caveats */}
      <Card>
        <CardHeader title="How to read this" />
        <CardBody>
          <ul className="space-y-2">
            {report.caveats.map((caveat, index) => (
              <li key={index} className="flex items-start gap-2.5 text-sm text-muted">
                <ShieldQuestion size={13} className="mt-0.5 shrink-0 text-warning" aria-hidden="true" />
                {caveat}
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>
    </div>
  );
}

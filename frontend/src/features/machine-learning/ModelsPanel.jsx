/**
 * Model training: configure -> train -> leaderboard, diagnostics, and history.
 *
 * The original endpoint guessed the target and gave the user no say. Here the
 * recommendation is shown with its reasoning and remains fully overridable, and
 * only metrics appropriate to the detected task are displayed.
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Scatter,
  ScatterChart, Tooltip as ReTooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import { toast } from "sonner";
import clsx from "clsx";
import {
  AlertTriangle, Award, Brain, Download, History, Play, Settings2, TrendingUp,
} from "lucide-react";

import { errorMessage, normalizeError } from "../../api/client.js";
import { ml as mlApi, saveBlobResponse } from "../../api/endpoints.js";
import {
  Alert, Badge, Button, Card, CardBody, CardHeader, Checkbox, EmptyState, ErrorState,
  Field, LoadingOverlay, Progress, SectionHeader, Select, Skeleton, Tooltip,
} from "../../components/ui/index.jsx";
import {
  CHART_AXIS_COLOR, CHART_GRID_COLOR, chartColor, formatDate, formatNumber,
  formatPercent, metricLabel, METRIC_HELP,
} from "../../lib/format.js";

export default function ModelsPanel({ datasetId }) {
  const queryClient = useQueryClient();
  const [config, setConfig] = useState(null);
  const [showConfig, setShowConfig] = useState(true);

  const options = useQuery({
    queryKey: ["train-options", datasetId],
    queryFn: () => mlApi.options(datasetId),
  });

  const history = useQuery({
    queryKey: ["model-history", datasetId],
    queryFn: () => mlApi.history(datasetId),
  });

  // Seed the form from the server's recommendation.
  useEffect(() => {
    if (options.data && !config) {
      setConfig({
        target_column: options.data.recommended_target || "",
        task_type: "auto",
        excluded_columns: options.data.suggested_exclusions.map((e) => e.column),
        test_size: 0.2,
        cross_validation_folds: 5,
        enable_tuning: true,
        use_cleaned: true,
      });
    }
  }, [options.data, config]);

  const train = useMutation({
    mutationFn: (payload) => mlApi.train(datasetId, payload),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["model-history", datasetId] });
      queryClient.invalidateQueries({ queryKey: ["dataset", String(datasetId)] });
      queryClient.invalidateQueries({ queryKey: ["explain", datasetId] });
      queryClient.invalidateQueries({ queryKey: ["user-summary"] });
      setShowConfig(false);
      toast.success(`${result.best_model} performed best`, {
        description: `${result.results.length} models compared on ${formatNumber(result.rows_used)} rows.`,
      });
    },
    onError: (error) => toast.error(errorMessage(error, "Training failed.")),
  });

  async function handleDownload() {
    try {
      const response = await mlApi.download(datasetId);
      saveBlobResponse(response, "model.joblib");
      toast.success("Model downloaded");
    } catch (error) {
      toast.error(errorMessage(error, "Could not download the model."));
    }
  }

  if (options.isLoading || !config) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-56 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (options.isError) {
    return (
      <ErrorState
        title="Could not load training options"
        message={errorMessage(options.error)}
        onRetry={options.refetch}
      />
    );
  }

  const result = train.data;
  const trainError = train.isError ? normalizeError(train.error) : null;
  const hasHistory = (history.data?.length || 0) > 0;

  return (
    <div className="space-y-5">
      {/* Configuration */}
      <Card className="relative">
        {train.isPending && (
          <LoadingOverlay message="Training and comparing models - this can take a minute" />
        )}
        <CardHeader
          title="Training configuration"
          description="Recommendations are a starting point; every option is yours to change"
          actions={
            <div className="flex gap-2">
              <Button
                variant="ghost"
                size="sm"
                icon={Settings2}
                onClick={() => setShowConfig((open) => !open)}
              >
                {showConfig ? "Hide" : "Show"}
              </Button>
              <Button
                size="sm"
                icon={Play}
                loading={train.isPending}
                onClick={() =>
                  train.mutate({
                    ...config,
                    target_column: config.target_column || null,
                  })
                }
              >
                Train models
              </Button>
            </div>
          }
        />

        {showConfig && (
          <CardBody className="space-y-5">
            <TargetPicker
              options={options.data}
              value={config.target_column}
              onChange={(value) => setConfig((c) => ({ ...c, target_column: value }))}
            />

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Task type" htmlFor="task-type" hint="Auto detects from the target">
                <Select
                  id="task-type"
                  value={config.task_type}
                  onChange={(event) => setConfig((c) => ({ ...c, task_type: event.target.value }))}
                  options={[
                    { value: "auto", label: "Detect automatically" },
                    { value: "classification", label: "Classification" },
                    { value: "regression", label: "Regression" },
                  ]}
                />
              </Field>

              <Field label="Test split" htmlFor="test-size" hint="Held back for evaluation">
                <Select
                  id="test-size"
                  value={config.test_size}
                  onChange={(event) => setConfig((c) => ({ ...c, test_size: Number(event.target.value) }))}
                  options={[
                    { value: 0.1, label: "10%" }, { value: 0.15, label: "15%" },
                    { value: 0.2, label: "20%" }, { value: 0.25, label: "25%" },
                    { value: 0.3, label: "30%" },
                  ]}
                />
              </Field>

              <Field label="Cross-validation folds" htmlFor="folds">
                <Select
                  id="folds"
                  value={config.cross_validation_folds}
                  onChange={(event) =>
                    setConfig((c) => ({ ...c, cross_validation_folds: Number(event.target.value) }))
                  }
                  options={[2, 3, 5, 10].map((n) => ({ value: n, label: `${n} folds` }))}
                />
              </Field>

              <div className="flex items-end pb-1">
                <Checkbox
                  label="Tune hyperparameters"
                  description="Searches the top two models. Slower, usually better."
                  checked={config.enable_tuning}
                  onChange={(event) => setConfig((c) => ({ ...c, enable_tuning: event.target.checked }))}
                />
              </div>
            </div>

            <FeatureSelector
              columns={options.data.columns}
              target={config.target_column}
              excluded={config.excluded_columns}
              suggestions={options.data.suggested_exclusions}
              onChange={(excluded) => setConfig((c) => ({ ...c, excluded_columns: excluded }))}
            />

            {options.data.warnings?.length > 0 && (
              <Alert tone="warning" title="Data quality issues that affect training">
                <ul className="mt-1 list-inside list-disc space-y-0.5">
                  {options.data.warnings.slice(0, 5).map((warning, index) => (
                    <li key={index}>{warning.message}</li>
                  ))}
                </ul>
              </Alert>
            )}

            <p className="text-sm text-muted">
              Training uses {formatNumber(options.data.row_count)} rows of{" "}
              {options.data.data_source} data.
            </p>
          </CardBody>
        )}
      </Card>

      {trainError && (
        <Alert tone="danger" title="Training could not run">{trainError.message}</Alert>
      )}

      {/* Results */}
      {result && <TrainingResult result={result} onDownload={handleDownload} />}

      {!result && !train.isPending && !hasHistory && (
        <EmptyState
          icon={Brain}
          title="No models trained yet"
          description="Pick a target column and train. InsightFlow fits up to twelve algorithms, cross-validates them, and tunes the strongest two."
        />
      )}

      {/* History */}
      {hasHistory && <ModelHistory runs={history.data} onDownload={handleDownload} />}
    </div>
  );
}

/* ----------------------------------------------------------- target picker */

function TargetPicker({ options, value, onChange }) {
  const selected = options.target_candidates.find((c) => c.column === value);
  return (
    <div>
      <Field
        label="Target column"
        htmlFor="target"
        hint="The column the model will learn to predict"
        required
      >
        <Select
          id="target"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="Choose a target"
          options={options.columns.map((c) => ({
            value: c.column,
            label: `${c.column} (${c.semantic_type})`,
          }))}
        />
      </Field>

      {selected && (
        <div className="mt-2 surface-inset rounded-lg px-3 py-2.5">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            <Badge tone="accent">{selected.task_type}</Badge>
            <Badge tone="neutral">{selected.distinct_values} distinct values</Badge>
            <div className="ml-auto flex items-center gap-1.5">
              <span className="text-xs text-subtle">Confidence</span>
              <span className="text-sm font-medium tabular-nums text-ink">
                {formatPercent(selected.confidence_pct, 0)}
              </span>
            </div>
          </div>
          <Progress value={selected.confidence_pct} showValue={false} tone="accent" />
          <p className="mt-1.5 text-sm text-muted">{selected.reason}</p>
          <p className="mt-1 text-xs text-subtle">
            This confidence is a name-and-shape heuristic, not a trained estimate. Override it freely.
          </p>
        </div>
      )}

      {options.target_candidates.length > 1 && (
        <div className="mt-2">
          <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-subtle">
            Other candidates
          </p>
          <div className="flex flex-wrap gap-1.5">
            {options.target_candidates
              .filter((c) => c.column !== value)
              .slice(0, 5)
              .map((candidate) => (
                <button
                  key={candidate.column}
                  type="button"
                  onClick={() => onChange(candidate.column)}
                  className="rounded border border-line bg-surface px-2 py-1 text-xs text-muted
                             transition-colors hover:border-accent hover:text-accent
                             focus-visible:ring-2 focus-visible:ring-accent/50"
                >
                  {candidate.column}
                  <span className="ml-1.5 text-subtle">{formatPercent(candidate.confidence_pct, 0)}</span>
                </button>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* --------------------------------------------------------- feature selector */

function FeatureSelector({ columns, target, excluded, suggestions, onChange }) {
  const suggestionMap = Object.fromEntries(suggestions.map((s) => [s.column, s.reason]));
  const available = columns.filter((c) => c.column !== target);

  function toggle(column) {
    onChange(
      excluded.includes(column)
        ? excluded.filter((c) => c !== column)
        : [...excluded, column],
    );
  }

  return (
    <div>
      <SectionHeader
        title="Features"
        description={`${available.length - excluded.length} of ${available.length} columns will be used`}
        actions={
          <div className="flex gap-1.5">
            <Button variant="ghost" size="sm" onClick={() => onChange([])}>Use all</Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onChange(suggestions.map((s) => s.column))}
            >
              Reset to suggested
            </Button>
          </div>
        }
      />
      <div className="flex flex-wrap gap-1.5">
        {available.map((column) => {
          const isExcluded = excluded.includes(column.column);
          const reason = suggestionMap[column.column];
          const chip = (
            <button
              type="button"
              onClick={() => toggle(column.column)}
              aria-pressed={!isExcluded}
              className={clsx(
                "rounded border px-2 py-1 text-xs transition-colors focus-visible:ring-2 focus-visible:ring-accent/50",
                isExcluded
                  ? "border-line bg-canvas text-subtle line-through"
                  : "border-accent/30 bg-accent-soft text-accent",
              )}
            >
              {column.column}
              {reason && !isExcluded && (
                <AlertTriangle size={10} className="ml-1 inline text-warning" aria-hidden="true" />
              )}
            </button>
          );
          return (
            <span key={column.column}>
              {reason ? (
                <Tooltip content={`${reason} ${isExcluded ? "Currently excluded." : "Consider excluding it."}`}>
                  {chip}
                </Tooltip>
              ) : (
                chip
              )}
            </span>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-subtle">
        Click a column to include or exclude it. Excluding identifiers and constants usually improves
        how well a model generalises.
      </p>
    </div>
  );
}

/* ---------------------------------------------------------------- results */

function TrainingResult({ result, onDownload }) {
  const isClassification = result.task_type === "classification";
  const best = result.results.find((r) => r.model === result.best_model);

  return (
    <div className="space-y-4">
      {/* Gold rim on the winner. This is the payoff of the whole panel, so it
          is the one surface on the screen allowed to use the luxe treatment. */}
      <Card className="luxe-rim">
        <CardHeader
          title="Best model"
          description={`${result.task_type} on ${result.target_column}`}
          actions={
            <Button variant="secondary" size="sm" icon={Download} onClick={onDownload}>
              Download model
            </Button>
          }
        />
        <CardBody className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="luxe" icon={Award}>{result.best_model}</Badge>
            <Badge tone="neutral">Version {result.model_version}</Badge>
            {best?.tuned && <Badge tone="success">Tuned</Badge>}
            <Badge tone="neutral">{result.data_source} data</Badge>
            {result.sampled && <Badge tone="warning">Sampled</Badge>}
            <span className="ml-auto text-sm text-muted">
              {formatNumber(result.rows_used)} rows &middot; {result.features_used.length} features
            </span>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {Object.entries(best?.metrics || {}).map(([key, value]) => (
              <div key={key} className="surface-inset rounded-lg px-3 py-2">
                <div className="flex items-center gap-1">
                  <p className="text-2xs uppercase tracking-wide text-subtle">{metricLabel(key)}</p>
                  {METRIC_HELP[key] && (
                    <Tooltip content={METRIC_HELP[key]}>
                      <span className="cursor-help text-subtle" aria-hidden="true">?</span>
                    </Tooltip>
                  )}
                </div>
                <p className="mt-0.5 text-lg font-semibold tabular-nums text-ink">
                  {formatNumber(value, { decimals: 4 })}
                </p>
              </div>
            ))}
            {best?.cv_score != null && (
              <div className="surface-inset rounded-lg px-3 py-2">
                <div className="flex items-center gap-1">
                  <p className="text-2xs uppercase tracking-wide text-subtle">CV score</p>
                  <Tooltip content={METRIC_HELP.cv_score}>
                    <span className="cursor-help text-subtle" aria-hidden="true">?</span>
                  </Tooltip>
                </div>
                <p className="mt-0.5 text-lg font-semibold tabular-nums text-ink">
                  {formatNumber(best.cv_score, { decimals: 4 })}
                </p>
              </div>
            )}
          </div>

          {result.warnings?.length > 0 && (
            <Alert tone="warning" title="Worth knowing about this run">
              <ul className="mt-1 list-inside list-disc space-y-0.5">
                {result.warnings.map((warning, index) => (
                  <li key={index}>{warning}</li>
                ))}
              </ul>
            </Alert>
          )}
        </CardBody>
      </Card>

      {/* Leaderboard */}
      <Card>
        <CardHeader
          title="Leaderboard"
          description={`${result.results.length} models compared. Sorted by ${isClassification ? "weighted F1" : "R²"}.`}
        />
        <CardBody className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="bg-canvas">
                <tr>
                  {["Model", "Score", "CV score", "Time", "Tuned"].map((heading) => (
                    <th
                      key={heading}
                      scope="col"
                      className={clsx(
                        "border-b border-line px-3 py-2 text-2xs font-semibold uppercase tracking-wide text-subtle",
                        heading === "Model" ? "text-left" : "text-right",
                      )}
                    >
                      {heading}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.results.map((row) => {
                  const isBest = row.model === result.best_model;
                  return (
                    <tr
                      key={row.model}
                      className={clsx(
                        "border-b border-line last:border-0",
                        isBest ? "bg-luxe-soft/60" : "hover:bg-canvas",
                      )}
                    >
                      <td className="px-3 py-2">
                        <span className="flex items-center gap-1.5">
                          {isBest && <Award size={12} className="text-luxe" aria-hidden="true" />}
                          <span className={clsx(isBest && "font-semibold text-ink")}>{row.model}</span>
                        </span>
                      </td>
                      <td className="numeric px-3 py-2 font-medium">
                        {formatNumber(row.score, { decimals: 4 })}
                      </td>
                      <td className="numeric px-3 py-2 text-muted">
                        {row.cv_score == null ? "-" : formatNumber(row.cv_score, { decimals: 4 })}
                      </td>
                      <td className="numeric px-3 py-2 text-muted">{row.training_time_sec}s</td>
                      <td className="px-3 py-2 text-right">
                        {row.tuned ? <Badge tone="success">Yes</Badge> : <span className="text-subtle">-</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardBody>
      </Card>

      {/* Diagnostics */}
      {isClassification
        ? result.diagnostics?.confusion_matrix && (
            <ConfusionMatrix matrix={result.diagnostics.confusion_matrix} distribution={result.class_distribution} />
          )
        : result.diagnostics?.predicted_vs_actual && (
            <RegressionDiagnostics diagnostics={result.diagnostics} />
          )}
    </div>
  );
}

function ConfusionMatrix({ matrix, distribution }) {
  const max = Math.max(...matrix.matrix.flat(), 1);
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title="Confusion matrix" description="Rows are actual, columns are predicted" />
        <CardBody className="overflow-x-auto">
          <table className="text-sm">
            <thead>
              <tr>
                <th />
                {matrix.labels.map((label) => (
                  <th key={label} scope="col" className="px-2 py-1 text-2xs font-semibold text-subtle">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {matrix.matrix.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  <th scope="row" className="px-2 py-1 text-right text-2xs font-semibold text-subtle">
                    {matrix.labels[rowIndex]}
                  </th>
                  {row.map((count, colIndex) => (
                    <td key={colIndex} className="p-0.5">
                      <div
                        className="flex h-11 w-14 items-center justify-center rounded text-sm font-medium tabular-nums"
                        style={{
                          backgroundColor:
                            rowIndex === colIndex
                              ? `rgb(var(--color-success) / ${0.12 + (count / max) * 0.5})`
                              : `rgb(var(--color-danger) / ${count ? 0.1 + (count / max) * 0.4 : 0})`,
                          color: "rgb(var(--color-text))",
                        }}
                      >
                        {count}
                      </div>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-subtle">
            The diagonal is correct predictions. Off-diagonal cells show which classes get confused.
          </p>
        </CardBody>
      </Card>

      {distribution?.length > 0 && (
        <Card>
          <CardHeader title="Class distribution" description="Balance of the target column" />
          <CardBody>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={distribution}>
                  <CartesianGrid stroke={CHART_GRID_COLOR} vertical={false} />
                  <XAxis dataKey="label" tick={{ fill: CHART_AXIS_COLOR, fontSize: 11 }} stroke={CHART_GRID_COLOR} />
                  <YAxis tick={{ fill: CHART_AXIS_COLOR, fontSize: 11 }} stroke={CHART_GRID_COLOR} width={48} />
                  <ReTooltip
                    contentStyle={{
                      background: "rgb(var(--color-elevated))",
                      border: "1px solid rgb(var(--color-border))",
                      borderRadius: 6, fontSize: 12,
                    }}
                  />
                  <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                    {distribution.map((_, index) => (
                      <Cell key={index} fill={chartColor(index)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

function RegressionDiagnostics({ diagnostics }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title="Predicted vs actual" description="Points on the diagonal are perfect predictions" />
        <CardBody>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart>
                <CartesianGrid stroke={CHART_GRID_COLOR} />
                <XAxis type="number" dataKey="actual" name="Actual" tick={{ fill: CHART_AXIS_COLOR, fontSize: 11 }} stroke={CHART_GRID_COLOR} />
                <YAxis type="number" dataKey="predicted" name="Predicted" tick={{ fill: CHART_AXIS_COLOR, fontSize: 11 }} stroke={CHART_GRID_COLOR} width={56} />
                <ZAxis range={[24, 24]} />
                <ReTooltip
                  contentStyle={{
                    background: "rgb(var(--color-elevated))",
                    border: "1px solid rgb(var(--color-border))",
                    borderRadius: 6, fontSize: 12,
                  }}
                />
                <Scatter data={diagnostics.predicted_vs_actual} fill={chartColor(0)} fillOpacity={0.5} />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Residuals" description="Should scatter evenly around zero" />
        <CardBody>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart>
                <CartesianGrid stroke={CHART_GRID_COLOR} />
                <XAxis type="number" dataKey="predicted" name="Predicted" tick={{ fill: CHART_AXIS_COLOR, fontSize: 11 }} stroke={CHART_GRID_COLOR} />
                <YAxis type="number" dataKey="residual" name="Residual" tick={{ fill: CHART_AXIS_COLOR, fontSize: 11 }} stroke={CHART_GRID_COLOR} width={56} />
                <ZAxis range={[24, 24]} />
                <ReferenceLine y={0} stroke="rgb(var(--color-danger))" strokeDasharray="4 4" />
                <ReTooltip
                  contentStyle={{
                    background: "rgb(var(--color-elevated))",
                    border: "1px solid rgb(var(--color-border))",
                    borderRadius: 6, fontSize: 12,
                  }}
                />
                <Scatter data={diagnostics.residuals} fill={chartColor(3)} fillOpacity={0.5} />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-xs text-subtle">
            A pattern here (a curve, or a widening fan) means the model is systematically wrong for
            part of the range.
          </p>
        </CardBody>
      </Card>
    </div>
  );
}

/* ---------------------------------------------------------------- history */

function ModelHistory({ runs, onDownload }) {
  return (
    <Card>
      <CardHeader
        title="Training history"
        description={`${runs.length} run(s). Version ${runs[0].version} is the current model.`}
        actions={
          <Button variant="secondary" size="sm" icon={Download} onClick={onDownload}>
            Download latest
          </Button>
        }
      />
      <CardBody className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="bg-canvas">
              <tr>
                {["Version", "Model", "Task", "Target", "Rows", "Data", "Trained", "Saved"].map((heading) => (
                  <th
                    key={heading}
                    scope="col"
                    className="border-b border-line px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wide text-subtle"
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runs.map((run, index) => (
                <tr key={run.id} className="border-b border-line last:border-0 hover:bg-canvas">
                  <td className="px-3 py-2">
                    <span className="flex items-center gap-1.5">
                      v{run.version}
                      {index === 0 && <Badge tone="accent">Current</Badge>}
                    </span>
                  </td>
                  <td className="px-3 py-2 font-medium text-ink">{run.best_model_name}</td>
                  <td className="px-3 py-2 text-muted">{run.task_type}</td>
                  <td className="px-3 py-2 text-muted">{run.target_column}</td>
                  <td className="numeric px-3 py-2">{formatNumber(run.rows_used)}</td>
                  <td className="px-3 py-2 text-muted">{run.data_source}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted">
                    {formatDate(run.created_at, { withTime: true })}
                  </td>
                  <td className="px-3 py-2">
                    {run.has_model_file ? (
                      <Badge tone="success">Yes</Badge>
                    ) : (
                      <Tooltip content="The model file is missing from disk. Re-train to regenerate it.">
                        <Badge tone="warning">Missing</Badge>
                      </Tooltip>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardBody>
    </Card>
  );
}

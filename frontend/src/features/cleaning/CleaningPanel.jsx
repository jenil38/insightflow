/**
 * Cleaning workflow: recommended plan -> configure -> preview -> apply, with
 * revert always available.
 *
 * Preview computes the full effect without writing anything, so the user sees
 * the before/after before committing. Destructive options are called out
 * explicitly rather than applied quietly - the original pipeline lower-cased
 * every text value with no warning at all.
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import clsx from "clsx";
import {
  AlertTriangle, ArrowRight, Check, Eye, RotateCcw, Sparkles, Wand2,
} from "lucide-react";

import { errorMessage } from "../../api/client.js";
import { cleaning as cleaningApi } from "../../api/endpoints.js";
import {
  Alert, Badge, Button, Card, CardBody, CardHeader, Checkbox, ConfirmDialog,
  ErrorState, Field, LoadingOverlay, SectionHeader, Select, Skeleton,
} from "../../components/ui/index.jsx";
import { formatNumber } from "../../lib/format.js";

const NUMERIC_STRATEGIES = [
  { value: "median", label: "Fill with median" },
  { value: "mean", label: "Fill with mean" },
  { value: "zero", label: "Fill with zero" },
  { value: "drop", label: "Drop those rows" },
  { value: "leave", label: "Leave as-is" },
];

const CATEGORICAL_STRATEGIES = [
  { value: "mode", label: "Fill with most frequent" },
  { value: "unknown", label: 'Fill with "Unknown"' },
  { value: "drop", label: "Drop those rows" },
  { value: "leave", label: "Leave as-is" },
];

const OUTLIER_STRATEGIES = [
  { value: "report", label: "Report only (no change)" },
  { value: "cap", label: "Cap to IQR bounds" },
  { value: "remove", label: "Remove those rows" },
  { value: "leave", label: "Skip outlier detection" },
];

const CASE_STRATEGIES = [
  { value: "none", label: "Leave capitalisation alone" },
  { value: "lower", label: "lowercase" },
  { value: "upper", label: "UPPERCASE" },
  { value: "title", label: "Title Case" },
];

export default function CleaningPanel({ datasetId, dataset }) {
  const queryClient = useQueryClient();
  const [config, setConfig] = useState(null);
  const [confirmApply, setConfirmApply] = useState(false);
  const [confirmRevert, setConfirmRevert] = useState(false);

  const planQuery = useQuery({
    queryKey: ["clean-plan", datasetId],
    queryFn: () => cleaningApi.plan(datasetId),
  });

  // Seed the form from the server's recommendation once it arrives.
  useEffect(() => {
    if (planQuery.data?.recommended_config && !config) {
      setConfig(planQuery.data.recommended_config);
    }
  }, [planQuery.data, config]);

  const preview = useMutation({
    mutationFn: () => cleaningApi.preview(datasetId, config),
    onError: (error) => toast.error(errorMessage(error, "Could not preview cleaning.")),
  });

  const apply = useMutation({
    mutationFn: () => cleaningApi.apply(datasetId, config),
    onSuccess: (report) => {
      // Everything downstream reads the cleaned file now, so drop the cached
      // results that were computed from the original.
      invalidateDatasetViews(queryClient, datasetId);
      setConfirmApply(false);
      toast.success("Cleaning applied", {
        description: `${formatNumber(report.before.rows)} rows in, ${formatNumber(report.after.rows)} out.`,
      });
    },
    onError: (error) => toast.error(errorMessage(error, "Could not apply cleaning.")),
  });

  const revert = useMutation({
    mutationFn: () => cleaningApi.revert(datasetId),
    onSuccess: (result) => {
      invalidateDatasetViews(queryClient, datasetId);
      setConfirmRevert(false);
      preview.reset();
      toast.success(result.reverted ? "Reverted to the original data" : "Nothing to revert");
    },
    onError: (error) => toast.error(errorMessage(error, "Could not revert.")),
  });

  if (planQuery.isLoading || !config) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (planQuery.isError) {
    return (
      <ErrorState
        title="Could not build a cleaning plan"
        message={errorMessage(planQuery.error)}
        onRetry={planQuery.refetch}
      />
    );
  }

  const hasCleaned = Boolean(dataset?.has_cleaned_version);
  const previewReport = preview.data;
  const isDestructive =
    config.standardize_case !== "none" ||
    config.outlier_strategy === "remove" ||
    config.outlier_strategy === "cap" ||
    config.numeric_missing_strategy === "drop" ||
    config.categorical_missing_strategy === "drop" ||
    config.drop_empty_columns;

  function update(patch) {
    setConfig((current) => ({ ...current, ...patch }));
    // Any config change invalidates the previous preview.
    preview.reset();
  }

  return (
    <div className="space-y-5">
      {hasCleaned ? (
        <Alert
          tone="success"
          title="This dataset has a cleaned version"
          action={
            <Button variant="secondary" size="sm" icon={RotateCcw} onClick={() => setConfirmRevert(true)}>
              Revert
            </Button>
          }
        >
          Analytics, models, and the data explorer are all reading the cleaned data. Reverting
          restores the original upload - nothing was overwritten.
        </Alert>
      ) : (
        <Alert tone="info" title="Currently using the original data">
          Cleaning writes a separate file. Your upload is never modified, so you can revert at any time.
        </Alert>
      )}

      {/* Recommended plan */}
      <Card>
        <CardHeader
          title="Recommended plan"
          description="Based on what this dataset actually contains"
        />
        <CardBody>
          <ul className="space-y-1.5">
            {planQuery.data.reasons.map((reason, index) => (
              <li key={index} className="flex items-start gap-2 text-base text-muted">
                <Sparkles size={13} className="mt-1 shrink-0 text-accent" aria-hidden="true" />
                {reason}
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>

      {/* Configuration */}
      <Card className="relative">
        {(preview.isPending || apply.isPending) && (
          <LoadingOverlay message={apply.isPending ? "Applying cleaning" : "Computing preview"} />
        )}
        <CardHeader
          title="Cleaning options"
          description="Nothing runs until you preview or apply"
          actions={
            <Button
              variant="secondary"
              size="sm"
              icon={Eye}
              onClick={() => preview.mutate()}
              loading={preview.isPending}
            >
              Preview changes
            </Button>
          }
        />
        <CardBody className="space-y-5">
          <div className="space-y-3">
            <Checkbox
              label="Remove duplicate rows"
              description="Drops rows that are exact duplicates across every column."
              checked={config.remove_duplicates}
              onChange={(event) => update({ remove_duplicates: event.target.checked })}
            />
            <Checkbox
              label="Trim leading and trailing whitespace"
              checked={config.trim_whitespace}
              onChange={(event) => update({ trim_whitespace: event.target.checked })}
            />
            <Checkbox
              label="Collapse repeated spaces inside text"
              checked={config.normalize_whitespace}
              onChange={(event) => update({ normalize_whitespace: event.target.checked })}
            />
            <Checkbox
              label="Parse date-like text columns"
              description="Converts recognised dates to YYYY-MM-DD. Unparseable values become empty."
              checked={config.parse_dates}
              onChange={(event) => update({ parse_dates: event.target.checked })}
            />
            <Checkbox
              label="Drop columns that are entirely empty"
              checked={config.drop_empty_columns}
              onChange={(event) => update({ drop_empty_columns: event.target.checked })}
            />
          </div>

          <div className="grid gap-4 border-t border-line pt-4 sm:grid-cols-2">
            <Field
              label="Missing numeric values"
              htmlFor="numeric-strategy"
              hint="Applies to every numeric column"
            >
              <Select
                id="numeric-strategy"
                value={config.numeric_missing_strategy}
                onChange={(event) => update({ numeric_missing_strategy: event.target.value })}
                options={NUMERIC_STRATEGIES}
              />
            </Field>

            <Field
              label="Missing text values"
              htmlFor="categorical-strategy"
              hint="Applies to every text column"
            >
              <Select
                id="categorical-strategy"
                value={config.categorical_missing_strategy}
                onChange={(event) => update({ categorical_missing_strategy: event.target.value })}
                options={CATEGORICAL_STRATEGIES}
              />
            </Field>

            <Field
              label="Outliers"
              htmlFor="outlier-strategy"
              hint="Detected with the 1.5×IQR rule"
            >
              <Select
                id="outlier-strategy"
                value={config.outlier_strategy}
                onChange={(event) => update({ outlier_strategy: event.target.value })}
                options={OUTLIER_STRATEGIES}
              />
            </Field>

            <Field
              label="Text capitalisation"
              htmlFor="case-strategy"
              hint="Off by default because it cannot be undone in place"
            >
              <Select
                id="case-strategy"
                value={config.standardize_case}
                onChange={(event) => update({ standardize_case: event.target.value })}
                options={CASE_STRATEGIES}
              />
            </Field>
          </div>

          {isDestructive && (
            <Alert tone="warning" title="These options change or discard data">
              <ul className="mt-1 list-inside list-disc space-y-0.5">
                {config.standardize_case !== "none" && (
                  <li>Original capitalisation will be lost.</li>
                )}
                {config.outlier_strategy === "cap" && <li>Outlier values will be clipped to the IQR bounds.</li>}
                {config.outlier_strategy === "remove" && <li>Rows containing outliers will be removed.</li>}
                {config.numeric_missing_strategy === "drop" && <li>Rows with missing numbers will be removed.</li>}
                {config.categorical_missing_strategy === "drop" && <li>Rows with missing text will be removed.</li>}
                {config.drop_empty_columns && <li>Fully empty columns will be dropped.</li>}
              </ul>
              You can still revert to the original upload afterwards.
            </Alert>
          )}
        </CardBody>
      </Card>

      {/* Preview */}
      {previewReport && (
        <Card>
          <CardHeader
            title="Preview"
            description="Nothing has been saved yet"
            actions={
              <Button icon={Wand2} onClick={() => setConfirmApply(true)}>Apply cleaning</Button>
            }
          />
          <CardBody className="space-y-5">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <BeforeAfter
                label="Rows"
                before={previewReport.before.rows}
                after={previewReport.after.rows}
              />
              <BeforeAfter
                label="Columns"
                before={previewReport.before.columns}
                after={previewReport.after.columns}
              />
              <BeforeAfter
                label="Missing values"
                before={previewReport.before.missing_values}
                after={previewReport.after.missing_values}
                lowerIsBetter
              />
              <BeforeAfter
                label="Duplicate rows"
                before={previewReport.before.duplicate_rows}
                after={previewReport.after.duplicate_rows}
                lowerIsBetter
              />
            </div>

            <div>
              <SectionHeader title="What will happen" />
              {previewReport.steps.length === 0 ? (
                <p className="text-base text-muted">
                  Nothing to change - this dataset is already clean under these settings.
                </p>
              ) : (
                <ul className="space-y-2">
                  {previewReport.steps.map((step, index) => (
                    <li key={index} className="flex items-start gap-2.5 surface-inset rounded-lg px-3 py-2">
                      <Check size={13} className="mt-0.5 shrink-0 text-success" aria-hidden="true" />
                      <div className="min-w-0">
                        <p className="text-base font-medium text-ink">{step.step}</p>
                        <p className="text-sm text-muted">{step.detail}</p>
                        {step.columns_affected?.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {step.columns_affected.slice(0, 6).map((column) => (
                              <code key={column} className="rounded bg-surface px-1.5 py-0.5 text-2xs text-muted">
                                {column}
                              </code>
                            ))}
                            {step.columns_affected.length > 6 && (
                              <span className="text-2xs text-subtle">
                                +{step.columns_affected.length - 6}
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {previewReport.preview_rows?.length > 0 && (
              <div>
                <SectionHeader title="Sample of the cleaned data" />
                <div className="overflow-x-auto rounded-md border border-line">
                  <table className="w-full text-sm">
                    <thead className="bg-canvas">
                      <tr>
                        {previewReport.preview_columns.map((column) => (
                          <th
                            key={column}
                            scope="col"
                            className="whitespace-nowrap px-3 py-1.5 text-left text-2xs font-semibold uppercase text-subtle"
                          >
                            {column}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {previewReport.preview_rows.slice(0, 6).map((row, rowIndex) => (
                        <tr key={rowIndex} className="border-t border-line">
                          {previewReport.preview_columns.map((column) => (
                            <td key={column} className="max-w-[12rem] truncate px-3 py-1.5">
                              {row[column] === null ? (
                                <span className="italic text-subtle">null</span>
                              ) : (
                                String(row[column])
                              )}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </CardBody>
        </Card>
      )}

      <ConfirmDialog
        open={confirmApply}
        onClose={() => setConfirmApply(false)}
        onConfirm={() => apply.mutate()}
        loading={apply.isPending}
        tone={isDestructive ? "danger" : "primary"}
        title="Apply cleaning?"
        confirmLabel="Apply cleaning"
        message={
          previewReport
            ? `This writes a cleaned copy with ${formatNumber(previewReport.after.rows)} rows ` +
              `(from ${formatNumber(previewReport.before.rows)}). Analytics and models will use it ` +
              "from now on. Your original upload is kept, so you can revert."
            : "This writes a cleaned copy. Your original upload is kept, so you can revert."
        }
      />

      <ConfirmDialog
        open={confirmRevert}
        onClose={() => setConfirmRevert(false)}
        onConfirm={() => revert.mutate()}
        loading={revert.isPending}
        title="Revert to the original data?"
        confirmLabel="Revert"
        message={
          "The cleaned copy will be deleted and everything will read the original upload again. " +
          "Trained models are kept, but they were fitted on the cleaned data - retrain for consistency."
        }
      />
    </div>
  );
}

function BeforeAfter({ label, before, after, lowerIsBetter = false }) {
  const changed = before !== after;
  const improved = lowerIsBetter ? after < before : after !== before;
  return (
    <div className="surface-inset rounded-lg px-3 py-2.5">
      <p className="text-2xs uppercase tracking-wide text-subtle">{label}</p>
      <div className="mt-1 flex items-center gap-1.5">
        <span className={clsx("tabular-nums", changed ? "text-subtle line-through" : "font-medium text-ink")}>
          {formatNumber(before)}
        </span>
        {changed && (
          <>
            <ArrowRight size={11} className="text-subtle" aria-hidden="true" />
            <span
              className={clsx(
                "font-medium tabular-nums",
                improved && lowerIsBetter ? "text-success" : "text-ink",
              )}
            >
              {formatNumber(after)}
            </span>
          </>
        )}
      </div>
    </div>
  );
}

/** Cleaning changes the active data, so every derived view must be refetched. */
function invalidateDatasetViews(queryClient, datasetId) {
  [
    "dataset", "datasets", "datasets-status", "preview", "columns", "column-profile",
    "quality", "clean-plan", "dashboard", "analytics", "train-options", "user-summary",
  ].forEach((key) => queryClient.invalidateQueries({ queryKey: [key] }));
  queryClient.invalidateQueries({ queryKey: ["dataset", String(datasetId)] });
}

/**
 * Automation pipeline.
 *
 * The timeline shows real per-step outcomes and measured durations returned by
 * the server. There is no simulated progress animation: the pipeline runs
 * synchronously, so while it is in flight the UI says exactly that, then renders
 * the actual results. A step that could not run is marked "skipped" with the
 * reason, rather than being hidden or reported as success.
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import clsx from "clsx";
import {
  AlertTriangle, ArrowRight, Bot, Check, CircleSlash, Clock, Download, Play, XCircle,
} from "lucide-react";

import { errorMessage } from "../../api/client.js";
import { agent as agentApi, reports as reportsApi, saveBlobResponse } from "../../api/endpoints.js";
import {
  Alert, Badge, Button, Card, CardBody, CardHeader, Checkbox, EmptyState,
  LoadingOverlay, Progress, SectionHeader, StatCard,
} from "../../components/ui/index.jsx";
import { formatNumber, formatPercent } from "../../lib/format.js";

const STATUS_META = {
  completed: { Icon: Check, tone: "text-success", ring: "border-success bg-success-soft", label: "Completed" },
  skipped: { Icon: CircleSlash, tone: "text-subtle", ring: "border-line bg-canvas", label: "Skipped" },
  failed: { Icon: XCircle, tone: "text-danger", ring: "border-danger bg-danger-soft", label: "Failed" },
  running: { Icon: Clock, tone: "text-accent", ring: "border-accent bg-accent-soft", label: "Running" },
};

export default function AgentPanel({ datasetId }) {
  const queryClient = useQueryClient();
  const [applyCleaning, setApplyCleaning] = useState(true);
  const [train, setTrain] = useState(true);
  const [downloading, setDownloading] = useState(false);

  const run = useMutation({
    mutationFn: () => agentApi.run(datasetId, { applyCleaning, train }),
    onSuccess: (result) => {
      // The pipeline mutates the dataset (cleaning, training), so every cached
      // view of it is now stale.
      [
        "dataset", "datasets", "datasets-status", "preview", "columns", "quality",
        "clean-plan", "dashboard", "model-history", "explain", "train-options", "user-summary",
      ].forEach((key) => queryClient.invalidateQueries({ queryKey: [key] }));

      const failed = result.steps_failed;
      if (failed) {
        toast.warning(`Pipeline finished with ${failed} failed step(s)`);
      } else {
        toast.success(`Pipeline completed in ${result.duration_sec}s`);
      }
    },
    onError: (error) => toast.error(errorMessage(error, "The pipeline could not run.")),
  });

  async function downloadReport() {
    setDownloading(true);
    try {
      const response = await reportsApi.download(datasetId);
      saveBlobResponse(response, `InsightFlow_Report_${datasetId}.pdf`);
      toast.success("Report downloaded");
    } catch (error) {
      toast.error(errorMessage(error, "Could not generate the report."));
    } finally {
      setDownloading(false);
    }
  }

  const result = run.data;

  return (
    <div className="space-y-5">
      <Card className="relative">
        {run.isPending && (
          <LoadingOverlay message="Pipeline running - profiling, cleaning, analytics, and training" />
        )}
        <CardHeader
          title="Full analysis pipeline"
          description="Profile, assess quality, clean, build analytics, train, explain, and summarise"
          actions={
            <Button icon={Play} onClick={() => run.mutate()} loading={run.isPending}>
              Run pipeline
            </Button>
          }
        />
        <CardBody className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Checkbox
              label="Apply the recommended cleaning plan"
              description="Writes a cleaned copy. Your original upload is preserved."
              checked={applyCleaning}
              onChange={(event) => setApplyCleaning(event.target.checked)}
            />
            <Checkbox
              label="Train and compare models"
              description="Adds a new model version. Skip for a faster, analysis-only run."
              checked={train}
              onChange={(event) => setTrain(event.target.checked)}
            />
          </div>

          {run.isPending && (
            <Alert tone="info" title="This runs synchronously">
              Results appear when the pipeline finishes - training up to twelve models can take a
              minute or two. Nothing is faked while you wait.
            </Alert>
          )}
        </CardBody>
      </Card>

      {!result && !run.isPending && (
        <EmptyState
          icon={Bot}
          title="Run the whole analysis in one step"
          description="Guided Analysis chains every stage together and reports what each one actually did, including anything it had to skip."
        />
      )}

      {result && (
        <>
          {/* Run stats */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard
              label="Steps completed"
              value={`${result.steps_completed}/${result.steps_total}`}
              tone={result.steps_failed ? "warning" : "success"}
            />
            <StatCard label="Duration" value={`${result.duration_sec}s`} />
            <StatCard
              label="Quality score"
              value={result.summary.quality_score ?? "-"}
              tone={
                result.summary.quality_score >= 90
                  ? "success"
                  : result.summary.quality_score >= 70
                    ? "warning"
                    : "danger"
              }
              hint={result.summary.quality_grade}
            />
            <StatCard
              label="Best model"
              value={result.summary.best_model || "Not trained"}
              tone={result.summary.best_model ? "accent" : "default"}
              hint={result.summary.task_type}
            />
          </div>

          {/* Timeline */}
          <Card>
            <CardHeader title="Pipeline timeline" description="Real outcomes and measured durations" />
            <CardBody>
              <ol className="relative space-y-0">
                {result.steps.map((step, index) => {
                  const meta = STATUS_META[step.status] || STATUS_META.skipped;
                  const isLast = index === result.steps.length - 1;
                  return (
                    <li key={step.key} className="relative flex gap-3 pb-4 last:pb-0">
                      {/* Connector */}
                      {!isLast && (
                        <span
                          className="absolute left-[13px] top-7 h-full w-px bg-line"
                          aria-hidden="true"
                        />
                      )}
                      <span
                        className={clsx(
                          "relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border",
                          meta.ring,
                        )}
                      >
                        <meta.Icon size={13} className={meta.tone} aria-hidden="true" />
                      </span>

                      <div className="min-w-0 flex-1 pt-0.5">
                        <div className="flex flex-wrap items-baseline gap-2">
                          <p className="text-base font-medium text-ink">{step.step}</p>
                          <Badge
                            tone={
                              step.status === "completed"
                                ? "success"
                                : step.status === "failed"
                                  ? "danger"
                                  : "neutral"
                            }
                          >
                            {meta.label}
                          </Badge>
                          {step.duration_sec != null && (
                            <span className="text-xs tabular-nums text-subtle">
                              {step.duration_sec}s
                            </span>
                          )}
                        </div>
                        {step.summary && (
                          <p
                            className={clsx(
                              "mt-0.5 text-sm",
                              step.status === "failed" ? "text-danger" : "text-muted",
                            )}
                          >
                            {step.summary}
                          </p>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ol>
            </CardBody>
          </Card>

          {/* Summary */}
          <Card>
            <CardHeader
              title="Summary"
              actions={
                <Button
                  variant="secondary"
                  size="sm"
                  icon={Download}
                  onClick={downloadReport}
                  loading={downloading}
                >
                  Download PDF report
                </Button>
              }
            />
            <CardBody className="space-y-5">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Detail label="Rows before cleaning" value={formatNumber(result.summary.rows_before_cleaning)} />
                <Detail label="Rows after cleaning" value={formatNumber(result.summary.rows_after_cleaning)} />
                <Detail label="Target column" value={result.summary.target_column || "-"} />
                <Detail
                  label="Top driver"
                  value={result.summary.top_feature || "-"}
                  hint={result.summary.explanation_method}
                />
              </div>

              {result.summary.kpis?.length > 0 && (
                <div>
                  <SectionHeader title="Key metrics" />
                  <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                    {result.summary.kpis.map((kpi) => (
                      <Detail
                        key={kpi.label}
                        label={kpi.label}
                        value={formatNumber(kpi.value, { compact: true })}
                      />
                    ))}
                  </div>
                </div>
              )}

              {result.summary.warnings?.length > 0 && (
                <Alert tone="warning" title="Important warnings">
                  <ul className="mt-1 list-inside list-disc space-y-0.5">
                    {result.summary.warnings.map((warning, index) => (
                      <li key={index}>{warning}</li>
                    ))}
                  </ul>
                </Alert>
              )}

              <div>
                <SectionHeader title="Recommended next actions" />
                <ul className="space-y-1.5">
                  {result.summary.next_actions.map((action, index) => (
                    <li key={index} className="flex items-start gap-2 text-base text-muted">
                      <ArrowRight size={13} className="mt-1 shrink-0 text-accent" aria-hidden="true" />
                      {action}
                    </li>
                  ))}
                </ul>
              </div>
            </CardBody>
          </Card>
        </>
      )}
    </div>
  );
}

function Detail({ label, value, hint }) {
  return (
    <div className="surface-inset rounded-lg px-3 py-2">
      <p className="text-2xs uppercase tracking-wide text-subtle">{label}</p>
      <p className="mt-0.5 truncate font-medium text-ink" title={String(value)}>{value}</p>
      {hint && <p className="text-2xs text-subtle">{hint}</p>}
    </div>
  );
}

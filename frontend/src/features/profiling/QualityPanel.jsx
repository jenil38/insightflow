/**
 * Data-quality report.
 *
 * Each score shows the formula that produced it (from the API's
 * `score_definitions`), so the number is auditable rather than a black box.
 */
import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip as ReTooltip, XAxis, YAxis,
} from "recharts";
import clsx from "clsx";
import { AlertTriangle, CheckCircle2, HelpCircle, Info, ShieldAlert } from "lucide-react";

import { errorMessage } from "../../api/client.js";
import { quality as qualityApi } from "../../api/endpoints.js";
import {
  Alert, Badge, Card, CardBody, CardHeader, ErrorState, Progress, SectionHeader,
  Skeleton, Tooltip,
} from "../../components/ui/index.jsx";
import {
  CHART_AXIS_COLOR, CHART_GRID_COLOR, chartColor, formatNumber, formatPercent, titleCase,
} from "../../lib/format.js";

const GRADE_TONE = { excellent: "success", good: "success", fair: "warning", poor: "danger" };
const SEVERITY_META = {
  danger: { tone: "danger", Icon: ShieldAlert },
  warning: { tone: "warning", Icon: AlertTriangle },
  info: { tone: "neutral", Icon: Info },
};

export default function QualityPanel({ datasetId }) {
  const query = useQuery({
    queryKey: ["quality", datasetId],
    queryFn: () => qualityApi.report(datasetId),
  });

  if (query.isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-28 w-full" />
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-24 w-full" />
          ))}
        </div>
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (query.isError) {
    return (
      <ErrorState
        title="Could not build the quality report"
        message={errorMessage(query.error)}
        onRetry={query.refetch}
      />
    );
  }

  const report = query.data;
  const { quality: scores, summary } = report;
  const grade = scores.grade;

  return (
    <div className="space-y-6">
      {summary.sampled && (
        <Alert tone="info" title="Computed on a sample">
          This dataset has {formatNumber(summary.rows_in_file)} rows, so the report was computed on a
          random sample of {formatNumber(summary.rows_analysed)}. Figures are representative, not exact.
        </Alert>
      )}

      {/* Headline score */}
      <Card>
        <CardBody className="flex flex-col gap-5 sm:flex-row sm:items-center">
          <div className="flex items-center gap-4">
            <ScoreDial value={scores.overall_score} tone={GRADE_TONE[grade]} />
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-subtle">
                Overall data quality
              </p>
              <p className="text-2xl font-semibold text-ink">
                {scores.overall_score}
                <span className="text-base font-normal text-muted">/100</span>
              </p>
              <Badge tone={GRADE_TONE[grade]} className="mt-1">{titleCase(grade)}</Badge>
            </div>
          </div>

          <div className="flex-1 sm:border-l sm:border-line sm:pl-5">
            <div className="mb-2 flex items-center gap-1.5">
              <p className="text-sm font-medium text-ink">How this is calculated</p>
              <Tooltip content={scores.score_definitions.overall}>
                <HelpCircle size={13} className="text-subtle" aria-hidden="true" />
              </Tooltip>
            </div>
            <p className="text-sm text-muted">{scores.score_definitions.overall}</p>
          </div>
        </CardBody>
      </Card>

      {/* Component scores */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ["Completeness", scores.completeness_score, scores.score_definitions.completeness],
          ["Duplicate-freedom", scores.duplicate_score, scores.score_definitions.duplicates],
          ["Type consistency", scores.consistency_score, scores.score_definitions.consistency],
          ["Uniqueness", scores.uniqueness_score, scores.score_definitions.uniqueness],
        ].map(([label, value, definition]) => (
          <Card key={label}>
            <CardBody className="p-4">
              <div className="mb-2 flex items-start justify-between gap-2">
                <p className="text-xs font-medium uppercase tracking-wide text-subtle">{label}</p>
                <Tooltip content={definition}>
                  <HelpCircle size={12} className="shrink-0 text-subtle" aria-hidden="true" />
                </Tooltip>
              </div>
              <Progress
                value={value}
                showValue={false}
                tone={value >= 90 ? "success" : value >= 70 ? "warning" : "danger"}
              />
              <p className="mt-1.5 text-xl font-semibold tabular-nums text-ink">{value}</p>
            </CardBody>
          </Card>
        ))}
      </div>

      {/* Findings */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Issues found"
            description={
              report.warnings.length
                ? `${report.warnings.length} finding(s) in this dataset`
                : "No problems detected"
            }
          />
          <CardBody>
            {report.warnings.length === 0 ? (
              <div className="flex items-center gap-2 text-base text-success">
                <CheckCircle2 size={16} aria-hidden="true" />
                This dataset passed every quality check.
              </div>
            ) : (
              <ul className="space-y-2.5">
                {report.warnings.map((warning, index) => {
                  const meta = SEVERITY_META[warning.severity] || SEVERITY_META.info;
                  return (
                    <li key={index} className="flex items-start gap-2.5">
                      <meta.Icon
                        size={14}
                        className={clsx(
                          "mt-0.5 shrink-0",
                          warning.severity === "danger" && "text-danger",
                          warning.severity === "warning" && "text-warning",
                          warning.severity === "info" && "text-subtle",
                        )}
                        aria-hidden="true"
                      />
                      <div className="min-w-0">
                        <p className="text-base text-ink">{warning.message}</p>
                        {warning.columns?.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {warning.columns.slice(0, 8).map((column) => (
                              <code key={column} className="rounded bg-canvas px-1.5 py-0.5 text-2xs text-muted">
                                {column}
                              </code>
                            ))}
                            {warning.columns.length > 8 && (
                              <span className="text-2xs text-subtle">
                                +{warning.columns.length - 8} more
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Recommended next steps" description="Each tied to a finding above" />
          <CardBody>
            {report.recommendations.length === 0 ? (
              <p className="text-base text-muted">Nothing to act on.</p>
            ) : (
              <ol className="space-y-3">
                {report.recommendations.map((rec, index) => (
                  <li key={index} className="flex gap-3">
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-soft text-2xs font-semibold text-accent">
                      {index + 1}
                    </span>
                    <div>
                      <p className="text-base font-medium text-ink">{rec.action}</p>
                      <p className="text-sm text-muted">{rec.why}</p>
                      <p className="mt-0.5 text-2xs uppercase tracking-wide text-subtle">{rec.where}</p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </CardBody>
        </Card>
      </div>

      {/* Missing values */}
      {report.missing_by_column?.length > 0 && (
        <Card>
          <CardHeader
            title="Missing values by column"
            description="Only columns with at least one missing value are shown"
          />
          <CardBody>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={report.missing_by_column.slice(0, 15)}
                  layout="vertical"
                  margin={{ left: 8, right: 16, top: 4, bottom: 4 }}
                >
                  <CartesianGrid stroke={CHART_GRID_COLOR} horizontal={false} />
                  <XAxis
                    type="number"
                    unit="%"
                    tick={{ fill: CHART_AXIS_COLOR, fontSize: 11 }}
                    stroke={CHART_GRID_COLOR}
                  />
                  <YAxis
                    type="category"
                    dataKey="column"
                    width={120}
                    tick={{ fill: CHART_AXIS_COLOR, fontSize: 11 }}
                    stroke={CHART_GRID_COLOR}
                  />
                  <ReTooltip content={<ChartTooltip suffix="% missing" />} />
                  <Bar dataKey="missing_pct" radius={[0, 3, 3, 0]}>
                    {report.missing_by_column.slice(0, 15).map((entry, index) => (
                      <Cell
                        key={index}
                        fill={
                          entry.missing_pct >= 40
                            ? "rgb(var(--color-danger))"
                            : "rgb(var(--color-warning))"
                        }
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardBody>
        </Card>
      )}

      {/* Column types + correlations */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Column types" />
          <CardBody>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={report.column_type_distribution} margin={{ left: -16, right: 8 }}>
                  <CartesianGrid stroke={CHART_GRID_COLOR} vertical={false} />
                  <XAxis dataKey="type" tick={{ fill: CHART_AXIS_COLOR, fontSize: 11 }} stroke={CHART_GRID_COLOR} />
                  <YAxis allowDecimals={false} tick={{ fill: CHART_AXIS_COLOR, fontSize: 11 }} stroke={CHART_GRID_COLOR} />
                  <ReTooltip content={<ChartTooltip suffix=" columns" />} />
                  <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                    {report.column_type_distribution.map((_, index) => (
                      <Cell key={index} fill={chartColor(index)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardBody>
        </Card>

        <CorrelationCard correlations={report.correlations} />
      </div>

      {/* Data dictionary */}
      <Card>
        <CardHeader
          title="Data dictionary"
          description={`All ${report.data_dictionary.length} columns`}
        />
        <CardBody className="p-0">
          <div className="max-h-96 overflow-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="sticky top-0 bg-canvas">
                <tr>
                  {["Column", "Type", "Storage", "Non-null", "Missing", "Distinct", "Examples"].map((heading) => (
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
                {report.data_dictionary.map((entry) => (
                  <tr key={entry.column} className="border-b border-line last:border-0 hover:bg-canvas">
                    <td className="px-3 py-1.5 font-medium text-ink">{entry.column}</td>
                    <td className="px-3 py-1.5">
                      <Badge tone="neutral">{entry.semantic_type}</Badge>
                    </td>
                    <td className="px-3 py-1.5 font-mono text-2xs text-subtle">{entry.dtype}</td>
                    <td className="numeric px-3 py-1.5">{formatNumber(entry.non_null_count)}</td>
                    <td className={clsx("numeric px-3 py-1.5", entry.missing_pct > 0 && "text-warning")}>
                      {formatPercent(entry.missing_pct)}
                    </td>
                    <td className="numeric px-3 py-1.5">{formatNumber(entry.unique_count)}</td>
                    <td className="max-w-[14rem] truncate px-3 py-1.5 text-subtle">
                      {entry.example_values?.map((v) => (v === null ? "null" : String(v))).join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}

/* ------------------------------------------------------------------ pieces */

/** SVG ring gauge. Uses stroke-dashoffset so it needs no chart library. */
function ScoreDial({ value, tone = "success" }) {
  const radius = 30;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - Math.max(0, Math.min(100, value)) / 100);
  const stroke = {
    success: "rgb(var(--color-success))",
    warning: "rgb(var(--color-warning))",
    danger: "rgb(var(--color-danger))",
  }[tone];

  return (
    <svg width="76" height="76" viewBox="0 0 76 76" role="img" aria-label={`Quality score ${value} out of 100`}>
      <circle cx="38" cy="38" r={radius} fill="none" stroke="rgb(var(--color-border))" strokeWidth="7" />
      <circle
        cx="38" cy="38" r={radius} fill="none" stroke={stroke} strokeWidth="7"
        strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={offset}
        transform="rotate(-90 38 38)"
      />
    </svg>
  );
}

function ChartTooltip({ active, payload, label, suffix = "" }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-line bg-elevated px-2.5 py-1.5 text-xs shadow-md">
      <p className="font-medium text-ink">{payload[0].payload.column || label}</p>
      <p className="text-muted">
        {formatNumber(payload[0].value)}
        {suffix}
      </p>
    </div>
  );
}

function CorrelationCard({ correlations }) {
  if (!correlations?.top_pairs?.length) {
    return (
      <Card>
        <CardHeader title="Correlations" />
        <CardBody>
          <p className="text-base text-muted">
            At least two numeric columns with variation are needed to compute correlations.
          </p>
        </CardBody>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader
        title="Strongest correlations"
        description="Pearson r between numeric columns"
        actions={
          correlations.truncated ? (
            <Tooltip content="Only the highest-variance columns were compared, to keep this fast.">
              <Badge tone="warning">Truncated</Badge>
            </Tooltip>
          ) : null
        }
      />
      <CardBody className="space-y-2.5">
        {correlations.top_pairs.slice(0, 8).map((pair, index) => {
          const strength = Math.abs(pair.correlation);
          const positive = pair.correlation >= 0;
          return (
            <div key={index}>
              <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
                <span className="min-w-0 truncate text-ink">
                  {pair.x} <span className="text-subtle">vs</span> {pair.y}
                </span>
                <span className={clsx("shrink-0 font-mono tabular-nums", positive ? "text-accent" : "text-warning")}>
                  {pair.correlation > 0 ? "+" : ""}
                  {pair.correlation}
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-canvas">
                <div
                  className={clsx("h-full rounded-full", positive ? "bg-accent" : "bg-warning")}
                  style={{ width: `${strength * 100}%` }}
                />
              </div>
            </div>
          );
        })}
        <p className="pt-1 text-xs text-subtle">
          Correlation measures association only. A strong r does not mean one column causes the other.
        </p>
      </CardBody>
    </Card>
  );
}

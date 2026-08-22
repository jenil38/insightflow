/**
 * Analytics: the automatic dashboard plus a configurable chart builder.
 *
 * The builder validates server-side, so statistically inappropriate
 * combinations (summing a text column, a 40-slice pie chart) come back as an
 * explained error instead of being rendered as nonsense.
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie,
  PieChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip as ReTooltip, XAxis, YAxis,
} from "recharts";
import clsx from "clsx";
import { BarChart3, Lightbulb, Play } from "lucide-react";

import { normalizeError } from "../../api/client.js";
import { analytics as analyticsApi, datasets as datasetsApi } from "../../api/endpoints.js";
import {
  Alert, Badge, Button, Card, CardBody, CardHeader, EmptyState, ErrorState, Field,
  LoadingOverlay, SectionHeader, Select, Skeleton, StatCard,
} from "../../components/ui/index.jsx";
import {
  CHART_AXIS_COLOR, CHART_GRID_COLOR, chartColor, formatNumber,
} from "../../lib/format.js";

const AGGREGATIONS = [
  { value: "sum", label: "Sum" },
  { value: "avg", label: "Average" },
  { value: "count", label: "Count" },
  { value: "min", label: "Minimum" },
  { value: "max", label: "Maximum" },
  { value: "median", label: "Median" },
];

const CHART_TYPES = [
  { value: "bar", label: "Bar" },
  { value: "horizontal_bar", label: "Horizontal bar" },
  { value: "line", label: "Line" },
  { value: "area", label: "Area" },
  { value: "pie", label: "Pie" },
  { value: "scatter", label: "Scatter" },
  { value: "histogram", label: "Histogram" },
  { value: "kpi", label: "Single value" },
];

const TIME_GRAINS = [
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "quarter", label: "Quarter" },
  { value: "year", label: "Year" },
];

export default function AnalyticsPanel({ datasetId }) {
  const dashboard = useQuery({
    queryKey: ["dashboard", datasetId],
    queryFn: () => analyticsApi.dashboard(datasetId),
  });

  const columnsQuery = useQuery({
    queryKey: ["columns", datasetId, true],
    queryFn: () => datasetsApi.columns(datasetId, true),
  });

  if (dashboard.isLoading) {
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-24 w-full" />
          ))}
        </div>
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  if (dashboard.isError) {
    return (
      <ErrorState
        title="Could not build the dashboard"
        message={normalizeError(dashboard.error).message}
        onRetry={dashboard.refetch}
      />
    );
  }

  const data = dashboard.data;

  return (
    <div className="space-y-6">
      {/* KPIs */}
      {data.kpis?.length > 0 && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {data.kpis.map((kpi) => (
            <StatCard
              key={kpi.label}
              label={kpi.label}
              value={formatNumber(kpi.value, { compact: true })}
            />
          ))}
        </div>
      )}

      {/* Insights */}
      {data.insights?.length > 0 && (
        <Card>
          <CardBody className="space-y-2">
            {data.insights.map((insight, index) => (
              <div key={index} className="flex items-start gap-2.5">
                <Lightbulb size={14} className="mt-0.5 shrink-0 text-accent" aria-hidden="true" />
                <p className="text-base text-muted">{insight}</p>
              </div>
            ))}
          </CardBody>
        </Card>
      )}

      {/* Auto charts */}
      <div className="grid gap-4 lg:grid-cols-2">
        {data.time_series?.length > 0 && (
          <Card>
            <CardHeader title={`${data.target_column} over time`} description="Monthly totals" />
            <CardBody>
              <ChartFrame>
                <LineChart data={data.time_series}>
                  <CartesianGrid stroke={CHART_GRID_COLOR} vertical={false} />
                  <XAxis dataKey="period" tick={axisTick} stroke={CHART_GRID_COLOR} />
                  <YAxis tick={axisTick} stroke={CHART_GRID_COLOR} width={56} />
                  <ReTooltip content={<SimpleTooltip />} />
                  <Line
                    type="monotone" dataKey="value" stroke={chartColor(0)}
                    strokeWidth={2} dot={false}
                  />
                </LineChart>
              </ChartFrame>
            </CardBody>
          </Card>
        )}

        {data.category_breakdown?.length > 0 && (
          <Card>
            <CardHeader title={`Rows by ${data.category_column}`} description="Top 10 values" />
            <CardBody>
              <ChartFrame>
                <BarChart data={data.category_breakdown}>
                  <CartesianGrid stroke={CHART_GRID_COLOR} vertical={false} />
                  <XAxis dataKey="category" tick={axisTick} stroke={CHART_GRID_COLOR} interval={0} angle={-20} textAnchor="end" height={54} />
                  <YAxis tick={axisTick} stroke={CHART_GRID_COLOR} width={48} />
                  <ReTooltip content={<SimpleTooltip />} />
                  <Bar dataKey="count" radius={[3, 3, 0, 0]} fill={chartColor(1)} />
                </BarChart>
              </ChartFrame>
            </CardBody>
          </Card>
        )}

        {data.histogram?.length > 0 && (
          <Card className="lg:col-span-2">
            <CardHeader title={`Distribution of ${data.target_column}`} />
            <CardBody>
              <ChartFrame>
                <BarChart data={data.histogram}>
                  <CartesianGrid stroke={CHART_GRID_COLOR} vertical={false} />
                  <XAxis dataKey="bin" tick={{ ...axisTick, fontSize: 9 }} stroke={CHART_GRID_COLOR} interval={0} angle={-25} textAnchor="end" height={60} />
                  <YAxis tick={axisTick} stroke={CHART_GRID_COLOR} width={48} />
                  <ReTooltip content={<SimpleTooltip />} />
                  <Bar dataKey="count" radius={[3, 3, 0, 0]} fill={chartColor(2)} />
                </BarChart>
              </ChartFrame>
            </CardBody>
          </Card>
        )}
      </div>

      {(!data.kpis?.length && !data.time_series?.length && !data.category_breakdown?.length) && (
        <EmptyState
          icon={BarChart3}
          title="No automatic charts for this dataset"
          description="Automatic charts need at least one numeric column. Use the chart builder below to configure a view manually."
        />
      )}

      {/* Builder */}
      <ChartBuilder
        datasetId={datasetId}
        columns={columnsQuery.data?.columns || []}
        loading={columnsQuery.isLoading}
        defaults={{ measure: data.target_column, dimension: data.category_column, date_column: data.date_column }}
      />
    </div>
  );
}

/* ------------------------------------------------------------ chart builder */

function ChartBuilder({ datasetId, columns, loading, defaults }) {
  const numeric = useMemo(() => columns.filter((c) => c.semantic_type === "numeric"), [columns]);
  const groupable = useMemo(
    () => columns.filter((c) => ["categorical", "boolean", "text"].includes(c.semantic_type)),
    [columns],
  );
  const dates = useMemo(() => columns.filter((c) => c.semantic_type === "datetime"), [columns]);

  const [query, setQuery] = useState({
    measure: defaults.measure || null,
    aggregation: "sum",
    dimension: defaults.dimension || null,
    date_column: null,
    time_grain: "month",
    top_n: 10,
    chart_type: "bar",
    secondary_measure: null,
    use_cleaned: true,
  });

  const run = useMutation({
    mutationFn: (payload) => analyticsApi.query(datasetId, payload),
  });

  function update(patch) {
    setQuery((current) => ({ ...current, ...patch }));
  }

  const needsDate = ["line", "area"].includes(query.chart_type);
  const needsDimension = ["bar", "horizontal_bar", "pie"].includes(query.chart_type);
  const needsSecond = query.chart_type === "scatter";
  const error = run.isError ? normalizeError(run.error) : null;

  if (loading) return <Skeleton className="h-48 w-full" />;

  return (
    <Card className="relative">
      {run.isPending && <LoadingOverlay message="Running query" />}
      <CardHeader
        title="Chart builder"
        description="Choose a measure, how to aggregate it, and how to show it"
        actions={
          <Button
            size="sm"
            icon={Play}
            onClick={() => run.mutate(query)}
            loading={run.isPending}
          >
            Run
          </Button>
        }
      />
      <CardBody className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Chart type" htmlFor="chart-type">
            <Select
              id="chart-type"
              value={query.chart_type}
              onChange={(event) => update({ chart_type: event.target.value })}
              options={CHART_TYPES}
            />
          </Field>

          <Field label="Aggregation" htmlFor="aggregation">
            <Select
              id="aggregation"
              value={query.aggregation}
              onChange={(event) => update({ aggregation: event.target.value })}
              options={AGGREGATIONS}
            />
          </Field>

          <Field
            label="Measure"
            htmlFor="measure"
            hint={query.aggregation === "count" ? "Optional for Count" : "Numeric columns only"}
          >
            <Select
              id="measure"
              value={query.measure || ""}
              onChange={(event) => update({ measure: event.target.value || null })}
              placeholder="Select a column"
              options={numeric.map((c) => ({ value: c.column, label: c.column }))}
            />
          </Field>

          {needsDimension && (
            <Field label="Group by" htmlFor="dimension">
              <Select
                id="dimension"
                value={query.dimension || ""}
                onChange={(event) => update({ dimension: event.target.value || null })}
                placeholder="Select a column"
                options={groupable.map((c) => ({ value: c.column, label: c.column }))}
              />
            </Field>
          )}

          {needsDate && (
            <>
              <Field label="Date column" htmlFor="date-column">
                <Select
                  id="date-column"
                  value={query.date_column || ""}
                  onChange={(event) => update({ date_column: event.target.value || null })}
                  placeholder={dates.length ? "Select a column" : "No date columns found"}
                  options={dates.map((c) => ({ value: c.column, label: c.column }))}
                />
              </Field>
              <Field label="Time grain" htmlFor="time-grain">
                <Select
                  id="time-grain"
                  value={query.time_grain}
                  onChange={(event) => update({ time_grain: event.target.value })}
                  options={TIME_GRAINS}
                />
              </Field>
            </>
          )}

          {needsSecond && (
            <Field label="Second measure (Y axis)" htmlFor="secondary">
              <Select
                id="secondary"
                value={query.secondary_measure || ""}
                onChange={(event) => update({ secondary_measure: event.target.value || null })}
                placeholder="Select a column"
                options={numeric
                  .filter((c) => c.column !== query.measure)
                  .map((c) => ({ value: c.column, label: c.column }))}
              />
            </Field>
          )}

          {needsDimension && (
            <Field label="Show top" htmlFor="top-n">
              <Select
                id="top-n"
                value={query.top_n}
                onChange={(event) => update({ top_n: Number(event.target.value) })}
                options={[5, 10, 15, 20, 30, 50].map((n) => ({ value: n, label: `Top ${n}` }))}
              />
            </Field>
          )}
        </div>

        {error && (
          <Alert tone="warning" title="That combination will not produce a meaningful chart">
            {error.message}
          </Alert>
        )}

        {run.data && <QueryResult result={run.data} />}
      </CardBody>
    </Card>
  );
}

/* ------------------------------------------------------------ result render */

function QueryResult({ result }) {
  const { chart_type: type } = result;

  if (type === "kpi") {
    return (
      <div className="rounded-lg border border-line bg-canvas p-6 text-center">
        <p className="text-sm text-muted">{result.label}</p>
        <p className="mt-1 text-3xl font-semibold tabular-nums text-ink">{formatNumber(result.value)}</p>
        <p className="mt-1 text-xs text-subtle">
          from {formatNumber(result.rows_considered)} rows
        </p>
      </div>
    );
  }

  const rows = result.data || [];
  if (rows.length === 0) {
    return <p className="py-6 text-center text-base text-muted">That query returned no data.</p>;
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm text-muted">
        {result.data_source && (
          <Badge tone={result.data_source === "cleaned" ? "success" : "neutral"}>
            {result.data_source} data
          </Badge>
        )}
        {result.sampled && <Badge tone="warning">Sampled</Badge>}
        {result.categories_hidden > 0 && (
          <span>{result.categories_hidden} more categories not shown</span>
        )}
        {result.correlation !== undefined && result.correlation !== null && (
          <span>Pearson r = <span className="font-mono text-ink">{result.correlation}</span></span>
        )}
      </div>

      <ChartFrame height={300}>{renderChart(type, rows, result)}</ChartFrame>
    </div>
  );
}

function renderChart(type, rows, result) {
  const common = (
    <>
      <CartesianGrid stroke={CHART_GRID_COLOR} vertical={false} />
      <ReTooltip content={<SimpleTooltip />} />
    </>
  );

  switch (type) {
    case "line":
      return (
        <LineChart data={rows}>
          {common}
          <XAxis dataKey="period" tick={axisTick} stroke={CHART_GRID_COLOR} />
          <YAxis tick={axisTick} stroke={CHART_GRID_COLOR} width={56} />
          <Line type="monotone" dataKey="value" stroke={chartColor(0)} strokeWidth={2} dot={false} />
        </LineChart>
      );
    case "area":
      return (
        <AreaChart data={rows}>
          {common}
          <XAxis dataKey="period" tick={axisTick} stroke={CHART_GRID_COLOR} />
          <YAxis tick={axisTick} stroke={CHART_GRID_COLOR} width={56} />
          <Area type="monotone" dataKey="value" stroke={chartColor(0)} fill={chartColor(0)} fillOpacity={0.18} strokeWidth={2} />
        </AreaChart>
      );
    case "horizontal_bar":
      return (
        <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 16 }}>
          <CartesianGrid stroke={CHART_GRID_COLOR} horizontal={false} />
          <ReTooltip content={<SimpleTooltip />} />
          <XAxis type="number" tick={axisTick} stroke={CHART_GRID_COLOR} />
          <YAxis type="category" dataKey="category" width={130} tick={axisTick} stroke={CHART_GRID_COLOR} />
          <Bar dataKey="value" radius={[0, 3, 3, 0]} fill={chartColor(1)} />
        </BarChart>
      );
    case "pie":
      return (
        <PieChart>
          <ReTooltip content={<SimpleTooltip />} />
          <Legend wrapperStyle={{ fontSize: 11, color: CHART_AXIS_COLOR }} />
          <Pie data={rows} dataKey="value" nameKey="category" innerRadius="45%" outerRadius="75%" paddingAngle={1}>
            {rows.map((_, index) => (
              <Cell key={index} fill={chartColor(index)} />
            ))}
          </Pie>
        </PieChart>
      );
    case "scatter":
      return (
        <ScatterChart>
          {common}
          <XAxis type="number" dataKey="x" name={result.x} tick={axisTick} stroke={CHART_GRID_COLOR} />
          <YAxis type="number" dataKey="y" name={result.y} tick={axisTick} stroke={CHART_GRID_COLOR} width={56} />
          <Scatter data={rows} fill={chartColor(4)} fillOpacity={0.65} />
        </ScatterChart>
      );
    case "histogram":
      return (
        <BarChart data={rows}>
          {common}
          <XAxis dataKey="bin" tick={{ ...axisTick, fontSize: 9 }} stroke={CHART_GRID_COLOR} interval={0} angle={-25} textAnchor="end" height={60} />
          <YAxis tick={axisTick} stroke={CHART_GRID_COLOR} width={48} />
          <Bar dataKey="count" radius={[3, 3, 0, 0]} fill={chartColor(2)} />
        </BarChart>
      );
    default:
      return (
        <BarChart data={rows}>
          {common}
          <XAxis dataKey="category" tick={axisTick} stroke={CHART_GRID_COLOR} interval={0} angle={-20} textAnchor="end" height={54} />
          <YAxis tick={axisTick} stroke={CHART_GRID_COLOR} width={56} />
          <Bar dataKey="value" radius={[3, 3, 0, 0]} fill={chartColor(1)} />
        </BarChart>
      );
  }
}

/* ------------------------------------------------------------------ shared */

const axisTick = { fill: CHART_AXIS_COLOR, fontSize: 11 };

function ChartFrame({ children, height = 240 }) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  );
}

function SimpleTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-line bg-elevated px-2.5 py-1.5 text-xs shadow-md">
      {label !== undefined && <p className="font-medium text-ink">{label}</p>}
      {payload.map((entry, index) => (
        <p key={index} className="text-muted">
          {entry.name}: <span className="font-mono text-ink">{formatNumber(entry.value)}</span>
        </p>
      ))}
    </div>
  );
}

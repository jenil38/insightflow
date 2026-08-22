/**
 * Overview dashboard.
 *
 * Every figure here comes from GET /users/me/summary, which is scoped to the
 * signed-in user. The global /metrics endpoint is deliberately not used - its
 * totals span all accounts, so showing them here would misreport the user's own
 * usage. There are no invented metrics (no "AI credits", no "team members").
 */
import { useOutletContext } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Brain, Columns3, Database, FileText, HardDrive, Rows3, Sparkles, Upload,
} from "lucide-react";

import { errorMessage } from "../api/client.js";
import { datasets as datasetsApi, users } from "../api/endpoints.js";
import { useAuth } from "../app/providers.jsx";
import DatasetTable from "../features/datasets/DatasetTable.jsx";
import {
  Alert, Button, Card, CardBody, CardHeader, ErrorState, PageHeader, Skeleton, StatCard,
} from "../components/ui/index.jsx";
import { formatBytes, formatNumber, formatRelative } from "../lib/format.js";

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export default function Home() {
  const { user } = useAuth();
  const context = useOutletContext() || {};

  const summary = useQuery({ queryKey: ["user-summary"], queryFn: users.summary });
  const datasetList = useQuery({ queryKey: ["datasets-status"], queryFn: datasetsApi.listWithStatus });

  const firstName = user?.full_name?.split(/\s+/)[0];
  const openUpload = context.onUploadClick;

  return (
    <div>
      <PageHeader
        title={`${greeting()}${firstName ? `, ${firstName}` : ""}`}
        description="Upload a dataset and InsightFlow profiles it, scores its quality, builds dashboards, trains and compares models, and explains what drives the outcome."
        actions={
          openUpload && (
            <Button icon={Upload} onClick={openUpload}>Upload dataset</Button>
          )
        }
      />

      {summary.isError ? (
        <Alert tone="danger" title="Could not load your summary" className="mb-6">
          {errorMessage(summary.error)}
        </Alert>
      ) : (
        <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatCard
            label="Datasets"
            value={formatNumber(summary.data?.dataset_count)}
            icon={Database}
            loading={summary.isLoading}
            hint={
              summary.data?.cleaned_dataset_count
                ? `${summary.data.cleaned_dataset_count} cleaned`
                : undefined
            }
          />
          <StatCard
            label="Total rows"
            value={formatNumber(summary.data?.total_rows, { compact: true })}
            icon={Rows3}
            loading={summary.isLoading}
            hint="Across all your datasets"
          />
          <StatCard
            label="Total columns"
            value={formatNumber(summary.data?.total_columns)}
            icon={Columns3}
            loading={summary.isLoading}
          />
          <StatCard
            label="Storage used"
            value={formatBytes(summary.data?.total_storage_bytes)}
            icon={HardDrive}
            loading={summary.isLoading}
          />
          {/* The one gold tile on the page. Models trained is the metric that
              represents actual work done, so it gets the standout treatment -
              but only once the user has any, or the emphasis is meaningless. */}
          <StatCard
            label="Models trained"
            value={formatNumber(summary.data?.model_run_count)}
            icon={Brain}
            loading={summary.isLoading}
            tone={summary.data?.model_run_count ? "luxe" : "default"}
          />
          <StatCard
            label="Reports generated"
            value={formatNumber(summary.data?.report_count)}
            icon={FileText}
            loading={summary.isLoading}
          />
          <StatCard
            label="Cleaned datasets"
            value={formatNumber(summary.data?.cleaned_dataset_count)}
            icon={Sparkles}
            loading={summary.isLoading}
          />
          <StatCard
            label="Latest upload"
            value={
              summary.data?.latest_upload_at ? formatRelative(summary.data.latest_upload_at) : "—"
            }
            loading={summary.isLoading}
          />
        </div>
      )}

      <Card>
        <CardHeader
          title="Your datasets"
          description="Open a workspace to explore, clean, visualise, and model a dataset."
        />
        <CardBody>
          {datasetList.isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, index) => (
                <Skeleton key={index} className="h-12 w-full" />
              ))}
            </div>
          ) : datasetList.isError ? (
            <ErrorState
              title="Could not load your datasets"
              message={errorMessage(datasetList.error)}
              onRetry={datasetList.refetch}
            />
          ) : (
            <DatasetTable datasets={datasetList.data} onUploadClick={openUpload} />
          )}
        </CardBody>
      </Card>

      {!datasetList.isLoading && datasetList.data?.length === 0 && (
        <Alert tone="info" title="What you can upload" className="mt-4">
          CSV, XLSX, XLS, or JSON, with column headers in the first row. Files are parsed on upload,
          so problems surface immediately instead of failing later in the pipeline.
        </Alert>
      )}
    </div>
  );
}

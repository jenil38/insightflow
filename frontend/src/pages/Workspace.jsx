/**
 * Dataset workspace.
 *
 * Tabs are backed by the URL (?tab=), so a view is linkable and survives a
 * refresh. Results are cached by TanStack Query rather than component state, so
 * switching tabs no longer discards everything the user just computed - the
 * original implementation cleared every result on any navigation within the
 * same dataset.
 */
import { Suspense, lazy, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  BarChart3, Bot, Brain, Download, FileText, Gauge, MessageSquare, MoreHorizontal,
  ShieldQuestion, Table2, Trash2, Wand2,
} from "lucide-react";

import { errorMessage } from "../api/client.js";
import {
  datasets as datasetsApi, reports as reportsApi, saveBlobResponse,
} from "../api/endpoints.js";
import {
  Badge, Button, ConfirmDialog, ErrorState, LoadingState, PageHeader, Skeleton,
  TabPanel, Tabs, Tooltip,
} from "../components/ui/index.jsx";

// Panels load on demand. Recharts is ~350 kB and only three panels need it, so
// opening the Data Explorer shouldn't pay for the charting library.
const DataExplorer = lazy(() => import("../features/datasets/DataExplorer.jsx"));
const QualityPanel = lazy(() => import("../features/profiling/QualityPanel.jsx"));
const CleaningPanel = lazy(() => import("../features/cleaning/CleaningPanel.jsx"));
const AnalyticsPanel = lazy(() => import("../features/analytics/AnalyticsPanel.jsx"));
const ModelsPanel = lazy(() => import("../features/machine-learning/ModelsPanel.jsx"));
const ExplainPanel = lazy(() => import("../features/explainability/ExplainPanel.jsx"));
const CopilotPanel = lazy(() => import("../features/copilot/CopilotPanel.jsx"));
const AgentPanel = lazy(() => import("../features/agent/AgentPanel.jsx"));
import { formatBytes, formatDate, formatNumber } from "../lib/format.js";

const TABS = [
  { key: "explorer", label: "Data Explorer", icon: Table2 },
  { key: "quality", label: "Data Quality", icon: Gauge },
  { key: "clean", label: "Cleaning", icon: Wand2 },
  { key: "analytics", label: "Analytics", icon: BarChart3 },
  { key: "models", label: "Models", icon: Brain },
  { key: "explain", label: "Explainability", icon: ShieldQuestion },
  { key: "copilot", label: "AI Copilot", icon: MessageSquare },
  { key: "agent", label: "Guided Analysis", icon: Bot },
];

export default function Workspace() {
  const { id } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const requestedTab = searchParams.get("tab");
  const tab = TABS.some((t) => t.key === requestedTab) ? requestedTab : "explorer";

  const dataset = useQuery({
    queryKey: ["dataset", id],
    queryFn: () => datasetsApi.get(id),
  });

  const remove = useMutation({
    mutationFn: () => datasetsApi.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["datasets"] });
      queryClient.invalidateQueries({ queryKey: ["datasets-status"] });
      queryClient.invalidateQueries({ queryKey: ["user-summary"] });
      toast.success("Dataset deleted");
      navigate("/datasets", { replace: true });
    },
    onError: (error) => toast.error(errorMessage(error, "Could not delete this dataset.")),
  });

  function setTab(next) {
    // `replace` keeps tab switches out of the browser history, so Back returns
    // to the previous page rather than walking back through tabs.
    setSearchParams({ tab: next }, { replace: true });
  }

  async function downloadReport() {
    setDownloading(true);
    try {
      const response = await reportsApi.download(id);
      saveBlobResponse(response, `InsightFlow_Report_${id}.pdf`);
      toast.success("Report downloaded");
    } catch (error) {
      toast.error(errorMessage(error, "Could not generate the report."));
    } finally {
      setDownloading(false);
    }
  }

  if (dataset.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-5 w-96" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (dataset.isError) {
    return (
      <ErrorState
        title="Could not load this dataset"
        message={errorMessage(dataset.error)}
        onRetry={dataset.refetch}
      />
    );
  }

  const info = dataset.data;

  return (
    <div>
      <PageHeader
        title={info.filename}
        actions={
          <>
            <Button
              variant="secondary"
              icon={FileText}
              onClick={downloadReport}
              loading={downloading}
            >
              Download report
            </Button>
            <Button
              variant="danger-ghost"
              icon={Trash2}
              onClick={() => setConfirmDelete(true)}
            >
              Delete
            </Button>
          </>
        }
        meta={
          <>
            <Badge tone="neutral">{info.file_type?.toUpperCase()}</Badge>
            <span>{formatNumber(info.rows)} rows</span>
            <span>{formatNumber(info.columns)} columns</span>
            <span>{formatBytes(info.size_bytes)}</span>
            <span>Uploaded {formatDate(info.uploaded_at)}</span>
            <Tooltip
              content={
                info.has_cleaned_version
                  ? "Analysis is reading the cleaned copy. The original upload is untouched."
                  : "Analysis is reading the original upload."
              }
            >
              <Badge tone={info.has_cleaned_version ? "success" : "neutral"}>
                {info.has_cleaned_version ? "Cleaned data" : "Original data"}
              </Badge>
            </Tooltip>
            {info.latest_model_name && (
              <Badge tone="accent" icon={Brain}>
                {info.latest_model_name} v{info.latest_model_version}
              </Badge>
            )}
          </>
        }
      />

      <Tabs
        tabs={TABS.map((t) => ({
          ...t,
          badge:
            t.key === "models" && info.model_run_count
              ? info.model_run_count
              : t.key === "copilot" && info.chat_message_count
                ? info.chat_message_count
                : undefined,
        }))}
        value={tab}
        onChange={setTab}
        className="mb-5"
      />

      {/* Only the active panel mounts, so switching tabs doesn't fire every
          panel's queries at once - but the query cache keeps prior results warm,
          which is what makes results survive tab switches. */}
      <Suspense fallback={<LoadingState message="Loading panel" rows={5} />}>
        <TabPanel tabKey="explorer" active={tab === "explorer"}>
          <DataExplorer datasetId={id} dataset={info} />
        </TabPanel>
        <TabPanel tabKey="quality" active={tab === "quality"}>
          <QualityPanel datasetId={id} />
        </TabPanel>
        <TabPanel tabKey="clean" active={tab === "clean"}>
          <CleaningPanel datasetId={id} dataset={info} />
        </TabPanel>
        <TabPanel tabKey="analytics" active={tab === "analytics"}>
          <AnalyticsPanel datasetId={id} />
        </TabPanel>
        <TabPanel tabKey="models" active={tab === "models"}>
          <ModelsPanel datasetId={id} />
        </TabPanel>
        <TabPanel tabKey="explain" active={tab === "explain"}>
          <ExplainPanel datasetId={id} onGoToModels={() => setTab("models")} />
        </TabPanel>
        <TabPanel tabKey="copilot" active={tab === "copilot"}>
          <CopilotPanel datasetId={id} dataset={info} />
        </TabPanel>
        <TabPanel tabKey="agent" active={tab === "agent"}>
          <AgentPanel datasetId={id} />
        </TabPanel>
      </Suspense>

      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() => remove.mutate()}
        loading={remove.isPending}
        title={`Delete ${info.filename}?`}
        message="This permanently removes the uploaded file, any cleaned copy, and every model trained from it. This cannot be undone."
        confirmLabel="Delete dataset"
      />
    </div>
  );
}

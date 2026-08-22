/**
 * Row-level data explorer.
 *
 * The original app had no way to see the actual rows. Pagination, sorting and
 * search all happen server-side, so the browser only ever holds one page - a
 * 500k-row dataset is as responsive as a 50-row one.
 */
import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import clsx from "clsx";
import {
  ArrowDown, ArrowUp, Calendar, ChevronLeft, ChevronRight, Download, Hash,
  Search, Table2, ToggleLeft, Type, X,
} from "lucide-react";

import { errorMessage } from "../../api/client.js";
import { datasets as datasetsApi, saveBlobResponse } from "../../api/endpoints.js";
import {
  Badge, Button, EmptyState, ErrorState, IconButton, Input, LoadingOverlay,
  Modal, Progress, Select, Skeleton, Tooltip,
} from "../../components/ui/index.jsx";
import { formatCell, formatNumber, formatPercent } from "../../lib/format.js";

const PAGE_SIZES = [10, 25, 50, 100];

/** Icon + colour per semantic type, so column types are scannable. */
const TYPE_META = {
  numeric: { Icon: Hash, tone: "text-accent", label: "Number" },
  datetime: { Icon: Calendar, tone: "text-success", label: "Date" },
  boolean: { Icon: ToggleLeft, tone: "text-warning", label: "Boolean" },
  categorical: { Icon: Type, tone: "text-muted", label: "Category" },
  text: { Icon: Type, tone: "text-subtle", label: "Text" },
  empty: { Icon: X, tone: "text-subtle", label: "Empty" },
};

export default function DataExplorer({ datasetId, dataset }) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [sortBy, setSortBy] = useState(null);
  const [sortDir, setSortDir] = useState("asc");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [useCleaned, setUseCleaned] = useState(true);
  const [profileColumn, setProfileColumn] = useState(null);
  const [exporting, setExporting] = useState(false);

  const hasCleaned = Boolean(dataset?.has_cleaned_version);

  // Debounce the search box so typing doesn't fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const columnsQuery = useQuery({
    queryKey: ["columns", datasetId, useCleaned],
    queryFn: () => datasetsApi.columns(datasetId, useCleaned),
  });

  const previewQuery = useQuery({
    queryKey: ["preview", datasetId, page, pageSize, sortBy, sortDir, search, useCleaned],
    queryFn: () =>
      datasetsApi.preview(datasetId, {
        page,
        page_size: pageSize,
        sort_by: sortBy || undefined,
        sort_dir: sortDir,
        search: search || undefined,
        use_cleaned: useCleaned,
      }),
    // Keep the previous page visible while the next one loads, so the table
    // doesn't collapse to a spinner on every page change.
    placeholderData: keepPreviousData,
  });

  const columnTypes = Object.fromEntries(
    (columnsQuery.data?.columns || []).map((column) => [column.column, column]),
  );

  function toggleSort(column) {
    if (sortBy !== column) {
      setSortBy(column);
      setSortDir("asc");
    } else if (sortDir === "asc") {
      setSortDir("desc");
    } else {
      setSortBy(null);
      setSortDir("asc");
    }
    setPage(1);
  }

  async function handleExport() {
    setExporting(true);
    try {
      const response = await datasetsApi.exportCsv(datasetId, useCleaned);
      saveBlobResponse(response, `${dataset?.filename || "dataset"}.csv`);
      toast.success("CSV downloaded");
    } catch (error) {
      toast.error(errorMessage(error, "Could not export this dataset."));
    } finally {
      setExporting(false);
    }
  }

  const data = previewQuery.data;
  const rows = data?.rows || [];
  const columns = data?.columns || [];

  if (previewQuery.isError) {
    return (
      <ErrorState
        title="Could not load the data"
        message={errorMessage(previewQuery.error)}
        onRetry={previewQuery.refetch}
      />
    );
  }

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[12rem] flex-1 sm:max-w-xs">
          <Search
            size={14}
            aria-hidden="true"
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-subtle"
          />
          <Input
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Search all columns"
            aria-label="Search all columns"
            className="h-9 pl-8"
          />
        </div>

        {hasCleaned && (
          <div className="flex overflow-hidden rounded-md border border-line" role="group" aria-label="Data source">
            {[
              { value: true, label: "Cleaned" },
              { value: false, label: "Original" },
            ].map((option) => (
              <button
                key={option.label}
                type="button"
                aria-pressed={useCleaned === option.value}
                onClick={() => { setUseCleaned(option.value); setPage(1); }}
                className={clsx(
                  "px-3 py-1.5 text-sm font-medium transition-colors",
                  useCleaned === option.value
                    ? "bg-accent text-accent-contrast"
                    : "bg-surface text-muted hover:bg-canvas hover:text-ink",
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        )}

        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            icon={Download}
            onClick={handleExport}
            loading={exporting}
          >
            Export CSV
          </Button>
        </div>
      </div>

      {/* Meta line */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
        <span>
          <span className="font-medium text-ink">{formatNumber(data?.total_rows)}</span> rows
          {search && " matching"}
        </span>
        <span>
          <span className="font-medium text-ink">{columns.length}</span> columns
        </span>
        {data?.source && (
          <Badge tone={data.source === "cleaned" ? "success" : "neutral"}>
            {data.source === "cleaned" ? "Cleaned data" : "Original data"}
          </Badge>
        )}
        {search && (
          <button
            type="button"
            onClick={() => setSearchInput("")}
            className="text-accent hover:underline"
          >
            Clear search
          </button>
        )}
      </div>

      {/* Table */}
      <div className="relative overflow-hidden rounded-lg border border-line">
        {previewQuery.isFetching && !previewQuery.isLoading && (
          <LoadingOverlay message="Loading rows" />
        )}

        {previewQuery.isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 8 }).map((_, index) => (
              <Skeleton key={index} className="h-8 w-full" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={Table2}
            title={search ? "No matching rows" : "No rows to show"}
            description={
              search
                ? `Nothing in this dataset matches "${search}".`
                : "This dataset appears to be empty."
            }
            action={
              search && (
                <Button variant="secondary" onClick={() => setSearchInput("")}>Clear search</Button>
              )
            }
          />
        ) : (
          <div className="max-h-[65vh] overflow-auto">
            <table className="w-full border-collapse text-sm">
              {/* Sticky header survives vertical scrolling of a long page. */}
              <thead className="sticky top-0 z-10 bg-canvas">
                <tr>
                  <th
                    scope="col"
                    className="w-12 border-b border-line px-2 py-2 text-right text-2xs font-semibold uppercase text-subtle"
                  >
                    #
                  </th>
                  {columns.map((column) => {
                    const meta = TYPE_META[columnTypes[column]?.semantic_type] || TYPE_META.text;
                    const active = sortBy === column;
                    const missingPct = columnTypes[column]?.missing_pct || 0;
                    return (
                      <th
                        key={column}
                        scope="col"
                        aria-sort={active ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
                        className="border-b border-line px-3 py-2 text-left font-semibold"
                      >
                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() => toggleSort(column)}
                            className="flex min-w-0 items-center gap-1.5 rounded transition-colors hover:text-accent focus-visible:ring-2 focus-visible:ring-accent/50"
                            title={`Sort by ${column}`}
                          >
                            <meta.Icon size={12} className={clsx("shrink-0", meta.tone)} aria-hidden="true" />
                            <span className="max-w-[12rem] truncate text-ink">{column}</span>
                            {active &&
                              (sortDir === "asc" ? (
                                <ArrowUp size={11} className="shrink-0 text-accent" aria-hidden="true" />
                              ) : (
                                <ArrowDown size={11} className="shrink-0 text-accent" aria-hidden="true" />
                              ))}
                          </button>
                          <button
                            type="button"
                            onClick={() => setProfileColumn(column)}
                            className="text-2xs font-normal text-subtle hover:text-accent hover:underline"
                            aria-label={`View statistics for ${column}`}
                          >
                            stats
                          </button>
                        </div>
                        {missingPct > 0 && (
                          <Tooltip content={`${formatPercent(missingPct)} of values are missing`}>
                            <span className="mt-0.5 block text-2xs font-normal text-warning">
                              {formatPercent(missingPct)} missing
                            </span>
                          </Tooltip>
                        )}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, rowIndex) => (
                  <tr key={rowIndex} className="border-b border-line last:border-0 hover:bg-canvas">
                    <td className="px-2 py-1.5 text-right text-2xs tabular-nums text-subtle">
                      {(page - 1) * pageSize + rowIndex + 1}
                    </td>
                    {columns.map((column) => {
                      const value = row[column];
                      const isNumeric = columnTypes[column]?.semantic_type === "numeric";
                      const rendered = formatCell(value);
                      return (
                        <td
                          key={column}
                          className={clsx("px-3 py-1.5", isNumeric && "numeric")}
                        >
                          {rendered === null ? (
                            // A missing value must be visibly distinct from an
                            // empty string, or data-quality problems stay hidden.
                            <span className="rounded bg-canvas px-1 text-2xs italic text-subtle">null</span>
                          ) : (
                            <span className="block max-w-[18rem] truncate" title={rendered}>
                              {rendered}
                            </span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination */}
      {data && data.total_pages > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <label htmlFor="page-size" className="text-sm text-muted">Rows per page</label>
            <Select
              id="page-size"
              value={pageSize}
              onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }}
              options={PAGE_SIZES.map((size) => ({ value: size, label: String(size) }))}
              className="h-8 w-20 py-1"
            />
          </div>

          <div className="flex items-center gap-2">
            <p className="text-sm text-muted" role="status" aria-live="polite">
              Page <span className="font-medium text-ink">{data.page}</span> of{" "}
              <span className="font-medium text-ink">{data.total_pages}</span>
            </p>
            <div className="flex gap-1">
              <IconButton
                icon={ChevronLeft}
                label="Previous page"
                variant="secondary"
                size="sm"
                disabled={data.page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              />
              <IconButton
                icon={ChevronRight}
                label="Next page"
                variant="secondary"
                size="sm"
                disabled={data.page >= data.total_pages}
                onClick={() => setPage((current) => current + 1)}
              />
            </div>
          </div>
        </div>
      )}

      <ColumnProfileModal
        datasetId={datasetId}
        column={profileColumn}
        useCleaned={useCleaned}
        onClose={() => setProfileColumn(null)}
      />
    </div>
  );
}

/* ------------------------------------------------------ column profile modal */

function ColumnProfileModal({ datasetId, column, useCleaned, onClose }) {
  const query = useQuery({
    queryKey: ["column-profile", datasetId, column, useCleaned],
    queryFn: () => datasetsApi.columnProfile(datasetId, column, useCleaned),
    enabled: Boolean(column),
  });

  const profile = query.data;
  const meta = TYPE_META[profile?.semantic_type] || TYPE_META.text;

  return (
    <Modal open={Boolean(column)} onClose={onClose} title={column || ""} size="lg">
      {query.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-8 w-full" />
          ))}
        </div>
      ) : query.isError ? (
        <ErrorState message={errorMessage(query.error)} onRetry={query.refetch} />
      ) : profile ? (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="accent" icon={meta.Icon}>{meta.label}</Badge>
            <Badge tone="neutral">{profile.dtype}</Badge>
            {profile.is_constant && <Badge tone="warning">Constant</Badge>}
            {profile.sampled && <Badge tone="warning">Sampled</Badge>}
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Non-null" value={formatNumber(profile.non_null_count)} />
            <Stat label="Missing" value={formatNumber(profile.missing_count)} />
            <Stat label="Missing %" value={formatPercent(profile.missing_pct)} />
            <Stat label="Distinct" value={formatNumber(profile.unique_count)} />
          </div>

          <Progress
            value={100 - (profile.missing_pct || 0)}
            label="Completeness"
            tone={(profile.missing_pct || 0) > 40 ? "danger" : (profile.missing_pct || 0) > 0 ? "warning" : "success"}
          />

          {profile.semantic_type === "numeric" && (
            <div>
              <h4 className="mb-2 text-sm font-semibold text-ink">Distribution statistics</h4>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Stat label="Minimum" value={formatNumber(profile.min)} />
                <Stat label="Maximum" value={formatNumber(profile.max)} />
                <Stat label="Mean" value={formatNumber(profile.mean)} />
                <Stat label="Median" value={formatNumber(profile.median)} />
                <Stat label="Std deviation" value={formatNumber(profile.std)} />
                <Stat
                  label="Outliers"
                  value={formatNumber(profile.outlier_count)}
                  hint="Outside 1.5×IQR"
                />
              </div>
            </div>
          )}

          {profile.histogram?.length > 0 && <MiniHistogram data={profile.histogram} />}

          {profile.top_values?.length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold text-ink">Most common values</h4>
              <div className="overflow-hidden rounded-md border border-line">
                <table className="w-full text-sm">
                  <thead className="bg-canvas">
                    <tr>
                      <th scope="col" className="px-3 py-1.5 text-left font-semibold text-subtle">Value</th>
                      <th scope="col" className="px-3 py-1.5 text-right font-semibold text-subtle">Count</th>
                      <th scope="col" className="px-3 py-1.5 text-right font-semibold text-subtle">Share</th>
                    </tr>
                  </thead>
                  <tbody>
                    {profile.top_values.map((entry, index) => (
                      <tr key={index} className="border-t border-line">
                        <td className="max-w-[16rem] truncate px-3 py-1.5">
                          {entry.value === null ? (
                            <span className="italic text-subtle">null</span>
                          ) : (
                            String(entry.value)
                          )}
                        </td>
                        <td className="numeric px-3 py-1.5">{formatNumber(entry.count)}</td>
                        <td className="numeric px-3 py-1.5 text-muted">{formatPercent(entry.pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {profile.example_values?.length > 0 && (
            <div>
              <h4 className="mb-1.5 text-sm font-semibold text-ink">Example values</h4>
              <div className="flex flex-wrap gap-1.5">
                {profile.example_values.map((value, index) => (
                  <code key={index} className="rounded bg-canvas px-1.5 py-0.5 text-xs text-muted">
                    {value === null ? "null" : String(value)}
                  </code>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : null}
    </Modal>
  );
}

function Stat({ label, value, hint }) {
  return (
    <div className="surface-inset rounded-lg px-3 py-2">
      <p className="text-2xs uppercase tracking-wide text-subtle">{label}</p>
      <p className="mt-0.5 font-medium tabular-nums text-ink">{value}</p>
      {hint && <p className="text-2xs text-subtle">{hint}</p>}
    </div>
  );
}

/** Pure-CSS bar chart - a full charting library is overkill for a modal sparkline. */
function MiniHistogram({ data }) {
  const max = Math.max(...data.map((bin) => bin.count), 1);
  return (
    <div>
      <h4 className="mb-2 text-sm font-semibold text-ink">Distribution</h4>
      <div className="flex h-24 items-end gap-0.5" role="img" aria-label="Value distribution histogram">
        {data.map((bin, index) => (
          <Tooltip key={index} content={`${bin.bin}: ${formatNumber(bin.count)}`}>
            <span
              className="block w-full min-w-[3px] rounded-t bg-accent/70 transition-colors hover:bg-accent"
              style={{ height: `${Math.max((bin.count / max) * 100, 2)}%` }}
            />
          </Tooltip>
        ))}
      </div>
      <div className="mt-1 flex justify-between text-2xs text-subtle">
        <span>{data[0]?.bin}</span>
        <span>{data[data.length - 1]?.bin}</span>
      </div>
    </div>
  );
}

/**
 * Datasets table, built on TanStack Table.
 *
 * Every column is real data from the API. Deletion is behind a confirmation
 * dialog because it removes the upload, the cleaned copy, and every trained
 * model for that dataset.
 */
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  createColumnHelper, flexRender, getCoreRowModel, getFilteredRowModel,
  getSortedRowModel, useReactTable,
} from "@tanstack/react-table";
import { toast } from "sonner";
import clsx from "clsx";
import {
  ArrowUpDown, Brain, Database, MoreHorizontal, Search, Sparkles, Trash2,
} from "lucide-react";

import { errorMessage } from "../../api/client.js";
import { datasets as datasetsApi } from "../../api/endpoints.js";
import {
  Badge, Button, ConfirmDialog, EmptyState, IconButton, Input,
} from "../../components/ui/index.jsx";
import { formatBytes, formatNumber, formatRelative } from "../../lib/format.js";

const helper = createColumnHelper();

export default function DatasetTable({ datasets = [], onUploadClick }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [sorting, setSorting] = useState([{ id: "uploaded_at", desc: true }]);
  const [pendingDelete, setPendingDelete] = useState(null);
  const [menuFor, setMenuFor] = useState(null);

  const remove = useMutation({
    mutationFn: (id) => datasetsApi.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["datasets"] });
      queryClient.invalidateQueries({ queryKey: ["datasets-status"] });
      queryClient.invalidateQueries({ queryKey: ["user-summary"] });
      toast.success(`${pendingDelete?.filename} deleted`);
      setPendingDelete(null);
    },
    onError: (error) => toast.error(errorMessage(error, "Could not delete that dataset.")),
  });

  const columns = useMemo(
    () => [
      helper.accessor("filename", {
        header: "Dataset",
        cell: (info) => (
          <div className="flex min-w-0 items-center gap-2.5">
            <Database size={15} className="shrink-0 text-subtle" aria-hidden="true" />
            <div className="min-w-0">
              <p className="truncate font-medium text-ink">{info.getValue()}</p>
              <p className="text-xs uppercase text-subtle">{info.row.original.file_type}</p>
            </div>
          </div>
        ),
      }),
      helper.accessor("rows", {
        header: "Rows",
        cell: (info) => <span className="numeric">{formatNumber(info.getValue())}</span>,
      }),
      helper.accessor("columns", {
        header: "Columns",
        cell: (info) => <span className="numeric">{formatNumber(info.getValue())}</span>,
      }),
      helper.accessor("size_bytes", {
        header: "Size",
        cell: (info) => <span className="numeric">{formatBytes(info.getValue())}</span>,
      }),
      helper.accessor("has_cleaned_version", {
        header: "Data",
        enableSorting: false,
        cell: (info) =>
          info.getValue() ? (
            <Badge tone="success" icon={Sparkles}>Cleaned</Badge>
          ) : (
            <Badge tone="neutral">Original</Badge>
          ),
      }),
      helper.accessor("latest_model_name", {
        header: "Model",
        enableSorting: false,
        cell: (info) => {
          const name = info.getValue();
          const count = info.row.original.model_run_count;
          if (!name) return <span className="text-sm text-subtle">Not trained</span>;
          return (
            <div className="flex items-center gap-1.5">
              <Badge tone="accent" icon={Brain}>{name}</Badge>
              {count > 1 && <span className="text-xs text-subtle">v{count}</span>}
            </div>
          );
        },
      }),
      helper.accessor("uploaded_at", {
        header: "Uploaded",
        cell: (info) => <span className="whitespace-nowrap text-muted">{formatRelative(info.getValue())}</span>,
      }),
      helper.display({
        id: "actions",
        header: "",
        cell: (info) => {
          const dataset = info.row.original;
          const open = menuFor === dataset.id;
          return (
            <div className="relative flex justify-end">
              <IconButton
                icon={MoreHorizontal}
                label={`Actions for ${dataset.filename}`}
                size="sm"
                aria-haspopup="menu"
                aria-expanded={open}
                onClick={(event) => {
                  event.stopPropagation();
                  setMenuFor(open ? null : dataset.id);
                }}
              />
              {open && (
                <>
                  {/* Click-away layer, so the menu closes on any outside click. */}
                  <div
                    className="fixed inset-0 z-30"
                    onClick={(event) => { event.stopPropagation(); setMenuFor(null); }}
                    aria-hidden="true"
                  />
                  <div
                    role="menu"
                    className="absolute right-0 top-8 z-40 w-44 overflow-hidden rounded-md border border-line bg-elevated shadow-lg"
                  >
                    <button
                      role="menuitem"
                      onClick={(event) => {
                        event.stopPropagation();
                        setMenuFor(null);
                        navigate(`/workspace/${dataset.id}`);
                      }}
                      className="block w-full px-3 py-2 text-left text-base text-muted hover:bg-canvas hover:text-ink"
                    >
                      Open workspace
                    </button>
                    <button
                      role="menuitem"
                      onClick={(event) => {
                        event.stopPropagation();
                        setMenuFor(null);
                        setPendingDelete(dataset);
                      }}
                      className="flex w-full items-center gap-2 px-3 py-2 text-left text-base text-danger hover:bg-danger-soft"
                    >
                      <Trash2 size={14} aria-hidden="true" />
                      Delete
                    </button>
                  </div>
                </>
              )}
            </div>
          );
        },
      }),
    ],
    [menuFor, navigate],
  );

  const table = useReactTable({
    data: datasets,
    columns,
    state: { sorting, globalFilter: search },
    onSortingChange: setSorting,
    onGlobalFilterChange: setSearch,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  if (datasets.length === 0) {
    return (
      <EmptyState
        icon={Database}
        title="No datasets yet"
        description="Upload a CSV, Excel, or JSON file to get profiling, a data-quality report, dashboards, and trained models."
        action={<Button onClick={onUploadClick}>Upload your first dataset</Button>}
      />
    );
  }

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <div className="relative max-w-xs flex-1">
          <Search
            size={14}
            aria-hidden="true"
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-subtle"
          />
          <Input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search datasets"
            aria-label="Search datasets"
            className="h-9 pl-8"
          />
        </div>
        <p className="ml-auto text-sm text-muted">
          {table.getFilteredRowModel().rows.length} of {datasets.length}
        </p>
      </div>

      {/* Horizontal scroll on small screens rather than a squashed layout. */}
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full min-w-[880px] border-collapse text-base">
          <thead className="bg-canvas">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const sortable = header.column.getCanSort();
                  const direction = header.column.getIsSorted();
                  return (
                    <th
                      key={header.id}
                      scope="col"
                      aria-sort={
                        direction === "asc" ? "ascending" : direction === "desc" ? "descending" : "none"
                      }
                      className="border-b border-line px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-subtle"
                    >
                      {sortable ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className="inline-flex items-center gap-1 rounded transition-colors hover:text-ink focus-visible:ring-2 focus-visible:ring-accent/50"
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          <ArrowUpDown size={11} className={clsx(direction ? "text-accent" : "opacity-40")} aria-hidden="true" />
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                onClick={() => navigate(`/workspace/${row.original.id}`)}
                className="cursor-pointer border-b border-line last:border-0 transition-colors hover:bg-canvas"
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-3 py-2.5 align-middle">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {table.getFilteredRowModel().rows.length === 0 && (
        <p className="py-6 text-center text-base text-muted">No datasets match "{search}".</p>
      )}

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={() => remove.mutate(pendingDelete.id)}
        loading={remove.isPending}
        title={`Delete ${pendingDelete?.filename}?`}
        message={
          "This permanently removes the uploaded file, any cleaned copy, and every model trained " +
          "from it. This cannot be undone."
        }
        confirmLabel="Delete dataset"
      />
    </div>
  );
}

/**
 * Dataset upload: drag-and-drop, client-side validation, real progress, cancel,
 * and retry.
 *
 * Only the formats the backend genuinely parses are advertised (CSV, XLSX, XLS,
 * JSON) - and the size limit shown is read from /health rather than hard-coded,
 * so the UI cannot drift from the server's actual MAX_UPLOAD_SIZE_MB.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import clsx from "clsx";
import { AlertCircle, FileSpreadsheet, UploadCloud, X } from "lucide-react";

import { normalizeError } from "../../api/client.js";
import { datasets as datasetsApi, ops } from "../../api/endpoints.js";
import { Alert, Button, Modal, Progress } from "../../components/ui/index.jsx";
import { formatBytes } from "../../lib/format.js";

const ACCEPTED_EXTENSIONS = [".csv", ".xlsx", ".xls", ".json"];
const DEFAULT_MAX_MB = 50;

export default function UploadDialog({ open, onClose }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const inputRef = useRef(null);
  const abortRef = useRef(null);

  const [file, setFile] = useState(null);
  const [validationError, setValidationError] = useState(null);
  const [progress, setProgress] = useState(null);
  const [dragActive, setDragActive] = useState(false);

  const { data: health } = useQuery({ queryKey: ["health"], queryFn: ops.health, staleTime: 60_000 });
  const maxMb = health?.limits?.max_upload_mb ?? DEFAULT_MAX_MB;

  const reset = useCallback(() => {
    setFile(null);
    setValidationError(null);
    setProgress(null);
    setDragActive(false);
    abortRef.current = null;
  }, []);

  useEffect(() => {
    if (!open) reset();
  }, [open, reset]);

  const upload = useMutation({
    mutationFn: (selected) => {
      const controller = new AbortController();
      abortRef.current = controller;
      return datasetsApi.upload(selected, {
        signal: controller.signal,
        onProgress: setProgress,
      });
    },
    onSuccess: (dataset) => {
      queryClient.invalidateQueries({ queryKey: ["datasets"] });
      queryClient.invalidateQueries({ queryKey: ["user-summary"] });
      toast.success(`${dataset.filename} uploaded`, {
        description: `${dataset.rows?.toLocaleString()} rows, ${dataset.columns} columns`,
      });
      onClose?.();
      navigate(`/workspace/${dataset.id}`);
    },
    onError: (error) => {
      setProgress(null);
      if (normalizeError(error).code === "cancelled") return;
    },
  });

  function validate(selected) {
    if (!selected) return "No file selected.";
    const extension = selected.name.slice(selected.name.lastIndexOf(".")).toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(extension)) {
      return `${extension || "That file type"} is not supported. Use CSV, XLSX, XLS, or JSON.`;
    }
    if (selected.size === 0) return "That file is empty.";
    if (selected.size > maxMb * 1024 * 1024) {
      return `That file is ${formatBytes(selected.size)}, over the ${maxMb} MB limit.`;
    }
    return null;
  }

  function select(selected) {
    const error = validate(selected);
    setValidationError(error);
    setFile(error ? null : selected);
    if (error) upload.reset();
  }

  function handleCancel() {
    abortRef.current?.abort();
    setProgress(null);
    upload.reset();
    toast.info("Upload cancelled");
  }

  const uploadError = upload.isError ? normalizeError(upload.error, "Upload failed.") : null
  const busy = upload.isPending;

  return (
    <Modal
      open={open}
      onClose={busy ? undefined : onClose}
      title="Upload a dataset"
      description={`CSV, XLSX, XLS, or JSON, up to ${maxMb} MB.`}
      footer={
        busy ? (
          <Button variant="secondary" icon={X} onClick={handleCancel}>Cancel upload</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={onClose}>Close</Button>
            <Button
              icon={UploadCloud}
              disabled={!file}
              onClick={() => upload.mutate(file)}
            >
              {uploadError ? "Retry upload" : "Upload"}
            </Button>
          </>
        )
      }
    >
      <div className="space-y-4">
        {/* Drop zone. Keyboard accessible: it is a real button, so Enter/Space
            open the file picker. */}
        <button
          type="button"
          disabled={busy}
          onClick={() => inputRef.current?.click()}
          onDragOver={(event) => { event.preventDefault(); setDragActive(true); }}
          onDragLeave={() => setDragActive(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragActive(false);
            if (!busy) select(event.dataTransfer.files?.[0]);
          }}
          className={clsx(
            "flex w-full flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-8 transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
            dragActive ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong hover:bg-canvas",
            busy && "cursor-not-allowed opacity-60",
          )}
        >
          <UploadCloud size={22} className={clsx("mb-2", dragActive ? "text-accent" : "text-subtle")} aria-hidden="true" />
          <span className="text-base font-medium text-ink">
            {dragActive ? "Drop the file here" : "Drag a file here, or click to browse"}
          </span>
          <span className="mt-0.5 text-sm text-muted">
            {ACCEPTED_EXTENSIONS.join(", ")} &middot; max {maxMb} MB
          </span>
        </button>

        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS.join(",")}
          className="sr-only"
          onChange={(event) => select(event.target.files?.[0])}
          aria-label="Choose a dataset file"
        />

        {validationError && (
          <Alert tone="danger" title="That file cannot be uploaded">{validationError}</Alert>
        )}

        {file && (
          <div className="flex items-center gap-3 surface-inset rounded-lg px-3 py-2.5">
            <FileSpreadsheet size={18} className="shrink-0 text-accent" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-base font-medium text-ink">{file.name}</p>
              <p className="text-sm text-muted">
                {formatBytes(file.size)}
                {" · "}
                {file.name.slice(file.name.lastIndexOf(".") + 1).toUpperCase()}
              </p>
            </div>
            {!busy && (
              <Button variant="ghost" size="sm" onClick={() => reset()}>Remove</Button>
            )}
          </div>
        )}

        {busy && (
          <div>
            <Progress
              value={progress ?? 0}
              label={progress === null ? "Uploading" : "Uploading"}
              showValue={progress !== null}
            />
            <p className="mt-1.5 text-sm text-muted" role="status" aria-live="polite">
              {progress === null
                ? "Uploading - the server did not report a total size, so progress is indeterminate."
                : progress >= 100
                  ? "Upload complete. Parsing and profiling the file..."
                  : `Uploading ${file?.name}`}
            </p>
          </div>
        )}

        {uploadError && (
          <Alert tone="danger" title="Upload failed">
            <p>{uploadError.message}</p>
            {uploadError.code === "unparseable_file" && (
              <p className="mt-1">
                The file reached the server but could not be parsed. Check that it opens correctly in
                a spreadsheet application first.
              </p>
            )}
          </Alert>
        )}

        {!file && !busy && (
          <div className="flex items-start gap-2 text-sm text-muted">
            <AlertCircle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
            <p>
              The first row should contain column headers. Files are parsed on upload, so an invalid
              file is rejected immediately rather than failing later.
            </p>
          </div>
        )}
      </div>
    </Modal>
  );
}

"""
Dataset service layer: upload validation, listing, row-level preview, column
metadata, CSV export, and deletion.

`read_dataframe` is re-exported from dataframe_io for backward compatibility -
several routers import it from this module.
"""

from __future__ import annotations

import io
import os
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..core.config import settings
from ..core.exceptions import NotFoundError, ValidationAppError
from ..core.serialization import dataframe_records, to_jsonable
from ..repositories.dataset_repository import DatasetRepository
from .dataframe_io import load_dataset, read_dataframe, resolve_path  # noqa: F401 - re-exported
from .profiling_service import profiling_service

ALLOWED_EXT = {".csv", ".xlsx", ".json"}

# Extension -> the content types browsers and tools actually send. Checked as a
# secondary signal only: the extension plus a successful parse is the real gate,
# because clients routinely send application/octet-stream for spreadsheets.
EXPECTED_CONTENT_TYPES = {
    ".csv": {"text/csv", "application/csv", "text/plain", "application/vnd.ms-excel"},
    ".xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/zip",
    },
    ".xls": {"application/vnd.ms-excel", "application/x-ole-storage"},
    ".json": {"application/json", "text/json", "text/plain"},
}
GENERIC_CONTENT_TYPES = {"application/octet-stream", "binary/octet-stream", ""}


def safe_filename(filename: str) -> str:
    """Keep the user-visible filename readable while removing anything that
    could escape the upload directory or confuse the filesystem.

    Note this is for display only - the file is stored under a generated UUID
    name, so a crafted filename can never determine the path written to.
    """
    base = os.path.basename(filename or "dataset")
    base = base.replace("\x00", "")
    base = re.sub(r"[^A-Za-z0-9._ \-()]", "_", base).strip(" .")
    if len(base) > 180:
        stem, ext = os.path.splitext(base)
        base = stem[: 180 - len(ext)] + ext
    return base or "dataset"


class DatasetService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = DatasetRepository(db)

    # -------------------------------------------------------------- upload
    def upload(
        self,
        owner_id: int,
        filename: str,
        contents: bytes,
        content_type: str | None = None,
    ) -> models.Dataset:
        display_name = safe_filename(filename)
        ext = os.path.splitext(display_name)[1].lower()

        if ext not in ALLOWED_EXT:
            raise ValidationAppError(
                "Only CSV, Excel (.xlsx/.xls), or JSON files are allowed",
                error_code="unsupported_file_type",
                status_code=400,
            )
        if len(contents) == 0:
            raise ValidationAppError(
                "Uploaded file is empty", error_code="empty_file", status_code=400
            )
        if len(contents) > settings.max_upload_size_bytes:
            raise ValidationAppError(
                f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB}MB upload limit",
                error_code="file_too_large",
                status_code=413,
            )

        normalized_type = (content_type or "").split(";")[0].strip().lower()
        if normalized_type and normalized_type not in GENERIC_CONTENT_TYPES:
            if normalized_type not in EXPECTED_CONTENT_TYPES.get(ext, set()):
                raise ValidationAppError(
                    f"The file's content type ({normalized_type}) does not match a {ext} file.",
                    error_code="content_type_mismatch",
                    status_code=400,
                )

        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}{ext}"
        stored_path = os.path.join(settings.UPLOAD_DIR, stored_name)
        with open(stored_path, "wb") as handle:
            handle.write(contents)

        try:
            df = read_dataframe(stored_path, ext)
        except Exception as exc:  # noqa: BLE001
            self._discard(stored_path)
            raise ValidationAppError(
                "Could not parse this file. Check that it is a valid, uncorrupted "
                f"{ext.lstrip('.').upper()} file.",
                error_code="unparseable_file",
                status_code=400,
            ) from exc

        if df is None or df.empty:
            self._discard(stored_path)
            raise ValidationAppError(
                "The file parsed successfully but contains no rows.",
                error_code="empty_dataset",
                status_code=400,
            )
        if df.shape[1] == 0:
            self._discard(stored_path)
            raise ValidationAppError(
                "The file contains no columns.",
                error_code="no_columns",
                status_code=400,
            )

        rows, cols = df.shape
        schema_info = [{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns]
        dataset = models.Dataset(
            owner_id=owner_id,
            filename=display_name,
            original_filename=display_name,
            stored_path=stored_path,
            file_type=ext.lstrip("."),
            rows=int(rows),
            columns=int(cols),
            size_bytes=len(contents),
            schema_info=schema_info,
            processing_status="ready",
        )
        return self.repo.create(dataset)

    @staticmethod
    def _discard(path: str) -> None:
        """Remove a just-written upload that turned out to be invalid, so a
        rejected upload doesn't leave an orphan file behind."""
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    # ------------------------------------------------------------- listing
    def list_all(self, owner_id: int):
        return self.repo.list_for_owner(owner_id)

    def list_paginated(self, owner_id: int, page: int, page_size: int):
        return self.repo.list_for_owner_paginated(owner_id, page, page_size)

    def list_with_status(self, owner_id: int) -> list[dict[str, Any]]:
        """Datasets plus their cleaning/model status, for the datasets table.

        Model counts are fetched in one grouped query rather than per row, so
        the list stays a fixed number of queries regardless of dataset count.
        """
        from sqlalchemy import func

        datasets = self.repo.list_for_owner(owner_id)
        if not datasets:
            return []

        ids = [d.id for d in datasets]
        counts = dict(
            self.db.query(models.ModelRun.dataset_id, func.count(models.ModelRun.id))
            .filter(models.ModelRun.dataset_id.in_(ids))
            .group_by(models.ModelRun.dataset_id)
            .all()
        )
        latest_runs = (
            self.db.query(models.ModelRun)
            .filter(models.ModelRun.dataset_id.in_(ids))
            .order_by(models.ModelRun.dataset_id, models.ModelRun.version.desc())
            .all()
        )
        latest_by_dataset: dict[int, models.ModelRun] = {}
        for run in latest_runs:
            latest_by_dataset.setdefault(run.dataset_id, run)

        out = []
        for d in datasets:
            latest = latest_by_dataset.get(d.id)
            out.append(
                {
                    "id": d.id,
                    "filename": d.filename,
                    "file_type": d.file_type,
                    "rows": d.rows,
                    "columns": d.columns,
                    "size_bytes": d.size_bytes,
                    "uploaded_at": d.uploaded_at,
                    "has_cleaned_version": bool(
                        d.cleaned_path and os.path.exists(d.cleaned_path)
                    ),
                    "model_run_count": int(counts.get(d.id, 0)),
                    "latest_model_name": latest.best_model_name if latest else None,
                }
            )
        return out

    def detail(self, dataset: models.Dataset, user_id: int) -> dict[str, Any]:
        """Full metadata for the workspace header, in a single request."""
        from sqlalchemy import func

        has_cleaned = bool(
            dataset.cleaned_path and os.path.exists(dataset.cleaned_path)
        )
        latest = (
            self.db.query(models.ModelRun)
            .filter(
                models.ModelRun.dataset_id == dataset.id,
                models.ModelRun.user_id == user_id,
            )
            .order_by(models.ModelRun.version.desc())
            .first()
        )
        model_count = (
            self.db.query(func.count(models.ModelRun.id))
            .filter(
                models.ModelRun.dataset_id == dataset.id,
                models.ModelRun.user_id == user_id,
            )
            .scalar()
            or 0
        )
        report_count = (
            self.db.query(func.count(models.ReportRecord.id))
            .filter(
                models.ReportRecord.dataset_id == dataset.id,
                models.ReportRecord.user_id == user_id,
            )
            .scalar()
            or 0
        )
        chat_count = (
            self.db.query(func.count(models.ChatMessage.id))
            .filter(
                models.ChatMessage.dataset_id == dataset.id,
                models.ChatMessage.user_id == user_id,
            )
            .scalar()
            or 0
        )
        return {
            "id": dataset.id,
            "filename": dataset.filename,
            "file_type": dataset.file_type,
            "rows": dataset.rows,
            "columns": dataset.columns,
            "size_bytes": dataset.size_bytes,
            "uploaded_at": dataset.uploaded_at,
            "has_cleaned_version": has_cleaned,
            "active_source": "cleaned" if has_cleaned else "original",
            "model_run_count": int(model_count),
            "latest_model_name": latest.best_model_name if latest else None,
            "latest_model_version": latest.version if latest else None,
            "latest_model_trained_at": latest.created_at if latest else None,
            "report_count": int(report_count),
            "chat_message_count": int(chat_count),
        }

    def user_summary(self, user_id: int) -> dict[str, Any]:
        """Per-user totals for the home dashboard. Scoped to this user only -
        the global /metrics endpoint must never be used for this."""
        from sqlalchemy import func

        datasets = self.repo.list_for_owner(user_id)
        model_runs = (
            self.db.query(func.count(models.ModelRun.id))
            .filter(models.ModelRun.user_id == user_id)
            .scalar()
            or 0
        )
        reports = (
            self.db.query(func.count(models.ReportRecord.id))
            .filter(models.ReportRecord.user_id == user_id)
            .scalar()
            or 0
        )
        return {
            "dataset_count": len(datasets),
            "total_rows": sum(d.rows or 0 for d in datasets),
            "total_columns": sum(d.columns or 0 for d in datasets),
            "total_storage_bytes": sum(d.size_bytes or 0 for d in datasets),
            "latest_upload_at": max(
                (d.uploaded_at for d in datasets if d.uploaded_at), default=None
            ),
            "model_run_count": int(model_runs),
            "report_count": int(reports),
            "cleaned_dataset_count": sum(
                1 for d in datasets if d.cleaned_path and os.path.exists(d.cleaned_path)
            ),
        }

    # ------------------------------------------------------------- preview
    def preview(
        self,
        dataset: models.Dataset,
        page: int = 1,
        page_size: int = 25,
        sort_by: str | None = None,
        sort_dir: str = "asc",
        search: str | None = None,
        columns: list[str] | None = None,
        use_cleaned: bool = True,
    ) -> dict[str, Any]:
        """Paginated row-level preview.

        Pagination happens server-side and `page_size` is capped, so a client can
        never pull an entire dataset into one response.
        """
        page_size = max(1, min(page_size, settings.PREVIEW_MAX_PAGE_SIZE))
        loaded = load_dataset(dataset, prefer="auto" if use_cleaned else "original")
        df = loaded.df

        if columns:
            missing = [c for c in columns if c not in df.columns]
            if missing:
                raise ValidationAppError(
                    f"Unknown column(s): {', '.join(missing[:5])}",
                    error_code="unknown_column",
                    status_code=400,
                )
            df = df[columns]

        if search:
            needle = str(search).strip()
            if needle:
                # Match across all columns as text; regex=False so user input is
                # never interpreted as a pattern.
                mask = df.apply(
                    lambda col: col.astype(str).str.contains(
                        needle, case=False, na=False, regex=False
                    )
                ).any(axis=1)
                df = df[mask]

        if sort_by:
            if sort_by not in df.columns:
                raise ValidationAppError(
                    f"Cannot sort by unknown column '{sort_by}'.",
                    error_code="unknown_column",
                    status_code=400,
                )
            df = df.sort_values(
                sort_by,
                ascending=(sort_dir != "desc"),
                kind="mergesort",
                na_position="last",
            )

        total = int(len(df))
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        window = df.iloc[(page - 1) * page_size : page * page_size]

        return to_jsonable(
            {
                "columns": [str(c) for c in df.columns],
                "rows": dataframe_records(window),
                "total_rows": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "source": loaded.source,
                "sort_by": sort_by,
                "sort_dir": "desc" if sort_dir == "desc" else "asc",
                "search": search,
            }
        )

    def columns_metadata(
        self, dataset: models.Dataset, use_cleaned: bool = True
    ) -> dict[str, Any]:
        loaded = load_dataset(
            dataset,
            prefer="auto" if use_cleaned else "original",
            max_rows=settings.PROFILE_SAMPLE_ROWS,
        )
        return {
            "columns": profiling_service.columns_overview(loaded.df),
            "source": loaded.source,
            "sampled": loaded.sampled,
        }

    def column_profile(
        self, dataset: models.Dataset, column: str, use_cleaned: bool = True
    ) -> dict[str, Any]:
        loaded = load_dataset(
            dataset,
            prefer="auto" if use_cleaned else "original",
            max_rows=settings.PROFILE_SAMPLE_ROWS,
        )
        if column not in loaded.df.columns:
            raise NotFoundError(
                f"Column '{column}' is not in this dataset.",
                error_code="unknown_column",
            )
        profile = profiling_service.column_profile(loaded.df, column)
        profile["data_source"] = loaded.source
        profile["sampled"] = loaded.sampled
        return profile

    def export_csv(
        self, dataset: models.Dataset, use_cleaned: bool = True
    ) -> tuple[bytes, str]:
        """Export the active (cleaned or original) data as CSV bytes."""
        loaded = load_dataset(dataset, prefer="auto" if use_cleaned else "original")
        buffer = io.StringIO()
        loaded.df.to_csv(buffer, index=False)
        stem = os.path.splitext(dataset.filename)[0]
        suffix = "cleaned" if loaded.source == "cleaned" else "original"
        return buffer.getvalue().encode("utf-8"), f"{stem}_{suffix}.csv"

    # -------------------------------------------------------------- access
    def get_or_404(self, dataset_id: int, owner_id: int) -> models.Dataset:
        dataset = self.repo.get_by_id_for_owner(dataset_id, owner_id)
        if not dataset:
            raise NotFoundError("Dataset not found", error_code="dataset_not_found")
        return dataset

    def delete(self, dataset_id: int, owner_id: int) -> None:
        dataset = self.get_or_404(dataset_id, owner_id)
        # Remove every artifact this dataset owns, not just the upload: cleaned
        # copies and persisted model binaries would otherwise leak disk space.
        paths = [dataset.stored_path, dataset.cleaned_path]
        for run in dataset.model_runs:
            if run.model_path:
                paths.append(run.model_path)
        for record in dataset.reports:
            if record.file_path:
                paths.append(record.file_path)
        for path in paths:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        self.repo.delete(dataset)

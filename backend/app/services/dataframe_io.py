"""
Single place where dataset files are read from and written to disk.

Before this module, six routers each did their own
`ext = "." + dataset.file_type` / `os.path.splitext(path)` dance and each
decided independently whether to use the original or the cleaned file. Two of
them disagreed - which is why cleaning appeared to have no effect on profiling.
Everything now goes through `load_dataset` / `resolve_path`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import pandas as pd

from .. import models
from ..core.config import settings
from ..core.exceptions import NotFoundError, ValidationAppError

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json"}


@dataclass(frozen=True)
class LoadedFrame:
    """A DataFrame plus the provenance the API needs to be honest about it."""

    df: pd.DataFrame
    source: str  # "original" | "cleaned"
    path: str
    total_rows: int  # rows in the file, before any sampling
    sampled: bool  # True when `df` is a sample of the file, not all of it

    @property
    def row_count(self) -> int:
        return int(len(self.df))


def read_dataframe(path: str, ext: str) -> pd.DataFrame:
    """Low-level reader. Kept at module scope (and re-exported from
    services.dataset_service and datasets.py) because existing callers import
    it from those places."""
    ext = ext.lower()
    if ext == ".csv":
        try:
            return pd.read_csv(path)
        except pd.errors.ParserError:
            # Ragged real-world CSVs that the fast C parser rejects outright.
            return pd.read_csv(path, engine="python", on_bad_lines="skip")
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path)
    if ext == ".json":
        try:
            return pd.read_json(path)
        except ValueError:
            # A JSON file can legitimately be newline-delimited records.
            return pd.read_json(path, lines=True)
    raise ValueError(f"Unsupported file type: {ext}")


def write_dataframe(df: pd.DataFrame, path: str) -> None:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        df.to_csv(path, index=False)
    elif ext in (".xlsx", ".xls"):
        df.to_excel(path, index=False)
    elif ext == ".json":
        df.to_json(path, orient="records", date_format="iso")
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def resolve_path(dataset: models.Dataset, prefer: str = "auto") -> tuple[str, str]:
    """Returns (path, source) where source is "original" or "cleaned".

    prefer="auto"     -> cleaned file when one exists on disk, else original
    prefer="original" -> always the original upload
    prefer="cleaned"  -> the cleaned file, erroring if there isn't one
    """
    has_cleaned = bool(dataset.cleaned_path) and os.path.exists(dataset.cleaned_path)

    if prefer == "cleaned":
        if not has_cleaned:
            raise NotFoundError(
                "This dataset has no cleaned version yet. Run cleaning first.",
                error_code="cleaned_data_missing",
            )
        return dataset.cleaned_path, "cleaned"

    if prefer == "auto" and has_cleaned:
        return dataset.cleaned_path, "cleaned"

    if not dataset.stored_path or not os.path.exists(dataset.stored_path):
        raise NotFoundError(
            "The stored file for this dataset is missing on the server. "
            "Re-upload the dataset to continue.",
            error_code="stored_file_missing",
        )
    return dataset.stored_path, "original"


def load_dataset(
    dataset: models.Dataset,
    prefer: str = "auto",
    max_rows: int | None = None,
) -> LoadedFrame:
    """Read a dataset off disk, optionally down-sampling for expensive work.

    When `max_rows` is set and the file has more rows than that, a deterministic
    random sample is returned with `sampled=True`. Callers surface that flag so
    the UI can label the numbers as sample-based rather than exact.
    """
    path, source = resolve_path(dataset, prefer=prefer)
    ext = os.path.splitext(path)[1].lower()

    try:
        df = read_dataframe(path, ext)
    except Exception as exc:  # noqa: BLE001 - every parser failure maps to one API error
        raise ValidationAppError(
            "Could not read this dataset file. It may be corrupt or in an "
            "unexpected format.",
            error_code="unreadable_file",
            status_code=400,
        ) from exc

    if df is None or df.empty:
        raise ValidationAppError(
            "This dataset contains no rows.", error_code="empty_dataset", status_code=400
        )

    # Duplicate column labels break almost every downstream pandas operation,
    # because df[col] then returns a DataFrame instead of a Series.
    df = deduplicate_columns(df)

    total_rows = int(len(df))
    sampled = False
    if max_rows is not None and total_rows > max_rows:
        df = df.sample(n=max_rows, random_state=42).reset_index(drop=True)
        sampled = True

    return LoadedFrame(df=df, source=source, path=path, total_rows=total_rows, sampled=sampled)


def deduplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename duplicate column labels to `name`, `name.1`, `name.2`, ..."""
    cols = [str(c) for c in df.columns]
    if len(set(cols)) == len(cols):
        df.columns = cols
        return df

    seen: dict[str, int] = {}
    renamed: list[str] = []
    for col in cols:
        if col in seen:
            seen[col] += 1
            renamed.append(f"{col}.{seen[col]}")
        else:
            seen[col] = 0
            renamed.append(col)
    df = df.copy()
    df.columns = renamed
    return df


def cleaned_path_for(dataset: models.Dataset) -> str:
    """Deterministic on-disk location for a dataset's cleaned copy."""
    base = os.path.basename(dataset.stored_path)
    return os.path.join(settings.UPLOAD_DIR, f"cleaned_{base}")

"""
PDF report generation.

The original implementation called the `/train` and `/explain` route functions
directly, so downloading a report retrained every candidate model and wrote a
new ModelRun version each time. It also ran a full cleaning pass just to
describe it, and never recorded anything in the ReportRecord table.

This version reads what already exists: the persisted latest ModelRun, the
current data-quality profile, and the saved explanation. Nothing is trained as a
side effect of generating a document. Sections whose data is unavailable are
replaced with an honest note rather than omitted silently.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session

from .. import models
from ..core.config import settings
from ..core.exceptions import AppException
from ..core.logging_config import get_logger
from .analytics_service import analytics_service
from .dataframe_io import load_dataset
from .explainability_service import ExplainabilityService
from .ml_service import MLService
from .profiling_service import profiling_service

logger = get_logger("insightflow.report")

BRAND = colors.HexColor("#4f46e5")
INK = colors.HexColor("#1e293b")
MUTED = colors.HexColor("#64748b")
RULE = colors.HexColor("#e2e8f0")
BAND = colors.HexColor("#f8fafc")


class ReportService:
    def __init__(self, db: Session):
        self.db = db
        self.ml = MLService(db)
        self.explainer = ExplainabilityService(db)

    def generate_pdf(self, dataset: models.Dataset, user_id: int) -> tuple[bytes, str]:
        """Build the report from persisted state. Returns (pdf_bytes, filename)."""
        sections = self._gather(dataset, user_id)
        pdf = self._render(dataset, sections)
        filename = f"InsightFlow_Report_{dataset.id}_v{sections['generated_stamp']}.pdf"
        self._record(dataset, user_id)
        return pdf, filename

    # ------------------------------------------------------------- gather
    def _gather(self, dataset: models.Dataset, user_id: int) -> dict[str, Any]:
        """Collect every section, tolerating missing pieces individually."""
        out: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc),
            "generated_stamp": datetime.now(timezone.utc).strftime("%Y%m%d%H%M"),
            "quality": None,
            "dashboard": None,
            "model": None,
            "explanation": None,
            "notes": [],
        }

        try:
            loaded = load_dataset(dataset, max_rows=settings.PROFILE_SAMPLE_ROWS)
            out["data_source"] = loaded.source
            out["sampled"] = loaded.sampled
            out["quality"] = profiling_service.full_profile(
                loaded.df,
                dataset.size_bytes or 0,
                source=loaded.source,
                sampled=loaded.sampled,
                total_rows=loaded.total_rows,
            )
            out["dashboard"] = analytics_service.auto_dashboard(loaded.df)
        except AppException as exc:
            out["notes"].append(f"Data quality and analytics unavailable: {exc.detail}")
        except Exception as exc:  # noqa: BLE001
            logger.error("Report profiling failed for dataset %s: %s", dataset.id, exc)
            out["notes"].append(
                "Data quality and analytics could not be computed for this dataset."
            )

        run = self.ml.latest_run(dataset.id, user_id)
        if run is None:
            out["notes"].append(
                "No model has been trained for this dataset, so the modelling and "
                "explainability sections are omitted. Train a model to include them."
            )
        else:
            out["model"] = {
                "name": run.best_model_name,
                "task_type": run.task_type,
                "target": run.target_column,
                "metrics": run.metrics or {},
                "version": run.version,
                "trained_at": run.created_at,
                "leaderboard": run.leaderboard or [],
                "features": run.features or [],
                "rows_used": run.rows_used,
                "data_source": run.data_source,
                "config": run.config or {},
            }
            try:
                out["explanation"] = self.explainer.explain(dataset, user_id)
            except AppException as exc:
                out["notes"].append(f"Explainability unavailable: {exc.detail}")

        return out

    # ------------------------------------------------------------- render
    def _render(self, dataset: models.Dataset, data: dict[str, Any]) -> bytes:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            topMargin=18 * mm,
            bottomMargin=18 * mm,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            title=f"InsightFlow Report - {dataset.filename}",
            author="InsightFlow AI",
        )
        styles = self._styles()
        story: list[Any] = []

        # --- cover -------------------------------------------------------
        story += [
            Paragraph("InsightFlow AI", styles["brand"]),
            Paragraph("Automated Data Analysis Report", styles["h1"]),
            Spacer(1, 6 * mm),
            self._kv_table(
                [
                    ("Dataset", dataset.filename),
                    ("File type", (dataset.file_type or "").upper()),
                    ("Rows", f"{dataset.rows:,}" if dataset.rows else "Unknown"),
                    ("Columns", str(dataset.columns or "Unknown")),
                    ("File size", self._human_bytes(dataset.size_bytes)),
                    ("Uploaded", self._fmt_date(dataset.uploaded_at)),
                    (
                        "Data analysed",
                        f"{data.get('data_source', 'original').title()} data",
                    ),
                    ("Report generated", self._fmt_date(data["generated_at"])),
                ]
            ),
            Spacer(1, 8 * mm),
        ]

        if data.get("sampled"):
            story += [
                Paragraph(
                    "Statistics in this report were computed on a random sample of this dataset "
                    "to keep processing responsive. Sampled figures are representative but not exact.",
                    styles["callout"],
                ),
                Spacer(1, 5 * mm),
            ]

        story += [
            Paragraph("Executive summary", styles["h2"]),
            *self._summary(dataset, data, styles),
        ]

        # --- data quality ------------------------------------------------
        quality = data.get("quality")
        if quality:
            story += [PageBreak(), Paragraph("Data quality", styles["h2"])]
            q = quality["quality"]
            story += [
                Paragraph(
                    f"Overall quality score <b>{q['overall_score']}/100</b> ({q['grade']}). "
                    "Each component below is a documented arithmetic formula, not a subjective rating.",
                    styles["body"],
                ),
                Spacer(1, 4 * mm),
                self._table(
                    ["Component", "Score", "How it is calculated"],
                    [
                        [
                            "Completeness",
                            f"{q['completeness_score']}",
                            q["score_definitions"]["completeness"],
                        ],
                        [
                            "Duplicate-freedom",
                            f"{q['duplicate_score']}",
                            q["score_definitions"]["duplicates"],
                        ],
                        [
                            "Type consistency",
                            f"{q['consistency_score']}",
                            q["score_definitions"]["consistency"],
                        ],
                        [
                            "Uniqueness",
                            f"{q['uniqueness_score']}",
                            q["score_definitions"]["uniqueness"],
                        ],
                        [
                            "Overall",
                            f"{q['overall_score']}",
                            q["score_definitions"]["overall"],
                        ],
                    ],
                    widths=[38 * mm, 18 * mm, 106 * mm],
                    wrap_last=True,
                ),
            ]

            warnings = quality.get("warnings") or []
            if warnings:
                story += [
                    Spacer(1, 6 * mm),
                    Paragraph("Issues found", styles["h3"]),
                    self._table(
                        ["Severity", "Finding"],
                        [[w["severity"].title(), w["message"]] for w in warnings[:12]],
                        widths=[24 * mm, 138 * mm],
                        wrap_last=True,
                    ),
                ]

            recommendations = quality.get("recommendations") or []
            if recommendations:
                story += [
                    Spacer(1, 6 * mm),
                    Paragraph("Recommended actions", styles["h3"]),
                    self._table(
                        ["Action", "Why it matters"],
                        [[r["action"], r["why"]] for r in recommendations[:8]],
                        widths=[56 * mm, 106 * mm],
                        wrap_last=True,
                    ),
                ]

            dictionary = quality.get("data_dictionary") or []
            if dictionary:
                story += [
                    PageBreak(),
                    Paragraph("Data dictionary", styles["h2"]),
                    self._table(
                        ["Column", "Type", "Non-null", "Missing %", "Distinct"],
                        [
                            [
                                d["column"],
                                d["semantic_type"],
                                f"{d['non_null_count']:,}",
                                f"{d['missing_pct']}%",
                                f"{d['unique_count']:,}",
                            ]
                            for d in dictionary[:45]
                        ],
                        widths=[54 * mm, 28 * mm, 26 * mm, 26 * mm, 28 * mm],
                    ),
                ]
                if len(dictionary) > 45:
                    story.append(
                        Paragraph(
                            f"Showing 45 of {len(dictionary)} columns.", styles["muted"]
                        )
                    )

        # --- analytics ---------------------------------------------------
        dashboard = data.get("dashboard")
        if dashboard and dashboard.get("kpis"):
            story += [PageBreak(), Paragraph("Key metrics", styles["h2"])]
            story.append(
                self._table(
                    ["Metric", "Value"],
                    [
                        [k["label"], self._fmt_number(k["value"])]
                        for k in dashboard["kpis"]
                    ],
                    widths=[100 * mm, 62 * mm],
                )
            )
            for insight in dashboard.get("insights") or []:
                story += [Spacer(1, 3 * mm), Paragraph(insight, styles["body"])]

            if dashboard.get("category_breakdown"):
                story += [
                    Spacer(1, 6 * mm),
                    Paragraph(
                        f"Top values by {dashboard.get('category_column')}",
                        styles["h3"],
                    ),
                    self._table(
                        ["Category", "Count"],
                        [
                            [c["category"], f"{c['count']:,}"]
                            for c in dashboard["category_breakdown"][:10]
                        ],
                        widths=[110 * mm, 52 * mm],
                    ),
                ]

        # --- modelling ---------------------------------------------------
        model = data.get("model")
        if model:
            story += [PageBreak(), Paragraph("Model results", styles["h2"])]
            story += [
                Paragraph(
                    f"The best-performing model was <b>{model['name']}</b>, a "
                    f"{model['task_type']} model predicting <b>{model['target']}</b>. "
                    f"This is version {model['version']}, trained "
                    f"{self._fmt_date(model['trained_at'])} on {model['rows_used'] or 0:,} rows "
                    f"of {model.get('data_source') or 'original'} data.",
                    styles["body"],
                ),
                Spacer(1, 4 * mm),
                self._table(
                    ["Metric", "Value"],
                    [
                        [self._metric_label(k), self._fmt_number(v)]
                        for k, v in (model["metrics"] or {}).items()
                    ],
                    widths=[100 * mm, 62 * mm],
                ),
            ]

            leaderboard = model.get("leaderboard") or []
            if leaderboard:
                story += [
                    Spacer(1, 6 * mm),
                    Paragraph("Model comparison", styles["h3"]),
                    self._table(
                        ["Model", "Score", "Cross-validated", "Tuned"],
                        [
                            [
                                entry.get("model", "?"),
                                self._fmt_number(entry.get("score")),
                                self._fmt_number(entry.get("cv_score")),
                                "Yes" if entry.get("tuned") else "No",
                            ]
                            for entry in leaderboard[:14]
                        ],
                        widths=[70 * mm, 30 * mm, 36 * mm, 26 * mm],
                    ),
                    Spacer(1, 3 * mm),
                    Paragraph(
                        "Score is weighted F1 for classification and R&#178; for regression. "
                        "The cross-validated column is the mean across folds and is the more "
                        "reliable indicator of how the model will generalise.",
                        styles["muted"],
                    ),
                ]

        # --- explainability ----------------------------------------------
        explanation = data.get("explanation")
        if explanation:
            story += [PageBreak(), Paragraph("Explainability", styles["h2"])]
            story += [
                Paragraph(
                    f"Method used: <b>{explanation['method_label']}</b>"
                    + (
                        f". SHAP was not available for this model type: {explanation['fallback_reason']}."
                        if explanation.get("fallback_used")
                        and explanation.get("fallback_reason")
                        else "."
                    ),
                    styles["body"],
                ),
                Spacer(1, 3 * mm),
                Paragraph(explanation["interpretation"], styles["body"]),
                Spacer(1, 4 * mm),
                self._table(
                    ["Feature", "Relative importance"],
                    [
                        [f["feature"], f"{f['importance_pct']}%"]
                        for f in explanation["feature_importance"][:15]
                    ],
                    widths=[110 * mm, 52 * mm],
                ),
            ]

        # --- limitations -------------------------------------------------
        story += [
            PageBreak(),
            Paragraph("Limitations and caveats", styles["h2"]),
            *[
                Paragraph(f"&bull; {note}", styles["body"])
                for note in self._caveats(data)
            ],
        ]

        doc.build(story, onLaterPages=self._footer, onFirstPage=self._footer)
        buffer.seek(0)
        return buffer.getvalue()

    # -------------------------------------------------------------- pieces
    def _summary(self, dataset, data, styles) -> list[Any]:
        quality = data.get("quality")
        model = data.get("model")
        explanation = data.get("explanation")

        if not quality:
            return [
                Paragraph(
                    "This dataset could not be analysed. " + " ".join(data["notes"]),
                    styles["body"],
                )
            ]

        summary = quality["summary"]
        parts = [
            f"<b>{dataset.filename}</b> contains {summary['rows']:,} rows across "
            f"{summary['columns']} columns, with {summary['missing_values_pct']}% of cells empty "
            f"and {summary['duplicates_pct']}% duplicate rows. Its overall data-quality score is "
            f"{quality['quality']['overall_score']}/100 ({quality['quality']['grade']})."
        ]
        if model:
            metric_name, metric_value = self._headline_metric(model)
            parts.append(
                f"A {model['task_type']} model was trained to predict <b>{model['target']}</b>; "
                f"the best performer was <b>{model['name']}</b> with {metric_name} of {metric_value}."
            )
            if explanation and explanation.get("feature_importance"):
                top = explanation["feature_importance"][0]
                parts.append(
                    f"The strongest measured driver was <b>{top['feature']}</b> "
                    f"({top['importance_pct']}% of total importance), according to "
                    f"{explanation['method_label'].lower()}. This is an association, not a "
                    "demonstrated cause."
                )
        else:
            parts.append(
                "No model has been trained for this dataset yet, so this report covers data "
                "quality and descriptive analytics only."
            )

        out = [Paragraph(p, styles["body"]) for p in parts]
        recommendations = quality.get("recommendations") or []
        if recommendations:
            out += [
                Spacer(1, 3 * mm),
                Paragraph(
                    "<b>Suggested next steps:</b> "
                    + "; ".join(r["action"] for r in recommendations[:3])
                    + ".",
                    styles["body"],
                ),
            ]
        return out

    @staticmethod
    def _headline_metric(model: dict[str, Any]) -> tuple[str, str]:
        metrics = model.get("metrics") or {}
        if model.get("task_type") == "classification":
            for key, label in (
                ("f1", "a weighted F1 score"),
                ("accuracy", "an accuracy"),
            ):
                if metrics.get(key) is not None:
                    return label, f"{metrics[key]:.3f}"
        else:
            if metrics.get("r2") is not None:
                return "an R²", f"{metrics['r2']:.3f}"
            if metrics.get("mae") is not None:
                return "a mean absolute error", f"{metrics['mae']:.3f}"
        return "a score", "not recorded"

    @staticmethod
    def _metric_label(key: str) -> str:
        return {
            "r2": "R² (variance explained)",
            "mae": "Mean absolute error",
            "rmse": "Root mean squared error",
            "mape": "Mean absolute percentage error (%)",
            "f1": "F1 score (weighted)",
            "accuracy": "Accuracy",
            "precision": "Precision (weighted)",
            "recall": "Recall (weighted)",
            "roc_auc": "ROC-AUC",
        }.get(key, key.replace("_", " ").title())

    @staticmethod
    def _caveats(data: dict[str, Any]) -> list[str]:
        out = list(data.get("notes") or [])
        out.append(
            "All findings are statistical associations computed from the supplied data. "
            "None of them establish causation."
        )
        if data.get("sampled"):
            out.append(
                "Figures were computed on a random sample, so exact totals may differ."
            )
        if data.get("model"):
            out.append(
                "Model metrics are measured on a held-out test split of this dataset. "
                "Performance on genuinely new data is typically lower."
            )
        if data.get("explanation"):
            out.extend(data["explanation"].get("caveats") or [])
        out.append(
            "This report is generated automatically and is intended to support analysis, "
            "not to replace review by someone familiar with how the data was collected."
        )
        return out

    def _record(self, dataset: models.Dataset, user_id: int) -> None:
        """Log the generated report. The PDF streams to the client rather than
        being stored server-side, so file_path stays null."""
        try:
            self.db.add(
                models.ReportRecord(
                    dataset_id=dataset.id, user_id=user_id, format="pdf", file_path=None
                )
            )
            self.db.commit()
        except Exception as exc:  # noqa: BLE001 - never fail a download over history
            logger.warning(
                "Could not record report history for dataset %s: %s", dataset.id, exc
            )
            self.db.rollback()

    def report_history(
        self, dataset_id: int, user_id: int
    ) -> list[models.ReportRecord]:
        return (
            self.db.query(models.ReportRecord)
            .filter(
                models.ReportRecord.dataset_id == dataset_id,
                models.ReportRecord.user_id == user_id,
            )
            .order_by(models.ReportRecord.created_at.desc())
            .all()
        )

    # ------------------------------------------------------------ styling
    @staticmethod
    def _styles():
        base = getSampleStyleSheet()
        return {
            "brand": ParagraphStyle(
                "brand",
                parent=base["Normal"],
                fontName="Helvetica-Bold",
                fontSize=10,
                textColor=BRAND,
                spaceAfter=2,
                alignment=TA_LEFT,
            ),
            "h1": ParagraphStyle(
                "h1",
                parent=base["Title"],
                fontName="Helvetica-Bold",
                fontSize=22,
                textColor=INK,
                spaceAfter=4,
                alignment=TA_LEFT,
                leading=26,
            ),
            "h2": ParagraphStyle(
                "h2",
                parent=base["Heading1"],
                fontName="Helvetica-Bold",
                fontSize=14,
                textColor=INK,
                spaceBefore=2,
                spaceAfter=6,
            ),
            "h3": ParagraphStyle(
                "h3",
                parent=base["Heading2"],
                fontName="Helvetica-Bold",
                fontSize=11,
                textColor=INK,
                spaceBefore=2,
                spaceAfter=4,
            ),
            "body": ParagraphStyle(
                "body",
                parent=base["Normal"],
                fontSize=9.5,
                leading=14,
                textColor=INK,
                spaceAfter=4,
            ),
            "muted": ParagraphStyle(
                "muted",
                parent=base["Normal"],
                fontSize=8,
                leading=11,
                textColor=MUTED,
            ),
            "cell": ParagraphStyle(
                "cell",
                parent=base["Normal"],
                fontSize=8.5,
                leading=11,
                textColor=INK,
            ),
            "callout": ParagraphStyle(
                "callout",
                parent=base["Normal"],
                fontSize=8.5,
                leading=12,
                textColor=MUTED,
                borderPadding=6,
                backColor=BAND,
            ),
        }

    def _kv_table(self, rows: list[tuple[str, str]]) -> Table:
        table = Table([[k, v] for k, v in rows], colWidths=[46 * mm, 116 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
                    ("TEXTCOLOR", (1, 0), (1, -1), INK),
                    ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        return table

    def _table(
        self,
        header: list[str],
        rows: list[list[str]],
        widths: list[float] | None = None,
        wrap_last: bool = False,
    ) -> Table:
        """A table with a header that repeats across page breaks.

        `wrap_last` wraps the final column in a Paragraph so long explanatory
        text flows instead of overflowing the cell.
        """
        styles = self._styles()
        body = []
        for row in rows:
            cells = list(row)
            if wrap_last and cells:
                cells[-1] = Paragraph(str(cells[-1]), styles["cell"])
            body.append(cells)

        table = Table([header] + body, colWidths=widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), INK),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("GRID", (0, 0), (-1, -1), 0.3, RULE),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        return table

    @staticmethod
    def _footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm, "Generated by InsightFlow AI")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.setStrokeColor(RULE)
        canvas.line(18 * mm, 14 * mm, A4[0] - 18 * mm, 14 * mm)
        canvas.restoreState()

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _fmt_date(value) -> str:
        if not value:
            return "Unknown"
        if isinstance(value, str):
            return value
        return value.strftime("%d %b %Y, %H:%M UTC")

    @staticmethod
    def _fmt_number(value) -> str:
        if value is None:
            return "n/a"
        if isinstance(value, (int,)) and not isinstance(value, bool):
            return f"{value:,}"
        if isinstance(value, float):
            return (
                f"{value:,.4f}".rstrip("0").rstrip(".")
                if abs(value) < 1000
                else f"{value:,.2f}"
            )
        return str(value)

    @staticmethod
    def _human_bytes(size: int | None) -> str:
        if not size:
            return "Unknown"
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GB"

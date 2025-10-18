"""Report writers for calibration results."""
from __future__ import annotations

from pathlib import Path
import pandas as pd

from .metrics import MetricSummary
from .pipeline import CalibrationResult


def export_results(
    result: CalibrationResult,
    output_dir: Path,
    *,
    figure_path: Path | None = None,
    input_path: Path | None = None,
    temp_mode: str | None = None,
) -> None:
    """Persist residuals, metrics and markdown report to *output_dir*."""

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_metrics_csv(result, output_dir)
    _write_residuals_csv(result, output_dir)
    _write_report_md(
        result,
        output_dir,
        figure_path=figure_path,
        input_path=input_path,
        temp_mode=temp_mode,
    )


def _write_metrics_csv(result: CalibrationResult, output_dir: Path) -> None:
    rows: list[dict[str, object]] = []
    metrics: MetricSummary = result.metrics
    for fit_name, values in metrics.linearity.items():
        rows.append(
            {
                "metric": "linearity",
                "mode": fit_name,
                "absolute": values.absolute,
                "percent_fs": values.percent_fs,
            }
        )
    rows.extend(
        [
            {
                "metric": "hysteresis",
                "mode": "aggregate",
                "absolute": metrics.hysteresis.absolute,
                "percent_fs": metrics.hysteresis.percent_fs,
            },
            {
                "metric": "repeatability",
                "mode": "aggregate",
                "absolute": metrics.repeatability.absolute,
                "percent_fs": metrics.repeatability.percent_fs,
            },
            {
                "metric": "total_error",
                "mode": "aggregate",
                "absolute": metrics.total_error.absolute,
                "percent_fs": metrics.total_error.percent_fs,
            },
        ]
    )
    df = pd.DataFrame(rows)
    df.to_csv(output_dir / "metrics.csv", index=False)


def _write_residuals_csv(result: CalibrationResult, output_dir: Path) -> None:
    result.residuals.to_csv(output_dir / "residuals.csv", index=False)


def _write_report_md(
    result: CalibrationResult,
    output_dir: Path,
    *,
    figure_path: Path | None,
    input_path: Path | None,
    temp_mode: str | None,
) -> None:
    metrics = result.metrics
    lines: list[str] = []
    lines.append("# BSL/FS Calibration Report")
    if input_path is not None:
        lines.append(f"*Input file:* `{input_path}`  ")
    lines.append(f"*Samples:* {len(result.data.pressure)}  ")
    lines.append(f"*Full scale (output):* {metrics.fs_output:.6g}  ")
    lines.append(f"*Full scale (pressure):* {metrics.fs_pressure:.6g}  ")
    if temp_mode:
        lines.append(f"*Temperature compensation:* {temp_mode}  ")
    lines.append("")

    lines.append("## Linearity")
    lines.append("| Fit | Max error | %FS |")
    lines.append("| --- | ---: | ---: |")
    for fit_name, values in metrics.linearity.items():
        lines.append(f"| {fit_name} | {values.absolute:.6g} | {values.percent_fs:.4f} |")
    lines.append("")

    lines.append("## Hysteresis & Repeatability")
    lines.append("| Metric | Absolute | %FS |")
    lines.append("| --- | ---: | ---: |")
    lines.append(
        f"| Hysteresis | {metrics.hysteresis.absolute:.6g} | {metrics.hysteresis.percent_fs:.4f} |"
    )
    lines.append(
        f"| Repeatability | {metrics.repeatability.absolute:.6g} | {metrics.repeatability.percent_fs:.4f} |"
    )
    lines.append(
        f"| Total error | {metrics.total_error.absolute:.6g} | {metrics.total_error.percent_fs:.4f} |"
    )
    lines.append("")

    if figure_path is not None:
        rel = figure_path.name
        lines.append(f"![Calibration plots]({rel})")
        lines.append("")

    lines.append("### Notes")
    lines.append(
        "- Linearity is computed against endpoint, BSL (minimax) and OLS references."
    )
    lines.append(
        "- %FS is referenced to the measured output full-scale span (max - min)."
    )
    if temp_mode:
        lines.append("- Temperature-compensated fits include a linear `temp` term.")

    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")

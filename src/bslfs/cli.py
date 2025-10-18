"""Command line interface for the bslfs package."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .demo import run_demo
from .pipeline import run_calibration
from .plotting import generate_plots
from .reporting import export_results

app = typer.Typer(context_settings={"help_option_names": ["-h", "--help"]})


@app.command()
def calc(
    input_path: Path = typer.Option(..., "--in", help="Input CSV with calibration data."),
    mode: str = typer.Option("bsl", "--mode", help="Calibration mode (only 'bsl' supported)."),
    report_dir: Path = typer.Option(..., "--report", help="Output directory for reports."),
    temp_comp: Optional[str] = typer.Option(
        None,
        "--temp-comp",
        case_sensitive=False,
        help="Enable temperature compensation (use 'linear').",
    ),
) -> None:
    """Compute calibration metrics and artefacts."""

    if mode.lower() != "bsl":
        raise typer.BadParameter("Only --mode bsl is supported at present", param_hint="--mode")

    include_temp = temp_comp is not None and temp_comp.lower() == "linear"

    result = run_calibration(str(input_path), include_temperature=include_temp)

    figure_path = None
    try:
        figure_path = generate_plots(result, report_dir)
    except RuntimeError as exc:
        typer.echo(f"[warning] plotting skipped: {exc}")

    export_results(
        result,
        report_dir,
        figure_path=figure_path,
        input_path=input_path,
        temp_mode="linear" if include_temp else None,
    )

    typer.echo(f"Report written to {report_dir}")


@app.command()
def demo(
    out_dir: Path = typer.Option(Path("demo_output"), "--out", help="Target directory for demo report."),
) -> None:
    """Generate synthetic data and reports."""

    run_demo(out_dir)
    typer.echo(f"Demo dataset and report written to {out_dir}")


def run() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    run()

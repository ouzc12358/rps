"""Plotting helpers for calibration outputs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .pipeline import CalibrationResult


def generate_plots(result: CalibrationResult, output_dir: Path) -> Path:
    plt = _require_matplotlib()
    output_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    _plot_scatter_with_models(result, axes[0])
    _plot_errors(result, axes[1])
    _plot_hysteresis(result, axes[2])

    fig.tight_layout()
    out_path = output_dir / "plots.png"
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


def _plot_scatter_with_models(result: CalibrationResult, ax) -> None:
    df = result.data.dataframe
    for direction, group in df.groupby("direction"):
        ax.scatter(
            group["pressure_ref"],
            group["output"],
            label=f"{direction} samples",
            alpha=0.7,
        )

    pressure_range = np.linspace(df["pressure_ref"].min(), df["pressure_ref"].max(), 250)
    temp_mean = float(df["temp"].mean()) if "temp" in df else 0.0

    for fit in result.fits:
        intercept = fit.coefficients.get("intercept", 0.0)
        slope = fit.coefficients.get("pressure_ref", 0.0)
        temp_coef = fit.coefficients.get("temp", 0.0)
        label = {
            "endpoint": "Endpoint",
            "ols": "OLS",
            "ols_temp": "OLS + temp",
            "bsl": "BSL",
            "bsl_temp": "BSL + temp",
        }.get(fit.name, fit.name)
        style = {
            "endpoint": ("green", "--"),
            "ols": ("red", ":"),
            "ols_temp": ("darkred", ":"),
            "bsl": ("black", "-"),
            "bsl_temp": ("navy", "-"),
        }.get(fit.name, ("gray", "-"))
        color, linestyle = style
        values = intercept + slope * pressure_range + temp_coef * temp_mean
        ax.plot(pressure_range, values, color=color, linestyle=linestyle, label=label)

    ax.set_title("Output vs. reference pressure")
    ax.set_xlabel("Pressure reference")
    ax.set_ylabel("Output")
    ax.legend(loc="best")


def _plot_errors(result: CalibrationResult, ax) -> None:
    df = result.residuals
    x = df["pressure_ref"].to_numpy(dtype=float)
    for fit in result.fits:
        residual_key = f"residual_{fit.name}"
        if residual_key not in df.columns:
            continue
        label = {
            "endpoint": "Endpoint",
            "ols": "OLS",
            "ols_temp": "OLS + temp",
            "bsl": "BSL",
            "bsl_temp": "BSL + temp",
        }.get(fit.name, fit.name)
        ax.plot(x, df[residual_key], marker="o", linestyle="-", label=label)

    ax.set_title("Error vs. pressure")
    ax.set_xlabel("Pressure reference")
    ax.set_ylabel("Output error")
    ax.axhline(0.0, color="black", linewidth=0.8, linestyle="--")
    ax.legend(loc="best")


def _plot_hysteresis(result: CalibrationResult, ax) -> None:
    df = result.data.dataframe
    for cycle, group in df.groupby("cycle_id"):
        group_sorted = group.sort_values("pressure_ref")
        ax.plot(
            group_sorted["pressure_ref"],
            group_sorted["output"],
            marker="o",
            label=f"cycle {cycle}",
            alpha=0.7,
        )
    ax.set_title("Hysteresis loops")
    ax.set_xlabel("Pressure reference")
    ax.set_ylabel("Output")
    if df["cycle_id"].nunique() <= 6:
        ax.legend(loc="best")



def _require_matplotlib() -> Any:
    from pathlib import Path as _Path

    home_cache = _Path.home() / ".cache" / "fontconfig"
    try:
        home_cache.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError("matplotlib cannot write font cache in this environment") from exc

    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("matplotlib is required for plotting; install bslfs[plot]") from exc
    except Exception as exc:  # pragma: no cover - environment issues
        raise RuntimeError(f"matplotlib initialisation failed: {exc}") from exc
    return plt

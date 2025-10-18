"""High level orchestration for BSL/FS processing."""
from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

from .data import CalibrationData, load_calibration_csv
from .metrics import MetricSummary, compute_metrics
from .models import FitResult, fit_bsl, fit_endpoint, fit_ols


@dataclass(frozen=True)
class CalibrationResult:
    data: CalibrationData
    fits: list[FitResult]
    metrics: MetricSummary
    residuals: pd.DataFrame


def run_calibration(
    path: str,
    *,
    include_temperature: bool = False,
) -> CalibrationResult:
    """Load data and evaluate calibration metrics."""

    data = load_calibration_csv(path)
    if include_temperature and data.temperature is None:
        raise ValueError("--temp-comp requires a 'temp' column in the input data")

    fits: list[FitResult] = []
    fits.append(fit_endpoint(data.pressure, data.output))
    fits.append(
        fit_ols(
            data.pressure,
            data.output,
            temperature=data.temperature,
            include_temperature=False,
        )
    )
    fits.append(
        fit_bsl(
            data.pressure,
            data.output,
            temperature=data.temperature,
            include_temperature=False,
        )
    )

    if include_temperature:
        fits.append(
            fit_ols(
                data.pressure,
                data.output,
                temperature=data.temperature,
                include_temperature=True,
            )
        )
        fits.append(
            fit_bsl(
                data.pressure,
                data.output,
                temperature=data.temperature,
                include_temperature=True,
            )
        )

    metrics = compute_metrics(data, fits)
    residuals = _build_residual_table(data, fits)

    return CalibrationResult(data=data, fits=fits, metrics=metrics, residuals=residuals)


def _build_residual_table(data: CalibrationData, fits: list[FitResult]) -> pd.DataFrame:
    df = data.dataframe.copy()
    for fit in fits:
        key_pred = f"pred_{fit.name}"
        key_res = f"residual_{fit.name}"
        df[key_pred] = fit.predictions
        df[key_res] = fit.residuals
    ordered_cols = [
        "pressure_ref",
        "output",
        "cycle_id",
        "direction",
    ]
    if data.temperature is not None:
        ordered_cols.append("temp")
    extra_cols = [col for col in df.columns if col not in ordered_cols]
    return df[ordered_cols + sorted(extra_cols)]

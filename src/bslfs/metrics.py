"""Metric calculations for calibration datasets."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import numpy as np

from .data import CalibrationData
from .models import FitResult


@dataclass(frozen=True)
class MetricValue:
    absolute: float
    percent_fs: float


@dataclass(frozen=True)
class MetricSummary:
    fs_output: float
    fs_pressure: float
    linearity: Dict[str, MetricValue]
    hysteresis: MetricValue
    repeatability: MetricValue
    total_error: MetricValue


def compute_metrics(data: CalibrationData, fits: list[FitResult]) -> MetricSummary:
    fs_output = data.fs_output
    linearity = {
        fit.name: MetricValue(absolute=fit.max_abs_error, percent_fs=_to_percent(fit.max_abs_error, fs_output))
        for fit in fits
    }

    hysteresis_abs = _hysteresis_abs(data)
    repeatability_abs = _repeatability_abs(data)

    hysteresis = MetricValue(hysteresis_abs, _to_percent(hysteresis_abs, fs_output))
    repeatability = MetricValue(repeatability_abs, _to_percent(repeatability_abs, fs_output))

    bsl = next((fit for fit in fits if fit.name.startswith("bsl")), fits[0] if fits else None)
    linear_component = bsl.max_abs_error if bsl is not None else 0.0
    total_abs = float(np.sqrt(linear_component**2 + hysteresis_abs**2 + repeatability_abs**2))
    total_error = MetricValue(total_abs, _to_percent(total_abs, fs_output))

    return MetricSummary(
        fs_output=fs_output,
        fs_pressure=data.fs_pressure,
        linearity=linearity,
        hysteresis=hysteresis,
        repeatability=repeatability,
        total_error=total_error,
    )


def _to_percent(value: float, fs: float) -> float:
    if fs <= 0:
        return float("nan")
    return float(value / fs * 100.0)


def _hysteresis_abs(data: CalibrationData) -> float:
    df = data.dataframe.copy()
    df["pressure_key"] = df["pressure_ref"].round(6)

    ups = (
        df[df["direction"] == "up"].groupby("pressure_key")["output"].mean()
    )
    downs = (
        df[df["direction"] == "down"].groupby("pressure_key")["output"].mean()
    )
    if ups.empty or downs.empty:
        return 0.0

    joined = ups.to_frame("up").join(downs.to_frame("down"), how="inner")
    if joined.empty:
        return 0.0

    diff = (joined["up"] - joined["down"]).abs()
    return float(diff.max())


def _repeatability_abs(data: CalibrationData) -> float:
    df = data.dataframe.copy()
    df["pressure_key"] = df["pressure_ref"].round(6)

    worst = 0.0
    for (_, _), group in df.groupby(["pressure_key", "direction"]):
        values = group["output"].to_numpy(dtype=float)
        if values.size < 2:
            continue
        mean = values.mean()
        within = np.max(np.abs(values - mean))
        if within > worst:
            worst = float(within)
    return worst

"""Data loading utilities for BSL/FS calibration."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = {"pressure_ref", "output", "cycle_id"}
OPTIONAL_COLUMNS = {"temp"}


@dataclass(frozen=True)
class CalibrationData:
    """Container for processed calibration measurements."""

    dataframe: pd.DataFrame
    pressure: np.ndarray
    output: np.ndarray
    cycle_id: np.ndarray
    direction: np.ndarray
    temperature: Optional[np.ndarray]
    fs_output: float
    fs_pressure: float


def load_calibration_csv(path: str | Path) -> CalibrationData:
    """Load calibration data from *path* and infer cycle direction.

    Parameters
    ----------
    path:
        Path to a CSV file containing `pressure_ref`, `output`, optional `temp`,
        and a `cycle_id` column identifying loading cycles.

    Returns
    -------
    CalibrationData
        Normalised data with inferred up/down direction and cached FS values.
    """

    path = Path(path)
    if not path.exists():  # pragma: no cover - defensive
        raise FileNotFoundError(path)

    df = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df = df.copy()
    df["cycle_id"] = df["cycle_id"].astype(str)

    directions = _infer_directions(df)
    df["direction"] = directions
    df = df.sort_values(["cycle_id", "pressure_ref", "output"], kind="mergesort")
    df.reset_index(drop=True, inplace=True)

    pressure = df["pressure_ref"].to_numpy(dtype=float)
    output = df["output"].to_numpy(dtype=float)
    cycle_id = df["cycle_id"].to_numpy(dtype=str)
    temp = df["temp"].to_numpy(dtype=float) if "temp" in df.columns else None
    direction = df["direction"].to_numpy(dtype=str)

    fs_output = float(output.max() - output.min())
    fs_pressure = float(pressure.max() - pressure.min())
    if fs_pressure <= 0:
        raise ValueError("pressure_ref must span more than a single value")
    if fs_output <= 0:
        raise ValueError("output must span more than a single value")

    return CalibrationData(
        dataframe=df,
        pressure=pressure,
        output=output,
        cycle_id=cycle_id,
        direction=direction,
        temperature=temp,
        fs_output=fs_output,
        fs_pressure=fs_pressure,
    )


def _infer_directions(df: pd.DataFrame) -> np.ndarray:
    """Infer loading direction ('up' / 'down') for each record."""

    directions: list[str] = []
    for _, group in df.groupby("cycle_id", sort=False):
        pressures = group["pressure_ref"].to_numpy(dtype=float)
        if len(pressures) < 2:
            trend = "up"
        else:
            diff = pressures[-1] - pressures[0]
            if np.isclose(diff, 0.0):
                gradients = np.diff(pressures)
                idx = np.flatnonzero(~np.isclose(gradients, 0.0))
                diff = gradients[idx[0]] if idx.size else 0.0
            trend = "up" if diff >= 0 else "down"
        directions.extend([trend] * len(group))
    return np.array(directions, dtype=str)

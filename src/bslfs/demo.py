"""Demo dataset utilities."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .pipeline import run_calibration
from .reporting import export_results
from .plotting import generate_plots


def create_demo_dataset(cycles: int = 3, points: int = 9) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rows = []
    pressures = np.linspace(0.0, 100.0, points)
    slope_true = 0.08
    bias_true = 1.2
    temp_gradient = 0.01

    for cycle in range(cycles):
        zero_shift = rng.normal(scale=0.05)
        span_shift = rng.normal(scale=0.002)
        temp_base = 20.0 + cycle * 2.0

        # ascending branch
        outputs_up = bias_true + (slope_true + span_shift) * pressures + zero_shift
        outputs_up += rng.normal(scale=0.03, size=pressures.size)
        temps_up = temp_base + temp_gradient * pressures
        rows.extend(
            {
                "pressure_ref": float(p),
                "output": float(o),
                "cycle_id": f"cycle{cycle}_up",
                "temp": float(t),
            }
            for p, o, t in zip(pressures, outputs_up, temps_up)
        )

        # descending branch with hysteresis
        hysteresis = 0.05 * (pressures / pressures.max())
        outputs_down = bias_true + (slope_true - span_shift) * pressures - hysteresis + zero_shift
        outputs_down += rng.normal(scale=0.03, size=pressures.size)
        temps_down = temp_base + temp_gradient * pressures + 1.0
        rows.extend(
            {
                "pressure_ref": float(p),
                "output": float(o),
                "cycle_id": f"cycle{cycle}_down",
                "temp": float(t),
            }
            for p, o, t in zip(reversed(pressures), outputs_down[::-1], temps_down[::-1])
        )

    return pd.DataFrame(rows)


def run_demo(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "demo_data.csv"
    df = create_demo_dataset()
    df.to_csv(csv_path, index=False)

    result = run_calibration(str(csv_path), include_temperature=True)
    figure_path = None
    try:
        figure_path = generate_plots(result, out_dir)
    except RuntimeError as exc:
        figure_path = None
        # re-raise would stop demo; instead, emit text report only
        print(f"[warning] plotting skipped: {exc}")

    export_results(
        result,
        out_dir,
        figure_path=figure_path,
        input_path=csv_path,
        temp_mode="linear",
    )

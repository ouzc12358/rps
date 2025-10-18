from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from bslfs.pipeline import run_calibration


def _synthetic_dataframe() -> pd.DataFrame:
    rng = np.random.default_rng(1234)
    pressures = np.linspace(0.0, 100.0, 9)
    base_output = 1.5 + 0.09 * pressures
    base_temp = 20.0 + 0.05 * pressures

    rows = []
    for cycle in range(2):
        zero_shift = cycle * 0.01
        span_shift = (-1) ** cycle * 0.002
        # ascending branch
        outputs_up = base_output * (1 + span_shift) + zero_shift
        outputs_up += rng.normal(scale=0.005, size=pressures.size)
        temps_up = base_temp + cycle
        outputs_up += 0.02 * (temps_up - 20.0)
        rows.extend(
            {
                "pressure_ref": float(p),
                "output": float(o),
                "cycle_id": f"c{cycle}_up",
                "temp": float(t),
            }
            for p, o, t in zip(pressures, outputs_up, temps_up)
        )

        # descending branch introduces hysteresis
        hysteresis = 0.12 * (pressures / pressures.max())
        outputs_down = base_output * (1 - span_shift) - hysteresis + zero_shift
        outputs_down += rng.normal(scale=0.005, size=pressures.size)
        temps_down = base_temp + cycle + 0.8
        outputs_down += 0.02 * (temps_down - 20.0)
        rows.extend(
            {
                "pressure_ref": float(p),
                "output": float(o),
                "cycle_id": f"c{cycle}_down",
                "temp": float(t),
            }
            for p, o, t in zip(pressures[::-1], outputs_down[::-1], temps_down[::-1])
        )

    return pd.DataFrame(rows)


def test_pipeline_metrics_improve_with_temperature(tmp_path: Path) -> None:
    df = _synthetic_dataframe()
    csv_path = tmp_path / "calibration.csv"
    df.to_csv(csv_path, index=False)

    result_no_temp = run_calibration(str(csv_path), include_temperature=False)
    result_with_temp = run_calibration(str(csv_path), include_temperature=True)

    lin_bsl = result_no_temp.metrics.linearity["bsl"].absolute
    lin_bsl_temp = result_with_temp.metrics.linearity["bsl_temp"].absolute

    assert lin_bsl_temp <= lin_bsl + 1e-6
    assert result_no_temp.metrics.hysteresis.absolute > 0
    assert result_no_temp.metrics.repeatability.absolute >= 0
    assert {"pred_bsl", "residual_bsl"}.issubset(result_no_temp.residuals.columns)

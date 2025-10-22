from __future__ import annotations

from pathlib import Path

import numpy as np

from bslfs.terps.coeff import coeff_from_sensor_poly
from bslfs.terps.config import SensorPoly, TerpsConfig, load_config
from bslfs.terps.processing import SamplePipeline
from bslfs.terps.frames import Frame


def test_pressure_polynomial_uses_microvolts(tmp_path: Path) -> None:
    cfg = load_config(Path("host_pi/config.json"))
    cfg.output_csv = tmp_path / "out.csv"
    cfg.sensor_poly = SensorPoly(
        X=30000.0,
        Y=600000.0,
        K=[
            [0.0, 1.0],
            [0.0, 0.0],
        ],
    )
    coeff = coeff_from_sensor_poly("test", cfg.sensor_poly)
    pipeline = SamplePipeline(cfg, coeff)
    frame = Frame(
        ts_ms=0.0,
        f_hz=cfg.sensor_poly.X,
        tau_ms=cfg.tau_ms,
        v_uV=600123.0,
        adc_gain=cfg.adc.gain,
        flags=0,
        ppm_corr=0.0,
        mode="RECIP",
    )
    samples = pipeline.process([frame])
    pipeline.close()
    assert len(samples) == 1
    assert np.isclose(samples[0].pressure, 123.0)

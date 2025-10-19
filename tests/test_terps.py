from __future__ import annotations

from pathlib import Path

import numpy as np

from bslfs.terps.config import SensorPoly, TerpsConfig, load_config
from bslfs.terps.frames import Frame, FrameFormat, FrameParser, crc16_ccitt
from bslfs.terps.processing import PressureCalculator, SamplePipeline


def test_load_config_overrides(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        """
        {
          "mode": "RECIP",
          "tau_ms": 100,
          "min_interval_frac": 0.25,
          "timebase_ppm": 0.0,
          "frame_format": "csv",
          "sensor_poly": {
            "X": 30000,
            "Y": 600000,
            "K": [[0,0,0,0,0],[0,0,0,0,0],[0,0,0,0,0],[0,0,0,0,0],[0,0,0,0,0],[0,0,0,0,0]]
          }
        }
        """,
        encoding="utf-8",
    )
    cfg = load_config(cfg_path, overrides=["frame_format=binary", "adc.gain=32"])
    assert isinstance(cfg, TerpsConfig)
    assert cfg.frame_format == "binary"
    assert cfg.adc.gain == 32


def test_parse_csv_frame() -> None:
    parser = FrameParser(FrameFormat.CSV)
    lines = [
        "ts_ms,f_hz,tau_ms,v_uV,adc_gain,flags,ppm_corr,mode",
        "123.0,30000.0,100.0,500000.0,16,1,0.2,RECIP",
    ]
    frames = list(parser.parse_csv(lines))
    assert len(frames) == 1
    frame = frames[0]
    assert frame.f_hz == 30000.0
    assert frame.mode == "RECIP"


def test_parse_binary_frame() -> None:
    parser = FrameParser(FrameFormat.BINARY)
    ts_ms = 123456
    f_hz = 30012.3456
    tau_ms = 100
    v_uV = 501234.0
    adc_gain = 16
    flags = 0b1010
    ppm_corr = 0.15
    mode = 1
    body = (
        ts_ms.to_bytes(4, "little")
        + int(f_hz * 1e4).to_bytes(4, "little", signed=True)
        + tau_ms.to_bytes(2, "little")
        + int(v_uV).to_bytes(4, "little", signed=True)
        + adc_gain.to_bytes(1, "little")
        + flags.to_bytes(1, "little")
        + int(ppm_corr * 1e2).to_bytes(2, "little", signed=True)
        + mode.to_bytes(1, "little")
    )
    crc = crc16_ccitt(body).to_bytes(2, "little")
    packet = b"\x55\xAA" + bytes([len(body)]) + body + crc
    frames = list(parser.parse_binary([packet]))
    assert len(frames) == 1
    frame = frames[0]
    assert frame.tau_ms == tau_ms
    assert frame.ppm_corr == ppm_corr
    assert frame.mode == "RECIP"


def test_pressure_calculator_linear() -> None:
    sensor_poly = SensorPoly(
        X=30000.0,
        Y=600000.0,
        K=[
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
        ],
    )
    calc = PressureCalculator(sensor_poly)
    pressure = calc.evaluate(30001.0, 600000.0)
    assert np.isclose(pressure, 1.0)


def test_pressure_calculator_microvolt_baseline() -> None:
    sensor_poly = SensorPoly(
        X=30000.0,
        Y=600000.0,
        K=[
            [0.0, 0.0, 1.0],
        ],
    )
    calc = PressureCalculator(sensor_poly)
    pressure = calc.evaluate(30000.0, 600123.0)
    assert np.isclose(pressure, 123.0**2)


def test_sample_pipeline_logs(tmp_path: Path) -> None:
    cfg = load_config(Path("host_pi/config.json"))
    cfg.output_csv = tmp_path / "out.csv"
    pipeline = SamplePipeline(cfg)
    frame = Frame(
        ts_ms=1.0,
        f_hz=cfg.sensor_poly.X,
        tau_ms=cfg.tau_ms,
        v_uV=cfg.sensor_poly.Y,
        adc_gain=cfg.adc.gain,
        flags=0,
        ppm_corr=cfg.timebase_ppm,
        mode=cfg.mode,
    )
    samples = pipeline.process([frame])
    pipeline.close()
    assert len(samples) == 1
    assert cfg.output_csv.exists()

def test_sample_pipeline_microvolt_frame(tmp_path: Path) -> None:
    cfg = load_config(Path("host_pi/config.json"))
    cfg.output_csv = tmp_path / "microvolt.csv"
    cfg.sensor_poly = SensorPoly(
        X=30000.0,
        Y=600000.0,
        K=[
            [0.0, 1.0],
            [0.0, 0.0],
        ],
    )
    pipeline = SamplePipeline(cfg)
    frame = Frame(
        ts_ms=10.0,
        f_hz=cfg.sensor_poly.X,
        tau_ms=cfg.tau_ms,
        v_uV=600123.0,
        adc_gain=cfg.adc.gain,
        flags=0,
        ppm_corr=cfg.timebase_ppm,
        mode=cfg.mode,
    )
    samples = pipeline.process([frame])
    pipeline.close()
    assert len(samples) == 1
    assert np.isclose(samples[0].pressure, 123.0)

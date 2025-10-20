from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, TextIO

import numpy as np

from .config import SensorPoly, TerpsConfig
from .frames import Frame


@dataclass
class SampleRecord:
    """Aggregated sample ready for persistence."""

    ts_ms: float
    frequency_hz: float
    tau_ms: float
    diode_uV: float
    pressure: float
    adc_gain: int
    flags: int
    ppm_corr: float
    mode: str


class PressureCalculator:
    """
    Evaluate the polynomial surface defined by the calibration coefficients.
    Uses numpy arrays to keep the implementation concise and fast.
    """

    def __init__(self, sensor_poly: SensorPoly):
        self.sensor_poly = sensor_poly
        self._k = np.array(sensor_poly.K, dtype=float)
        if self._k.ndim != 2 or self._k.size == 0:
            raise ValueError("sensor_poly.K must be a non-empty 2D matrix")
        self._rows, self._cols = self._k.shape

    def evaluate(self, frequency_hz: float, diode_uV: float) -> float:
        x = frequency_hz - self.sensor_poly.X
        y = diode_uV - self.sensor_poly.Y
        x_indices = np.arange(self._rows, dtype=float)
        y_indices = np.arange(self._cols, dtype=float)
        x_powers = np.power(x, x_indices, dtype=float)
        y_powers = np.power(y, y_indices, dtype=float)
        return float(np.sum(self._k * np.outer(x_powers, y_powers)))


class CsvLogger:
    """
    Lazily creates a CSV writer when the first record arrives. Keeping writer
    creation lazy avoids touching the filesystem during dry runs or tests.
    """

    def __init__(self, path: Path):
        self.path = path
        self._handle: Optional[csv.DictWriter[str]] = None
        self._file_handle: Optional[TextIO] = None

    def append(self, sample: SampleRecord) -> None:
        if self._handle is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file_handle = self.path.open("w", newline="", encoding="utf-8")
            fieldnames = [
                "ts_ms",
                "frequency_hz",
                "tau_ms",
                "diode_uV",
                "pressure",
                "adc_gain",
                "flags",
                "ppm_corr",
                "mode",
            ]
            self._handle = csv.DictWriter(self._file_handle, fieldnames=fieldnames)
            self._handle.writeheader()
        assert self._handle is not None
        self._handle.writerow(sample.__dict__)
        if self._file_handle is not None:
            self._file_handle.flush()

    def close(self) -> None:
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None
            self._handle = None


class SamplePipeline:
    """
    Glue that converts frames into processed samples and optionally logs them.
    """

    def __init__(self, config: TerpsConfig):
        self.config = config
        self.calculator = PressureCalculator(config.sensor_poly)
        self.logger = CsvLogger(config.output_csv) if config.output_csv else None
        self._callbacks: List[Callable[[SampleRecord], None]] = []

    def process(self, frames: Iterable[Frame]) -> List[SampleRecord]:
        processed: List[SampleRecord] = []
        for frame in frames:
            pressure = self.calculator.evaluate(frame.f_hz, frame.v_uV)
            sample = SampleRecord(
                ts_ms=frame.ts_ms,
                frequency_hz=frame.f_hz,
                tau_ms=frame.tau_ms,
                diode_uV=frame.v_uV,
                pressure=pressure,
                adc_gain=frame.adc_gain,
                flags=frame.flags,
                ppm_corr=frame.ppm_corr,
                mode=frame.mode,
            )
            processed.append(sample)
            if self.logger:
                self.logger.append(sample)
            for callback in self._callbacks:
                callback(sample)
        return processed

    def register_callback(self, callback: Callable[[SampleRecord], None]) -> None:
        self._callbacks.append(callback)

    def close(self) -> None:
        if self.logger:
            self.logger.close()

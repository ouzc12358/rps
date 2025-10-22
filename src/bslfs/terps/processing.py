from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, TextIO

import numpy as np

from .coeff import Coeff, coeff_metadata
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
        self._pending_metadata: List[str] = []

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
            for line in self._pending_metadata:
                if self._file_handle is not None:
                    self._file_handle.write(line + "\n")
            if self._pending_metadata and self._file_handle is not None:
                self._file_handle.flush()
            self._pending_metadata.clear()
            self._handle.writeheader()
        assert self._handle is not None
        self._handle.writerow(sample.__dict__)
        if self._file_handle is not None:
            self._file_handle.flush()

    def set_metadata(self, metadata: Dict[str, str]) -> None:
        if not metadata:
            return
        line = "# " + " ".join(f"{key}={value}" for key, value in metadata.items())
        if self._handle is None:
            self._pending_metadata.append(line)
            return
        if self._file_handle is None:
            return
        self._file_handle.write(line + "\n")
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

    def __init__(self, config: TerpsConfig, coeff: Coeff):
        self.config = config
        self.coeff = coeff
        self.logger = CsvLogger(config.output_csv) if config.output_csv else None
        self._callbacks: List[Callable[[SampleRecord], None]] = []
        poly = coeff.as_sensor_poly()
        self.config.sensor_poly = poly
        self.calculator = PressureCalculator(poly)
        if self.logger:
            self.logger.set_metadata(coeff_metadata(coeff))

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

    def update_coeff(self, coeff: Coeff) -> None:
        self.coeff = coeff
        poly = coeff.as_sensor_poly()
        self.config.sensor_poly = poly
        self.calculator = PressureCalculator(poly)
        if self.logger:
            self.logger.set_metadata(coeff_metadata(coeff))

    def close(self) -> None:
        if self.logger:
            self.logger.close()

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Deque, Optional, Sequence

try:  # pragma: no cover - optional dependency
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
except ImportError:  # pragma: no cover - handled in runner
    raise

from .processing import SampleRecord


class LivePlotter:
    """Realtime 2×2 dashboard for pressure, temperature proxy, frequency, and diode voltage."""

    def __init__(
        self,
        *,
        baseline_uv: float,
        temp_mode: str = "off",
        temp_linear_v0: float = 600000.0,
        temp_linear_slope: float = -2000.0,
        temp_poly: Optional[Sequence[float]] = None,
        window: int = 500,
        refresh_ms: int = 500,
        snapshot_every: float = 0.0,
        snapshot_dir: Optional[Path] = None,
    ) -> None:
        self._logger = logging.getLogger(__name__)
        self._baseline_uv = baseline_uv
        self._temp_mode = temp_mode
        self._temp_linear_v0 = temp_linear_v0
        self._temp_linear_slope = temp_linear_slope
        self._temp_poly = list(temp_poly) if temp_poly is not None else None
        self._lock = threading.Lock()
        self._t0: Optional[float] = None
        self._time: Deque[float] = deque(maxlen=window)
        self._pressure: Deque[float] = deque(maxlen=window)
        self._temp: Deque[float] = deque(maxlen=window)
        self._freq: Deque[float] = deque(maxlen=window)
        self._diode: Deque[float] = deque(maxlen=window)
        self._running = True
        self._drop_count = 0
        self._next_drop_log = time.monotonic() + 60.0
        self._autoscale_every = 5
        self._autoscale_counter = 0
        self._snapshot_every = snapshot_every
        self._next_snapshot = time.monotonic() + snapshot_every if snapshot_every > 0 else None
        self._snapshot_dir = snapshot_dir

        self.fig, axes = plt.subplots(2, 2, figsize=(11, 6), sharex=False)
        (self.ax_press, self.ax_temp), (self.ax_freq, self.ax_diode) = axes

        self.ax_press.set_title("Pressure")
        self.ax_press.set_ylabel("Pressure")
        self.ax_temp.set_title("Temperature")
        self.ax_temp.set_ylabel("Proxy (°C)")
        self.ax_freq.set_title("Frequency")
        self.ax_freq.set_ylabel("Hz")
        self.ax_diode.set_title("Diode Voltage")
        self.ax_diode.set_ylabel("µV")
        self.ax_freq.set_xlabel("Time (s)")
        self.ax_diode.set_xlabel("Time (s)")

        self.line_press, = self.ax_press.plot([], [], color="tab:blue")
        self.line_temp, = self.ax_temp.plot([], [], color="tab:orange")
        self.line_freq, = self.ax_freq.plot([], [], color="tab:green")
        self.line_diode, = self.ax_diode.plot([], [], color="tab:red")

        self._anim = FuncAnimation(self.fig, self._update_plot, interval=refresh_ms, blit=False)

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:  # pragma: no cover - GUI loop
        plt.show(block=False)
        while self._running:
            try:
                plt.pause(0.1)
            except Exception:
                break

    def on_sample(self, sample: SampleRecord) -> None:
        with self._lock:
            t_now = sample.ts_ms / 1000.0
            if self._t0 is None:
                self._t0 = t_now
            relative_t = t_now - self._t0
            drop_imminent = len(self._time) == self._time.maxlen
            self._time.append(relative_t)
            self._pressure.append(sample.pressure)
            self._temp.append(self._compute_temperature(sample))
            self._freq.append(sample.frequency_hz)
            self._diode.append(sample.diode_uV)
            if drop_imminent:
                self._drop_count += 1
            now = time.monotonic()
            if self._drop_count and now >= self._next_drop_log:
                self._logger.warning("Live plot queue dropped %d samples", self._drop_count)
                self._drop_count = 0
                self._next_drop_log = now + 60.0
            if self._snapshot_every > 0 and self._next_snapshot and now >= self._next_snapshot:
                self._save_snapshot(now)
                self._next_snapshot = now + self._snapshot_every

    def _compute_temperature(self, sample: SampleRecord) -> float:
        if self._temp_mode == "off":
            return 0.0
        if self._temp_mode == "linear":
            slope = self._temp_linear_slope
            if slope == 0:
                return 0.0
            return (sample.diode_uV - self._temp_linear_v0) / slope
        if self._temp_mode == "poly":
            if not self._temp_poly:
                return 0.0
            y = sample.diode_uV
            value = 0.0
            power = 1.0
            for coeff in self._temp_poly:
                value += coeff * power
                power *= y
            return value
        return 0.0

    def _save_snapshot(self, now: float) -> None:
        if not self._snapshot_dir:
            return
        try:
            self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self._logger.error("Unable to create snapshot directory %s: %s", self._snapshot_dir, exc)
            return
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        path = self._snapshot_dir / f"plot_{timestamp}.png"
        try:
            self.fig.savefig(path)
            self._logger.info("Saved plot snapshot to %s", path)
        except Exception as exc:
            self._logger.error("Failed to save snapshot %s: %s", path, exc)

    def _update_plot(self, _frame):  # pragma: no cover - GUI callback
        with self._lock:
            times = list(self._time)
            if not times:
                return self.line_press, self.line_temp, self.line_freq, self.line_diode
            pressure = list(self._pressure)
            temp = list(self._temp)
            freq = list(self._freq)
            diode = list(self._diode)

        xmin = times[0]
        xmax = times[-1] if times[-1] > xmin else xmin + 1.0

        data_series = [
            (self.ax_press, self.line_press, pressure),
            (self.ax_temp, self.line_temp, temp),
            (self.ax_freq, self.line_freq, freq),
            (self.ax_diode, self.line_diode, diode),
        ]

        for axis, line, data in data_series:
            line.set_data(times, data)
            axis.set_xlim(xmin, xmax)

        self._autoscale_counter = (self._autoscale_counter + 1) % self._autoscale_every
        if self._autoscale_counter == 0:
            for axis, _, data in data_series:
                axis.relim()
                axis.autoscale_view()

        return self.line_press, self.line_temp, self.line_freq, self.line_diode

    def close(self) -> None:
        self._running = False
        try:
            plt.close(self.fig)
        except Exception:
            pass
        thread = getattr(self, "_thread", None)
        if thread and thread.is_alive():
            thread.join(timeout=1.0)


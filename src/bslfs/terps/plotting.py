from __future__ import annotations

import threading
from collections import deque
from typing import Deque, Optional

try:
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
except ImportError as exc:  # pragma: no cover - guarded by CLI
    raise ImportError("matplotlib is required for realtime plotting") from exc

from .processing import SampleRecord


class LivePlotter:
    """Realtime 2×2 dashboard for pressure/temperature/frequency/diode signals."""

    def __init__(
        self,
        baseline_uv: float,
        window: int = 500,
        temp_scale: float = 0.001,
        refresh_ms: int = 500,
    ) -> None:
        self._baseline_uv = baseline_uv
        self._temp_scale = temp_scale
        self._lock = threading.Lock()
        self._t0: Optional[float] = None
        self._time: Deque[float] = deque(maxlen=window)
        self._pressure: Deque[float] = deque(maxlen=window)
        self._temp: Deque[float] = deque(maxlen=window)
        self._freq: Deque[float] = deque(maxlen=window)
        self._diode: Deque[float] = deque(maxlen=window)
        self._running = True

        self.fig, axes = plt.subplots(2, 2, figsize=(10, 6), sharex=False)
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

    def _loop(self) -> None:
        plt.show(block=False)
        while self._running:
            try:
                plt.pause(0.1)
            except Exception:  # pragma: no cover - GUI specific
                break

    def on_sample(self, sample: SampleRecord) -> None:
        with self._lock:
            t_now = sample.ts_ms / 1000.0
            if self._t0 is None:
                self._t0 = t_now
            relative_t = t_now - self._t0
            self._time.append(relative_t)
            self._pressure.append(sample.pressure)
            delta_uv = sample.diode_uV - self._baseline_uv
            self._temp.append(delta_uv * self._temp_scale)
            self._freq.append(sample.frequency_hz)
            self._diode.append(sample.diode_uV)

    def _update_plot(self, _frame):  # pragma: no cover - GUI callback
        with self._lock:
            times = list(self._time)
            if not times:
                return self.line_press, self.line_temp, self.line_freq, self.line_diode
            pressure = list(self._pressure)
            temp = list(self._temp)
            freq = list(self._freq)
            diode = list(self._diode)

        for axis, line, data in [
            (self.ax_press, self.line_press, pressure),
            (self.ax_temp, self.line_temp, temp),
            (self.ax_freq, self.line_freq, freq),
            (self.ax_diode, self.line_diode, diode),
        ]:
            line.set_data(times, data)
            axis.relim()
            axis.autoscale_view()

        return self.line_press, self.line_temp, self.line_freq, self.line_diode

    def close(self) -> None:
        self._running = False
        plt.close(self.fig)
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

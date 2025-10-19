from __future__ import annotations

import logging
import queue
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import typer

try:
    import serial  # type: ignore[import]
except ImportError:  # pragma: no cover - handled in CLI validation
    serial = None  # type: ignore[assignment]

from .config import TerpsConfig, load_config
from .frames import Frame, FrameFormat, FrameParser, iterate_binary_stream, iterate_text_stream
from .processing import SamplePipeline

logger = logging.getLogger(__name__)


PRESETS: Dict[str, Dict[str, Any]] = {
    "0p02": {
        "mode": "RECIP",
        "tau_ms": 100.0,
        "min_interval_frac": 0.25,
        "timebase_ppm": 0.0,
        "adc": {"gain": 16, "rate_sps": 50, "mains_reject": True},
    },
    "0p01": {
        "mode": "RECIP",
        "tau_ms": 500.0,
        "min_interval_frac": 0.25,
        "timebase_ppm": 0.0,
        "adc": {"gain": 32, "rate_sps": 40, "mains_reject": True},
    },
    "0p003": {
        "mode": "RECIP",
        "tau_ms": 2000.0,
        "min_interval_frac": 0.25,
        "timebase_ppm": 0.0,
        "adc": {"gain": 32, "rate_sps": 20, "mains_reject": True},
    },
}


def preset_overrides(preset: str) -> list[str]:
    data = PRESETS[preset]
    overrides = [
        f"mode={data['mode']}",
        f"tau_ms={data['tau_ms']}",
        f"min_interval_frac={data['min_interval_frac']}",
        f"timebase_ppm={data['timebase_ppm']}",
        f"adc.gain={data['adc']['gain']}",
        f"adc.rate_sps={data['adc']['rate_sps']}",
        f"adc.mains_reject={'true' if data['adc']['mains_reject'] else 'false'}",
    ]
    return overrides


@dataclass
class SerialSettings:
    port: str
    baudrate: int = 921600
    timeout: float = 2.0


class SerialReaderThread(threading.Thread):
    def __init__(
        self,
        settings: SerialSettings,
        frame_format: FrameFormat,
        config: TerpsConfig,
        frame_queue: "queue.Queue[Frame]",
    ) -> None:
        super().__init__(daemon=True)
        self.settings = settings
        self.frame_format = frame_format
        self.config = config
        self.queue = frame_queue
        self.parser = FrameParser(frame_format)
        self._stop_event = threading.Event()
        self._serial_handle = None
        self._dropped = 0
        self._reconnects = 0
        self._connected_once = False
        self.last_exception: Optional[Exception] = None
        self._log = logging.getLogger(__name__)

    def run(self) -> None:  # pragma: no cover - exercised via integration-style tests
        initial_delay = max(self.config.host.reconnect_initial_sec, 0.1)
        max_delay = max(self.config.host.reconnect_max_sec, initial_delay)
        backoff = initial_delay
        while not self._stop_event.is_set():
            self._serial_handle = None
            try:
                self._serial_handle = self._open_serial()
                if self._connected_once:
                    self._reconnects += 1
                    self._log.info("Reconnected to %s", self.settings.port)
                else:
                    self._log.info("Connected to %s", self.settings.port)
                    self._connected_once = True
                self.last_exception = None
                backoff = initial_delay
                self.parser.reset()
                if self.frame_format is FrameFormat.CSV:
                    wrapper = TextWrapper(self._serial_handle)
                    try:
                        for frame in self.parser.parse_csv(iterate_text_stream(wrapper)):
                            if self._stop_event.is_set():
                                break
                            self._emit(frame)
                    finally:
                        wrapper.close()
                else:
                    chunk_size = max(self.config.host.binary_chunk_size, 16)
                    assert self._serial_handle is not None
                    for frame in self.parser.parse_binary(
                        iterate_binary_stream(self._serial_handle, chunk_size=chunk_size)
                    ):
                        if self._stop_event.is_set():
                            break
                        self._emit(frame)
            except serial.SerialException as exc:  # type: ignore[attr-defined]
                self.last_exception = exc
                self._log.warning("Serial error (%s): %s", self.settings.port, exc)
            except Exception as exc:  # pragma: no cover - defensive
                self.last_exception = exc
                self._log.exception("Unexpected error in serial reader")
            finally:
                if self._serial_handle is not None:
                    try:
                        self._serial_handle.close()
                    except Exception:
                        pass
                    self._serial_handle = None
            if self._stop_event.is_set():
                break
            wait_time = min(backoff, max_delay)
            self._log.info("Reconnecting in %.1fs", wait_time)
            self._stop_event.wait(wait_time)
            backoff = min(backoff * 2, max_delay)

    def stop(self) -> None:
        self._stop_event.set()
        if self._serial_handle is not None:
            try:
                self._serial_handle.close()
            except Exception:
                pass

    def stats(self) -> dict[str, int]:
        stats = self.parser.stats()
        stats["dropped"] = self._dropped
        stats["reconnects"] = self._reconnects
        return stats

    def _emit(self, frame: Frame) -> None:
        try:
            self.queue.put(frame, timeout=1.0)
        except queue.Full:
            self._dropped += 1
            self._log.warning("Frame queue full (%d), dropping frame", self.queue.qsize())

    def _open_serial(self):
        if serial is None:
            raise ImportError("pyserial is required but not installed. Install extra 'terps'.")
        return serial.Serial(
            port=self.settings.port,
            baudrate=self.settings.baudrate,
            timeout=self.settings.timeout,
        )


class TerpsHost:
    """Host-side orchestrator running on Raspberry Pi."""

    def __init__(self, settings: SerialSettings, config: TerpsConfig):
        self.settings = settings
        self.config = config
        self.frame_format = FrameFormat(config.frame_format_enum)
        self.pipeline = SamplePipeline(config)

    def run(self) -> None:
        if self.settings.port == "-":
            self._run_from_stream()
            return

        frame_queue: "queue.Queue[Frame]" = queue.Queue(maxsize=self.config.host.queue_maxsize)
        reader = SerialReaderThread(self.settings, self.frame_format, self.config, frame_queue)
        reader.start()
        processed = 0
        interval_sec = max(float(self.config.host.stats_log_interval), 5.0)
        next_log = time.monotonic() + interval_sec

        def emit_stats() -> None:
            stats = reader.stats()
            logger.info(
                "processed=%d frames=%d crc_errors=%d length_errors=%d dropped=%d reconnects=%d",
                processed,
                stats.get("frames", 0),
                stats.get("crc_errors", 0),
                stats.get("length_errors", 0),
                stats.get("dropped", 0),
                stats.get("reconnects", 0),
            )
        try:
            while True:
                try:
                    frame = frame_queue.get(timeout=1.0)
                except queue.Empty:
                    if time.monotonic() >= next_log:
                        emit_stats()
                        next_log = time.monotonic() + interval_sec
                    continue
                self.pipeline.process([frame])
                processed += 1
                if time.monotonic() >= next_log:
                    emit_stats()
                    next_log = time.monotonic() + interval_sec
        except KeyboardInterrupt:
            logger.info("Stopping host (Ctrl+C)")
        finally:
            reader.stop()
            reader.join(timeout=5)
            final_stats = reader.stats()
            self.pipeline.close()
            logger.info(
                "Final stats: processed=%d frames=%d crc_errors=%d length_errors=%d dropped=%d reconnects=%d",
                processed,
                final_stats.get("frames", 0),
                final_stats.get("crc_errors", 0),
                final_stats.get("length_errors", 0),
                final_stats.get("dropped", 0),
                final_stats.get("reconnects", 0),
            )

    def _run_from_stream(self) -> None:
        parser = FrameParser(self.frame_format)
        if self.frame_format is FrameFormat.CSV:
            frames = parser.parse_csv(iterate_text_stream(sys.stdin))
        else:
            frames = parser.parse_binary(iterate_binary_stream(sys.stdin.buffer))
        try:
            samples = self.pipeline.process(frames)
            stats = parser.stats()
            logger.info(
                "Processed %d samples from stdin (crc_errors=%d length_errors=%d)",
                len(samples),
                stats.get("crc_errors", 0),
                stats.get("length_errors", 0),
            )
        finally:
            self.pipeline.close()


class TextWrapper:
    """Minimal adapter exposing a text iterator from a pyserial device."""

    def __init__(self, ser):
        self.ser = ser

    def __iter__(self):
        return self

    def __next__(self):
        line = self.ser.readline()
        if not line:
            raise StopIteration
        return line.decode("utf-8", errors="ignore")

    def close(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass


app = typer.Typer(add_completion=False, help="TERPS RPS host utilities.")


@app.command()
def run(
    port: str = typer.Option(
        "/dev/ttyACM0", "--port", "-p", help="Serial device. Use '-' to read from stdin."
    ),
    baudrate: int = typer.Option(921600, "--baud", help="Serial baudrate for UART fallback."),
    timeout: float = typer.Option(2.0, "--timeout", help="Serial read timeout (seconds)."),
    config_path: Path = typer.Option(
        Path("host_pi/config.json"), "--config", "-c", help="Path to TERPS host config."
    ),
    preset: Optional[str] = typer.Option(
        None,
        "--preset",
        "-P",
        help="Apply preset (0p02|0p01|0p003) before other overrides.",
    ),
    override: Optional[list[str]] = typer.Option(
        None,
        "--set",
        help="Override config keys, e.g. --set frame_format=binary --set adc.gain=32",
    ),
):
    """Run the host pipeline: read frames, compute pressure, persist CSV."""

    preset_overrides_list: list[str] = []
    if preset:
        key = preset.lower()
        if key not in PRESETS:
            raise typer.BadParameter(f"Unknown preset '{preset}'. Expected one of {list(PRESETS)}")
        preset_overrides_list = preset_overrides(key)
    combined_overrides = preset_overrides_list + (override or [])
    cfg = load_config(config_path, combined_overrides or None)
    if preset:
        logger.info("Applied preset %s (tau_ms=%.1f, adc_gain=%d, rate_sps=%d)",
                    preset.lower(), cfg.tau_ms, cfg.adc.gain, cfg.adc.rate_sps)
    settings = SerialSettings(port=port, baudrate=baudrate, timeout=timeout)
    host = TerpsHost(settings=settings, config=cfg)
    host.run()

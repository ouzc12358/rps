from __future__ import annotations

import logging
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence

import typer

try:
    import serial  # type: ignore[import]
except ImportError:  # pragma: no cover - handled in CLI validation
    serial = None  # type: ignore[assignment]

from .coeff import (
    Coeff,
    CoeffManager,
    DefaultConfig,
    EepromOverCdc,
    ManualOverride,
    RPS_EEPROM_SIZE,
    parse_eeprom_dump,
    parse_rps_eeprom,
    save_manual_coeff,
)
from .config import TerpsConfig, load_config
from .frames import Frame, FrameFormat, FrameParser
from .processing import SamplePipeline

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .plotting import LivePlotter


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


@dataclass
class CommandRequest:
    command: str
    response: "queue.Queue[List[str]]"
    timeout: float
    started: float = field(default=0.0)


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
        self._command_queue: "queue.Queue[CommandRequest]" = queue.Queue()
        self._active_command: Optional[CommandRequest] = None
        self._command_buffer: List[str] = []
        self._ready_event = threading.Event()

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
                self._ready_event.set()
                if self.frame_format is FrameFormat.CSV:
                    for frame in self.parser.parse_csv(self._iter_csv_lines()):
                        if self._stop_event.is_set():
                            break
                        self._emit(frame)
                else:
                    chunk_size = max(self.config.host.binary_chunk_size, 16)
                    for frame in self.parser.parse_binary(self._iter_binary_chunks(chunk_size)):
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
                self._ready_event.clear()
                if self._active_command is not None:
                    self._complete_command(["ERR DISCONNECTED"])
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

    def execute_command(self, command: str, timeout: float = 2.0) -> List[str]:
        if not self._ready_event.wait(timeout):
            raise TimeoutError("Serial device not ready")
        response: "queue.Queue[List[str]]" = queue.Queue(maxsize=1)
        request = CommandRequest(command=command.strip(), response=response, timeout=timeout)
        self._command_queue.put(request)
        try:
            return response.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError(f"Timeout waiting for command '{command}'") from exc

    def wait_ready(self, timeout: float = 2.0) -> bool:
        return self._ready_event.wait(timeout)

    def _iter_csv_lines(self):
        while not self._stop_event.is_set():
            self._process_command_queue()
            if self._active_command is not None:
                line = self._readline()
                if line is None:
                    continue
                self._handle_command_line(line)
                continue
            line = self._readline()
            if line is None:
                continue
            if self._handle_command_line(line):
                continue
            yield line

    def _iter_binary_chunks(self, chunk_size: int):
        while not self._stop_event.is_set():
            self._process_command_queue()
            if self._active_command is not None:
                line = self._readline()
                if line is None:
                    continue
                self._handle_command_line(line)
                continue
            if self._serial_handle is None:
                time.sleep(0.01)
                continue
            data = self._serial_handle.read(chunk_size)
            if not data:
                continue
            yield data

    def _process_command_queue(self) -> None:
        if self._active_command is not None:
            if self._active_command.started and (time.monotonic() - self._active_command.started) > self._active_command.timeout:
                self._complete_command(["ERR TIMEOUT"])
            return
        try:
            request = self._command_queue.get_nowait()
        except queue.Empty:
            return
        if self._serial_handle is None:
            request.response.put(["ERR NOT_CONNECTED"])
            return
        payload = (request.command + "\n").encode("ascii", errors="ignore")
        try:
            self._serial_handle.write(payload)
            self._serial_handle.flush()
        except Exception as exc:
            request.response.put([f"ERR WRITE_FAILED {exc}"])
            return
        request.started = time.monotonic()
        self._active_command = request
        self._command_buffer = []

    def _readline(self) -> Optional[str]:
        if self._serial_handle is None:
            return None
        try:
            raw = self._serial_handle.readline()
        except Exception as exc:
            self._log.debug("readline error: %s", exc)
            return None
        if not raw:
            return None
        return raw.decode("utf-8", errors="ignore")

    def _handle_command_line(self, line: str) -> bool:
        if self._active_command is None:
            return False
        stripped = line.rstrip("\r\n")
        if stripped:
            self._command_buffer.append(stripped)
        if stripped == "END":
            self._complete_command(self._command_buffer.copy())
        return True

    def _complete_command(self, lines: List[str]) -> None:
        if self._active_command is None:
            return
        try:
            self._active_command.response.put_nowait(lines)
        except queue.Full:
            pass
        finally:
            self._active_command = None
            self._command_buffer = []

    def _open_serial(self):
        if serial is None:
            raise ImportError("pyserial is required but not installed. Install extra 'terps'.")
        return serial.Serial(
            port=self.settings.port,
            baudrate=self.settings.baudrate,
            timeout=self.settings.timeout,
        )


class SerialCommandClient:
    def __init__(self, settings: SerialSettings):
        if serial is None:
            raise ImportError("pyserial is required but not installed. Install extra 'terps'.")
        self._serial = serial.Serial(
            port=settings.port,
            baudrate=settings.baudrate,
            timeout=settings.timeout,
        )
        self._timeout = settings.timeout

    def execute(self, command: str, timeout: Optional[float] = None) -> List[str]:
        deadline = time.monotonic() + (timeout or self._timeout)
        payload = (command.strip() + "\n").encode("ascii", errors="ignore")
        self._serial.reset_input_buffer()
        self._serial.write(payload)
        self._serial.flush()
        lines: List[str] = []
        while time.monotonic() < deadline:
            raw = self._serial.readline()
            if not raw:
                continue
            decoded = raw.decode("utf-8", errors="ignore").rstrip("\r\n")
            lines.append(decoded)
            if decoded == "END":
                return lines
        raise TimeoutError(f"Timeout waiting for '{command}' response")

    def close(self) -> None:
        try:
            self._serial.close()
        except Exception:
            pass


class TerpsHost:
    """Host-side orchestrator running on Raspberry Pi."""

    def __init__(
        self,
        settings: SerialSettings,
        config: TerpsConfig,
        coeff_mode: str,
        coeff_refresh_sec: float,
        manual_override: Optional[ManualOverride] = None,
        plotter: Optional["LivePlotter"] = None,
    ):
        self.settings = settings
        self.config = config
        self.frame_format = FrameFormat(config.frame_format_enum)
        self.plotter = plotter
        self._coeff_mode = coeff_mode.lower()
        self._coeff_refresh_sec = max(coeff_refresh_sec, 1.0)
        self._manual_override = manual_override or ManualOverride()
        self._default_provider = DefaultConfig(config)
        initial_coeff = self._manual_override.get() or self._default_provider.get()
        self.pipeline = SamplePipeline(config, initial_coeff)
        if self.plotter:
            self.pipeline.register_callback(self.plotter.on_sample)
        self._coeff_manager: Optional[CoeffManager] = None
        self._eeprom_provider: Optional[EepromOverCdc] = None

    def run(self) -> None:
        if self.settings.port == "-":
            self._run_from_stream()
            return

        frame_queue: "queue.Queue[Frame]" = queue.Queue(maxsize=self.config.host.queue_maxsize)
        reader = SerialReaderThread(self.settings, self.frame_format, self.config, frame_queue)
        reader.start()
        self._setup_coeff_manager(reader)
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
                if self._coeff_manager is not None:
                    updated = self._coeff_manager.refresh(time.monotonic())
                    if updated is not None:
                        self._apply_coeff(updated)
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
            if self.plotter:
                self.plotter.close()

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
            if self.plotter:
                self.plotter.close()

    def _setup_coeff_manager(self, reader: SerialReaderThread) -> None:
        wait_timeout = max(self.settings.timeout, 1.0)
        reader.wait_ready(wait_timeout)
        eeprom_provider = None
        if self._coeff_mode != "manual" and self.frame_format is FrameFormat.CSV:
            eeprom_provider = EepromOverCdc(reader.execute_command)
            self._eeprom_provider = eeprom_provider
        elif self._coeff_mode != "manual" and self.frame_format is FrameFormat.BINARY:
            logger.warning("Disabling EEPROM refresh while streaming binary frames")
        self._coeff_manager = CoeffManager(
            default_provider=self._default_provider,
            manual_provider=self._manual_override,
            eeprom_provider=eeprom_provider,
            mode=self._coeff_mode,
            refresh_interval=self._coeff_refresh_sec,
        )
        self._apply_coeff(self._coeff_manager.current)

    def _apply_coeff(self, coeff) -> None:
        self.pipeline.update_coeff(coeff)
        if self.plotter and hasattr(self.plotter, "set_coeff_source"):
            try:
                self.plotter.set_coeff_source(coeff)
            except Exception:
                logger.debug("Plotter does not support coeff updates", exc_info=True)


coeff_app = typer.Typer(help="EEPROM coefficient utilities.")


@coeff_app.command("dump")
def coeff_dump(
    port: str = typer.Option("/dev/ttyACM0", "--port", "-p", help="Serial device"),
    baudrate: int = typer.Option(921600, "--baud", help="Serial baudrate"),
    timeout: float = typer.Option(2.0, "--timeout", help="Serial timeout (seconds)"),
    out: Path = typer.Option(Path("rps_eeprom.bin"), "--out", help="Output file for EEPROM blob"),
):
    settings = SerialSettings(port=port, baudrate=baudrate, timeout=timeout)
    client = SerialCommandClient(settings)
    try:
        lines = client.execute("EEPROM.DUMP 0 512", timeout=timeout)
    finally:
        client.close()
    blob, header = parse_eeprom_dump(lines)
    data = blob[:RPS_EEPROM_SIZE]
    out.write_bytes(data)
    typer.echo(f"Saved {len(data)} bytes from device {header.get('DEV', '?')} to {out}")


@coeff_app.command("parse")
def coeff_parse(
    input_path: Path = typer.Option(..., "--in", help="EEPROM binary file", exists=True, readable=True)
):
    blob = input_path.read_bytes()
    if len(blob) < RPS_EEPROM_SIZE:
        raise typer.BadParameter(f"File must contain at least {RPS_EEPROM_SIZE} bytes")
    try:
        coeff = parse_rps_eeprom(blob[:RPS_EEPROM_SIZE], source="file")
    except ValueError as exc:
        typer.echo(f"Checksum FAILED: {exc}")
        raise typer.Exit(code=1) from exc
    typer.echo("Checksum OK")
    typer.echo(f"Serial: {coeff.serial or 'n/a'}")
    typer.echo(f"Unit: {coeff.unit}")
    typer.echo(f"Order: {coeff.order} (nx={coeff.nx}, ny={coeff.ny})")
    typer.echo(f"X_ref: {coeff.x_ref:.6f}")
    typer.echo(f"Y_ref: {coeff.y_ref:.6f}")
    typer.echo(f"Coefficients: {len(coeff.a)} values")


@coeff_app.command("set")
def coeff_set(
    out: Path = typer.Option(..., "--out", help="Destination manual JSON"),
    order: Optional[int] = typer.Option(None, "--order", help="Polynomial order (applies to nx/ny)"),
    nx: Optional[int] = typer.Option(None, "--nx", help="Frequency axis order"),
    ny: Optional[int] = typer.Option(None, "--ny", help="Temperature axis order"),
    x_ref: float = typer.Option(..., "--x-ref", help="Reference frequency"),
    y_ref: float = typer.Option(..., "--y-ref", help="Reference diode voltage (µV)"),
    unit: str = typer.Option("Pa", "--unit", help="Pressure unit label"),
    serial: Optional[str] = typer.Option(None, "--serial", help="Manual serial identifier"),
    coeffs: List[float] = typer.Argument(..., help="Flattened coefficient matrix (row-major)"),
):
    if order is not None:
        nx_val = ny_val = order
    else:
        if nx is None or ny is None:
            raise typer.BadParameter("Provide --order or both --nx and --ny")
        nx_val = nx
        ny_val = ny
    expected = (nx_val + 1) * (ny_val + 1)
    if len(coeffs) != expected:
        raise typer.BadParameter(f"Expected {expected} coefficients, got {len(coeffs)}")
    coeff = Coeff(
        order=max(nx_val, ny_val),
        unit=unit,
        a=[float(value) for value in coeffs],
        serial=serial,
        source="manual",
        x_ref=x_ref,
        y_ref=y_ref,
        nx=nx_val,
        ny=ny_val,
    )
    save_manual_coeff(out, coeff)
    typer.echo(f"Wrote manual coefficient profile to {out}")


app = typer.Typer(add_completion=False, help="TERPS RPS host utilities.")
app.add_typer(coeff_app, name="coeff")


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
    plot: bool = typer.Option(False, "--plot", help="Show realtime 2x2 Matplotlib dashboard."),
    plot_snapshot_every: float = typer.Option(0.0, "--plot-snapshot-every", help="Save PNG every N seconds (0=off)."),
    temp_mode: str = typer.Option("off", "--temp-mode", help="Temperature proxy mode: off|linear|poly."),
    temp_linear_v0_uv: float = typer.Option(600000.0, "--temp-linear-v0-uV", help="Linear mode reference voltage in µV."),
    temp_linear_slope_uv_per_c: float = typer.Option(-2000.0, "--temp-linear-slope-uV-per-C", help="Linear mode slope (µV/°C)."),
    override: Optional[list[str]] = typer.Option(
        None,
        "--set",
        help="Override config keys, e.g. --set frame_format=binary --set adc.gain=32",
    ),
    coeff_source: str = typer.Option(
        "auto",
        "--coeff-source",
        help="Coefficient source priority: auto|manual|config.",
    ),
    coeff_refresh_sec: float = typer.Option(
        60.0,
        "--coeff-refresh-sec",
        help="Refresh interval for EEPROM coefficients (seconds).",
    ),
    coeff_manual_json: Optional[Path] = typer.Option(
        None,
        "--coeff-manual-json",
        help="Manual coefficient override in JSON format.",
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
    plotter = None
    if plot:
        try:
            from .plotting import LivePlotter
        except ImportError as exc:
            raise typer.BadParameter("Matplotlib is required for --plot (pip install .[plot])") from exc
        baseline_uv = cfg.sensor_poly.Y
        snapshot_dir = None
        if plot_snapshot_every > 0:
            if cfg.output_csv:
                snapshot_dir = Path(cfg.output_csv).resolve().parent
            else:
                snapshot_dir = Path.cwd() / "plot_snapshots"
        plotter = LivePlotter(
            baseline_uv=baseline_uv,
            temp_mode=temp_mode.lower(),
            temp_linear_v0=temp_linear_v0_uv,
            temp_linear_slope=temp_linear_slope_uv_per_c,
            temp_poly=cfg.temp_poly,
            snapshot_every=plot_snapshot_every,
            snapshot_dir=snapshot_dir,
        )
        logger.info("Live plot enabled (tau=%.1f ms, mode=%s)", cfg.tau_ms, temp_mode)
    if preset:
        logger.info("Applied preset %s (tau_ms=%.1f, adc_gain=%d, rate_sps=%d)",
                    preset.lower(), cfg.tau_ms, cfg.adc.gain, cfg.adc.rate_sps)
    settings = SerialSettings(port=port, baudrate=baudrate, timeout=timeout)
    coeff_mode = coeff_source.lower()
    if coeff_mode not in {"auto", "manual", "config"}:
        raise typer.BadParameter("--coeff-source must be one of auto, manual, config")
    manual_override = None
    if coeff_manual_json is not None:
        try:
            manual_override = ManualOverride.load(coeff_manual_json)
        except Exception as exc:  # pragma: no cover - user input validation
            raise typer.BadParameter(f"Failed to load manual coefficient JSON: {exc}") from exc
    if coeff_mode == "manual" and manual_override is None:
        raise typer.BadParameter("--coeff-manual-json is required when --coeff-source=manual")
    host = TerpsHost(
        settings=settings,
        config=cfg,
        coeff_mode=coeff_mode,
        coeff_refresh_sec=coeff_refresh_sec,
        manual_override=manual_override,
        plotter=plotter,
    )
    try:
        host.run()
    except KeyboardInterrupt:
        logger.info("Stopping host (Ctrl+C)")
    finally:
        if plotter is not None:
            try:
                plotter.close()  # 关闭 Matplotlib 线程/窗口，避免残留
            except Exception:
                pass

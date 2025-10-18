from __future__ import annotations

import contextlib
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import typer

try:
    import serial  # type: ignore[import]
except ImportError:  # pragma: no cover - handled in CLI validation
    serial = None  # type: ignore[assignment]

from .config import TerpsConfig, load_config
from .frames import FrameFormat, FrameParser, iterate_binary_stream, iterate_text_stream
from .processing import SamplePipeline

logger = logging.getLogger(__name__)


@dataclass
class SerialSettings:
    port: str
    baudrate: int = 921600
    timeout: float = 2.0


class TerpsHost:
    """
    Top-level runner for the Raspberry Pi host application. It pulls frames
    from a serial device (or stdin for testing), pipes them through the frame
    parser, and forwards samples into the processing pipeline.
    """

    def __init__(self, settings: SerialSettings, config: TerpsConfig):
        self.settings = settings
        self.config = config
        self.parser = FrameParser(FrameFormat(config.frame_format_enum))
        self.pipeline = SamplePipeline(config)

    def run(self) -> None:
        with contextlib.ExitStack() as stack:
            source = self._iter_source(stack)
            try:
                frames = self.parser.iter_frames(source)
                samples = self.pipeline.process(frames)
                logger.info("Processed %d samples", len(samples))
            finally:
                self.pipeline.close()

    def _iter_source(self, stack: contextlib.ExitStack) -> Iterator[str] | Iterator[bytes]:
        if self.parser.fmt is FrameFormat.CSV:
            handle = self._open_text_handle(stack)
            return iterate_text_stream(handle)
        handle = self._open_binary_handle(stack)
        return iterate_binary_stream(handle)

    def _open_text_handle(self, stack: contextlib.ExitStack):
        if self.settings.port == "-":
            return sys.stdin
        ser = _open_serial(self.settings)
        wrapper = TextWrapper(ser)
        stack.callback(wrapper.close)
        return wrapper

    def _open_binary_handle(self, stack: contextlib.ExitStack):
        if self.settings.port == "-":
            return sys.stdin.buffer
        ser = _open_serial(self.settings)
        stack.callback(ser.close)
        return ser


class TextWrapper:
    """
    Minimal adapter exposing a text iterator from a pyserial device.
    """

    def __init__(self, ser):
        self.ser = ser

    def __iter__(self):
        return self

    def __next__(self):
        line = self.ser.readline()
        if not line:
            raise StopIteration
        return line.decode("utf-8", errors="ignore")

    def close(self):
        self.ser.close()


def _open_serial(settings: SerialSettings):
    if serial is None:
        raise ImportError("pyserial is required but not installed. Install extra 'terps'.")
    return serial.Serial(
        port=settings.port,
        baudrate=settings.baudrate,
        timeout=settings.timeout,
    )


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
    override: Optional[list[str]] = typer.Option(
        None,
        "--set",
        help="Override config keys, e.g. --set frame_format=binary --set adc.gain=32",
    ),
):
    """
    Run the host pipeline: read frames, compute pressure, persist CSV.
    """

    cfg = load_config(config_path, override)
    settings = SerialSettings(port=port, baudrate=baudrate, timeout=timeout)
    host = TerpsHost(settings=settings, config=cfg)
    host.run()

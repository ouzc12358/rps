from __future__ import annotations

import queue

from bslfs.terps.config import HostRuntime, TerpsConfig
from bslfs.terps.frames import FrameFormat
from bslfs.terps.runner import SerialReaderThread, SerialSettings


class FakeSerialInstance:
    def __init__(self, lines: list[bytes]):
        self._lines = lines

    def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""

    def close(self) -> None:
        pass


class FakeSerialModule:
    def __init__(self, lines: list[bytes]):
        self.calls = 0
        self._lines = lines
        self.SerialException = RuntimeError

    def Serial(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise self.SerialException("mock disconnect")
        # Provide a fresh copy of lines for each connection
        return FakeSerialInstance(list(self._lines))


def test_serial_reader_reconnect(monkeypatch):
    lines = [
        b"ts_ms,f_hz,tau_ms,v_uV,adc_gain,flags,ppm_corr,mode\n",
        b"1000.0,30000.0,100.0,600000.0,16,0,0.0,RECIP\n",
    ]
    fake_serial = FakeSerialModule(lines)
    monkeypatch.setattr("bslfs.terps.runner.serial", fake_serial)

    settings = SerialSettings(port="/dev/ttyFAKE", baudrate=115200, timeout=0.05)
    cfg = TerpsConfig()
    cfg.frame_format = "csv"
    cfg.host = HostRuntime(
        queue_maxsize=4,
        reconnect_initial_sec=0.01,
        reconnect_max_sec=0.02,
        stats_log_interval=1,
        binary_chunk_size=64,
    )

    frame_queue: "queue.Queue" = queue.Queue()
    reader = SerialReaderThread(settings, FrameFormat(cfg.frame_format_enum), cfg, frame_queue)
    reader.start()
    try:
        frame = frame_queue.get(timeout=1.0)
        assert frame.f_hz == 30000.0
        assert fake_serial.calls >= 2  # initial failure + successful reconnect
    finally:
        reader.stop()
        reader.join(timeout=1.0)

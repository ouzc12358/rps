from __future__ import annotations

import csv
import enum
import logging
import struct
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, Optional


FLAG_SYNC_ACTIVE = 0x01
FLAG_ADC_TIMEOUT = 0x02
FLAG_PPS_LOCKED = 0x04
FLAG_ADC_SATURATED = 0x08


class FrameFormat(str, enum.Enum):
    CSV = "csv"
    BINARY = "binary"


@dataclass
class Frame:
    ts_ms: float
    f_hz: float
    tau_ms: float
    v_uV: float
    adc_gain: int
    flags: int
    ppm_corr: float
    mode: str


def crc16_ccitt(data: bytes, poly: int = 0x1021, init: int = 0xFFFF) -> int:
    crc = init
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ poly
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


class FrameParser:
    """
    Streaming frame parser supporting CSV lines and binary packets.
    The binary format follows the 0x55AA magic header described in the spec.
    """

    def __init__(self, fmt: FrameFormat):
        self.fmt = fmt
        self._buffer = bytearray()
        self._stats: Dict[str, int] = {"frames": 0, "crc_errors": 0, "length_errors": 0}
        self._payload_len = struct.calcsize("<IiHiBBhB")
        self._log = logging.getLogger(__name__)

    def parse_csv(self, lines: Iterable[str]) -> Iterator[Frame]:
        reader = csv.DictReader(lines)
        for row in reader:
            if not row:
                continue
            self._stats["frames"] += 1
            yield Frame(
                ts_ms=float(row["ts_ms"]),
                f_hz=float(row["f_hz"]),
                tau_ms=float(row["tau_ms"]),
                v_uV=float(row["v_uV"]),
                adc_gain=int(row["adc_gain"]),
                flags=int(row["flags"]),
                ppm_corr=float(row["ppm_corr"]),
                mode=row["mode"],
            )

    def parse_binary(self, chunks: Iterable[bytes]) -> Iterator[Frame]:
        for chunk in chunks:
            if not chunk:
                continue
            self._buffer.extend(chunk)
            yield from self._extract_frames()

    def _extract_frames(self) -> Iterator[Frame]:
        header = b"\x55\xAA"
        while True:
            start = self._buffer.find(header)
            if start < 0:
                self._buffer.clear()
                break
            if len(self._buffer) < start + 3:
                # Insufficient length to read frame len
                break
            length = self._buffer[start + 2]
            frame_end = start + 3 + length + 2  # payload + CRC16
            if len(self._buffer) < frame_end:
                break
            if length != self._payload_len:
                self._stats["length_errors"] += 1
                self._log.debug("Discarding frame with unexpected payload length: %s", length)
                del self._buffer[:frame_end]
                continue
            payload = bytes(self._buffer[start + 3 : start + 3 + length])
            crc_expected = struct.unpack_from("<H", self._buffer, frame_end - 2)[0]
            body = payload
            crc_actual = crc16_ccitt(body)
            if crc_actual != crc_expected:
                # Drop the corrupted frame
                self._stats["crc_errors"] += 1
                self._log.debug(
                    "CRC mismatch (expected=%04X, actual=%04X)", crc_expected, crc_actual
                )
                del self._buffer[: frame_end]
                continue
            frame = self._decode_body(body)
            if frame:
                self._stats["frames"] += 1
                yield frame
            del self._buffer[: frame_end]

    def _decode_body(self, body: bytes) -> Optional[Frame]:
        if len(body) != 4 + 4 + 2 + 4 + 1 + 1 + 2 + 1:
            return None
        (
            ts_ms_raw,
            f_hz_raw,
            tau_ms_raw,
            v_uV_raw,
            adc_gain,
            flags,
            ppm_corr_raw,
            mode,
        ) = struct.unpack("<IiHiBBhB", body)
        ts_ms = ts_ms_raw / 1.0
        f_hz = f_hz_raw / 1e4
        tau_ms = tau_ms_raw / 1.0
        v_uV = v_uV_raw / 1.0
        ppm_corr = ppm_corr_raw / 1e2
        mode_str = {0: "GATED", 1: "RECIP"}.get(mode, f"UNKNOWN({mode})")
        return Frame(
            ts_ms=ts_ms,
            f_hz=f_hz,
            tau_ms=tau_ms,
            v_uV=v_uV,
            adc_gain=adc_gain,
            flags=flags,
            ppm_corr=ppm_corr,
            mode=mode_str,
        )

    def iter_frames(self, source: Iterable[str] | Iterable[bytes]) -> Iterator[Frame]:
        if self.fmt is FrameFormat.CSV:
            assert isinstance(source, Iterable)
            return self.parse_csv(source)  # type: ignore[arg-type]
        return self.parse_binary(source)  # type: ignore[arg-type]

    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def reset(self) -> None:
        self._buffer.clear()


def iterate_text_stream(handle: Iterable[str]) -> Iterator[str]:
    for line in handle:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        yield line


def iterate_binary_stream(handle: Any, chunk_size: int = 256) -> Iterator[bytes]:
    while True:
        chunk = handle.read(chunk_size)
        if not chunk:
            break
        yield chunk

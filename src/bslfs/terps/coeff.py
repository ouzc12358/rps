from __future__ import annotations

import json
import logging
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .config import SensorPoly, TerpsConfig

logger = logging.getLogger(__name__)

RPS_EEPROM_SIZE = 0x200
RPS_EEPROM_CHECKSUM = 0x1234
RPS_UNIT_DEFAULT = "Pa"
K_TABLE_BASE = 0x0100


def _is_printable(byte_value: int) -> bool:
    return 32 <= byte_value <= 126


@dataclass
class Coeff:
    order: int
    unit: str
    a: List[float]
    serial: Optional[str]
    source: str
    x_ref: float
    y_ref: float
    nx: int
    ny: int
    product: Optional[str] = None
    device_address: Optional[int] = None

    def as_sensor_poly(self) -> SensorPoly:
        expected = (self.nx + 1) * (self.ny + 1)
        if len(self.a) != expected:
            raise ValueError(f"Coefficient vector has {len(self.a)} entries, expected {expected}")
        rows: List[List[float]] = []
        idx = 0
        for _ in range(self.nx + 1):
            row = self.a[idx : idx + self.ny + 1]
            if len(row) != self.ny + 1:
                raise ValueError("Coefficient vector does not align with nx/ny dimensions")
            rows.append(list(row))
            idx += self.ny + 1
        return SensorPoly(X=self.x_ref, Y=self.y_ref, K=rows)


def coeff_from_sensor_poly(source: str, sensor_poly: SensorPoly, unit: str = RPS_UNIT_DEFAULT) -> Coeff:
    nx = len(sensor_poly.K) - 1 if sensor_poly.K else 0
    ny = len(sensor_poly.K[0]) - 1 if sensor_poly.K and sensor_poly.K[0] else 0
    flattened: List[float] = []
    for row in sensor_poly.K:
        flattened.extend(float(value) for value in row)
    return Coeff(
        order=max(nx, ny),
        unit=unit,
        a=flattened,
        serial=None,
        source=source,
        x_ref=float(sensor_poly.X),
        y_ref=float(sensor_poly.Y),
        nx=nx,
        ny=ny,
    )


def _parse_header_tokens(header: str) -> Dict[str, str]:
    tokens = header.strip().split()
    data: Dict[str, str] = {}
    for token in tokens[1:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        data[key.upper()] = value
    return data


def parse_eeprom_dump(lines: Sequence[str]) -> Tuple[bytes, Dict[str, str]]:
    if not lines:
        raise ValueError("EEPROM dump is empty")
    header = lines[0].strip()
    if not header.startswith("OK"):
        raise ValueError(f"Unexpected EEPROM header: {header}")
    header_map = _parse_header_tokens(header)
    payload_hex: List[str] = []
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "END":
            break
        if stripped.startswith("ERR"):
            raise ValueError(f"Firmware reported error: {stripped}")
        payload_hex.append(stripped)
    payload = "".join(payload_hex)
    if len(payload) % 2 != 0:
        raise ValueError("EEPROM hex payload has odd length")
    data = bytes.fromhex(payload)
    try:
        expected_len = int(header_map.get("LEN", str(len(data))))
    except ValueError as exc:
        raise ValueError("Invalid LEN field in EEPROM header") from exc
    if expected_len != len(data):
        raise ValueError(f"EEPROM length mismatch (expected {expected_len}, got {len(data)})")
    return data, header_map


def _decode_ascii_field(blob: bytes) -> str:
    return blob.decode("ascii", errors="ignore").rstrip("\x00").strip()


def parse_rps_eeprom(blob: bytes, *, source: str, device_address: Optional[int] = None) -> Coeff:
    if len(blob) < RPS_EEPROM_SIZE:
        raise ValueError(f"EEPROM blob must be {RPS_EEPROM_SIZE} bytes, got {len(blob)}")
    checksum = sum(blob[:RPS_EEPROM_SIZE]) & 0xFFFF
    if checksum != RPS_EEPROM_CHECKSUM:
        raise ValueError(f"EEPROM checksum mismatch (expected 0x{RPS_EEPROM_CHECKSUM:04X}, got 0x{checksum:04X})")

    serial_raw = blob[0x0002:0x0006]
    serial = serial_raw.hex().upper()

    product_raw = blob[0x0008:0x0018]
    product = _decode_ascii_field(product_raw) or None

    unit_code = blob[0x0048]
    unit = chr(unit_code) if _is_printable(unit_code) else f"0x{unit_code:02X}"

    n_p = blob[0x0050]
    n_t = blob[0x0051]
    nx = int(n_p)
    ny = int(n_t)
    if nx < 0 or ny < 0:
        raise ValueError("Polynomial orders must be non-negative")
    total_coeff = (nx + 1) * (ny + 1)

    def read_float(offset: int) -> float:
        end = offset + 4
        if end > len(blob):
            raise ValueError("Unexpected end of EEPROM blob while decoding float")
        return struct.unpack(">f", blob[offset:end])[0]

    x_ref = read_float(0x0080)
    y_ref = read_float(0x0084)

    coeffs: List[float] = []
    for idx in range(total_coeff):
        offset = K_TABLE_BASE + idx * 4
        coeffs.append(read_float(offset))

    return Coeff(
        order=max(nx, ny),
        unit=unit,
        a=coeffs,
        serial=serial,
        source=source,
        x_ref=x_ref,
        y_ref=y_ref,
        nx=nx,
        ny=ny,
        product=product,
        device_address=device_address,
    )


class ManualOverride:
    def __init__(self, coeff: Optional[Coeff] = None) -> None:
        self._coeff = coeff

    @staticmethod
    def load(path: Path) -> "ManualOverride":
        data = json.loads(path.read_text(encoding="utf-8"))
        coeff = _coeff_from_mapping(data, source="manual")
        return ManualOverride(coeff)

    def get(self) -> Optional[Coeff]:
        return self._coeff


class DefaultConfig:
    def __init__(self, config: TerpsConfig, unit: str = RPS_UNIT_DEFAULT) -> None:
        self._coeff = coeff_from_sensor_poly("config", config.sensor_poly, unit=unit)

    def get(self) -> Coeff:
        return self._coeff


class EepromOverCdc:
    def __init__(self, executor: Callable[[str, float], Sequence[str]], timeout_sec: float = 2.0) -> None:
        self._executor = executor
        self._timeout = timeout_sec
        self._last_blob: Optional[bytes] = None
        self._last_coeff: Optional[Coeff] = None

    def fetch(self) -> Coeff:
        lines = self._executor("EEPROM.DUMP 0 512", self._timeout)
        blob, header = parse_eeprom_dump(lines)
        if self._last_blob == blob and self._last_coeff is not None:
            return self._last_coeff
        device_addr = None
        dev_field = header.get("DEV")
        if dev_field:
            try:
                device_addr = int(dev_field, 0)
            except ValueError:
                device_addr = None
        coeff = parse_rps_eeprom(blob, source="eeprom", device_address=device_addr)
        self._last_blob = blob
        self._last_coeff = coeff
        return coeff


def _coeff_from_mapping(data: Dict[str, object], source: str) -> Coeff:
    try:
        order = int(data["order"])
        unit = str(data.get("unit", RPS_UNIT_DEFAULT))
        serial = data.get("serial")
        serial_str = None if serial is None else str(serial)
        x_ref = float(data["x_ref"])
        y_ref = float(data["y_ref"])
        nx = int(data["nx"])
        ny = int(data["ny"])
        a = [float(value) for value in data["a"]]
    except KeyError as exc:
        raise ValueError(f"Manual coefficient missing field {exc}") from exc
    coeff = Coeff(
        order=order,
        unit=unit,
        a=a,
        serial=serial_str,
        source=source,
        x_ref=x_ref,
        y_ref=y_ref,
        nx=nx,
        ny=ny,
        product=str(data.get("product")) if data.get("product") else None,
    )
    return coeff


class CoeffManager:
    def __init__(
        self,
        *,
        default_provider: DefaultConfig,
        manual_provider: Optional[ManualOverride] = None,
        eeprom_provider: Optional[EepromOverCdc] = None,
        mode: str = "auto",
        refresh_interval: float = 60.0,
    ) -> None:
        self._default = default_provider
        self._manual = manual_provider or ManualOverride()
        self._eeprom = eeprom_provider
        self._mode = mode.lower()
        self._refresh_interval = max(refresh_interval, 1.0)
        self._last_refresh = 0.0
        self._current = self._select_initial()

    @property
    def current(self) -> Coeff:
        return self._current

    def _select_initial(self) -> Coeff:
        manual = self._manual.get()
        if self._mode == "manual":
            if manual is None:
                raise ValueError("Manual coefficient required but not provided")
            logger.info("Using manual coefficients (serial=%s)", manual.serial or "n/a")
            return manual
        if self._mode == "auto" and manual is not None:
            logger.info("Manual coefficient override active (serial=%s)", manual.serial or "n/a")
            return manual
        if self._mode == "auto" and self._eeprom is not None:
            coeff = self._try_fetch_eeprom(initial=True)
            if coeff is not None:
                return coeff
        logger.info("Falling back to config coefficients")
        return self._default.get()

    def refresh(self, now: float) -> Optional[Coeff]:
        manual = self._manual.get()
        if self._mode == "manual":
            if manual and not self._equivalent(manual, self._current):
                self._current = manual
                logger.info("Manual coefficients updated (serial=%s)", manual.serial or "n/a")
                return manual
            return None
        if self._mode == "config":
            target = self._default.get()
            if not self._equivalent(target, self._current):
                self._current = target
                logger.info("Reverting to config coefficients")
                return target
            return None

        # auto mode
        if manual is not None and not self._equivalent(manual, self._current):
            self._current = manual
            logger.info("Switching to manual coefficients (serial=%s)", manual.serial or "n/a")
            return manual
        if manual is not None:
            return None

        if self._eeprom is None:
            target = self._default.get()
            if not self._equivalent(target, self._current):
                self._current = target
                logger.info("Falling back to config coefficients (no EEPROM provider)")
                return target
            return None

        if now - self._last_refresh < self._refresh_interval:
            return None
        self._last_refresh = now
        coeff = self._try_fetch_eeprom(initial=False)
        if coeff is None:
            return None
        if self._equivalent(coeff, self._current):
            return None
        self._current = coeff
        logger.info(
            "Loaded EEPROM coefficients (serial=%s device=0x%02X)",
            coeff.serial or "n/a",
            coeff.device_address or 0,
        )
        return coeff

    def _try_fetch_eeprom(self, *, initial: bool) -> Optional[Coeff]:
        try:
            coeff = self._eeprom.fetch() if self._eeprom else None
        except Exception as exc:
            level = logging.DEBUG if initial else logging.WARNING
            logger.log(level, "Failed to load EEPROM coefficients: %s", exc)
            return None
        return coeff

    @staticmethod
    def _equivalent(lhs: Coeff, rhs: Coeff) -> bool:
        if lhs.source == rhs.source and lhs.serial and rhs.serial:
            return lhs.serial == rhs.serial
        return lhs.a == rhs.a and lhs.x_ref == rhs.x_ref and lhs.y_ref == rhs.y_ref


def coeff_metadata(coeff: Coeff) -> Dict[str, str]:
    return {
        "coeff_source": coeff.source,
        "coeff_order": str(coeff.order),
        "coeff_serial": coeff.serial or "",
        "unit": coeff.unit,
    }


def save_manual_coeff(path: Path, coeff: Coeff) -> None:
    data = {
        "order": coeff.order,
        "unit": coeff.unit,
        "serial": coeff.serial,
        "x_ref": coeff.x_ref,
        "y_ref": coeff.y_ref,
        "nx": coeff.nx,
        "ny": coeff.ny,
        "a": coeff.a,
        "product": coeff.product,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

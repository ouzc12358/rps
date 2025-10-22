from __future__ import annotations

import struct
from pathlib import Path
from typing import List

import numpy as np

from bslfs.terps.coeff import (
    Coeff,
    CoeffManager,
    DefaultConfig,
    EepromOverCdc,
    ManualOverride,
    RPS_EEPROM_SIZE,
    parse_rps_eeprom,
)
from bslfs.terps.config import load_config


def _make_eeprom_blob() -> bytes:
    blob = bytearray(RPS_EEPROM_SIZE)
    blob[0x0002:0x0006] = b"\x12\x34\x56\x78"
    blob[0x0008:0x0008 + len(b"RPS8000")] = b"RPS8000"
    blob[0x0048] = ord("P")
    blob[0x0050] = 1
    blob[0x0051] = 1
    blob[0x0080:0x0084] = struct.pack(">f", 123.25)
    blob[0x0084:0x0088] = struct.pack(">f", 456.5)
    coeffs = [1.0, 2.0, 3.0, 4.0]
    base = 0x0100
    for idx, value in enumerate(coeffs):
        blob[base + idx * 4 : base + (idx + 1) * 4] = struct.pack(">f", value)
    partial = sum(blob[:-2]) & 0xFFFF
    last_value = (0x1234 - partial) & 0xFFFF
    blob[-2] = (last_value >> 8) & 0xFF
    blob[-1] = last_value & 0xFF
    return bytes(blob)


def _hex_lines_from_blob(blob: bytes) -> List[str]:
    hex_str = blob.hex().upper()
    return [hex_str[i : i + 64] for i in range(0, len(hex_str), 64)]


def test_parse_rps_eeprom_big_endian() -> None:
    blob = _make_eeprom_blob()
    coeff = parse_rps_eeprom(blob, source="test", device_address=0xA0)
    assert coeff.serial == "12345678"
    assert np.isclose(coeff.x_ref, 123.25)
    assert np.isclose(coeff.y_ref, 456.5)
    assert coeff.device_address == 0xA0
    assert coeff.a == [1.0, 2.0, 3.0, 4.0]


def test_eeprom_over_cdc_fetch_parses_dump() -> None:
    blob = _make_eeprom_blob()
    header = ["OK DEV=0xA2 LEN=512", *_hex_lines_from_blob(blob), "END"]

    def executor(_command: str, _timeout: float) -> List[str]:
        return header

    provider = EepromOverCdc(executor)
    coeff = provider.fetch()
    assert coeff.device_address == 0xA2
    assert coeff.source == "eeprom"


def test_coeff_manager_prioritises_manual(tmp_path: Path) -> None:
    cfg = load_config(Path("host_pi/config.json"))
    default_provider = DefaultConfig(cfg)
    manual_coeff = Coeff(
        order=1,
        unit="Pa",
        a=[0.0, 1.0, 0.0, 0.0],
        serial="MANUAL",
        source="manual",
        x_ref=cfg.sensor_poly.X,
        y_ref=cfg.sensor_poly.Y,
        nx=1,
        ny=1,
    )
    manual = ManualOverride(manual_coeff)
    manager = CoeffManager(
        default_provider=default_provider,
        manual_provider=manual,
        eeprom_provider=None,
        mode="auto",
        refresh_interval=10.0,
    )
    assert manager.current.source == "manual"


def test_coeff_manager_auto_loads_eeprom(monkeypatch) -> None:
    cfg = load_config(Path("host_pi/config.json"))
    default_provider = DefaultConfig(cfg)
    blob = _make_eeprom_blob()
    header = ["OK DEV=0xA0 LEN=512", *_hex_lines_from_blob(blob), "END"]

    fetches = 0

    def executor(_command: str, _timeout: float) -> List[str]:
        nonlocal fetches
        fetches += 1
        return header

    eeprom = EepromOverCdc(executor)
    manager = CoeffManager(
        default_provider=default_provider,
        manual_provider=ManualOverride(),
        eeprom_provider=eeprom,
        mode="auto",
        refresh_interval=1.0,
    )
    assert manager.current.source == "eeprom"
    assert fetches == 1


def test_coeff_manager_refresh_interval(monkeypatch) -> None:
    cfg = load_config(Path("host_pi/config.json"))
    default_provider = DefaultConfig(cfg)
    blob = _make_eeprom_blob()
    header = ["OK DEV=0xA0 LEN=512", *_hex_lines_from_blob(blob), "END"]

    fetches = 0

    def executor(_command: str, _timeout: float) -> List[str]:
        nonlocal fetches
        fetches += 1
        return header

    eeprom = EepromOverCdc(executor)
    manager = CoeffManager(
        default_provider=default_provider,
        manual_provider=ManualOverride(),
        eeprom_provider=eeprom,
        mode="auto",
        refresh_interval=10.0,
    )
    assert fetches == 1
    assert manager.refresh(0.0) is None
    assert fetches == 1
    refreshed = manager.refresh(12.0)
    assert refreshed is None  # no change because data identical
    assert fetches == 2

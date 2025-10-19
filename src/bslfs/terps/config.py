from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Sequence


@dataclass
class AdcConfig:
    gain: int = 16
    rate_sps: int = 20
    mains_reject: bool = True


@dataclass
class HostRuntime:
    queue_maxsize: int = 512
    reconnect_initial_sec: float = 0.5
    reconnect_max_sec: float = 5.0
    stats_log_interval: float = 60.0
    binary_chunk_size: int = 256


@dataclass
class SensorPoly:
    X: float
    Y: float
    K: List[List[float]]

    @staticmethod
    def from_mapping(data: Dict[str, Any]) -> "SensorPoly":
        if "X" not in data or "Y" not in data or "K" not in data:
            raise ValueError("sensor_poly requires fields 'X', 'Y', and 'K'")
        k_matrix = data.get("K") or []
        if not isinstance(k_matrix, list) or not k_matrix:
            raise ValueError("sensor_poly.K must be a non-empty 2D list")
        first_len = None
        normalized: List[List[float]] = []
        for row in k_matrix:
            if not isinstance(row, list) or not row:
                raise ValueError("sensor_poly.K rows must be non-empty lists")
            row_len = len(row)
            if first_len is None:
                first_len = row_len
            elif row_len != first_len:
                raise ValueError("sensor_poly.K rows must have identical length")
            normalized.append([float(value) for value in row])
        return SensorPoly(
            X=float(data["X"]),
            Y=float(data["Y"]),
            K=normalized,
        )


@dataclass
class TerpsConfig:
    mode: str = "RECIP"
    tau_ms: float = 100.0
    min_interval_frac: float = 0.25
    timebase_ppm: float = 0.0
    frame_format: str = "csv"  # csv | binary
    output_csv: Path | None = None
    adc: AdcConfig = field(default_factory=AdcConfig)
    sensor_poly: SensorPoly = field(
        default_factory=lambda: SensorPoly(X=30000.0, Y=600000.0, K=[[0.0] * 5 for _ in range(6)])
    )
    allan_window: int = 0  # optional sample count for Allan deviation
    host: HostRuntime = field(default_factory=HostRuntime)

    @property
    def frame_format_enum(self) -> str:
        fmt = self.frame_format.lower()
        if fmt not in {"csv", "binary"}:
            raise ValueError(f"Unsupported frame_format '{self.frame_format}'")
        return fmt


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {**base}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merged[key] = _merge(base[key], value)  # type: ignore[index]
        else:
            merged[key] = value
    return merged


def load_config(path: Path | str, overrides: Sequence[str] | None = None) -> TerpsConfig:
    """
    Load a TERPS host configuration from JSON and apply CLI-style overrides.

    Overrides are expressed as dotted `key=value` pairs, e.g.:
        ["adc.gain=32", "sensor_poly.X=30500"]
    """
    config_path = Path(path)
    data = _load_json(config_path)
    override_data: Dict[str, Any] = {}
    for override in overrides or []:
        key, raw_value = _parse_override(override)
        _assign_nested(override_data, key, raw_value)
    merged = _merge(data, override_data)
    default_poly_data = {
        "X": 30000.0,
        "Y": 600000.0,
        "K": [[0.0] * 5 for _ in range(6)],
    }
    sensor_poly_data = merged.get("sensor_poly") or default_poly_data
    host_data = merged.get("host") or {}
    return TerpsConfig(
        mode=merged.get("mode", "RECIP"),
        tau_ms=float(merged.get("tau_ms", 100.0)),
        min_interval_frac=float(merged.get("min_interval_frac", 0.25)),
        timebase_ppm=float(merged.get("timebase_ppm", 0.0)),
        frame_format=str(merged.get("frame_format", "csv")),
        output_csv=Path(merged["output_csv"]) if merged.get("output_csv") else None,
        adc=AdcConfig(
            gain=int(merged.get("adc", {}).get("gain", 16)),
            rate_sps=int(merged.get("adc", {}).get("rate_sps", 20)),
            mains_reject=bool(merged.get("adc", {}).get("mains_reject", True)),
        ),
        sensor_poly=SensorPoly.from_mapping(sensor_poly_data),
        allan_window=int(merged.get("allan_window", 0)),
        host=HostRuntime(
            queue_maxsize=int(host_data.get("queue_maxsize", 512)),
            reconnect_initial_sec=float(host_data.get("reconnect_initial_sec", 0.5)),
            reconnect_max_sec=float(host_data.get("reconnect_max_sec", 5.0)),
            stats_log_interval=float(host_data.get("stats_log_interval", 60.0)),
            binary_chunk_size=int(host_data.get("binary_chunk_size", 256)),
        ),
    )


def _parse_override(item: str) -> tuple[str, Any]:
    if "=" not in item:
        raise ValueError(f"Override '{item}' must use key=value syntax")
    key, raw_value = item.split("=", 1)
    key = key.strip()
    if not key:
        raise ValueError("Override key may not be empty")
    value = _coerce_value(raw_value.strip())
    return key, value


def _coerce_value(raw: str) -> Any:
    if raw.lower() in {"true", "false"}:
        return raw.lower() == "true"
    try:
        if "." in raw or "e" in raw.lower():
            return float(raw)
        return int(raw)
    except ValueError:
        pass
    if raw.startswith("[") and raw.endswith("]"):
        return json.loads(raw)
    if raw.startswith("{") and raw.endswith("}"):
        return json.loads(raw)
    return raw


def _assign_nested(target: Dict[str, Any], dotted_key: str, value: Any) -> None:
    cursor = target
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value

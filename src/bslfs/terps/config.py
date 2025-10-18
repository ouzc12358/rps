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
class SensorPoly:
    X: float
    Y: float
    K: List[List[float]]  # 6x5 matrix by convention

    @staticmethod
    def from_mapping(data: Dict[str, Any]) -> "SensorPoly":
        k_matrix = data.get("K") or []
        if len(k_matrix) != 6:
            raise ValueError("sensor_poly.K must contain 6 rows")
        for row in k_matrix:
            if len(row) != 5:
                raise ValueError("sensor_poly.K rows must contain 5 columns")
        return SensorPoly(
            X=float(data["X"]),
            Y=float(data["Y"]),
            K=[[float(value) for value in row] for row in k_matrix],
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
        default_factory=lambda: SensorPoly(X=30000.0, Y=0.6, K=[[0.0] * 5 for _ in range(6)])
    )
    allan_window: int = 0  # optional sample count for Allan deviation

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
        sensor_poly=SensorPoly.from_mapping(merged.get("sensor_poly", {})),
        allan_window=int(merged.get("allan_window", 0)),
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

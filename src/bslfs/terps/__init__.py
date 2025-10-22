"""
Utilities for TERPS RPS frequency + diode voltage synchronized acquisition.

The subpackage exposes configuration models, frame decoders, and orchestration
helpers used by the Raspberry Pi host application. Keeping this logic inside
`bslfs` lets tests reuse existing dependencies (numpy, pandas) without
introducing a parallel package.
"""

from .coeff import Coeff, CoeffManager, coeff_from_sensor_poly, coeff_metadata
from .config import AdcConfig, HostRuntime, SensorPoly, TerpsConfig, load_config
from .frames import Frame, FrameFormat, FrameParser, crc16_ccitt
from .processing import PressureCalculator, SampleRecord
from .runner import TerpsHost

__all__ = [
    "AdcConfig",
    "HostRuntime",
    "SensorPoly",
    "TerpsConfig",
    "load_config",
    "Coeff",
    "CoeffManager",
    "coeff_from_sensor_poly",
    "coeff_metadata",
    "Frame",
    "FrameFormat",
    "FrameParser",
    "crc16_ccitt",
    "PressureCalculator",
    "SampleRecord",
    "TerpsHost",
]

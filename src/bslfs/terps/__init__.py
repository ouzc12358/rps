"""
Utilities for TERPS RPS frequency + diode voltage synchronized acquisition.

The subpackage exposes configuration models, frame decoders, and orchestration
helpers used by the Raspberry Pi host application. Keeping this logic inside
`bslfs` lets tests reuse existing dependencies (numpy, pandas) without
introducing a parallel package.
"""

from .config import TerpsConfig, load_config
from .frames import Frame, FrameFormat, FrameParser, crc16_ccitt
from .processing import PressureCalculator, SampleRecord
from .runner import TerpsHost

__all__ = [
    "TerpsConfig",
    "load_config",
    "Frame",
    "FrameFormat",
    "FrameParser",
    "crc16_ccitt",
    "PressureCalculator",
    "SampleRecord",
    "TerpsHost",
]

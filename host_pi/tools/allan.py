"""Utility helpers to compute Allan deviation from processed samples."""

from __future__ import annotations

import numpy as np


def allan_deviation(frequency: np.ndarray, tau: float) -> np.ndarray:
    """Compute overlapping Allan deviation for a series of frequency samples."""
    if frequency.size < 3:
        raise ValueError("Need >=3 samples to compute Allan deviation")
    diff = frequency[2:] - 2 * frequency[1:-1] + frequency[:-2]
    return np.sqrt(0.5 * np.cumsum(diff**2) / (tau**2 * np.arange(1, diff.size + 1)))

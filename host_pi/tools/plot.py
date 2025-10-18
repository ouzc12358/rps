"""Simple plotting companion for TERPS host logs."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def plot_timeseries(csv_path: Path) -> None:
    """Plot frequency and pressure from a processed CSV log."""
    data = pd.read_csv(csv_path)
    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax1.plot(data["ts_ms"] / 1000.0, data["frequency_hz"], label="frequency [Hz]", color="tab:blue")
    ax1.set_xlabel("Time [s]")
    ax1.set_ylabel("Frequency [Hz]", color="tab:blue")
    ax1.tick_params(axis="y", labelcolor="tab:blue")

    ax2 = ax1.twinx()
    ax2.plot(data["ts_ms"] / 1000.0, data["pressure"], label="pressure", color="tab:orange")
    ax2.set_ylabel("Pressure", color="tab:orange")
    ax2.tick_params(axis="y", labelcolor="tab:orange")

    fig.tight_layout()
    plt.show()

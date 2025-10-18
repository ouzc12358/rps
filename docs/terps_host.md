# TERPS Host Application

This document summarises how to run the Raspberry Pi host utilities that accompany the TERPS RPS synchronous acquisition system.

## Setup

1. Create a virtual environment and install dependencies with the optional TERPS extra:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .[dev,plot,terps]
   ```

2. Plug the Pico 2 into the Raspberry Pi 3B+ via USB. The device enumerates as `/dev/ttyACM*` once the firmware is running.

3. Update `host_pi/config.json` with the desired acquisition profile (mode, window length, ADC settings, polynomial coefficients).

## Running

Use the Typer CLI registered as `terps-host`:

```bash
terps-host run --port /dev/ttyACM0 --config host_pi/config.json --set output_csv=/tmp/terps.csv
```

- CSV streaming is the default. Switch to binary parsing with `--set frame_format=binary`.
- Pass `--set sensor_poly.K=[[...]]` to inject updated polynomial coefficients without editing files.
- Use `--port -` to pipe synthetic frames from stdin during testing.

Processed samples are written to the configured CSV path and include timestamp, frequency, tau, diode microvolts, computed pressure, ADC gain, flags, and ppm correction.

## Tooling

- `host_pi/tools/allan.py` computes Allan deviation sequences for logged frequency data.
- `host_pi/tools/plot.py` visualises time-series data from processed CSV logs.

## Firmware Notes

The `firmware_pico2/` directory contains a stub Pico SDK project with module placeholders for reciprocal counting, ADS1220 sampling, TinyUSB framing, and PPS calibration. Implementations must honour the fixed frame layout described in `bslfs/terps/frames.py` to maintain compatibility with the host decoding logic.

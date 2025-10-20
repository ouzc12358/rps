# BSL/FS Calibration Toolkit

`bslfs` is a Python package and CLI that evaluates pressure sensor calibration data following JJG860/JJG882 conventions. It ingests CSV data, performs best straight line (BSL) fitting, compares against endpoint and least-squares references, and produces metrics, plots, and reports.

It also ships a `terps-host` command that runs on Raspberry Pi to decode TERPS RPS frames (frequency + diode voltage), compute pressure with polynomial coefficients, and archive synchronized samples. See `docs/terps_host.md` for wiring and usage notes.

## Installation

```bash
pip install -e .[dev,plot]
```

- Core dependencies: `numpy`, `pandas`, `typer`.
- Optional plotting extras (`[plot]`) enable PNG outputs via `matplotlib`.

### TERPS Host Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev,plot,terps]
terps-host run --port /dev/ttyACM0 --config host_pi/config.json --set output_csv=run.csv
```

Use `--set frame_format=binary` once the Pico 2 firmware is streaming binary frames reliably.

Replay the bundled sample frames to sanity-check the pipeline:

```bash
cat samples/sample_frames.bin | terps-host --port - --frame-format binary --set output_csv=replay.csv
```

Add `--plot` to open a realtime Matplotlib dashboard (requires `pip install -e .[plot]`).

## Input Format

Provide a CSV file with the following columns:

| Column        | Required | Description                                  |
|---------------|----------|----------------------------------------------|
| `pressure_ref`| ✅        | Applied reference pressure (engineering units) |
| `output`      | ✅        | Sensor output reading                         |
| `cycle_id`    | ✅        | Identifier for each loading branch (up/down)  |
| `temp`        | ➕        | Measured temperature (optional)               |

Rows may be unordered; the tool infers loading direction per `cycle_id` based on the pressure trend. Multiple cycles and repeated pressures are supported.

Full-scale span `%FS` is defined as `max(output) - min(output)` for the provided dataset.

## CLI Usage

Generate calibration artefacts:

```bash
bslfs calc --in data.csv --mode bsl --report out/ --temp-comp linear
```

Outputs in `out/`:

- `metrics.csv` – summary table of linearity, hysteresis, repeatability, total error (absolute + %FS)
- `residuals.csv` – per-sample predictions and residuals for all fits
- `report.md` – Markdown report ready for sharing
- `plots.png` – scatter, error, and hysteresis loop visualisations (requires `[plot]` extra)

Create a demo dataset and matching report:

```bash
bslfs demo --out demo_output/
```

## Algorithms

- **Endpoint line**: straight line between minimum and maximum pressures.
- **OLS line**: ordinary least squares regression.
- **BSL line**: Chebyshev (minimax) fit that minimises the peak absolute deviation while constraining all points within the band.
- **Temperature compensation** (`--temp-comp linear`): augments the regression with a linear temperature term and reports compensated metrics alongside uncompensated ones.

Metrics follow JJG definitions:

- **Linearity**: peak absolute deviation from each reference line, reported in output units and %FS.
- **Hysteresis**: maximum up/down difference at matching reference pressures.
- **Repeatability**: worst-case deviation from the mean for repeated pressures in the same direction.
- **Total error**: root-sum-square of BSL linearity, hysteresis, and repeatability.

## Development

- Format and lint: `ruff check .` and `black .`
- Run tests: `pytest -q`
- Pre-commit hooks: `pre-commit install`

See `docs/formulas.md` for detailed derivations and JJG references.

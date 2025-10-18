# Repository Guidelines

## Project Structure & Module Organization
- Core package lives in `src/bslfs/`; keep new logic next to existing modules such as `metrics.py`, `pipeline.py`, and `reporting.py`.
- CLI entry sits in `src/bslfs/cli.py` and `__main__.py`; route new commands through the Typer `app`.
- Shared data contracts and IO helpers belong in `data.py` and `models.py`; extend them instead of inventing new schemas.
- Mirror module layout under `tests/`; docs stay in `docs/` and automation scripts in `scripts/` (mark executables with `chmod +x`).

## Build, Test, and Development Commands
- Provision dev tools with `pip install -e .[dev,plot]`.
- Sanity-check the CLI via `bslfs demo --out tmp_demo/` (delete the folder when done).
- Run `pytest -q` before every PR.
- Keep formatting and lint clean with `ruff check . && black .`; run `pre-commit run --all-files` when updating hooks.

## Coding Style & Naming Conventions
- Target Python 3.10+, 88-column formatting; let Black and Ruff rewrite files instead of manual tweaks.
- Use `snake_case` for modules, functions, and variables; reserve `PascalCase` for classes or structured models.
- Keep numerical routines pure inside `metrics.py` and `models.py`; confine side-effects (filesystem, CLI parsing) to the CLI layer.
- Annotate public functions, prefer f-strings, and avoid pandas chained assignments by using `.loc` updates.

## Testing Guidelines
- Add pytest modules that mirror `src/` paths and name files `test_*.py`.
- Use deterministic fixtures and `tmp_path` helpers for CLI output checks; store shared CSV samples under `tests/data/`.
- Parametrise scenarios instead of looping to keep the suite under 30 s.
- Any bug fix must ship with a regression test referencing the triggering input.

## Data & Configuration Tips
- Input CSVs must include `pressure_ref`, `output`, and `cycle_id`; document optional `temp` usage in help text before relying on it.
- Write generated artefacts (`metrics.csv`, `residuals.csv`, `report.md`, `plots.png`) to caller-supplied directories and keep them out of git.
- Expose tunable constants through Typer options or structured config objects rather than mutable module globals.

## Commit & Pull Request Guidelines
- Adopt Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`) and keep each commit focused.
- PR descriptions should cover the problem, solution, and validation commands; attach report diffs when behaviour changes.
- Link issues with `Closes #ID` and update `docs/` whenever formulas or workflows shift.
- Request review only after lint/tests pass and any demo artefacts are regenerated.

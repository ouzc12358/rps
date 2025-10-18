"""Model fitting primitives for BSL/FS calibration."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product
from math import comb

import numpy as np


@dataclass
class FitResult:
    """Summary of a linear model fit."""

    name: str
    coefficients: dict[str, float]
    predictions: np.ndarray
    residuals: np.ndarray
    max_abs_error: float
    metadata: dict[str, float]

    def as_dict(self) -> dict[str, float]:
        return {
            "name": self.name,
            "max_abs_error": self.max_abs_error,
            **{f"coef_{k}": v for k, v in self.coefficients.items()},
            **{f"meta_{k}": v for k, v in self.metadata.items()},
        }


def build_design_matrix(
    pressure: np.ndarray,
    *,
    temperature: np.ndarray | None = None,
    include_temperature: bool = False,
) -> tuple[np.ndarray, list[str]]:
    """Return design matrix (with intercept) and column labels."""

    if pressure.ndim != 1:
        raise ValueError("pressure must be 1-D array")

    columns = [np.ones_like(pressure), pressure.astype(float)]
    names = ["intercept", "pressure_ref"]
    if include_temperature:
        if temperature is None:
            raise ValueError("Temperature compensation requested but 'temp' column missing")
        columns.append(temperature.astype(float))
        names.append("temp")

    X = np.column_stack(columns)
    return X, names


def fit_endpoint(
    pressure: np.ndarray,
    output: np.ndarray,
) -> FitResult:
    """Fit endpoint line passing through min/max pressure points."""

    idx_min = int(np.argmin(pressure))
    idx_max = int(np.argmax(pressure))
    p_min, y_min = float(pressure[idx_min]), float(output[idx_min])
    p_max, y_max = float(pressure[idx_max]), float(output[idx_max])
    if np.isclose(p_max, p_min):
        raise ValueError("Endpoint fit requires distinct pressure points")

    slope = (y_max - y_min) / (p_max - p_min)
    intercept = y_min - slope * p_min

    predictions = intercept + slope * pressure
    residuals = output - predictions
    max_abs_error = float(np.max(np.abs(residuals)))

    return FitResult(
        name="endpoint",
        coefficients={"intercept": intercept, "pressure_ref": slope},
        predictions=predictions,
        residuals=residuals,
        max_abs_error=max_abs_error,
        metadata={},
    )


def fit_ols(
    pressure: np.ndarray,
    output: np.ndarray,
    *,
    temperature: np.ndarray | None = None,
    include_temperature: bool = False,
) -> FitResult:
    """Ordinary least squares fit."""

    X, names = build_design_matrix(
        pressure, temperature=temperature, include_temperature=include_temperature
    )
    beta, *_ = np.linalg.lstsq(X, output, rcond=None)
    predictions = X @ beta
    residuals = output - predictions

    coefficients = {name: float(value) for name, value in zip(names, beta)}
    max_abs_error = float(np.max(np.abs(residuals)))

    return FitResult(
        name="ols_temp" if include_temperature else "ols",
        coefficients=coefficients,
        predictions=predictions,
        residuals=residuals,
        max_abs_error=max_abs_error,
        metadata={},
    )


def fit_bsl(
    pressure: np.ndarray,
    output: np.ndarray,
    *,
    temperature: np.ndarray | None = None,
    include_temperature: bool = False,
    atol: float = 1e-9,
) -> FitResult:
    """Chebyshev/minimax best-straight-line fit."""

    X, names = build_design_matrix(
        pressure, temperature=temperature, include_temperature=include_temperature
    )
    beta, t_opt, residuals = _solve_minimax(X, output, atol=atol)

    coefficients = {name: float(value) for name, value in zip(names, beta)}
    predictions = X @ beta
    max_abs_error = float(np.max(np.abs(residuals)))

    return FitResult(
        name="bsl_temp" if include_temperature else "bsl",
        coefficients=coefficients,
        predictions=predictions,
        residuals=residuals,
        max_abs_error=max_abs_error,
        metadata={"max_deviation": float(t_opt)},
    )


def _solve_minimax(X: np.ndarray, y: np.ndarray, *, atol: float = 1e-9) -> tuple[np.ndarray, float, np.ndarray]:
    """Return (beta, t, residuals) that minimise max |y - X@beta|."""

    n, d = X.shape
    subset_size = d + 1
    if n < subset_size:
        raise ValueError("Not enough samples for minimax fit")

    try:
        combinations_count = comb(n, subset_size)
    except OverflowError:  # pragma: no cover - very large n
        combinations_count = float("inf")

    if combinations_count <= 100_000:
        solution = _enumerate_extrema(X, y, atol=atol)
        if solution is not None:
            return solution

    try:
        return _remez_exchange(X, y, atol=atol)
    except RuntimeError:
        if combinations_count <= 500_000:
            solution = _enumerate_extrema(X, y, atol=atol)
            if solution is not None:
                return solution
        raise


def _enumerate_extrema(
    X: np.ndarray, y: np.ndarray, *, atol: float = 1e-9
) -> tuple[np.ndarray, float, np.ndarray] | None:
    n, d = X.shape
    subset_size = d + 1
    indices = range(n)
    best: tuple[np.ndarray, float, np.ndarray] | None = None
    best_t = float("inf")
    sign_patterns = _sign_patterns(subset_size)

    for subset in combinations(indices, subset_size):
        A_base = X[list(subset)]
        for signs in sign_patterns:
            sign_vec = np.array(signs, dtype=float, copy=True)
            A = np.column_stack([A_base, sign_vec])
            try:
                sol = np.linalg.solve(A, y[list(subset)])
            except np.linalg.LinAlgError:
                continue
            beta = sol[:-1]
            t = float(sol[-1])
            if t < 0:
                beta = beta.copy()
                t = -t
                sign_vec = -sign_vec
            residuals = y - X @ beta
            if np.max(np.abs(residuals)) <= t + atol and t < best_t:
                best = (beta, t, residuals)
                best_t = t
    return best


def _sign_patterns(size: int) -> list[np.ndarray]:
    patterns: list[np.ndarray] = []
    for combo in product([-1.0, 1.0], repeat=size):
        if len(set(combo)) == 1:  # skip all equal
            continue
        arr = np.array(combo, dtype=float)
        # normalise first sign to +1 for symmetry reduction
        if arr[0] < 0:
            arr *= -1
        patterns.append(arr)
    unique_patterns: dict[tuple[float, ...], np.ndarray] = {}
    for pattern in patterns:
        key = tuple(pattern.tolist())
        unique_patterns.setdefault(key, pattern)
    return list(unique_patterns.values())


def _remez_exchange(
    X: np.ndarray, y: np.ndarray, *, atol: float = 1e-9, max_iter: int = 200
) -> tuple[np.ndarray, float, np.ndarray]:
    n, d = X.shape
    subset_size = d + 1
    if n < subset_size:
        raise ValueError("Not enough samples for minimax fit")

    indices = np.arange(n)
    # start with evenly spaced sample indices
    subset = np.linspace(0, n - 1, subset_size, dtype=int)
    subset = np.unique(subset)
    if subset.size < subset_size:
        extra = np.setdiff1d(indices, subset, assume_unique=True)
        subset = np.concatenate([subset, extra[: subset_size - subset.size]])
    signs = np.ones(subset_size)

    beta = np.zeros(d)
    t = float(0.0)

    for _ in range(max_iter):
        A = np.column_stack([X[subset], signs])
        try:
            sol, *_ = np.linalg.lstsq(A, y[subset], rcond=None)
        except np.linalg.LinAlgError as exc:  # pragma: no cover - unlikely
            raise RuntimeError("Minimax solver failed to converge") from exc
        beta = sol[:-1]
        t = float(sol[-1])
        if t < 0:
            beta = beta.copy()
            t = -t
            signs = -signs

        residuals = y - X @ beta
        max_idx = int(np.argmax(np.abs(residuals)))
        max_res = float(residuals[max_idx])
        if abs(max_res) <= t + atol:
            return beta, t, residuals

        # determine sign for entering index
        s_new = 1.0 if max_res >= 0 else -1.0
        subset_res_signs = np.sign(residuals[subset])
        subset_res_signs[subset_res_signs == 0] = 1.0

        if max_idx not in subset:
            same_sign_positions = np.where(subset_res_signs == s_new)[0]
            if same_sign_positions.size == 0:
                replace_pos = int(np.argmin(np.abs(residuals[subset])))
            else:
                replace_pos = int(same_sign_positions[0])
            subset[replace_pos] = max_idx
            subset_res_signs[replace_pos] = s_new
        else:
            pos = int(np.where(subset == max_idx)[0][0])
            subset_res_signs[pos] = s_new

        signs = subset_res_signs

    raise RuntimeError("Minimax solver did not converge")

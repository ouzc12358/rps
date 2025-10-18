# Calibration Formulae

## Linearity

For a fit line \( \hat{y} = f(p, t) \), linearity error is the maximum absolute residual:
\[
L = \max_i |y_i - \hat{y}_i|
\]

Linearity in %FS uses the output span \(FS = y_{\max} - y_{\min}\):
\[
L_{\%FS} = 100 \times \frac{L}{FS}
\]

## Best Straight Line (BSL)

BSL minimises the Chebyshev norm of residuals:
\[
\min_{\beta, t} t \quad \text{s.t.} \quad |y_i - X_i \beta| \le t,\; \forall i
\]

For pressure-only fitting, \(X_i = [1, p_i]\); with temperature compensation, \(X_i = [1, p_i, t_i]\). The solver applies an exchange algorithm (Remez) with an exhaustive fallback for small samples to guarantee the minimax error band.

## Hysteresis

Upward/downward mean outputs at identical reference pressures (rounded to \(10^{-6}\)):
\[
H = \max_p |\bar{y}_{\text{up}}(p) - \bar{y}_{\text{down}}(p)|
\]

## Repeatability

For each \((p, \text{direction})\), compute deviations from the directional mean:
\[
R = \max_{p, d} \max_j |y_{p,d,j} - \bar{y}_{p,d}|
\]

## Total Error

The composite error reported is the root-sum-square of BSL linearity, hysteresis, and repeatability:
\[
E = \sqrt{L^2 + H^2 + R^2}
\]

All metrics are expressed both in output units and as %FS.

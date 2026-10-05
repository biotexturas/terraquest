"""Angle / magnitude / denoise stage for TerraQuest CV pipeline.

Extracted from ``cv/clusters.md`` (extraction D0437B3E). Splits the flow
field into per-cell angle and magnitude, applies ``vmin/vmax`` masking, and
provides circular helpers (``ang_dif``, ``denoise``) used by the clustering
stage.

Demo call (D0437B3E): ``get_angle(V, res=0, vmin=1, vmax=20000)``. The
``res=0`` invocation is preserved as a PENDING thesis pin -- see
:func:`get_angle`.
"""
from __future__ import annotations

import numpy as np

from .config import ClusterParams


def get_angle(
    V: np.ndarray,
    res: int,
    vmin: float,
    vmax: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Decompose the flow field into per-cell ``(Angle, Magnitude)``.

    Computes the grid-center displacement by subtracting the implicit
    ``res * idx`` offset from each cell of ``V``. Cells whose magnitude
    falls outside ``[vmin, vmax]`` or which carry a zero displacement are
    NaN-ed in both outputs.

    PENDING thesis pin: the D0437B3E demo passed ``res=0``, which collapses
    the ``res * idx`` offset term to zero. That behaviour is preserved so
    downstream stages (which were tuned on the demo) keep matching.
    """
    h, w, _ = V.shape
    row_idx = np.arange(h, dtype=np.float32).reshape(-1, 1)
    col_idx = np.arange(w, dtype=np.float32).reshape(1, -1)
    # Grid-center displacement: subtract the implicit ``res * idx`` to
    # recover displacement relative to each cell centre
    # ``(res // 2 + j * res, res // 2 + i * res)``.
    dx = V[..., 0] - res * col_idx
    dy = V[..., 1] - res * row_idx

    mag = np.hypot(dx, dy)
    zero_disp = (dx == 0) & (dy == 0)
    invalid = (mag < vmin) | (mag > vmax) | zero_disp

    # Source quirk: NaN out cells whose magnitude / displacement is invalid;
    # arctan2(0, 0) is undefined and would otherwise poison downstream
    # clustering, so mask it explicitly via ``zero_disp``.
    Angle = np.where(invalid, np.nan, np.arctan2(dy, dx))
    Mag = np.where(invalid, np.nan, mag)
    return Angle, Mag


def ang_dif(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Minimal circular difference between two angle arrays (period ``2*pi``).

    Result lies in ``[0, pi]`` regardless of input sign convention; NaN
    inputs propagate through the modulo and the :func:`numpy.where` mask.
    """
    L = 2.0 * np.pi
    diff = (a - b) % L
    # Fold the upper half of the circle back onto [0, pi].
    diff = np.where(diff > np.pi, L - diff, diff)
    return diff


def denoise(A1: np.ndarray, A2: np.ndarray) -> np.ndarray:
    """Circular mean of two angle arrays, with NaN propagation.

    Computes ``arctan2(sin(A1) + sin(A2), cos(A1) + cos(A2))``. NaN inputs
    propagate naturally through :func:`numpy.sin` / :func:`numpy.cos`. The
    exact-zero result -- which :func:`numpy.arctan2` returns for a
    zero-length resultant vector -- is mapped to NaN per the D0437B3E
    notebook convention (a zero angle is treated as "no data" rather than
    a real heading).
    """
    s = np.sin(A1) + np.sin(A2)
    c = np.cos(A1) + np.cos(A2)
    result = np.arctan2(s, c)
    # Source quirk: arctan2(0, +x) returns 0; treat that as "no data"
    # rather than a valid heading of zero radians.
    result = np.where(result == 0, np.nan, result)
    return result

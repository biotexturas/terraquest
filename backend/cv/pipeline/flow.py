"""Sparse Lucas-Kanade optical flow stage for TerraQuest CV pipeline.

Extracted from notebook D0437B3E. Provides a regular starting grid, LK
tracking via :func:`cv2.calcOpticalFlowPyrLK`, and assembly of the resulting
vectors into a ``(ceil(h / res), ceil(w / res), 2)`` float32 flow field that
the angle stage consumes.

Demo parameters (D0437B3E): ``res=50, win=15, levels=4`` with termination
criteria ``(EPS | COUNT, 10, 0.03)``.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from .config import FlowParams


def grid_points(h: int, w: int, res: int) -> np.ndarray:
    """Build the ``(N, 1, 2)`` float32 starting grid for LK.

    Mirrors the D0437B3E extraction: ``arange(res // 2, h, res)`` over rows
    and ``arange(res // 2, w, res)`` over columns, reshaped to OpenCV's
    expected ``(N, 1, 2)`` layout.
    """
    ys = np.arange(res // 2, h, res, dtype=np.float32)
    xs = np.arange(res // 2, w, res, dtype=np.float32)
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    pts = np.stack([xx.ravel(), yy.ravel()], axis=-1).astype(np.float32)
    return pts.reshape(-1, 1, 2)


def calc_flow(
    prev_gray: np.ndarray,
    cur_gray: np.ndarray,
    p: FlowParams,
) -> tuple[np.ndarray, np.ndarray]:
    """Run :func:`cv2.calcOpticalFlowPyrLK` over the starting grid.

    Returns ``(pts_old_good, pts_new_good)`` filtered to ``status == 1`` so
    the assembler only sees vectors that were successfully tracked.
    """
    h, w = prev_gray.shape[:2]
    p0 = grid_points(h, w, p.res)
    pts_new, status, _ = cv2.calcOpticalFlowPyrLK(
        prev_gray,
        cur_gray,
        p0,
        None,
        winSize=(p.win, p.win),
        maxLevel=p.levels,
        criteria=(
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
            p.criteria_count,
            p.criteria_eps,
        ),
    )
    good = status.ravel() == 1
    return p0[good], pts_new[good]


def assemble_field(
    pts_old: np.ndarray,
    pts_new: np.ndarray,
    h: int,
    w: int,
    res: int,
) -> np.ndarray:
    """Assemble tracked vectors into a ``(nh, nw, 2)`` float32 flow field.

    For each successfully tracked point at ``(old_x, old_y)`` the
    displacement ``(new_x - old_x, new_y - old_y)`` is written into cell
    ``(i, j) = (int(old_y / res), int(old_x / res))``. Cells not touched by
    any good vector remain zero (preserving the D0437B3E notebook behaviour).

    The original notebook wrote ``V[i, j] = np.array(v[1], v[0])``: the
    second positional argument of :func:`numpy.array` is ``dtype``, so the
    displacement was silently lost. We assign an explicit ``[dx, dy]``
    float32 array instead.
    """
    nh = int(math.ceil(h / res))
    nw = int(math.ceil(w / res))
    V = np.zeros((nh, nw, 2), dtype=np.float32)

    # LK returns (N, 1, 2); flatten for easy scalar access.
    old_flat = pts_old.reshape(-1, 2)
    new_flat = pts_new.reshape(-1, 2)
    for old, new in zip(old_flat, new_flat):
        old_x, old_y = float(old[0]), float(old[1])
        new_x, new_y = float(new[0]), float(new[1])
        j = int(old_x / res)
        i = int(old_y / res)
        # Source-quirk fix: ``np.array(v[1], v[0])`` passed v[0] as dtype.
        # Use an explicit 2-element array so both dx and dy survive
        # assignment into the (nh, nw, 2) field.
        V[i, j] = np.array([new_x - old_x, new_y - old_y], dtype=np.float32)
    return V

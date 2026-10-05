"""Pinned parameters for the cv-pipeline rebuild (v0.1.0).

Every value is quoted from the extracted notebook sources (artifact D0437B3E).
Values the demo got wrong, or that only the thesis can settle, are marked PENDING.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlowParams:
    res: int = 50           # grid spacing px (demo; Pablo's own variant: 10)
    win: int = 15           # LK window (demo; Pablo's own variant: 10)
    levels: int = 4         # pyramid levels (demo)
    criteria_eps: float = 0.03
    criteria_count: int = 10


@dataclass(frozen=True)
class HeadTrackParams:
    blur_ksize: int = 101      # GaussianBlur (101, 101)
    score_gain: float = 0.001  # exp(0.001 * area) / dist^2 criterion
    circle_radius: int = 25
    draw_thickness: int = 25


@dataclass(frozen=True)
class ClusterParams:
    n_clusters: int = 20
    r: int = 0              # DEMO VALUE - suspicious (self-only neighbor window); PENDING thesis pin
    theta: float = 0.1      # angular-coherence threshold (radians)
    vmin: float = 1.0
    vmax: float = 20000.0


@dataclass(frozen=True)
class VelocityParams:
    """Tracking3HS reference - README-unmapped in source, role PENDING Juan/b0."""

    ncase: float = 1.3
    size: int = 490
    time_min: int = 12
    blur_ksize: int = 21
    areamin: int = 20000
    dmin: float = 20.0
    merge_dist: float = 50.0
    r2_min: float = 0.9
    scale: int = 1400


# Score aggregation - PENDING (not in any source notebook).
# See cv/README.md score_formula line and pipeline/score.py.

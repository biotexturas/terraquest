"""Synthetic-data tests for the cv.pipeline stages (v0.2).

Runnable with pytest or ``python cv/tests/test_pipeline.py``.
Requires numpy + opencv-python importable (flow module imports cv2);
skimage is NOT required (head_tracking/score are untested here).

All tests use crafted inputs - no footage needed:
    * grid/assemble: exact control over point displacements.
    * angle: hand-built V fields.
    * clusters: small hand-built angle/label fields.

Provenance: validates the D0437B3E-derived stage bodies and the three
source bug fixes (dtype misuse, cvals NameError, ~n: off-by-one).
"""
from __future__ import annotations

import math

import numpy as np

from cv.pipeline import angle, flow
from cv.pipeline.clusters import (
    big_clusters,
    float_range_hk,
    float_range_neighbors,
)
from cv.pipeline.config import FlowParams


def test_grid_points_matches_notebook_sampling():
    """Grid = arange(res//2, dim, res) per axis (notebook semantics)."""
    gp = flow.grid_points(240, 320, 50)
    n_rows = len(np.arange(25, 240, 50))   # 5
    n_cols = len(np.arange(25, 320, 50))   # 6
    assert gp.shape == (n_rows * n_cols, 1, 2)
    assert gp.dtype == np.float32


def test_assemble_field_fixes_source_dtype_bug():
    """Displacements must survive into V (source lost them to dtype arg)."""
    res = 50
    # Two tracked points inside cells (0,0) and (1,2).
    pts_old = np.array([[[25.0, 25.0]], [[125.0, 75.0]]], np.float32)
    pts_new = np.array([[[28.0, 23.0]], [[135.0, 70.0]]], np.float32)
    V = flow.assemble_field(pts_old, pts_new, 240, 320, res)
    assert V.shape == (math.ceil(240 / res), math.ceil(320 / res), 2)
    assert np.allclose(V[0, 0], [3.0, -2.0])       # dx=+3, dy=-2
    assert np.allclose(V[1, 2], [10.0, -5.0])
    # Cells without vectors stay zero (source behavior).
    assert np.all(V[2, 2] == 0)


def test_get_angle_grid_center_offset_and_masking():
    V = np.zeros((2, 3, 2), np.float32)
    V[..., 0] = 3
    V[..., 1] = -2
    A, M = angle.get_angle(V, 50, 1.0, 20000.0)
    # cell (0,0): displacement from implicit res*idx offset
    assert np.isfinite(A[0, 0]) and np.isclose(M[0, 0], np.hypot(3, 2))
    # cell (0,1): dx = 3 - 50*1 = -47
    assert np.isfinite(A[0, 1]) and np.isclose(M[0, 1], np.hypot(47, 2))
    # zero displacement -> NaN in both outputs
    A0, M0 = angle.get_angle(np.zeros((1, 1, 2), np.float32), 50, 1.0, 20000.0)
    assert np.isnan(A0[0, 0]) and np.isnan(M0[0, 0])
    # magnitude below vmin -> NaN
    Vsmall = np.zeros((1, 1, 2), np.float32)
    Vsmall[0, 0] = [0.5, 0.0]  # dx=0.5 -> below vmin=1 after offset math?
    # (cell (0,0) with res=0 keeps raw displacement 0.5 < vmin=1)
    A1, M1 = angle.get_angle(Vsmall, 0, 1.0, 20000.0)
    assert np.isnan(A1[0, 0]) and np.isnan(M1[0, 0])


def test_ang_dif_range_symmetry_wrap():
    a, b = np.float64(0.2), np.float64(6.0)
    d = float(angle.ang_dif(a, b))
    assert 0 <= d <= np.pi
    assert np.isclose(d, float(angle.ang_dif(b, a)))
    assert np.isclose(d, 2 * np.pi - (6.0 - 0.2))


def test_denoise_circular_mean_and_nan():
    D = angle.denoise(
        np.array([[0.0, np.pi / 2]]),
        np.array([[np.pi / 2, np.pi]]),
    )
    assert np.isclose(D[0, 0], np.pi / 4)
    assert np.isclose(D[0, 1], 3 * np.pi / 4)
    assert np.isnan(angle.denoise(np.array([[np.nan]]), np.array([[1.0]]))[0, 0])
    # Exact-zero resultant -> NaN (source 0->NaN quirk).
    assert np.isnan(angle.denoise(np.array([[0.0]]), np.array([[0.0]]))[0, 0])
    # KNOWN FLOAT EDGE (documented, not asserted as NaN): exact antipodal
    # angles (0, pi) leave sin(pi)~1.2e-16 residual, so arctan2 returns
    # ~pi/2 instead of the zero->NaN path. Matches source arithmetic;
    # measure-zero in real data.


def test_float_range_neighbors_predicate():
    A = np.array([[0.0, 0.05], [np.nan, 0.0]])
    C = np.array([[1, 2], [3, 0]])
    # Cell (0,0), r=1: labeled neighbors are (0,1)=L2 (diff 0.05 < 0.1
    # qualifies), (1,0)=L3 (NaN -> skipped), (1,1)=L0 (unlabeled).
    got = sorted(float_range_neighbors(A, C, 1, 0.1, 0, 0))
    assert got == [2]
    # Incoherent label (diff pi) must not qualify.
    A2 = np.array([[0.0, np.pi]])
    C2 = np.array([[1, 2]])
    assert float_range_neighbors(A2, C2, 1, 0.1, 0, 0) == []


def test_float_range_hk_coherent_nan_incoherent():
    # Fully coherent block -> single label.
    Ch = float_range_hk(np.full((2, 2), 0.5), 1, 0.1)
    assert len(np.unique(Ch)) == 1 and Ch[0, 0] == 1
    # NaN cell stays background 0, finite rest share a label.
    Ch2 = float_range_hk(np.array([[0.5, np.nan], [0.5, 0.5]]), 1, 0.1)
    assert Ch2[0, 1] == 0 and len(np.unique(Ch2[Ch2 > 0])) == 1
    # Two incoherent columns -> exactly 2 labels (no background).
    Ch3 = float_range_hk(np.array([[0.0, np.pi], [0.0, np.pi]]), 1, 0.1)
    assert sorted(np.unique(Ch3).tolist()) == [1, 2]
    # r=0 (demo PENDING value): window is self-only -> fresh label per cell.
    Ch4 = float_range_hk(np.full((2, 2), 0.5), 0, 0.1)
    assert sorted(np.unique(Ch4).tolist()) == [1, 2, 3, 4]


def test_big_clusters_top_n_off_by_one_fix():
    A = np.zeros((10, 30), np.int64)
    A[0:10, 0:10] = 1   # 100
    A[0:8, 10:20] = 2   # 80
    A[0:6, 20:26] = 3   # 60
    A[8:10, 26:30] = 4  # 8
    A[0:2, 28:30] = 5   # 4
    B = big_clusters(A, 3)
    assert set(np.unique(B[B > 0]).tolist()) == {1, 2, 3}
    assert (B == 1).sum() == 100
    assert (B == 4).sum() == 0 and (B == 5).sum() == 0
    # n larger than label count -> keep and relabel everything.
    B2 = big_clusters(A, 10)
    assert len(np.unique(B2[B2 > 0])) == len(np.unique(A[A > 0]))
    # all-background input -> all-background output.
    assert np.all(big_clusters(np.zeros((5, 5), np.int64), 3) == 0)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = []
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except AssertionError as exc:
            failed.append(fn.__name__)
            print(f"[FAIL] {fn.__name__}: {exc}")
    print(f"{len(fns) - len(failed)}/{len(fns)} passed; failures: {failed}")
    raise SystemExit(1 if failed else 0)

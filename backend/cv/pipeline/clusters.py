"""TerraQuest CV pipeline - clusters stage.

Extraction D0437B3E. Thesis core.

Implements:
    * float_range_neighbors - angular-coherence neighbor predicate.
    * float_range_hk        - modified Hoshen-Kopelman row-major labeling
                              with inline label merging.
    * big_clusters          - keep the n largest labels by pixel count,
                              relabeled 1..n in order of decreasing size.
    * big_work2             - end-to-end: load frames -> dual LK flow ->
                              angle split -> denoise -> HK -> top-N ->
                              0->NaN.

Source bug fixes vs the v0.1.0 stub / notebook extraction:

    (1) float_range_hk merge branch referenced an undefined name
        ``cvals`` instead of the loop variable ``cvalues`` -> corrected
        to use ``cvalues``.
    (2) big_clusters top-N slice was ``unique[~n:]`` (bitwise-not on
        an int, i.e. ``~n == -n-1``) -> corrected to ``unique[-n:]``.

Parameter caution: the demo call ``big_work2(20, folder, 0, 50, 15, 4,
0, 0.1, 1, 20000)`` ran with ``r = 0``, which is suspicious (the
neighbor window becomes self-only). The thesis-pinned ``r`` is still
PENDING; ``config.ClusterParams.r`` carries that marker. big_work2
passes ``p.r`` through as-is - it does not paper over the pin.
"""

from __future__ import annotations

import glob
import os

import cv2
import numpy as np

from . import angle as angle_mod
from . import flow as flow_mod
from .angle import ang_dif
from .config import ClusterParams, FlowParams


def float_range_neighbors(
    A: np.ndarray,
    C: np.ndarray,
    r: int,
    theta: float,
    i: int,
    j: int,
) -> list[int]:
    """Distinct neighbor labels within Chebyshev radius ``r`` of (i, j).

    Scans the (2r + 1) x (2r + 1) Chebyshev window centered on (i, j),
    excluding the cell itself, and collects the distinct labels of
    cells that are already labeled (``C != 0``) and whose angle differs
    from ``A[i, j]`` by less than ``theta`` radians (via
    :func:`ang_dif`). NaN angles are skipped - they do not qualify as
    neighbors regardless of their label.

    Extracted as D0437B3E: float_range_neighbors.
    """
    h, w = A.shape
    i_lo = max(0, i - r)
    i_hi = min(h, i + r + 1)
    j_lo = max(0, j - r)
    j_hi = min(w, j + r + 1)

    center = A[i, j]
    labels: set[int] = set()
    for ii in range(i_lo, i_hi):
        for jj in range(j_lo, j_hi):
            if ii == i and jj == j:
                continue
            if C[ii, jj] == 0:
                continue
            neighbor = A[ii, jj]
            if not np.isfinite(neighbor):
                continue
            if ang_dif(neighbor, center) < theta:
                labels.add(int(C[ii, jj]))
    return list(labels)


def float_range_hk(
    A: np.ndarray,
    r: int,
    theta: float,
) -> np.ndarray:
    """Row-major Hoshen-Kopelman labeling with angular-coherence merging.

    Scans ``A`` in row-major order. An unlabeled cell (``C[i, j] == 0``)
    with a finite angle is processed as follows:

        * No qualifying neighbors         -> assign a fresh label
                                            (``C_max + 1``).
        * Exactly one qualifying neighbor -> take that label.
        * Multiple distinct qualifying neighbors -> merge: the label
          covering the most pixels is kept, all other qualifying
          labels are rewritten onto it, and the cell adopts the
          canonical label.

    NaN cells are skipped entirely (they keep label 0). Cells already
    labeled by an earlier scan step are left untouched.

    Returns a 2D int label array with labels in ``1..N`` where ``N`` is
    the highest label assigned.

    Extracted as D0437B3E: float_range_hk.

    Bug fix vs source: the merge branch referenced an undefined name
    ``cvals`` instead of the loop variable ``cvalues`` -> corrected.
    """
    h, w = A.shape
    C = np.zeros((h, w), dtype=np.int64)
    C_max = 0
    for i in range(h):
        for j in range(w):
            val = A[i, j]
            if not np.isfinite(val):
                continue
            if C[i, j] != 0:
                continue
            cvalues = float_range_neighbors(A, C, r, theta, i, j)
            if not cvalues:
                C_max += 1
                C[i, j] = C_max
            elif len(cvalues) == 1:
                C[i, j] = cvalues[0]
            else:
                # Multiple distinct labels qualify -> inline merge.
                # Replace the smaller-count occurrences with the
                # larger-count label. The source bug used the
                # undefined name ``cvals`` in place of ``cvalues``.
                counts = {c: int(np.sum(C == c)) for c in cvalues}
                keep = max(cvalues, key=lambda c: counts[c])
                for c in cvalues:
                    if c != keep:
                        C[C == c] = keep
                C[i, j] = keep
    return C


def big_clusters(A: np.ndarray, n: int) -> np.ndarray:
    """Keep the ``n`` largest labels by pixel count, relabeled 1..n.

    The background label ``0`` is excluded from the cluster ranking.
    Surviving labels are remapped to ``1..k`` with
    ``k = min(n, #distinct non-zero labels)``, in order of decreasing
    pixel count - the largest surviving cluster becomes ``1``. Cells
    whose original label was dropped become ``0``.

    If fewer than ``n`` non-zero labels exist in ``A``, all of them are
    kept and relabeled ``1..k``.

    Extracted as D0437B3E: big_clusters.

    Bug fix vs source: the top-N slice was ``unique[~n:]`` (bitwise-not
    on int, ``~n == -n-1`` - off by one); corrected to ``unique[-n:]``.
    """
    unique, counts = np.unique(A, return_counts=True)

    # Drop background label 0 from the cluster ranking.
    mask = unique != 0
    unique = unique[mask]
    counts = counts[mask]

    # Sort ascending by count so that the largest labels are last.
    order = np.argsort(counts)
    unique = unique[order]
    counts = counts[order]

    k = min(n, len(unique))
    if k <= 0:
        return np.zeros_like(A)

    # Source bug: ``unique[~n:]`` is bitwise-not on int (off-by-one).
    # Fix: the last k elements of the ascending-by-count array are the
    # k largest clusters.
    keep_asc = unique[-k:]
    # Reverse to descending-size order and map to 1..k.
    mapping = {int(old): idx + 1 for idx, old in enumerate(keep_asc[::-1])}

    out = np.zeros_like(A)
    for old, new in mapping.items():
        out[A == old] = new
    return out


# ---------------------------------------------------------------------------
# Frame loading for the end-to-end stage
# ---------------------------------------------------------------------------

_IMAGE_EXTS: tuple[str, ...] = ("jpg", "jpeg", "png")


def _sorted_image_paths(folder: str) -> list[str]:
    """Sorted list of image paths in ``folder`` (jpg/jpeg/png)."""
    paths: list[str] = []
    for ext in _IMAGE_EXTS:
        paths.extend(glob.glob(os.path.join(folder, f"*.{ext}")))
    paths.sort()
    return paths


def _load_gray_triple(
    folder: str, frame: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load the consecutive gray triple (n, n+1, n+2) from ``folder``.

    Raises ``FileNotFoundError`` when the folder holds fewer than
    ``frame + 3`` images or any requested image fails to decode.
    """
    paths = _sorted_image_paths(folder)
    if len(paths) < frame + 3:
        raise FileNotFoundError(
            f"Need at least {frame + 3} images in {folder!r}; "
            f"found {len(paths)}."
        )
    out: list[np.ndarray] = []
    for idx in (frame, frame + 1, frame + 2):
        img = cv2.imread(paths[idx], cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise FileNotFoundError(
                f"Could not read image as grayscale: {paths[idx]!r}"
            )
        out.append(img)
    return out[0], out[1], out[2]


# ---------------------------------------------------------------------------
# End-to-end stage
# ---------------------------------------------------------------------------

def big_work2(
    n_clusters: int,
    folder: str,
    frame: int,
    p: ClusterParams,
    flow_p: FlowParams,
) -> np.ndarray:
    """Cluster a consecutive frame triple and label coherent flow regions.

    Steps (D0437B3E ``big_work2``):

        1. Load gray frames ``n``, ``n+1``, ``n+2`` from ``folder``.
        2. Compute LK flow for pairs ``(n, n+1)`` and ``(n+1, n+2)``.
        3. Assemble the velocity fields at ``flow_p.res``.
        4. Per-cell angles with magnitude gating ``p.vmin`` / ``p.vmax``.
        5. Circular-mean denoise of the two angle fields (NaN-propagating).
        6. HK angular labeling with ``p.r`` (PENDING thesis pin) and
           ``p.theta``.
        7. Keep the ``n_clusters`` largest labels.
        8. Promote label 0 to NaN.

    Demo call from D0437B3E::

        big_work2(20, "./pictures_Saturns/", 0, 50, 15, 4, 0, 0.1, 1, 20000)

    ``p.r`` is passed through as-is: the demo's ``r = 0`` remains a
    PENDING thesis pin and is not silently substituted here.
    """
    # 1. Load the consecutive triple (n, n+1, n+2) as grayscale.
    f0, f1, f2 = _load_gray_triple(folder, frame)
    h, w = f0.shape[:2]

    # 2-3. Two LK flow runs on consecutive pairs; assemble to grid.
    pts_old_0, pts_new_0 = flow_mod.calc_flow(f0, f1, flow_p)
    V0 = flow_mod.assemble_field(pts_old_0, pts_new_0, h, w, flow_p.res)

    pts_old_1, pts_new_1 = flow_mod.calc_flow(f1, f2, flow_p)
    V1 = flow_mod.assemble_field(pts_old_1, pts_new_1, h, w, flow_p.res)

    # 4. Per-cell angles with magnitude gating.
    A0, _M0 = angle_mod.get_angle(V0, flow_p.res, p.vmin, p.vmax)
    A1, _M1 = angle_mod.get_angle(V1, flow_p.res, p.vmin, p.vmax)

    # 5. Circular-mean denoise (NaN-propagating).
    Angle = angle_mod.denoise(A0, A1)

    # 6. HK angular labeling (p.r PENDING thesis pin - passed as-is).
    labeled = float_range_hk(Angle, p.r, p.theta)

    # 7. Keep the top n_clusters largest labels.
    labeled = big_clusters(labeled, n_clusters)

    # 8. 0 -> NaN postprocessing.
    out = labeled.astype(float)
    out[out == 0] = np.nan
    return out
